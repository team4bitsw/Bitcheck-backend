"""
Verification views — submission, retrieval, and deletion.

Endpoints:
  POST   /api/verifications/                — submit a new verification (B2C)
  GET    /api/verifications/                — list user's verifications (B2C)
  DELETE /api/verifications/                — delete ALL user's verifications
  GET    /api/verifications/<id>/           — get verification detail
  DELETE /api/verifications/<id>/           — soft-delete a single verification
  GET    /api/verifications/costs/          — get verification costs per modality
  POST   /api/verifications/verify/image/   — direct image verification
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


@api_view(['GET', 'POST', 'DELETE'])
@permission_classes([IsAuthenticated])
def verification_list_view(request):
    """
    GET:    List the current user's verifications.
    POST:   Submit a new B2C verification.
    DELETE: Soft-delete ALL of the current user's verifications.
    """
    if request.method == 'DELETE':
        from django.utils import timezone
        count = Verification.objects.filter(
            user=request.user,
            deleted_at__isnull=True,
        ).update(deleted_at=timezone.now())
        return Response({
            'detail': f'{count} verification(s) deleted.',
            'count': count,
        })

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


@api_view(['GET', 'DELETE'])
@permission_classes([IsAuthenticated])
def verification_detail_view(request, verification_id):
    """
    GET:    Get a single verification's full details including results.
    DELETE: Soft-delete a single verification (sets deleted_at timestamp).
    """
    from django.utils import timezone

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

    if request.method == 'DELETE':
        verification.deleted_at = timezone.now()
        verification.save(update_fields=['deleted_at'])
        return Response(
            {'detail': f'Verification {verification_id} deleted.'},
            status=status.HTTP_200_OK,
        )

    return Response({
        'verification': VerificationSerializer(verification).data,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def verify_image_view(request):
    """
    Direct image verification — upload an image and get AI analysis results.

    Accepts multipart/form-data. Forwards the image to the ML service,
    stores the results, and debits bits on success.

    Form fields:
        file*:   Image file (.jpg, .jpeg, .png, .webp) — max 12 MB
        label:   Optional user-provided identifier (e.g., "invoice_q4_2026")
    """
    from .image_service import verify_image_direct

    image_file = request.FILES.get('file')
    if not image_file:
        return Response(
            {'detail': 'No image file provided. Send as multipart/form-data with field name "file".'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Parse optional label
    label = request.data.get('label', '').strip()

    try:
        verification, ml_result = verify_image_direct(
            user=request.user,
            image_file=image_file,
            label=label,
        )
    except InsufficientBitsError as e:
        return Response(
            {
                'detail': 'Insufficient bits for image verification.',
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
            'detail': 'Image verification completed.',
            'verification': VerificationSerializer(verification).data,
        },
        status=status.HTTP_200_OK,
    )

