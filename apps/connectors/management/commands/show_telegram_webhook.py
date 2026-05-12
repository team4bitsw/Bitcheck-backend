"""Print Telegram getWebhookInfo for the shared bot (debug local vs prod URL mismatch)."""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from apps.connectors.adapters.telegram import bot as tg_bot


class Command(BaseCommand):
    help = 'Shows the webhook URL Telegram is calling (must reach the same server that created link codes).'

    def handle(self, *args, **options):
        tok = tg_bot.shared_bot_token()
        info = tg_bot.get_webhook_info(tok)
        self.stdout.write(json.dumps(info, indent=2))
        url = info.get('url') or ''
        if url and 'localhost' not in url and '127.0.0.1' not in url:
            self.stdout.write(
                self.style.WARNING(
                    '\nTelegram sends updates to that URL only. '
                    'A local runserver will NOT see /start unless you use ngrok (and re-run '
                    'register_telegram_webhook) or you test against the deployed API + DB.',
                ),
            )
