"""
Verification views — retrieval, deletion, and direct verification.

Endpoints:
  GET    /api/verifications/                — list user's verifications (B2C)
  DELETE /api/verifications/                — delete ALL user's verifications
  DELETE /api/verifications/<id>/           — soft-delete a single verification
  GET    /api/verifications/costs/          — get verification costs per modality
  POST   /api/verifications/verify/image/   — direct image verification
  POST   /api/verifications/verify/text/    — direct text verification
"""

from django.conf import settings
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .models import Verification
from .serializers import (
    VerificationSerializer,
    VerificationListSerializer,
)
from .services import (
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


@api_view(['GET', 'DELETE'])
@permission_classes([IsAuthenticated])
def verification_list_view(request):
    """
    GET:    List the current user's verifications.
    DELETE: Soft-delete ALL of the current user's verifications.
    """
    if request.method == 'DELETE':
        count = Verification.objects.filter(
            user=request.user,
            deleted_at__isnull=True,
        ).update(deleted_at=timezone.now())
        return Response({
            'detail': f'{count} verification(s) deleted.',
            'count': count,
        })

    # GET — list
    verifications = Verification.objects.filter(
        user=request.user,
        deleted_at__isnull=True,
    ).order_by('-created_at')[:50]

    serializer = VerificationListSerializer(verifications, many=True)
    return Response({'verifications': serializer.data})


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def verification_detail_view(request, verification_id):
    """
    DELETE: Soft-delete a single verification (sets deleted_at timestamp).
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

    verification.deleted_at = timezone.now()
    verification.save(update_fields=['deleted_at'])
    return Response(
        {'detail': f'Verification {verification_id} deleted.'},
        status=status.HTTP_200_OK,
    )


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


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def verify_text_view(request):
    """
    Direct text verification — submit text and get AI analysis results.

    Accepts application/json. Forwards text to the ML text service,
    stores the results, and debits bits on success. Costs 1 bit.

    JSON fields:
        text*:                Text to verify (5–8000 characters)
        source_url:           Optional URL where the text was found
        context:              Optional context hint (e.g., "WhatsApp broadcast")
        label:                Optional tracking identifier
        check_ai_likelihood:  true/false (default: true)
        check_fraud_signals:  true/false (default: true)
        check_claims:         true/false (default: true)
        check_source_url:     true/false (default: true)
    """
    from .text_service import verify_text_direct

    text_input = request.data.get('text', '').strip()
    if not text_input:
        return Response(
            {'detail': 'Text input is required. Send JSON with a "text" field.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Parse optional fields
    source_url = request.data.get('source_url', '').strip() or None
    context = request.data.get('context', '').strip() or None
    label = request.data.get('label', '').strip() or None

    # Analysis toggles (default all True)
    check_ai_likelihood = request.data.get('check_ai_likelihood', True)
    check_fraud_signals = request.data.get('check_fraud_signals', True)
    check_claims = request.data.get('check_claims', True)
    check_source_url = request.data.get('check_source_url', True)

    try:
        verification, ml_result = verify_text_direct(
            user=request.user,
            text_input=text_input,
            source_url=source_url,
            context=context,
            label=label,
            check_ai_likelihood=check_ai_likelihood,
            check_fraud_signals=check_fraud_signals,
            check_claims=check_claims,
            check_source_url=check_source_url,
        )
    except InsufficientBitsError as e:
        return Response(
            {
                'detail': 'Insufficient bits for text verification.',
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
            'detail': 'Text verification completed.',
            'verification': VerificationSerializer(verification).data,
        },
        status=status.HTTP_200_OK,
    )
