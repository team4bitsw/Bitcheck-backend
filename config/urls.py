"""
Root URL configuration for Bitcheck / ProofChain AI.

All API routes are namespaced under /api/.
"""

from django.contrib import admin
from django.urls import path, include
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)


@api_view(['GET'])
@permission_classes([AllowAny])
def health_check(request):
    """Basic health check endpoint for uptime monitoring."""
    return Response({'status': 'ok', 'service': 'bitcheck-api'})


urlpatterns = [
    # Admin
    path('admin/', admin.site.urls),

    # Health check
    path('api/health/', health_check, name='health-check'),

    # Phase 1 — Identity & Access
    path('api/auth/', include('apps.accounts.urls')),

    # Phase 3 — B2C Subscriptions
    path('api/billing/', include('apps.billing.urls')),

    # Phase 4 — B2B API Infrastructure
    path('api/keys/', include('apps.api_keys.urls')),

    # Phase 5 — Verifications Core
    path('api/verifications/', include('apps.verifications.urls')),

    # Connectors (catalogue, installs, inbound webhooks)
    path('api/connectors/', include('apps.connectors.urls')),

    # Phase 6 — Webhooks
    path('api/webhooks/', include('apps.webhooks.urls')),

    # API Documentation (Swagger / ReDoc)
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),

    # B2B — Virtual Accounts & Wallet
    path('api/bits/', include('apps.bits.urls')),

    # Internal / no user-facing endpoints
    # path('api/usage/', include('apps.usage.urls')),
]
