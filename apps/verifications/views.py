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


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def verify_image_view(request):
    """
    Direct image verification — upload an image and get AI analysis results.

    Accepts multipart/form-data. Forwards the image to the ML service,
    stores the results, and debits bits on success.

    Form fields:
        file*:               Image file (.jpg, .jpeg, .png, .webp)
        label:               User-provided identifier (e.g., "invoice_q4_2026")
        run_explainability:  "true"/"false" — Grad-CAM heatmap (default: true)
        run_ocr:             "true"/"false" — watermark/text check (default: true)
        run_c2pa:            "true"/"false" — C2PA provenance (default: true)
        threshold:           Custom AI detection threshold (float)
    """
    from .image_service import verify_image_direct

    image_file = request.FILES.get('file')
    if not image_file:
        return Response(
            {'detail': 'No image file provided. Send as multipart/form-data with field name "file".'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Parse optional fields
    label = request.data.get('label', '').strip()
    run_explainability = request.data.get('run_explainability', 'true').lower() == 'true'
    run_ocr = request.data.get('run_ocr', 'true').lower() == 'true'
    run_c2pa = request.data.get('run_c2pa', 'true').lower() == 'true'

    threshold = None
    threshold_str = request.data.get('threshold', '').strip()
    if threshold_str:
        try:
            threshold = float(threshold_str)
        except ValueError:
            return Response(
                {'detail': 'threshold must be a valid float.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

    try:
        verification, ml_result = verify_image_direct(
            user=request.user,
            image_file=image_file,
            label=label,
            run_explainability=run_explainability,
            run_ocr=run_ocr,
            run_c2pa=run_c2pa,
            threshold=threshold,
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

