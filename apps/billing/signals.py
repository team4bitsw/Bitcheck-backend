"""
Billing signals — auto-provisioning on user signup.

When a new user is created, we automatically:
  1. Create a TokenWallet for them (B2C, balance 0)
  2. Create a free-plan Subscription
  3. Credit the free plan's monthly_grant_bits to their wallet

This ensures every user starts with a wallet and a subscription
from the moment they register.

Ref: database design doc § 4.4 — wallet lifecycle.
"""

import logging
from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def provision_new_user(sender, instance, created, **kwargs):
    """
    On user creation: create wallet → create free subscription →
    credit initial bits.
    """
    if not created:
        return

    from apps.billing.models import Plan, Subscription
    from apps.bits.services import get_wallet_for_user, credit_wallet

    try:
        with transaction.atomic():
            # 1. Create wallet
            wallet = get_wallet_for_user(instance)

            # 2. Create free subscription
            try:
                subscription = Subscription.create_free_subscription(instance)
            except Plan.DoesNotExist:
                # Plans haven't been seeded yet (e.g., during initial migration)
                logger.warning(
                    f'Free plan not found — skipping subscription for user '
                    f'{instance.email}. Run the seed migration first.'
                )
                return

            # 3. Credit initial bits
            if subscription.plan.monthly_grant_bits > 0:
                credit_wallet(
                    wallet_id=wallet.id,
                    amount=subscription.plan.monthly_grant_bits,
                    entry_type='subscription_grant',
                    reference_type='subscription',
                    reference_id=str(subscription.id),
                    note=f'Welcome grant: {subscription.plan.monthly_grant_bits} bits ({subscription.plan.name} plan)',
                )

            logger.info(
                f'Provisioned new user {instance.email}: '
                f'wallet={wallet.id}, subscription={subscription.plan.name}, '
                f'bits={subscription.plan.monthly_grant_bits}'
            )

    except Exception as e:
        logger.error(
            f'Failed to provision new user {instance.email}: {e}',
            exc_info=True,
        )
