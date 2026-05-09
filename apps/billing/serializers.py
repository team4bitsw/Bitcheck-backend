"""
Billing serializers — Plans & Subscriptions.
"""

from rest_framework import serializers
from .models import Plan, Subscription


class PlanSerializer(serializers.ModelSerializer):
    """Read-only plan representation for the pricing page."""

    class Meta:
        model = Plan
        fields = [
            'id', 'code', 'name', 'recurring_charge_naira',
            'monthly_grant_bits', 'billing_interval', 'is_active',
        ]
        read_only_fields = fields


class SubscriptionSerializer(serializers.ModelSerializer):
    """Subscription details for the user dashboard."""

    plan = PlanSerializer(read_only=True)

    class Meta:
        model = Subscription
        fields = [
            'id', 'plan', 'status',
            'current_period_start', 'current_period_end',
            'cancel_at_period_end', 'canceled_at',
            'created_at', 'updated_at',
        ]
        read_only_fields = fields


class SubscriptionSummarySerializer(serializers.ModelSerializer):
    """Compact subscription view (no nested plan)."""

    plan_code = serializers.CharField(source='plan.code', read_only=True)
    plan_name = serializers.CharField(source='plan.name', read_only=True)

    class Meta:
        model = Subscription
        fields = [
            'id', 'plan_code', 'plan_name', 'status',
            'current_period_start', 'current_period_end',
            'cancel_at_period_end',
        ]
        read_only_fields = fields
