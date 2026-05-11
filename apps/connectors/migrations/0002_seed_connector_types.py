"""Seed connector catalogue rows (idempotent)."""

from django.db import migrations


def seed_connector_types(apps, schema_editor):
    ConnectorType = apps.get_model('connectors', 'ConnectorType')
    rows = [
        dict(
            slug='gmail',
            name='Gmail',
            description='Verify content from incoming mail.',
            category='email',
            status='coming_soon',
            auth_type='oauth2',
            supports_b2c=True,
            supports_b2b=True,
            supports_auto_verify=False,
        ),
        dict(
            slug='telegram',
            name='Telegram',
            description='Bot-based verification in Telegram.',
            category='chat',
            status='coming_soon',
            auth_type='bot_token',
            supports_b2c=True,
            supports_b2b=True,
            supports_auto_verify=False,
        ),
        dict(
            slug='slack',
            name='Slack',
            description='Workspace app for Slack.',
            category='chat',
            status='coming_soon',
            auth_type='oauth2',
            supports_b2c=True,
            supports_b2b=True,
            supports_auto_verify=False,
        ),
        dict(
            slug='whatsapp',
            name='WhatsApp',
            description='Business messaging connector.',
            category='chat',
            status='coming_soon',
            auth_type='api_key',
            supports_b2c=True,
            supports_b2b=True,
            supports_auto_verify=False,
        ),
        dict(
            slug='discord',
            name='Discord',
            description='Server bot for Discord.',
            category='social',
            status='coming_soon',
            auth_type='bot_token',
            supports_b2c=True,
            supports_b2b=True,
            supports_auto_verify=False,
        ),
        dict(
            slug='chrome_extension',
            name='Chrome extension',
            description='Browser-side capture (coming soon).',
            category='browser',
            status='coming_soon',
            auth_type='api_key',
            supports_b2c=True,
            supports_b2b=True,
            supports_auto_verify=False,
        ),
        dict(
            slug='echo',
            name='Echo (dev)',
            description='Internal test harness — not shown in consumer catalog.',
            category='other',
            status='beta',
            auth_type='webhook_signature',
            supports_b2c=False,
            supports_b2b=False,
            supports_auto_verify=False,
        ),
    ]
    for r in rows:
        ConnectorType.objects.update_or_create(slug=r['slug'], defaults=r)


def unseed_connector_types(apps, schema_editor):
    ConnectorType = apps.get_model('connectors', 'ConnectorType')
    ConnectorType.objects.filter(
        slug__in=[
            'gmail',
            'telegram',
            'slack',
            'whatsapp',
            'discord',
            'chrome_extension',
            'echo',
        ]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('connectors', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_connector_types, unseed_connector_types),
    ]
