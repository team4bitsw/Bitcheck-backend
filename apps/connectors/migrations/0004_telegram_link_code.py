"""Telegram shared-bot link codes + new auth_type choices."""

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('connectors', '0003_gmail_beta'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('accounts', '0002_add_organization_description'),
    ]

    operations = [
        migrations.CreateModel(
            name='TelegramLinkCode',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('code', models.CharField(db_index=True, max_length=64, unique=True)),
                ('chat_id', models.BigIntegerField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('expires_at', models.DateTimeField()),
                ('used_at', models.DateTimeField(blank=True, null=True)),
                (
                    'install',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name='telegram_link_codes',
                        to='connectors.connectorinstall',
                    ),
                ),
                (
                    'organization',
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='telegram_link_codes',
                        to='accounts.organization',
                    ),
                ),
                (
                    'user',
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='telegram_link_codes',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                'db_table': 'telegram_link_codes',
            },
        ),
        migrations.AddIndex(
            model_name='telegramlinkcode',
            index=models.Index(fields=['code', 'expires_at'], name='idx_tl_code_exp'),
        ),
        migrations.AlterField(
            model_name='connectortype',
            name='auth_type',
            field=models.CharField(
                max_length=32,
                choices=[
                    ('oauth2', 'OAuth2'),
                    ('bot_token', 'Bot token'),
                    ('webhook_signature', 'Webhook signature'),
                    ('api_key', 'API key'),
                    ('telegram_shared', 'Telegram shared bot'),
                    ('telegram_dual', 'Telegram shared or own bot'),
                ],
            ),
        ),
    ]
