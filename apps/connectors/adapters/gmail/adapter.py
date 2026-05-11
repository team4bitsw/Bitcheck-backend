"""Gmail connector — Phase 1: OAuth install + credential refresh only."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterable

from django.http import HttpRequest

from apps.connectors.adapters.gmail.oauth import (
    build_auth_url,
    build_oauth_state,
    exchange_code,
    exchange_refresh_token,
    get_user_email,
    verify_oauth_state_for_install,
)
from apps.connectors.base import ConnectorAdapter, InstallContext, ParsedEvent, VerifiableContent
from apps.connectors.exceptions import AuthExpired, InvalidPayload
from apps.connectors.models import ConnectorInstall, ConnectorType
from apps.connectors.registry import register

if TYPE_CHECKING:
    from apps.verifications.models import Verification


@register
class GmailAdapter(ConnectorAdapter):
    slug = 'gmail'

    def begin_install(
        self,
        user,
        *,
        organization=None,
    ) -> dict[str, Any]:
        state = build_oauth_state(user, organization, slug=self.slug)
        return {'redirect_url': build_auth_url(state)}

    def complete_install(
        self,
        user,
        payload: dict[str, Any],
        *,
        organization=None,
    ) -> ConnectorInstall:
        code = payload.get('code')
        state = payload.get('state')
        if not code or not state:
            raise InvalidPayload('Missing code or state.')

        verify_oauth_state_for_install(
            str(state),
            expected_slug=self.slug,
            user=user,
            organization=organization,
        )

        tokens = exchange_code(str(code))
        email = get_user_email(tokens['access_token'])

        ct = ConnectorType.objects.get(slug=self.slug)
        install, _created = ConnectorInstall.objects.update_or_create(
            type=ct,
            external_account_id=email,
            defaults={
                'user': None if organization else user,
                'organization': organization,
                'external_account_label': email,
                'credentials': {
                    'access_token': tokens['access_token'],
                    'refresh_token': tokens.get('refresh_token'),
                    'expires_in': tokens.get('expires_in'),
                    'token_type': tokens.get('token_type', 'Bearer'),
                },
                'settings': {
                    'auto_verify': False,
                    'attachment_kinds': ['image', 'document'],
                    'min_attachment_bytes': 25_000,
                    'daily_cap': 100,
                },
                'is_active': True,
                'last_error_message': '',
            },
        )
        return install

    def refresh_credentials(self, install: ConnectorInstall) -> None:
        creds = install.credentials or {}
        refresh = creds.get('refresh_token')
        if not refresh:
            raise AuthExpired('No refresh token stored for this Gmail install.')
        new_tokens = exchange_refresh_token(str(refresh))
        creds['access_token'] = new_tokens['access_token']
        if new_tokens.get('expires_in') is not None:
            creds['expires_in'] = new_tokens['expires_in']
        install.credentials = creds
        install.save(update_fields=['credentials', 'updated_at'])

    def verify_webhook(self, request: HttpRequest) -> bool:
        # Pub/Sub push auth in Phase 2.
        return False

    def parse_event(self, request: HttpRequest) -> tuple[InstallContext, ParsedEvent]:
        raise InvalidPayload('Gmail Pub/Sub webhook not implemented yet.')

    def extract_content(
        self,
        ctx: InstallContext,
        event: ParsedEvent,
    ) -> Iterable[VerifiableContent]:
        return []

    def send_result(
        self,
        ctx: InstallContext,
        event: ParsedEvent,
        verification: Verification,
    ) -> dict[str, Any]:
        # Workspace add-on cards in Phase 3.
        return {}
