"""
Billing views — plan listing, subscription management, and Pro upgrade.

Endpoints:
  GET  /api/billing/plans/                  — list all active plans
  GET  /api/billing/subscription/           — subscription + wallet (``subscription`` may be null or ``incomplete``)
  POST /api/billing/subscription/upgrade/   — initiate Pro upgrade (Squad checkout)
  POST /api/billing/subscription/cancel/    — set cancel_at_period_end flag
"""

from datetime import timedelta

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from django.utils import timezone

from .models import Plan, Subscription
from .serializers import PlanSerializer, SubscriptionSerializer
from .services import initiate_pro_checkout, cancel_card_token


@api_view(['GET'])
@permission_classes([AllowAny])
def plan_list_view(request):
    """
    List all active plans. Public endpoint for the pricing page.
    """
    plans = Plan.objects.filter(is_active=True).order_by('recurring_charge_naira')
    serializer = PlanSerializer(plans, many=True)
    return Response({'plans': serializer.data})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def subscription_detail_view(request):
    """
    Get the current user's subscription with plan details and wallet balance.

    Returns 200 always (authenticated). Includes an ``incomplete`` row while
    Squad checkout is finishing so the client can poll without hitting 404
    after the free plan row was canceled.

    If the user has no subscription rows (provisioning edge cases), returns
    ``subscription: null`` with their B2C wallet.
    """
    from apps.bits.services import get_wallet_for_user

    qs = Subscription.objects.select_related('plan').filter(user=request.user)

    subscription = qs.filter(
        status__in=[
            Subscription.Status.ACTIVE,
            Subscription.Status.PAST_DUE,
            Subscription.Status.PAUSED,
        ],
    ).first()

    if not subscription:
        subscription = qs.filter(
            status=Subscription.Status.INCOMPLETE,
        ).order_by('-created_at').first()

    wallet = get_wallet_for_user(request.user)

    payload = {
        'subscription': SubscriptionSerializer(subscription).data
        if subscription
        else None,
        'wallet': {
            'id': str(wallet.id),
            'balance_bits': wallet.balance_bits,
        },
    }
    return Response(payload)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def upgrade_subscription_view(request):
    """
    Initiate a Pro plan upgrade via Squad card tokenization.

    Flow:
      1. Validate user isn't already on Pro
      2. Cancel their free subscription
      3. Create an 'incomplete' Pro subscription
      4. Call Squad's /transaction/initiate with is_recurring=True
      5. Return the checkout_url → frontend redirects user to Squad

    After payment, Squad sends a charge_successful webhook with token_id.
    Our webhook handler activates the subscription and credits bits.
    """
    user = request.user

    # Check: already on Pro?
    active_sub = Subscription.objects.select_related('plan').filter(
        user=user,
        status__in=['active', 'past_due', 'paused'],
    ).first()

    if active_sub and active_sub.plan.code == Plan.Code.PRO:
        return Response(
            {'detail': 'You are already on the Pro plan.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Get callback_url from the frontend (where to redirect after payment)
    callback_url = request.data.get('callback_url', '')

    try:
        result = initiate_pro_checkout(user, callback_url=callback_url)
    except ValueError as e:
        return Response(
            {'detail': str(e)},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    # Cancel the old free subscription
    if active_sub and active_sub.plan.is_free:
        active_sub.status = Subscription.Status.CANCELED
        active_sub.canceled_at = timezone.now()
        active_sub.save(update_fields=['status', 'canceled_at', 'updated_at'])

    # Create an incomplete Pro subscription (activated by webhook)
    pro_plan = Plan.objects.get(code=Plan.Code.PRO)
    now = timezone.now()

    incomplete_sub = Subscription.objects.create(
        user=user,
        plan=pro_plan,
        status=Subscription.Status.INCOMPLETE,
        squad_subscription_id=result['transaction_ref'],
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
    )

    return Response({
        'checkout_url': result['checkout_url'],
        'transaction_ref': result['transaction_ref'],
        'subscription_id': str(incomplete_sub.id),
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def cancel_subscription_view(request):
    """
    Set the cancel_at_period_end flag on the user's active subscription.
    The subscription will remain active until the current period ends,
    then be canceled by the rollover task.

    If a Squad card token exists, it is also canceled so we can no longer
    charge the card.
    """
    subscription = Subscription.objects.filter(
        user=request.user,
        status__in=['active', 'past_due', 'paused'],
    ).first()

    if not subscription:
        return Response(
            {'detail': 'No active subscription to cancel.'},
            status=status.HTTP_404_NOT_FOUND,
        )

    if subscription.plan.is_free:
        return Response(
            {'detail': 'Cannot cancel the free plan.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    subscription.cancel_at_period_end = True
    subscription.canceled_at = timezone.now()
    subscription.save(update_fields=[
        'cancel_at_period_end', 'canceled_at', 'updated_at',
    ])

    # Cancel the Squad card token so we can't charge them again
    if subscription.squad_card_token_id:
        cancel_card_token(subscription.squad_card_token_id)

    return Response({
        'detail': 'Subscription will be canceled at the end of the current period.',
        'subscription': SubscriptionSerializer(subscription).data,
    })

