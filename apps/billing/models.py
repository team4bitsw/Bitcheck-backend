"""
Billing models — Plans & Subscriptions (B2C).

Models:
  - Plan:         Static catalog of subscription tiers (free, pro).
                  Seeded via data migration, not user-created.
  - Subscription: One row per (user, plan) lifecycle. Tracks billing
                  periods, Squad mandate, and status.

Ref: database design doc § 4.3
"""

import uuid
from datetime import timedelta
from django.conf import settings
from django.db import models
from django.utils import timezone


# ============================================================
# Plan
# ============================================================

class Plan(models.Model):
    """
    A subscription plan defining the monthly bit-token grant and
    recurring charge.

    Static catalog — seeded via data migration. Plans are never
    created by users.

    Ref: database design doc § 4.3 — plans table.
    """

    class Code(models.TextChoices):
        FREE = 'free', 'Free'
        PRO = 'pro', 'Pro'

    class BillingInterval(models.TextChoices):
        NONE = 'none', 'None'
        MONTHLY = 'monthly', 'Monthly'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=20, unique=True, choices=Code.choices)
    name = models.CharField(max_length=100)

    # Financial
    recurring_charge_naira = models.BigIntegerField(
        default=0,
        help_text='Whole-naira amount Squad debits per period. 0 for free.',
    )
    monthly_grant_bits = models.BigIntegerField(
        help_text='Bit tokens credited to the user wallet at the start of each period.',
    )
    billing_interval = models.CharField(
        max_length=20,
        choices=BillingInterval.choices,
        default=BillingInterval.NONE,
    )

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'plans'
        verbose_name = 'plan'
        verbose_name_plural = 'plans'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(monthly_grant_bits__gte=0),
                name='plan_non_negative_grant',
            ),
        ]

    def __str__(self):
        return f'{self.name} ({self.code})'

    @property
    def is_free(self):
        return self.code == self.Code.FREE

    @property
    def charge_kobo_for_squad(self):
        """Convert naira to kobo for the Squad API boundary."""
        return self.recurring_charge_naira * 100


# ============================================================
# Subscription
# ============================================================

class Subscription(models.Model):
    """
    A user's subscription lifecycle. One row per (user, plan) attempt.

    The 'current' subscription for a user is the row with status in
    ('active', 'past_due', 'paused'). A partial unique index enforces
    at most one such row per user.

    Ref: database design doc § 4.3 — subscriptions table.
    """

    class Status(models.TextChoices):
        INCOMPLETE = 'incomplete', 'Incomplete'
        ACTIVE = 'active', 'Active'
        PAST_DUE = 'past_due', 'Past Due'
        CANCELED = 'canceled', 'Canceled'
        PAUSED = 'paused', 'Paused'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='subscriptions',
    )
    plan = models.ForeignKey(
        Plan,
        on_delete=models.RESTRICT,
        related_name='subscriptions',
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )

    # Period tracking
    current_period_start = models.DateTimeField()
    current_period_end = models.DateTimeField()

    # Cancellation
    cancel_at_period_end = models.BooleanField(default=False)
    canceled_at = models.DateTimeField(null=True, blank=True)

    # Squad integration (Pro plans only)
    squad_subscription_id = models.CharField(
        max_length=255, null=True, blank=True, unique=True,
    )
    squad_customer_id = models.CharField(
        max_length=255, null=True, blank=True,
    )
    squad_card_token_id = models.CharField(
        max_length=255, null=True, blank=True,
        help_text='Card token from Squad for recurring charges (returned via webhook).',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'subscriptions'
        verbose_name = 'subscription'
        verbose_name_plural = 'subscriptions'
        indexes = [
            models.Index(
                fields=['user', 'status'],
                name='idx_sub_user_status',
            ),
        ]
        constraints = [
            # At most one active/past_due/paused subscription per user
            models.UniqueConstraint(
                fields=['user'],
                condition=models.Q(
                    status__in=['active', 'past_due', 'paused']
                ),
                name='one_active_sub_per_user',
            ),
        ]

    def __str__(self):
        return f'{self.user.email} → {self.plan.name} ({self.status})'

    @property
    def is_current(self):
        """Is this subscription in an active-ish state?"""
        return self.status in (
            self.Status.ACTIVE,
            self.Status.PAST_DUE,
            self.Status.PAUSED,
        )

    def advance_period(self):
        """
        Move the billing period forward by one month.
        Call this during subscription rollover.
        """
        self.current_period_start = self.current_period_end
        self.current_period_end = self.current_period_end + timedelta(days=30)
        self.save(update_fields=[
            'current_period_start', 'current_period_end', 'updated_at',
        ])

    @classmethod
    def create_free_subscription(cls, user):
        """
        Create an active free-plan subscription for a new user.

        Called during user signup. Sets period to now → +30 days.
        """
        free_plan = Plan.objects.get(code=Plan.Code.FREE)
        now = timezone.now()

        return cls.objects.create(
            user=user,
            plan=free_plan,
            status=cls.Status.ACTIVE,
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
        )
