"""Celery tasks — process inbound connector events and dispatch outbound results."""

from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

from apps.bits.services import (
    check_balance,
    get_wallet_for_organization,
    get_wallet_for_user,
)
from apps.connectors.base import InstallContext, ParsedEvent
from apps.connectors.exceptions import AuthExpired, ConnectorError, QuotaExceeded, RateLimited
from apps.connectors.models import ConnectorEvent, ConnectorInstall, ConnectorMessage
from apps.connectors.registry import get as get_adapter
from apps.verifications.services import (
    InsufficientBitsError,
    get_verification_cost,
    submit_b2b_verification,
    submit_b2c_verification,
)

logger = logging.getLogger(__name__)


def install_context_from_install(install: ConnectorInstall) -> InstallContext:
    return InstallContext(
        install_id=str(install.id),
        credentials=install.credentials or {},
        settings=install.settings or {},
        org_id=str(install.organization_id) if install.organization_id else None,
        user_id=str(install.user_id) if install.user_id else None,
    )


def enforce_quota(install: ConnectorInstall, required_bits: int) -> None:
    """Raise QuotaExceeded if wallet balance is below ``required_bits``."""
    if install.user_id:
        wallet = get_wallet_for_user(install.user)
    elif install.organization_id:
        wallet = get_wallet_for_organization(install.organization)
    else:
        raise QuotaExceeded('Connector install has no owner')

    if not check_balance(wallet.id, required_bits):
        raise QuotaExceeded(
            f'Insufficient bits: need {required_bits}, wallet {wallet.id}'
        )


def create_verification_from_connector(
    install: ConnectorInstall,
    source_event: ConnectorEvent,
    content,
) -> 'apps.verifications.models.Verification':
    from apps.verifications.models import Verification

    if content.kind != 'text':
        raise ValueError(f'Unsupported connector modality in phase 0: {content.kind}')

    if install.user_id:
        verification = submit_b2c_verification(
            install.user,
            'text',
            text_input=str(content.payload),
        )
    else:
        verification = submit_b2b_verification(
            install.organization,
            None,
            'text',
            text_input=str(content.payload),
        )

    verification.source = 'connector'
    verification.source_install = install
    verification.source_event = source_event
    verification.save(
        update_fields=['source', 'source_install', 'source_event'],
    )
    return verification


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_connector_event(self, event_id: str) -> None:
    event = ConnectorEvent.objects.select_related('install', 'install__type').get(
        pk=event_id,
    )
    install = event.install
    event.status = ConnectorEvent.Status.PROCESSING
    event.save(update_fields=['status'])

    adapter = get_adapter(install.type.slug)
    ctx = install_context_from_install(install)
    parsed = ParsedEvent(
        external_event_id=event.external_event_id,
        event_type=event.event_type,
        raw_payload=event.raw_payload or {},
    )

    try:
        contents = list(adapter.extract_content(ctx, parsed))
    except Exception as e:
        logger.exception('extract_content failed event=%s', event_id)
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e) from e
        event.status = ConnectorEvent.Status.FAILED
        event.processed_at = timezone.now()
        event.save(update_fields=['status', 'processed_at'])
        return

    if not contents:
        event.status = ConnectorEvent.Status.PROCESSED
        event.processed_at = timezone.now()
        event.save(update_fields=['status', 'processed_at'])
        return

    total_bits = sum(get_verification_cost(c.kind) for c in contents)

    try:
        enforce_quota(install, total_bits)
    except QuotaExceeded:
        event.status = ConnectorEvent.Status.IGNORED
        event.processed_at = timezone.now()
        event.save(update_fields=['status', 'processed_at'])
        ConnectorMessage.objects.create(
            install=install,
            event=event,
            verification=None,
            kind='quota_warning',
            payload={'detail': 'Insufficient bits for this verification.'},
            status=ConnectorMessage.Status.SENT,
            sent_at=timezone.now(),
        )
        return

    for item in contents:
        try:
            verification = create_verification_from_connector(install, event, item)
        except InsufficientBitsError:
            event.status = ConnectorEvent.Status.IGNORED
            event.processed_at = timezone.now()
            event.save(update_fields=['status', 'processed_at'])
            ConnectorMessage.objects.create(
                install=install,
                event=event,
                verification=None,
                kind='quota_warning',
                payload={'detail': 'Insufficient bits at submission time.'},
                status=ConnectorMessage.Status.SENT,
                sent_at=timezone.now(),
            )
            return
        event.verifications.add(verification)

    event.status = ConnectorEvent.Status.PROCESSED
    event.processed_at = timezone.now()
    event.save(update_fields=['status', 'processed_at'])


@shared_task(bind=True, max_retries=5)
def send_connector_result(self, verification_id: str) -> None:
    from apps.verifications.models import Verification

    verification = Verification.objects.select_related(
        'source_install',
        'source_install__type',
        'source_event',
    ).get(pk=verification_id)

    if verification.source != 'connector' or not verification.source_install_id:
        return

    install = verification.source_install
    event = verification.source_event
    adapter = get_adapter(install.type.slug)
    ctx = install_context_from_install(install)

    raw: dict = {}
    ext_id = ''
    ev_type = ''
    if event:
        raw = event.raw_payload or {}
        ext_id = event.external_event_id
        ev_type = event.event_type

    parsed = ParsedEvent(
        external_event_id=ext_id,
        event_type=ev_type,
        raw_payload=raw,
    )

    try:
        adapter.refresh_credentials(install)
        provider_response = adapter.send_result(ctx, parsed, verification)
    except AuthExpired:
        install.is_active = False
        install.last_error_message = 'Authorisation expired; reconnect required'
        install.last_error_at = timezone.now()
        install.save(
            update_fields=[
                'is_active',
                'last_error_message',
                'last_error_at',
                'updated_at',
            ],
        )
        return
    except RateLimited as e:
        raise self.retry(exc=e, countdown=e.retry_after)
    except ConnectorError:
        logger.exception('send_result connector error verification=%s', verification_id)
        raise

    ConnectorMessage.objects.create(
        install=install,
        event=event,
        verification=verification,
        kind='result',
        external_message_id=str(provider_response.get('message_id', '')),
        payload=provider_response,
        status=ConnectorMessage.Status.SENT,
        sent_at=timezone.now(),
    )
