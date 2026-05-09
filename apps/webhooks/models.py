"""
Webhooks models — Inbound webhook inbox.

Stub model created in Phase 2 so that bits.TopUp can FK to WebhookEvent.
Full implementation (processing logic, views) will be added in Phase 6.

Ref: database design doc § 4.8
"""

import uuid
from django.db import models


class WebhookEvent(models.Model):
    """
    Every incoming event from external systems (Squad first; future: ML callbacks).
    Append-only inbox — never deleted, never updated (except status).

    Processing rule: the HTTP handler does ONLY two things — verify signature,
    insert row. Actual processing happens in a Celery worker that picks up
    status='received' rows.
    """

    class Source(models.TextChoices):
        SQUAD = 'squad', 'Squad'

    class Status(models.TextChoices):
        RECEIVED = 'received', 'Received'
        PROCESSED = 'processed', 'Processed'
        FAILED = 'failed', 'Failed'
        IGNORED = 'ignored', 'Ignored'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source = models.CharField(max_length=20, choices=Source.choices)
    event_type = models.CharField(max_length=100)
    external_id = models.CharField(max_length=255, null=True, blank=True)
    signature = models.TextField(null=True, blank=True)
    payload = models.JSONField(default=dict)
    headers = models.JSONField(default=dict)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.RECEIVED,
    )
    processing_error = models.TextField(null=True, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'webhook_events'
        verbose_name = 'webhook event'
        verbose_name_plural = 'webhook events'
        indexes = [
            models.Index(
                fields=['status', 'received_at'],
                name='idx_webhook_status_received',
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['source', 'external_id'],
                condition=models.Q(external_id__isnull=False),
                name='unique_source_external_id',
            ),
        ]

    def __str__(self):
        return f'{self.source}:{self.event_type} ({self.status})'
