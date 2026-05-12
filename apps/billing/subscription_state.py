"""
Keep per-user subscription rows consistent when Pro checkout is abandoned or stalls.

- ``incomplete`` rows expire after :setting:`BILLING_INCOMPLETE_CHECKOUT_TTL_HOURS`.
- Starting a new upgrade abandons any current ``incomplete`` rows and ensures a free
  plan row exists before the normal cancel-free → create-incomplete flow runs.
- Canceled incompletes clear ``squad_subscription_id`` so a late Squad webhook does
  not resurrect the wrong row.
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.billing.models import Plan, Subscription

logger = logging.getLogger(__name__)


def _incomplete_ttl_cutoff():
    hours = getattr(settings, 'BILLING_INCOMPLETE_CHECKOUT_TTL_HOURS', 24)
    try:
        hours = int(hours)
    except (TypeError, ValueError):
        hours = 24
    return timezone.now() - timedelta(hours=hours)


def _cancel_incomplete_rows(queryset):
    """Mark rows canceled and drop squad ref so webhooks cannot reactivate them."""
    now = timezone.now()
    for sub in queryset:
        sub.status = Subscription.Status.CANCELED
        sub.canceled_at = now
        sub.squad_subscription_id = None
        sub.save(
            update_fields=[
                'status',
                'canceled_at',
                'squad_subscription_id',
                'updated_at',
            ],
        )


def _user_has_active_like(user) -> bool:
    return Subscription.objects.filter(
        user=user,
        status__in=[
            Subscription.Status.ACTIVE,
            Subscription.Status.PAST_DUE,
            Subscription.Status.PAUSED,
        ],
    ).exists()


def _user_has_incomplete(user) -> bool:
    return Subscription.objects.filter(
        user=user,
        status=Subscription.Status.INCOMPLETE,
    ).exists()


def _ensure_free_subscription(user):
    """Create an active free row when the user has no billable subscription."""
    try:
        Subscription.create_free_subscription(user)
    except Plan.DoesNotExist:
        logger.warning(
            'Free plan missing — cannot restore subscription for %s',
            getattr(user, 'email', user.pk),
        )
    except IntegrityError:
        logger.debug(
            'Skip creating free subscription for %s (already exists)',
            getattr(user, 'email', user.pk),
        )


def reconcile_stale_incomplete_subscriptions(user):
    """
    Expire ``incomplete`` checkouts older than the configured TTL.

    If the user ends up with no active-like subscription and no remaining
    ``incomplete`` row, create a free subscription (checkout fully abandoned).
    """
    cutoff = _incomplete_ttl_cutoff()
    stale = Subscription.objects.filter(
        user=user,
        status=Subscription.Status.INCOMPLETE,
        created_at__lt=cutoff,
    )
    if stale.exists():
        with transaction.atomic():
            _cancel_incomplete_rows(stale.select_for_update())

    if not _user_has_active_like(user) and not _user_has_incomplete(user):
        with transaction.atomic():
            if not _user_has_active_like(user) and not _user_has_incomplete(user):
                _ensure_free_subscription(user)


def prepare_new_pro_checkout(user):
    """
    Run before initiating Squad checkout: TTL cleanup, cancel all open incompletes,
    then ensure there is an active free plan to upgrade from.

    Call inside ``upgrade_subscription_view`` after auth checks and before
    ``initiate_pro_checkout``.
    """
    reconcile_stale_incomplete_subscriptions(user)

    open_incomplete = Subscription.objects.filter(
        user=user,
        status=Subscription.Status.INCOMPLETE,
    )
    if open_incomplete.exists():
        with transaction.atomic():
            _cancel_incomplete_rows(
                open_incomplete.select_for_update(),
            )

    if not _user_has_active_like(user):
        with transaction.atomic():
            if not _user_has_active_like(user):
                _ensure_free_subscription(user)
