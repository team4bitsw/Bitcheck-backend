"""
Root URL configuration for Bitcheck / ProofChain AI.

All API routes are namespaced under /api/.
"""

from django.contrib import admin
from django.urls import path, include
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


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

    # Future phases — will be uncommented as we go
    # path('api/bits/', include('apps.bits.urls')),
    # path('api/verifications/', include('apps.verifications.urls')),
    # path('api/usage/', include('apps.usage.urls')),
    # path('api/webhooks/', include('apps.webhooks.urls')),
]
