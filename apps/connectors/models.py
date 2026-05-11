"""Connector catalogue, installs, inbound events, and outbound messages."""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from .crypto import EncryptedJSONField


class ConnectorType(models.Model):
    """Seeded connector kinds (Gmail, Slack, …)."""

    class Category(models.TextChoices):
        EMAIL = 'email', 'Email'
        CHAT = 'chat', 'Chat'
        SOCIAL = 'social', 'Social'
        PRODUCTIVITY = 'productivity', 'Productivity'
        BROWSER = 'browser', 'Browser'
        OTHER = 'other', 'Other'

    class Status(models.TextChoices):
        COMING_SOON = 'coming_soon', 'Coming soon'
        ALPHA = 'alpha', 'Alpha'
        BETA = 'beta', 'Beta'
        GA = 'ga', 'General availability'

    class AuthType(models.TextChoices):
        OAUTH2 = 'oauth2', 'OAuth2'
        BOT_TOKEN = 'bot_token', 'Bot token'
        WEBHOOK_SIGNATURE = 'webhook_signature', 'Webhook signature'
        API_KEY = 'api_key', 'API key'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    slug = models.SlugField(max_length=32, unique=True)
    name = models.CharField(max_length=64)
    description = models.TextField(blank=True, default='')
    icon_url = models.URLField(max_length=500, blank=True, default='')
    category = models.CharField(max_length=32, choices=Category.choices, default=Category.OTHER)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.COMING_SOON)
    auth_type = models.CharField(max_length=32, choices=AuthType.choices)
    supports_b2c = models.BooleanField(default=True)
    supports_b2b = models.BooleanField(default=True)
    supports_auto_verify = models.BooleanField(default=False)
    settings_schema = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'connector_types'
        ordering = ['name']

    def __str__(self):
        return self.name


class ConnectorInstall(models.Model):
    """A user's or org's connection to one external account (workspace, bot, …)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    type = models.ForeignKey(
        ConnectorType,
        on_delete=models.CASCADE,
        related_name='installs',
    )
    organization = models.ForeignKey(
        'accounts.Organization',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='connector_installs',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='connector_installs',
    )
    external_account_id = models.CharField(max_length=128)
    external_account_label = models.CharField(max_length=255, blank=True, default='')
    credentials = EncryptedJSONField(null=True, blank=True)
    settings = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)
    last_event_at = models.DateTimeField(null=True, blank=True)
    last_error_at = models.DateTimeField(null=True, blank=True)
    last_error_message = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'connector_installs'
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(user__isnull=False, organization__isnull=True)
                    | models.Q(user__isnull=True, organization__isnull=False)
                ),
                name='connector_install_xor_owner',
            ),
            models.UniqueConstraint(
                fields=['type', 'external_account_id'],
                name='connector_install_unique_external',
            ),
        ]
        indexes = [
            models.Index(fields=['type', 'is_active'], name='idx_conn_install_type_active'),
        ]

    def __str__(self):
        return f'{self.type.slug} · {self.external_account_label or self.external_account_id}'


class ConnectorEvent(models.Model):
    """One inbound webhook / event; idempotent on (install, external_event_id)."""

    class Status(models.TextChoices):
        RECEIVED = 'received', 'Received'
        PROCESSING = 'processing', 'Processing'
        PROCESSED = 'processed', 'Processed'
        IGNORED = 'ignored', 'Ignored'
        FAILED = 'failed', 'Failed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    install = models.ForeignKey(
        ConnectorInstall,
        on_delete=models.CASCADE,
        related_name='events',
    )
    external_event_id = models.CharField(max_length=128)
    event_type = models.CharField(max_length=64)
    raw_payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.RECEIVED,
    )
    verifications = models.ManyToManyField(
        'verifications.Verification',
        related_name='connector_events_m2m',
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'connector_events'
        constraints = [
            models.UniqueConstraint(
                fields=['install', 'external_event_id'],
                name='connector_event_idempotent',
            ),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.event_type} ({self.status})'


class ConnectorMessage(models.Model):
    """Outbound delivery audit (Slack reply, Telegram message, …)."""

    class Direction(models.TextChoices):
        OUTBOUND = 'outbound', 'Outbound'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        SENT = 'sent', 'Sent'
        FAILED = 'failed', 'Failed'
        RETRYING = 'retrying', 'Retrying'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    install = models.ForeignKey(
        ConnectorInstall,
        on_delete=models.CASCADE,
        related_name='messages',
    )
    event = models.ForeignKey(
        ConnectorEvent,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='messages',
    )
    verification = models.ForeignKey(
        'verifications.Verification',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='connector_messages',
    )
    direction = models.CharField(
        max_length=16,
        choices=Direction.choices,
        default=Direction.OUTBOUND,
    )
    kind = models.CharField(max_length=32)
    external_message_id = models.CharField(max_length=128, blank=True, default='')
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
    )
    attempts = models.IntegerField(default=0)
    last_error_message = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'connector_messages'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.kind} ({self.status})'


class ConnectorTypeInterest(models.Model):
    """Demand capture for coming-soon connector tiles."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    connector_type = models.ForeignKey(
        ConnectorType,
        on_delete=models.CASCADE,
        related_name='interests',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='connector_interests',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'connector_type_interests'
        constraints = [
            models.UniqueConstraint(
                fields=['connector_type', 'user'],
                name='connector_interest_unique_user_type',
            ),
        ]
