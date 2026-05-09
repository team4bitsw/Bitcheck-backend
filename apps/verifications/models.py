"""
Verifications models — core domain.

Models:
  - UploadedFile:     S3 storage reference with XOR ownership.
  - Verification:     The core entity — one row per verification job.
  - VerificationJob:  1:1 with Verification — tracks ML queue state
                      and stores raw ML response.

Ref: database design doc § 4.6
"""

import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


# ============================================================
# UploadedFile
# ============================================================

class UploadedFile(models.Model):
    """
    Storage reference for an uploaded file. The actual file lives
    in S3-compatible object storage; this table keeps the key.

    XOR ownership: exactly one of owner_user or owner_organization.

    Ref: database design doc § 4.6 — uploaded_files table.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # XOR ownership
    owner_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='uploaded_files',
    )
    owner_organization = models.ForeignKey(
        'accounts.Organization',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='uploaded_files',
    )

    # Storage location
    bucket = models.CharField(max_length=255)
    storage_key = models.CharField(max_length=500)
    mime_type = models.CharField(max_length=100)
    size_bytes = models.BigIntegerField()
    sha256 = models.CharField(max_length=64)
    original_filename = models.CharField(max_length=500, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'uploaded_files'
        verbose_name = 'uploaded file'
        verbose_name_plural = 'uploaded files'
        indexes = [
            models.Index(fields=['owner_user'], name='idx_file_owner_user'),
            models.Index(fields=['owner_organization'], name='idx_file_owner_org'),
            models.Index(fields=['sha256'], name='idx_file_sha256'),
        ]
        constraints = [
            # XOR ownership
            models.CheckConstraint(
                condition=(
                    models.Q(owner_user__isnull=False, owner_organization__isnull=True)
                    | models.Q(owner_user__isnull=True, owner_organization__isnull=False)
                ),
                name='file_xor_owner',
            ),
            models.CheckConstraint(
                condition=models.Q(size_bytes__gt=0),
                name='file_positive_size',
            ),
        ]

    def __str__(self):
        name = self.original_filename or self.storage_key
        return f'{name} ({self.mime_type})'


# ============================================================
# Verification
# ============================================================

class Verification(models.Model):
    """
    The core domain entity. One row per verification job,
    regardless of B2C or B2B origin.

    XOR ownership: exactly one of user (B2C) or organization (B2B).
    XOR input: exactly one of uploaded_file or text_input.

    Ref: database design doc § 4.6 — verifications table.
    """

    class Modality(models.TextChoices):
        IMAGE = 'image', 'Image'
        VIDEO = 'video', 'Video'
        AUDIO = 'audio', 'Audio'
        DOCUMENT = 'document', 'Document'
        TEXT = 'text', 'Text'

    class Status(models.TextChoices):
        QUEUED = 'queued', 'Queued'
        ANALYZING = 'analyzing', 'Analyzing'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'
        CANCELED = 'canceled', 'Canceled'

    class Verdict(models.TextChoices):
        AUTHENTIC = 'authentic', 'Authentic'
        SUSPICIOUS = 'suspicious', 'Suspicious'
        MANIPULATED = 'manipulated', 'Manipulated'
        INCONCLUSIVE = 'inconclusive', 'Inconclusive'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # XOR ownership
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='verifications',
    )
    organization = models.ForeignKey(
        'accounts.Organization',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='verifications',
    )

    # B2B tracing
    api_key = models.ForeignKey(
        'api_keys.ApiKey',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verifications',
    )
    api_call = models.ForeignKey(
        'usage.ApiCall',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verifications',
    )

    # Input — XOR: file or text
    uploaded_file = models.ForeignKey(
        UploadedFile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verifications',
    )
    text_input = models.TextField(null=True, blank=True)

    # Classification
    modality = models.CharField(max_length=20, choices=Modality.choices)
    bits_charged = models.IntegerField(default=0)

    # Status + results
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.QUEUED,
    )
    trust_score = models.IntegerField(null=True, blank=True)
    verdict = models.CharField(
        max_length=20,
        choices=Verdict.choices,
        null=True,
        blank=True,
    )
    result_summary = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(null=True, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'verifications'
        verbose_name = 'verification'
        verbose_name_plural = 'verifications'
        ordering = ['-created_at']
        indexes = [
            models.Index(
                fields=['user', '-created_at'],
                condition=models.Q(deleted_at__isnull=True),
                name='idx_verif_user_recent',
            ),
            models.Index(
                fields=['organization', '-created_at'],
                condition=models.Q(deleted_at__isnull=True),
                name='idx_verif_org_recent',
            ),
            models.Index(
                fields=['status'],
                condition=models.Q(status__in=['queued', 'analyzing']),
                name='idx_verif_active_queue',
            ),
        ]
        constraints = [
            # XOR ownership: exactly one of user or organization
            models.CheckConstraint(
                condition=(
                    models.Q(user__isnull=False, organization__isnull=True)
                    | models.Q(user__isnull=True, organization__isnull=False)
                ),
                name='verif_xor_owner',
            ),
            # Trust score range
            models.CheckConstraint(
                condition=(
                    models.Q(trust_score__isnull=True)
                    | (models.Q(trust_score__gte=0) & models.Q(trust_score__lte=100))
                ),
                name='verif_trust_score_range',
            ),
            # B2B-only fields require organization
            models.CheckConstraint(
                condition=(
                    models.Q(api_key__isnull=True)
                    | models.Q(organization__isnull=False)
                ),
                name='verif_api_key_requires_org',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(api_call__isnull=True)
                    | models.Q(organization__isnull=False)
                ),
                name='verif_api_call_requires_org',
            ),
        ]

    def __str__(self):
        owner = self.user or self.organization
        return f'{self.modality} verification [{self.status}] by {owner}'

    @property
    def cost_bits(self):
        """Get the bit cost for this verification's modality."""
        return settings.BITCHECK_VERIFICATION_COSTS.get(self.modality, 0)

    @staticmethod
    def derive_verdict(trust_score):
        """
        Derive a verdict from the trust score.

        Thresholds (from PRD):
          0-30:   manipulated
          31-60:  suspicious
          61-85:  inconclusive
          86-100: authentic
        """
        if trust_score is None:
            return None
        if trust_score >= 86:
            return Verification.Verdict.AUTHENTIC
        elif trust_score >= 61:
            return Verification.Verdict.INCONCLUSIVE
        elif trust_score >= 31:
            return Verification.Verdict.SUSPICIOUS
        else:
            return Verification.Verdict.MANIPULATED


# ============================================================
# VerificationJob
# ============================================================

class VerificationJob(models.Model):
    """
    1:1 with Verification. Tracks ML queue state and stores the
    raw ML response separately so the user-facing verifications
    table stays clean.

    Ref: database design doc § 4.6 — verification_jobs table.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    verification = models.OneToOneField(
        Verification,
        on_delete=models.CASCADE,
        related_name='job',
    )

    celery_task_id = models.CharField(max_length=255, null=True, blank=True)
    attempts = models.IntegerField(default=0)
    last_error = models.TextField(null=True, blank=True)

    ml_endpoint = models.CharField(max_length=500, null=True, blank=True)
    ml_response_raw = models.JSONField(default=dict, blank=True)

    enqueued_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'verification_jobs'
        verbose_name = 'verification job'
        verbose_name_plural = 'verification jobs'
        indexes = [
            models.Index(fields=['celery_task_id'], name='idx_job_celery_task'),
        ]

    def __str__(self):
        return f'Job for {self.verification_id} (attempts={self.attempts})'
