"""
Billing Celery tasks — subscription period rollover.

The rollover task runs hourly via Celery beat. It picks up all active
subscriptions whose current period has ended and:
  1. Resets the user's wallet (use-it-or-lose-it)
  2. Credits the new period's bit grant
  3. Advances the subscription period by one month

Ref: database design doc § 4.3 — period rollover logic.
"""

import logging
from celery import shared_task
from django.utils import timezone
from django.db import transaction

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_subscription_rollovers(self):
    """
    Hourly Celery beat task: find all active subscriptions whose
    current_period_end <= now() and process their rollover.

    Each subscription is processed independently so a failure on one
    doesn't block the others.
    """
    from apps.billing.models import Subscription
    from apps.bits.services import reset_and_grant, get_wallet_for_user

    now = timezone.now()

    # Find subscriptions that need rollover
    due_subscriptions = Subscription.objects.select_related(
        'user', 'plan',
    ).filter(
        status=Subscription.Status.ACTIVE,
        current_period_end__lte=now,
    )

    total = due_subscriptions.count()
    if total == 0:
        logger.info('No subscriptions due for rollover.')
        return {'processed': 0, 'errors': 0}

    logger.info(f'Processing {total} subscription rollovers...')

    processed = 0
    errors = 0

    for subscription in due_subscriptions:
        try:
            _rollover_single_subscription(subscription)
            processed += 1
        except Exception as e:
            errors += 1
            logger.error(
                f'Rollover failed for subscription {subscription.id} '
                f'(user={subscription.user.email}): {e}',
                exc_info=True,
            )

    logger.info(
        f'Rollover complete: {processed} processed, {errors} errors '
        f'out of {total} total.'
    )

    return {'processed': processed, 'errors': errors}


def _rollover_single_subscription(subscription):
    """
    Process rollover for a single subscription.

    Steps (in one transaction):
      1. Check if the user wants to cancel at period end
      2. If canceling: set status to 'canceled' and stop
      3. Otherwise: reset wallet + grant new bits + advance period

    Ref: database design doc § 4.3 — period rollover notes.
    """
    from apps.billing.models import Subscription
    from apps.bits.services import reset_and_grant, get_wallet_for_user

    user = subscription.user
    plan = subscription.plan

    with transaction.atomic():
        # Re-fetch with lock to prevent double-processing
        subscription = Subscription.objects.select_for_update().get(
            pk=subscription.pk,
        )

        # Guard: skip if already processed or no longer active
        if subscription.status != Subscription.Status.ACTIVE:
            logger.info(
                f'Skipping subscription {subscription.id}: '
                f'status is {subscription.status}'
            )
            return

        if subscription.current_period_end > timezone.now():
            logger.info(
                f'Skipping subscription {subscription.id}: '
                f'period not yet ended'
            )
            return

        # Handle cancel-at-period-end
        if subscription.cancel_at_period_end:
            subscription.status = Subscription.Status.CANCELED
            subscription.canceled_at = timezone.now()
            subscription.save(update_fields=[
                'status', 'canceled_at', 'updated_at',
            ])
            logger.info(
                f'Subscription {subscription.id} canceled at period end '
                f'for user {user.email}'
            )
            return

        # Get or create the user's wallet
        wallet = get_wallet_for_user(user)

        # Reset unused bits and grant new period's bits
        reset_and_grant(
            wallet_id=wallet.id,
            grant_amount=plan.monthly_grant_bits,
            subscription_id=subscription.id,
        )

        # Advance the subscription period
        subscription.advance_period()

        logger.info(
            f'Rolled over subscription {subscription.id} for {user.email}: '
            f'granted {plan.monthly_grant_bits} bits, '
            f'new period ends {subscription.current_period_end}'
        )
