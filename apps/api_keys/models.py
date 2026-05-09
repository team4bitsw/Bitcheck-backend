"""
API Keys models — B2B API key management.

The ApiKey model stores hashed secrets with a displayable prefix.
Raw secrets are NEVER stored — they're shown once on creation and forgotten.

Auth flow (§ 4.5):
  1. Request comes in with `Authorization: Bearer bk_live_a8f3…full…secret`
  2. Extract prefix (first 12 chars), look up key by prefix
  3. Hash the full bearer string with SHA-256 + server pepper
  4. Constant-time compare against hashed_secret
  5. Reject if revoked_at IS NOT NULL
  6. Update last_used_at

Ref: database design doc § 4.5
"""

import hashlib
import hmac
import secrets
import uuid
from django.conf import settings
from django.db import models


class ApiKey(models.Model):
    """
    A hashed API key belonging to an Organization.

    The raw secret is generated once, returned to the user, and
    never stored. Only the SHA-256 hash (with pepper) is persisted.

    Ref: database design doc § 4.5 — api_keys table.
    """

    class Environment(models.TextChoices):
        TEST = 'test', 'Test'
        LIVE = 'live', 'Live'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        'accounts.Organization',
        on_delete=models.CASCADE,
        related_name='api_keys',
    )
    name = models.CharField(max_length=255)
    environment = models.CharField(
        max_length=10,
        choices=Environment.choices,
        default=Environment.TEST,
    )

    # The first 12 chars of the key — safe to display in UI
    prefix = models.CharField(max_length=20, unique=True)

    # SHA-256(full_secret + pepper) — hex digest
    hashed_secret = models.TextField()

    last_used_at = models.DateTimeField(null=True, blank=True)

    # Soft-delete: revoked keys remain for audit
    revoked_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'api_keys'
        verbose_name = 'API key'
        verbose_name_plural = 'API keys'
        indexes = [
            models.Index(
                fields=['organization', 'revoked_at'],
                name='idx_apikey_org_revoked',
            ),
        ]

    def __str__(self):
        status = 'revoked' if self.revoked_at else 'active'
        return f'{self.name} ({self.prefix}…) [{status}]'

    @property
    def is_active(self):
        return self.revoked_at is None

    # ============================================================
    # Key generation and hashing
    # ============================================================

    @staticmethod
    def _generate_raw_key(environment):
        """
        Generate a raw API key string.

        Format: bk_{env}_{32_random_hex_chars}
        Example: bk_live_a8f3b2c1d4e5f6a7b8c9d0e1f2a3b4c5

        Returns the full raw key string.
        """
        env_prefix = 'live' if environment == 'live' else 'test'
        random_part = secrets.token_hex(16)  # 32 hex chars
        return f'bk_{env_prefix}_{random_part}'

    @staticmethod
    def _extract_prefix(raw_key):
        """Extract the first 12 characters as the prefix."""
        return raw_key[:12]

    @staticmethod
    def _hash_secret(raw_key):
        """
        Hash the full key with SHA-256 and the server pepper.
        The pepper prevents rainbow table attacks if the DB is leaked.
        """
        pepper = settings.API_KEY_PEPPER
        salted = f'{raw_key}{pepper}'.encode('utf-8')
        return hashlib.sha256(salted).hexdigest()

    @staticmethod
    def _constant_time_compare(hash_a, hash_b):
        """Constant-time comparison to prevent timing attacks."""
        return hmac.compare_digest(hash_a, hash_b)

    @classmethod
    def create_key(cls, organization, name, environment='test', created_by=None):
        """
        Generate a new API key for an organization.

        Returns a tuple of (ApiKey instance, raw_secret).
        The raw_secret is shown once to the user and NEVER stored.
        """
        # Generate key, handle prefix collisions
        for _ in range(5):  # max 5 attempts
            raw_key = cls._generate_raw_key(environment)
            prefix = cls._extract_prefix(raw_key)

            if not cls.objects.filter(prefix=prefix).exists():
                break
        else:
            raise RuntimeError('Failed to generate unique API key prefix after 5 attempts')

        hashed = cls._hash_secret(raw_key)

        api_key = cls.objects.create(
            organization=organization,
            name=name,
            environment=environment,
            prefix=prefix,
            hashed_secret=hashed,
            created_by=created_by,
        )

        return api_key, raw_key

    @classmethod
    def authenticate(cls, raw_key):
        """
        Authenticate a raw API key string.

        Returns the ApiKey instance if valid, None otherwise.

        Steps:
          1. Extract prefix
          2. Look up by prefix
          3. Hash and constant-time compare
          4. Check if revoked
        """
        if not raw_key or len(raw_key) < 12:
            return None

        prefix = cls._extract_prefix(raw_key)

        try:
            api_key = cls.objects.select_related('organization').get(prefix=prefix)
        except cls.DoesNotExist:
            # Hash anyway to prevent timing attacks
            cls._hash_secret(raw_key)
            return None

        # Check if revoked
        if api_key.revoked_at is not None:
            return None

        # Constant-time hash comparison
        provided_hash = cls._hash_secret(raw_key)
        if not cls._constant_time_compare(provided_hash, api_key.hashed_secret):
            return None

        return api_key
