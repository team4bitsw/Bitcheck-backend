"""
Billing URL configuration.

All routes are mounted under /api/billing/ by the root urlconf.
"""

from django.urls import path
from . import views

app_name = 'billing'

urlpatterns = [
    path('plans/', views.plan_list_view, name='plan-list'),
    path('subscription/', views.subscription_detail_view, name='subscription-detail'),
    path('subscription/cancel/', views.cancel_subscription_view, name='subscription-cancel'),
]
