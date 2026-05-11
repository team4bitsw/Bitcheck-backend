"""Seed Gmail connector for Phase 1 OAuth (beta + settings schema)."""

from django.db import migrations

GMAIL_SCHEMA = {
    'auto_verify': {
        'type': 'boolean',
        'title': 'Auto-verify attachments',
        'default': False,
    },
    'attachment_kinds': {
        'type': 'array',
        'title': 'Attachment types to auto-verify',
        'items': {'type': 'string', 'enum': ['image', 'document', 'audio', 'video']},
        'default': ['image', 'document'],
    },
    'min_attachment_bytes': {
        'type': 'integer',
        'title': 'Minimum attachment size (bytes)',
        'default': 25_000,
    },
    'daily_cap': {
        'type': 'integer',
        'title': 'Max auto-verifications per day',
        'default': 100,
    },
}

GMAIL_DESCRIPTION = (
    'Verify attachments from incoming Gmail messages. '
    'Connect your Google account to enable manual verification from the Gmail sidebar '
    '(add-on in a later release).'
)


def upgrade(apps, schema_editor):
    ConnectorType = apps.get_model('connectors', 'ConnectorType')
    ConnectorType.objects.filter(slug='gmail').update(
        status='beta',
        supports_auto_verify=False,
        settings_schema=GMAIL_SCHEMA,
        description=GMAIL_DESCRIPTION,
    )


def downgrade(apps, schema_editor):
    ConnectorType = apps.get_model('connectors', 'ConnectorType')
    ConnectorType.objects.filter(slug='gmail').update(
        status='coming_soon',
        supports_auto_verify=False,
        settings_schema={},
        description='Verify content from incoming mail.',
    )


class Migration(migrations.Migration):
    dependencies = [
        ('connectors', '0002_seed_connector_types'),
    ]

    operations = [
        migrations.RunPython(upgrade, downgrade),
    ]
