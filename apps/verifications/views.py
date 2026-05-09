"""
Verification views — submission and result retrieval.

Endpoints:
  POST /api/verifications/                — submit a new verification (B2C)
  GET  /api/verifications/                — list user's verifications (B2C)
  GET  /api/verifications/<id>/           — get verification detail
  GET  /api/verifications/costs/          — get verification costs per modality
"""

from django.conf import settings
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .models import Verification
from .serializers import (
    VerificationSerializer,
    VerificationListSerializer,
    VerificationSubmitSerializer,
)
from .services import (
    submit_b2c_verification,
    InsufficientBitsError,
    VerificationError,
    get_verification_cost,
)


@api_view(['GET'])
@permission_classes([AllowAny])
def verification_costs_view(request):
    """
    Public endpoint: return the bit cost per modality.
    Used by the frontend to show costs before submission.
    """
    return Response({
        'costs': settings.BITCHECK_VERIFICATION_COSTS,
    })


@api_view(['GET', 'POST'])
@permission_classes([IsAuthenticated])
def verification_list_view(request):
    """
    GET:  List the current user's verifications (paginated).
    POST: Submit a new B2C verification.
    """
    if request.method == 'GET':
        verifications = Verification.objects.filter(
            user=request.user,
            deleted_at__isnull=True,
        ).order_by('-created_at')[:50]

        serializer = VerificationListSerializer(verifications, many=True)
        return Response({'verifications': serializer.data})

    # POST — submit new verification
    serializer = VerificationSubmitSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    modality = serializer.validated_data['modality']
    cost = get_verification_cost(modality)

    try:
        verification = submit_b2c_verification(
            user=request.user,
            modality=modality,
            text_input=serializer.validated_data.get('text_input'),
            uploaded_file_id=serializer.validated_data.get('uploaded_file_id'),
        )
    except InsufficientBitsError as e:
        return Response(
            {
                'detail': 'Insufficient bits.',
                'required': e.required,
                'available': e.available,
            },
            status=status.HTTP_402_PAYMENT_REQUIRED,
        )
    except VerificationError as e:
        return Response(
            {'detail': str(e)},
            status=status.HTTP_400_BAD_REQUEST,
        )

    return Response(
        {
            'detail': 'Verification submitted.',
            'verification': VerificationSerializer(verification).data,
            'cost_bits': cost,
        },
        status=status.HTTP_202_ACCEPTED,
    )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def verification_detail_view(request, verification_id):
    """
    Get a single verification's full details including results.
    """
    try:
        verification = Verification.objects.get(
            pk=verification_id,
            user=request.user,
            deleted_at__isnull=True,
        )
    except Verification.DoesNotExist:
        return Response(
            {'detail': 'Verification not found.'},
            status=status.HTTP_404_NOT_FOUND,
        )

    return Response({
        'verification': VerificationSerializer(verification).data,
    })
