"""
Data migration: seed the free and pro plans.

These are the only plans for the hackathon MVP.
Ref: database design doc § 9 — Seed data.
"""

from django.db import migrations


def seed_plans(apps, schema_editor):
    Plan = apps.get_model('billing', 'Plan')

    Plan.objects.update_or_create(
        code='free',
        defaults={
            'name': 'Free',
            'recurring_charge_naira': 0,
            'monthly_grant_bits': 3,
            'billing_interval': 'none',
            'is_active': True,
        },
    )

    Plan.objects.update_or_create(
        code='pro',
        defaults={
            'name': 'Pro',
            'recurring_charge_naira': 5000,
            'monthly_grant_bits': 50,
            'billing_interval': 'monthly',
            'is_active': True,
        },
    )


def reverse_seed(apps, schema_editor):
    Plan = apps.get_model('billing', 'Plan')
    Plan.objects.filter(code__in=['free', 'pro']).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_plans, reverse_seed),
    ]
