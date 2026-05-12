"""
Bits URL configuration — B2B virtual account and wallet endpoints.

All routes are mounted under /api/bits/ by the root urlconf.
"""

from django.urls import path
from . import views

app_name = 'bits'

urlpatterns = [
    # Virtual Account provisioning & detail
    path('virtual-account/provision/', views.provision_virtual_account_view, name='va-provision'),
    path('virtual-account/', views.virtual_account_detail_view, name='va-detail'),
    path('virtual-account/simulate-payment/', views.simulate_va_payment_view, name='va-simulate'),

    # Wallet balance & top-up history
    path('wallet/', views.wallet_detail_view, name='wallet-detail'),
]
