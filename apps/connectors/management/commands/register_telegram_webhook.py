"""Register Telegram shared bot webhook (setWebhook) — run after deploy or URL change."""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.connectors.adapters.telegram import bot as tg_bot

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Calls Telegram setWebhook for the shared Bitcheck bot (CONNECTORS_PUBLIC_BASE_URL + secret).'

    def handle(self, *args, **options):
        secret = (getattr(settings, 'TELEGRAM_SHARED_BOT_SECRET', '') or '').strip()
        if not secret:
            raise CommandError(
                'TELEGRAM_SHARED_BOT_SECRET is required — generate a random string, set it in .env, '
                'and pass the same value to Telegram setWebhook as secret_token.',
            )
        base = settings.CONNECTORS_PUBLIC_BASE_URL.rstrip('/')
        url = f'{base}/api/connectors/webhook/telegram/'
        token = tg_bot.shared_bot_token()
        tg_bot.set_webhook(token, url=url, secret_token=secret)
        self.stdout.write(self.style.SUCCESS(f'Registered Telegram shared webhook url={url}'))
