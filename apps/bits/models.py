"""
Bits models — Unified bit-token accounting layer.

Models:
  - TokenWallet:      1:1 with either a User (B2C) or Organization (B2B).
                      XOR ownership enforced at model + DB level.
  - TokenLedgerEntry: Append-only audit trail. Every credit/debit is one row.
  - VirtualAccount:   1:1 with Organization. Squad virtual bank account for B2B top-ups.
  - TopUp:            One row per credited bank transfer to a B2B virtual account.

Ref: database design doc § 4.4, § 6 (money handling rules)
"""

import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


# ============================================================
# TokenWallet
# ============================================================

class TokenWallet(models.Model):
    """
    A single wallet holding bit tokens. Owned by EITHER a User (B2C)
    or an Organization (B2B) — never both, never neither.

    balance_bits is a materialized balance updated transactionally
    with every ledger entry. Use select_for_update() to prevent races.

    Ref: database design doc § 4.4 — token_wallets table.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # XOR ownership: exactly one of these must be set
    owner_user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='token_wallet',
    )
    owner_organization = models.OneToOneField(
        'accounts.Organization',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='token_wallet',
    )

    balance_bits = models.BigIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'token_wallets'
        verbose_name = 'token wallet'
        verbose_name_plural = 'token wallets'
        constraints = [
            # XOR: exactly one owner must be set
            models.CheckConstraint(
                condition=(
                    models.Q(owner_user__isnull=False, owner_organization__isnull=True)
                    | models.Q(owner_user__isnull=True, owner_organization__isnull=False)
                ),
                name='wallet_xor_owner',
            ),
            # Balance must never go negative
            models.CheckConstraint(
                condition=models.Q(balance_bits__gte=0),
                name='wallet_non_negative_balance',
            ),
        ]

    def __str__(self):
        owner = self.owner_user or self.owner_organization
        return f'Wallet({owner}) — {self.balance_bits} bits'

    def clean(self):
        """Enforce XOR ownership at the application level."""
        super().clean()
        has_user = self.owner_user_id is not None
        has_org = self.owner_organization_id is not None

        if has_user == has_org:
            raise ValidationError(
                'A wallet must belong to exactly one owner: '
                'either a User or an Organization, not both and not neither.'
            )

    @property
    def owner(self):
        """Return the owning entity (User or Organization)."""
        return self.owner_user or self.owner_organization

    @property
    def owner_type(self):
        """Return 'user' or 'organization'."""
        if self.owner_user_id:
            return 'user'
        return 'organization'


# ============================================================
# TokenLedgerEntry
# ============================================================

class TokenLedgerEntry(models.Model):
    """
    Append-only audit trail for all wallet changes.

    Every credit and debit — subscription grant, top-up, verification
    usage, adjustment, refund — is exactly one row. Never deleted,
    never updated.

    Ref: database design doc § 4.4 — token_ledger_entries table.
    """

    class EntryType(models.TextChoices):
        SUBSCRIPTION_GRANT = 'subscription_grant', 'Subscription Grant'
        PERIOD_RESET = 'period_reset', 'Period Reset'
        TOPUP = 'topup', 'Top-Up'
        USAGE = 'usage', 'Usage'
        ADJUSTMENT = 'adjustment', 'Adjustment'
        REFUND = 'refund', 'Refund'

    # BigAutoField (bigserial) — internal-only, high-write table
    id = models.BigAutoField(primary_key=True)

    wallet = models.ForeignKey(
        TokenWallet,
        on_delete=models.RESTRICT,
        related_name='ledger_entries',
    )

    delta_bits = models.BigIntegerField()
    balance_after_bits = models.BigIntegerField()

    entry_type = models.CharField(max_length=30, choices=EntryType.choices)

    # Loose reference to the source entity (avoids cross-app FK soup)
    reference_type = models.CharField(max_length=50, null=True, blank=True)
    reference_id = models.CharField(max_length=255, null=True, blank=True)

    note = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )

    class Meta:
        db_table = 'token_ledger_entries'
        verbose_name = 'token ledger entry'
        verbose_name_plural = 'token ledger entries'
        ordering = ['-created_at']
        indexes = [
            models.Index(
                fields=['wallet', '-created_at'],
                name='idx_ledger_wallet_recent',
            ),
            models.Index(
                fields=['reference_type', 'reference_id'],
                name='idx_ledger_reference',
            ),
        ]
        constraints = [
            # Delta must never be zero
            models.CheckConstraint(
                condition=~models.Q(delta_bits=0),
                name='ledger_non_zero_delta',
            ),
            # Balance snapshot must be non-negative
            models.CheckConstraint(
                condition=models.Q(balance_after_bits__gte=0),
                name='ledger_non_negative_balance_after',
            ),
        ]

    def __str__(self):
        sign = '+' if self.delta_bits > 0 else ''
        return f'{self.entry_type}: {sign}{self.delta_bits} bits (→ {self.balance_after_bits})'


# ============================================================
# VirtualAccount
# ============================================================

class VirtualAccount(models.Model):
    """
    A Squad virtual bank account, 1:1 with an Organization.
    Created at org-signup time via Squad API. B2B only.

    Ref: database design doc § 4.4 — virtual_accounts table.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.OneToOneField(
        'accounts.Organization',
        on_delete=models.CASCADE,
        related_name='virtual_account',
    )
    bank_name = models.CharField(max_length=100)
    account_number = models.CharField(max_length=20, unique=True)
    account_name = models.CharField(max_length=255)
    squad_account_reference = models.CharField(max_length=255, unique=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'virtual_accounts'
        verbose_name = 'virtual account'
        verbose_name_plural = 'virtual accounts'

    def __str__(self):
        return f'{self.account_name} ({self.account_number})'


# ============================================================
# TopUp
# ============================================================

class TopUp(models.Model):
    """
    One row per credited bank transfer to a B2B virtual account.

    Idempotency is enforced via the unique squad_transaction_reference.
    Re-processing the same webhook is a no-op.

    Ref: database design doc § 4.4 — top_ups table.
    """

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        CREDITED = 'credited', 'Credited'
        FAILED = 'failed', 'Failed'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    organization = models.ForeignKey(
        'accounts.Organization',
        on_delete=models.CASCADE,
        related_name='topups',
    )
    virtual_account = models.ForeignKey(
        VirtualAccount,
        on_delete=models.RESTRICT,
        related_name='topups',
    )

    # Financial fields — all in whole naira / bit tokens
    amount_naira = models.BigIntegerField()
    bits_credited = models.BigIntegerField()
    rate_naira_per_bit = models.PositiveIntegerField()

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    # Squad reference — unique for idempotency
    squad_transaction_reference = models.CharField(max_length=255, unique=True)

    # Link to the webhook event that created this row
    webhook_event = models.ForeignKey(
        'webhooks.WebhookEvent',
        on_delete=models.RESTRICT,
        related_name='topups',
    )

    credited_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'top_ups'
        verbose_name = 'top-up'
        verbose_name_plural = 'top-ups'
        indexes = [
            models.Index(
                fields=['organization', '-created_at'],
                name='idx_topup_org_recent',
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount_naira__gt=0),
                name='topup_positive_naira',
            ),
            models.CheckConstraint(
                condition=models.Q(bits_credited__gt=0),
                name='topup_positive_bits',
            ),
            models.CheckConstraint(
                condition=models.Q(rate_naira_per_bit__gt=0),
                name='topup_positive_rate',
            ),
        ]

    def __str__(self):
        return f'TopUp ₦{self.amount_naira} → {self.bits_credited} bits ({self.status})'
