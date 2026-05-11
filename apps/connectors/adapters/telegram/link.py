"""One-time link codes for shared Telegram bot install."""

from __future__ import annotations

import logging
import secrets
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.connectors.models import ConnectorInstall, ConnectorType, TelegramLinkCode

logger = logging.getLogger(__name__)

LINK_TTL = timedelta(minutes=30)
CODE_BYTES = 18  # urlsafe ~24 chars, under Telegram 64 limit for /start


def create_link_code(user, organization) -> str:
    """Create a pending row and return the opaque code for deep-link + polling."""
    code = secrets.token_urlsafe(CODE_BYTES).replace('-', '_')[:48]
    TelegramLinkCode.objects.create(
        user=user,
        organization=organization,
        code=code,
        expires_at=timezone.now() + LINK_TTL,
    )
    return code


def poll_link_status(user, code: str) -> dict:
    try:
        row = TelegramLinkCode.objects.get(code=code, user=user)
    except TelegramLinkCode.DoesNotExist:
        return {'linked': False, 'detail': 'not_found'}
    if row.expires_at < timezone.now():
        return {'linked': False, 'detail': 'expired'}
    if row.used_at and row.install_id:
        return {'linked': True, 'install_id': str(row.install_id)}
    return {'linked': False}


@transaction.atomic
def complete_link_with_chat(
    *,
    code: str,
    chat_id: int,
    telegram_user: dict,
) -> ConnectorInstall | None:
    """
    Claim ``code``, create ``ConnectorInstall`` for shared bot + chat.

    Returns None if code invalid/expired/used.
    """
    try:
        row = TelegramLinkCode.objects.select_for_update().get(code=code, used_at__isnull=True)
    except TelegramLinkCode.DoesNotExist:
        return None
    if row.expires_at < timezone.now():
        return None

    ct = ConnectorType.objects.get(slug='telegram')
    from_username = (telegram_user.get('username') or '') or ''
    label = f'@{from_username}' if from_username else str(telegram_user.get('id', ''))
    install, _ = ConnectorInstall.objects.update_or_create(
        type=ct,
        external_account_id=f'shared:{chat_id}',
        defaults={
            'user': None if row.organization_id else row.user,
            'organization': row.organization,
            'external_account_label': label[:255],
            'credentials': {
                'bot_mode': 'shared',
                'telegram_user_id': telegram_user.get('id'),
            },
            'settings': _default_install_settings(),
            'is_active': True,
            'last_error_message': '',
        },
    )
    row.chat_id = chat_id
    row.install = install
    row.used_at = timezone.now()
    row.save(update_fields=['chat_id', 'install', 'used_at'])
    logger.info('telegram link completed user=%s chat=%s install=%s', row.user_id, chat_id, install.id)
    return install


def _default_install_settings() -> dict:
    ct = ConnectorType.objects.filter(slug='telegram').first()
    schema = (ct.settings_schema if ct else {}) or {}
    out: dict = {}
    for key, defn in schema.items():
        if isinstance(defn, dict) and 'default' in defn:
            out[key] = defn['default']
    if 'group_result_visibility' not in out:
        out['group_result_visibility'] = 'public'
    if 'daily_cap' not in out:
        out['daily_cap'] = 100
    return out
