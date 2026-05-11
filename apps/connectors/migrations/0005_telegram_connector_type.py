"""Telegram connector catalogue row — beta + dual install + settings schema."""

from django.db import migrations

TELEGRAM_SCHEMA = {
    'group_result_visibility': {
        'type': 'string',
        'title': 'Where to post results in groups',
        'enum': ['public', 'private', 'silent'],
        'default': 'public',
    },
    'allowed_chat_types': {
        'type': 'array',
        'title': 'Allowed chat types',
        'items': {'type': 'string', 'enum': ['private', 'group', 'supergroup', 'channel']},
        'default': ['private', 'group', 'supergroup', 'channel'],
    },
    'allowed_user_ids': {
        'type': 'string',
        'title': 'Allowed Telegram user IDs (comma-separated, own-bot only; empty = all)',
        'default': '',
    },
    'auto_verify_media': {
        'type': 'boolean',
        'title': 'Auto-verify every media message in groups (own bot)',
        'default': False,
    },
    'auto_verify_groups': {
        'type': 'string',
        'title': 'Group chat IDs for auto-verify (comma-separated; empty = all allowed groups)',
        'default': '',
    },
    'daily_cap': {
        'type': 'integer',
        'title': 'Max verifications per day for this install',
        'default': 100,
    },
}

TELEGRAM_DESCRIPTION = (
    'Verify images, documents, audio, video, and text via Telegram. '
    'Use the shared Bitcheck bot or connect your own bot for a branded experience.'
)


def upgrade(apps, schema_editor):
    ConnectorType = apps.get_model('connectors', 'ConnectorType')
    ConnectorType.objects.filter(slug='telegram').update(
        status='beta',
        auth_type='telegram_dual',
        supports_auto_verify=False,
        settings_schema=TELEGRAM_SCHEMA,
        description=TELEGRAM_DESCRIPTION,
    )


def downgrade(apps, schema_editor):
    ConnectorType = apps.get_model('connectors', 'ConnectorType')
    ConnectorType.objects.filter(slug='telegram').update(
        status='coming_soon',
        auth_type='bot_token',
        supports_auto_verify=False,
        settings_schema={},
        description='Bot-based verification in Telegram.',
    )


class Migration(migrations.Migration):
    dependencies = [
        ('connectors', '0004_telegram_link_code'),
    ]

    operations = [
        migrations.RunPython(upgrade, downgrade),
    ]
