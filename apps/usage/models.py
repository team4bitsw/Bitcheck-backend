"""
Usage models — B2B API call logging.

The ApiCall model logs every API request for usage tracking,
billing, and debugging. Designed for write-heavy + range scans.

Ref: database design doc § 4.7
"""

import uuid
from django.db import models


class ApiCall(models.Model):
    """
    One row per B2B API request. Grows fast — designed for
    write-heavy inserts and time-range scans.

    The request_id is exposed in response headers for customer
    support. The idempotency_key enforces at-most-once processing
    per API key.

    Ref: database design doc § 4.7 — api_calls table.
    """

    class Modality(models.TextChoices):
        IMAGE = 'image', 'Image'
        VIDEO = 'video', 'Video'
        AUDIO = 'audio', 'Audio'
        DOCUMENT = 'document', 'Document'
        TEXT = 'text', 'Text'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        'accounts.Organization',
        on_delete=models.CASCADE,
        related_name='api_calls',
    )
    api_key = models.ForeignKey(
        'api_keys.ApiKey',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='api_calls',
    )

    endpoint = models.CharField(max_length=255)
    modality = models.CharField(
        max_length=20,
        choices=Modality.choices,
        null=True,
        blank=True,
    )
    http_status = models.IntegerField()
    bits_charged = models.IntegerField(default=0)
    latency_ms = models.IntegerField()

    # Exposed in X-Request-Id response header
    request_id = models.CharField(max_length=255, unique=True)

    # Client-supplied for at-most-once processing
    idempotency_key = models.CharField(max_length=255, null=True, blank=True)

    client_ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'api_calls'
        verbose_name = 'API call'
        verbose_name_plural = 'API calls'
        ordering = ['-created_at']
        indexes = [
            models.Index(
                fields=['organization', '-created_at'],
                name='idx_apicall_org_recent',
            ),
            models.Index(
                fields=['api_key', '-created_at'],
                name='idx_apicall_key_recent',
            ),
        ]
        constraints = [
            # Idempotency: unique per API key
            models.UniqueConstraint(
                fields=['api_key', 'idempotency_key'],
                condition=models.Q(idempotency_key__isnull=False),
                name='unique_idempotency_per_key',
            ),
        ]

    def __str__(self):
        return f'{self.endpoint} [{self.http_status}] ({self.request_id})'
