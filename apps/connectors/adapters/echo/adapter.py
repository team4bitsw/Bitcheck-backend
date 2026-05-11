"""Echo test adapter — exercises the base layer without a third party."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Iterable

from django.conf import settings
from django.http import HttpRequest

from apps.connectors.base import ConnectorAdapter, InstallContext, ParsedEvent, VerifiableContent
from apps.connectors.exceptions import InvalidPayload
from apps.connectors.models import ConnectorInstall, ConnectorType
from apps.connectors.registry import register

if TYPE_CHECKING:
    from apps.verifications.models import Verification

logger = logging.getLogger(__name__)

ECHO_EXTERNAL_ID = 'echo-test'


@register
class EchoAdapter(ConnectorAdapter):
    slug = 'echo'

    def verify_webhook(self, request: HttpRequest) -> bool:
        return True

    def parse_event(self, request: HttpRequest) -> tuple[InstallContext, ParsedEvent]:
        try:
            payload = json.loads(request.body.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise InvalidPayload('Invalid JSON body') from e

        ext_id = payload.get('id')
        text = payload.get('text')
        if not ext_id or text is None:
            raise InvalidPayload('Missing id or text')

        try:
            install = ConnectorInstall.objects.select_related('type').get(
                type__slug=self.slug,
                external_account_id=ECHO_EXTERNAL_ID,
                is_active=True,
            )
        except ConnectorInstall.DoesNotExist as e:
            raise InvalidPayload('Echo connector not installed') from e

        ctx = InstallContext(
            install_id=str(install.id),
            credentials=install.credentials or {},
            settings=install.settings or {},
            org_id=str(install.organization_id) if install.organization_id else None,
            user_id=str(install.user_id) if install.user_id else None,
        )
        parsed = ParsedEvent(
            external_event_id=str(ext_id),
            event_type='text_submitted',
            raw_payload=payload,
        )
        return ctx, parsed

    def extract_content(
        self,
        ctx: InstallContext,
        event: ParsedEvent,
    ) -> Iterable[VerifiableContent]:
        yield VerifiableContent(
            kind='text',
            payload=str(event.raw_payload.get('text', '')),
        )

    def send_result(
        self,
        ctx: InstallContext,
        event: ParsedEvent,
        verification: Verification,
    ) -> dict[str, Any]:
        logger.info(
            'EchoAdapter.send_result verification=%s score=%s',
            verification.id,
            verification.trust_score,
        )
        return {'message_id': 'echo-noop'}

    def begin_install(
        self,
        user,
        *,
        organization=None,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        base = settings.CONNECTORS_PUBLIC_BASE_URL.rstrip('/')
        return {
            'webhook_url': f'{base}/api/connectors/webhook/echo/',
        }

    def complete_install(
        self,
        user,
        payload: dict[str, Any],
        *,
        organization=None,
    ) -> ConnectorInstall:
        ct = ConnectorType.objects.get(slug=self.slug)
        install, _created = ConnectorInstall.objects.update_or_create(
            type=ct,
            external_account_id=ECHO_EXTERNAL_ID,
            defaults={
                'user': None if organization else user,
                'organization': organization,
                'external_account_label': 'Echo test harness',
                'credentials': {},
                'settings': {},
                'is_active': True,
            },
        )
        return install
