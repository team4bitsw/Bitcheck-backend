"""
API Keys views — CRUD for B2B API keys.

All endpoints require session auth + org membership.

Endpoints:
  GET    /api/keys/                  — list org's API keys
  POST   /api/keys/                  — create a new key (returns secret once)
  DELETE /api/keys/<id>/revoke/      — revoke (soft-delete) a key
"""

from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.models import Membership
from .models import ApiKey
from .serializers import ApiKeySerializer, ApiKeyCreateSerializer


def _get_user_organization(user):
    """
    Get the organization the user belongs to.
    For the hackathon, each user has at most one org.
    """
    membership = Membership.objects.select_related('organization').filter(
        user=user,
    ).first()

    if not membership:
        return None
    return membership.organization


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def api_key_list_view(request):
    """
    GET:  List all API keys for the user's organization.
    POST: Create a new API key (returns the raw secret ONCE).
    """
    organization = _get_user_organization(request.user)

    if not organization:
        return Response(
            {'detail': 'You must belong to an organization to manage API keys.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    if request.method == 'GET':
        keys = ApiKey.objects.filter(
            organization=organization,
        ).order_by('-created_at')

        serializer = ApiKeySerializer(keys, many=True)
        return Response({'api_keys': serializer.data})

    # POST — create a new key
    serializer = ApiKeyCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    api_key, raw_secret = ApiKey.create_key(
        organization=organization,
        name=serializer.validated_data['name'],
        environment=serializer.validated_data.get('environment', 'test'),
        created_by=request.user,
    )

    return Response(
        {
            'detail': 'API key created. Save the secret — it will not be shown again.',
            'key': ApiKeySerializer(api_key).data,
            'raw_secret': raw_secret,
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def api_key_revoke_view(request, key_id):
    """
    Revoke (soft-delete) an API key.
    The key remains in the DB for audit but can no longer authenticate.
    """
    organization = _get_user_organization(request.user)

    if not organization:
        return Response(
            {'detail': 'You must belong to an organization to manage API keys.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    try:
        api_key = ApiKey.objects.get(
            pk=key_id,
            organization=organization,
        )
    except ApiKey.DoesNotExist:
        return Response(
            {'detail': 'API key not found.'},
            status=status.HTTP_404_NOT_FOUND,
        )

    if api_key.revoked_at is not None:
        return Response(
            {'detail': 'This key is already revoked.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    api_key.revoked_at = timezone.now()
    api_key.save(update_fields=['revoked_at'])

    return Response({
        'detail': 'API key revoked.',
        'key': ApiKeySerializer(api_key).data,
    })
