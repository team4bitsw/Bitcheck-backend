"""
Billing admin — Plans & Subscriptions.
"""

from django.contrib import admin
from .models import Plan, Subscription


@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'monthly_grant_bits', 'recurring_charge_naira', 'billing_interval', 'is_active')
    list_filter = ('is_active', 'billing_interval')
    readonly_fields = ('id', 'created_at', 'updated_at')
    ordering = ('code',)


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('user', 'plan', 'status', 'current_period_start', 'current_period_end', 'cancel_at_period_end')
    list_filter = ('status', 'plan', 'cancel_at_period_end')
    search_fields = ('user__email', 'squad_subscription_id')
    readonly_fields = ('id', 'created_at', 'updated_at')
    ordering = ('-created_at',)
    raw_id_fields = ('user',)
