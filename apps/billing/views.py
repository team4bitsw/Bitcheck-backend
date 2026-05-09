"""
Billing views — plan listing and subscription management.

Endpoints:
  GET  /api/billing/plans/          — list all active plans
  GET  /api/billing/subscription/   — current user's active subscription
  POST /api/billing/subscription/cancel/ — set cancel_at_period_end flag
"""

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .models import Plan, Subscription
from .serializers import PlanSerializer, SubscriptionSerializer


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
    Get the current user's active subscription with plan details
    and wallet balance.
    """
    from apps.bits.services import get_wallet_for_user

    subscription = Subscription.objects.select_related('plan').filter(
        user=request.user,
        status__in=['active', 'past_due', 'paused'],
    ).first()

    if not subscription:
        return Response(
            {'detail': 'No active subscription found.'},
            status=status.HTTP_404_NOT_FOUND,
        )

    wallet = get_wallet_for_user(request.user)

    return Response({
        'subscription': SubscriptionSerializer(subscription).data,
        'wallet': {
            'id': str(wallet.id),
            'balance_bits': wallet.balance_bits,
        },
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def cancel_subscription_view(request):
    """
    Set the cancel_at_period_end flag on the user's active subscription.
    The subscription will remain active until the current period ends,
    then be canceled by the rollover task.
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

    from django.utils import timezone
    subscription.cancel_at_period_end = True
    subscription.canceled_at = timezone.now()
    subscription.save(update_fields=[
        'cancel_at_period_end', 'canceled_at', 'updated_at',
    ])

    return Response({
        'detail': 'Subscription will be canceled at the end of the current period.',
        'subscription': SubscriptionSerializer(subscription).data,
    })
