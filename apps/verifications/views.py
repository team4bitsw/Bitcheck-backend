"""
Verification views — retrieval, deletion, and direct verification.

Endpoints:
  GET    /api/verifications/                  — list user's verifications (B2C)
  DELETE /api/verifications/                  — delete ALL user's verifications
  GET    /api/verifications/<id>/             — get verification detail + results
  DELETE /api/verifications/<id>/             — soft-delete a single verification
  GET    /api/verifications/costs/            — get verification costs per modality
  POST   /api/verifications/verify/image/     — direct image verification
  POST   /api/verifications/verify/text/      — direct text verification
  POST   /api/verifications/verify/document/  — direct document verification

B2B vs B2C:
  When request.auth is an ApiKey, the request is B2B:
    - Verification ownership → organization (not user)
    - Wallet debit → organization wallet (not personal wallet)
    - An ApiCall usage record is logged
  When request.auth is NOT an ApiKey, the request is B2C:
    - Verification ownership → user
    - Wallet debit → personal wallet
"""

import logging
import time
import traceback

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

logger = logging.getLogger(__name__)


def _is_b2b(request):
    """Check if the request is authenticated via B2B API key."""
    from apps.api_keys.models import ApiKey
    return isinstance(getattr(request, 'auth', None), ApiKey)


def _log_api_call(request, endpoint, modality, http_status, latency_ms, bits_charged=0):
    """Log a B2B API call for usage tracking. No-op for B2C requests."""
    if not _is_b2b(request):
        return None
    try:
        from apps.usage.services import log_api_call, generate_request_id, get_client_ip
        return log_api_call(
            organization=request.auth.organization,
            api_key=request.auth,
            endpoint=endpoint,
            modality=modality,
            http_status=http_status,
            latency_ms=latency_ms,
            bits_charged=bits_charged,
            request_id=generate_request_id(),
            client_ip=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
        )
    except Exception as exc:
        logger.warning('[API-CALL-LOG] Failed to log API call: %s', exc)
        return None


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
    GET:    List the current user's (or org's) verifications.
    DELETE: Soft-delete ALL of the current user's (or org's) verifications.
    """
    # Build filter based on auth type
    if _is_b2b(request):
        base_filter = {'organization': request.auth.organization}
    else:
        base_filter = {'user': request.user}

    if request.method == 'DELETE':
        count = Verification.objects.filter(
            **base_filter,
            deleted_at__isnull=True,
        ).update(deleted_at=timezone.now())
        return Response({
            'detail': f'{count} verification(s) deleted.',
            'count': count,
        })

    # GET — list
    verifications = Verification.objects.filter(
        **base_filter,
        deleted_at__isnull=True,
    ).order_by('-created_at')[:50]

    serializer = VerificationListSerializer(verifications, many=True)
    return Response({'verifications': serializer.data})


@api_view(['GET', 'DELETE'])
@permission_classes([IsAuthenticated])
def verification_detail_view(request, verification_id):
    """
    GET:    Get a single verification's full details including results.
    DELETE: Soft-delete a single verification (sets deleted_at timestamp).
    """
    # Build filter based on auth type
    if _is_b2b(request):
        lookup = {
            'pk': verification_id,
            'organization': request.auth.organization,
            'deleted_at__isnull': True,
        }
    else:
        lookup = {
            'pk': verification_id,
            'user': request.user,
            'deleted_at__isnull': True,
        }

    try:
        verification = Verification.objects.get(**lookup)
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

    # GET — return full detail
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

    B2B: authenticated via API key → org wallet + org ownership
    B2C: authenticated via session → personal wallet + user ownership

    Form fields:
        file*:   Image file (.jpg, .jpeg, .png, .webp) — max 12 MB
        label:   Optional user-provided identifier (e.g., "invoice_q4_2026")
    """
    from .image_service import verify_image_direct

    start_time = time.monotonic()

    image_file = request.FILES.get('file')
    if not image_file:
        if _is_b2b(request):
            _log_api_call(request, '/verify/image', 'image', 400, 0)
        return Response(
            {'detail': 'No image file provided. Send as multipart/form-data with field name "file".'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Parse optional label
    label = request.data.get('label', '').strip()

    # Determine B2B vs B2C context
    b2b = _is_b2b(request)
    organization = request.auth.organization if b2b else None
    api_key = request.auth if b2b else None

    try:
        verification, ml_result = verify_image_direct(
            user=request.user,
            image_file=image_file,
            label=label,
            organization=organization,
            api_key=api_key,
        )
    except InsufficientBitsError as e:
        latency = int((time.monotonic() - start_time) * 1000)
        if b2b:
            _log_api_call(request, '/verify/image', 'image', 402, latency)
        return Response(
            {
                'detail': 'Insufficient bits for image verification.',
                'required': e.required,
                'available': e.available,
            },
            status=status.HTTP_402_PAYMENT_REQUIRED,
        )
    except VerificationError as e:
        latency = int((time.monotonic() - start_time) * 1000)
        if b2b:
            _log_api_call(request, '/verify/image', 'image', 400, latency)
        return Response(
            {'detail': str(e)},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except Exception as e:
        latency = int((time.monotonic() - start_time) * 1000)
        if b2b:
            _log_api_call(request, '/verify/image', 'image', 500, latency)
        logger.error(
            '[VERIFY-IMAGE] Unhandled exception for user=%s file=%s: %s\n%s',
            getattr(request.user, 'email', '?'),
            getattr(image_file, 'name', '?'),
            str(e),
            traceback.format_exc(),
        )
        return Response(
            {'detail': 'An unexpected error occurred. Our team has been notified.'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    latency = int((time.monotonic() - start_time) * 1000)
    cost = get_verification_cost('image')
    if b2b:
        _log_api_call(request, '/verify/image', 'image', 200, latency, bits_charged=cost)

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

    B2B: authenticated via API key → org wallet + org ownership
    B2C: authenticated via session → personal wallet + user ownership

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

    start_time = time.monotonic()

    text_input = request.data.get('text', '').strip()
    if not text_input:
        if _is_b2b(request):
            _log_api_call(request, '/verify/text', 'text', 400, 0)
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

    # Determine B2B vs B2C context
    b2b = _is_b2b(request)
    organization = request.auth.organization if b2b else None
    api_key = request.auth if b2b else None

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
            organization=organization,
            api_key=api_key,
        )
    except InsufficientBitsError as e:
        latency = int((time.monotonic() - start_time) * 1000)
        if b2b:
            _log_api_call(request, '/verify/text', 'text', 402, latency)
        return Response(
            {
                'detail': 'Insufficient bits for text verification.',
                'required': e.required,
                'available': e.available,
            },
            status=status.HTTP_402_PAYMENT_REQUIRED,
        )
    except VerificationError as e:
        latency = int((time.monotonic() - start_time) * 1000)
        if b2b:
            _log_api_call(request, '/verify/text', 'text', 400, latency)
        return Response(
            {'detail': str(e)},
            status=status.HTTP_400_BAD_REQUEST,
        )

    latency = int((time.monotonic() - start_time) * 1000)
    cost = get_verification_cost('text')
    if b2b:
        _log_api_call(request, '/verify/text', 'text', 200, latency, bits_charged=cost)

    return Response(
        {
            'detail': 'Text verification completed.',
            'verification': VerificationSerializer(verification).data,
        },
        status=status.HTTP_200_OK,
    )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def verify_document_view(request):
    """
    Direct document verification — upload a document and get analysis results.

    Accepts multipart/form-data. Forwards the document to the ML document
    service, stores the results, and debits 3 bits on success.

    B2B: authenticated via API key → org wallet + org ownership
    B2C: authenticated via session → personal wallet + user ownership

    Form fields:
        file*:              Document file (.pdf, .jpg, .jpeg, .png) — max 20 MB
        label:              Optional user-provided identifier
        document_type:      Type hint: "general", "invoice", "id_card", etc. (default: "general")
        run_ocr:            Extract text via OCR (default: true)
        run_forensics:      Run visual tampering checks (default: true)
        run_qr:             Scan for QR codes (default: true)
        run_live_qr_check:  Verify QR URLs live (default: false)
        run_llm_analysis:   Use LLM for deep analysis (default: true)
        max_pages:          Max pages for multi-page PDFs (default: 5)
    """
    from .document_service import verify_document_direct

    start_time = time.monotonic()

    doc_file = request.FILES.get('file')
    if not doc_file:
        if _is_b2b(request):
            _log_api_call(request, '/verify/document', 'document', 400, 0)
        return Response(
            {'detail': 'No document file provided. Send as multipart/form-data with field name "file".'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Parse optional fields
    label = request.data.get('label', '').strip()
    document_type = request.data.get('document_type', 'general').strip() or 'general'

    # Analysis toggles (booleans sent as form strings)
    def _parse_bool(val, default=True):
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.lower() not in ('false', '0', 'no')
        return default

    run_ocr = _parse_bool(request.data.get('run_ocr', True))
    run_forensics = _parse_bool(request.data.get('run_forensics', True))
    run_qr = _parse_bool(request.data.get('run_qr', True))
    run_live_qr_check = _parse_bool(request.data.get('run_live_qr_check', False), default=False)
    run_llm_analysis = _parse_bool(request.data.get('run_llm_analysis', True))

    try:
        max_pages = int(request.data.get('max_pages', 5))
        max_pages = max(1, min(max_pages, 20))  # Clamp to 1-20
    except (TypeError, ValueError):
        max_pages = 5

    # Determine B2B vs B2C context
    b2b = _is_b2b(request)
    organization = request.auth.organization if b2b else None
    api_key = request.auth if b2b else None

    try:
        verification, ml_result = verify_document_direct(
            user=request.user,
            doc_file=doc_file,
            label=label,
            document_type=document_type,
            run_ocr=run_ocr,
            run_forensics=run_forensics,
            run_qr=run_qr,
            run_live_qr_check=run_live_qr_check,
            run_llm_analysis=run_llm_analysis,
            max_pages=max_pages,
            organization=organization,
            api_key=api_key,
        )
    except InsufficientBitsError as e:
        latency = int((time.monotonic() - start_time) * 1000)
        if b2b:
            _log_api_call(request, '/verify/document', 'document', 402, latency)
        return Response(
            {
                'detail': 'Insufficient bits for document verification.',
                'required': e.required,
                'available': e.available,
            },
            status=status.HTTP_402_PAYMENT_REQUIRED,
        )
    except VerificationError as e:
        latency = int((time.monotonic() - start_time) * 1000)
        if b2b:
            _log_api_call(request, '/verify/document', 'document', 400, latency)
        return Response(
            {'detail': str(e)},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except Exception as e:
        latency = int((time.monotonic() - start_time) * 1000)
        if b2b:
            _log_api_call(request, '/verify/document', 'document', 500, latency)
        logger.error(
            '[VERIFY-DOC] Unhandled exception for user=%s file=%s: %s\n%s',
            getattr(request.user, 'email', '?'),
            getattr(doc_file, 'name', '?'),
            str(e),
            traceback.format_exc(),
        )
        return Response(
            {'detail': 'An unexpected error occurred. Our team has been notified.'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    latency = int((time.monotonic() - start_time) * 1000)
    cost = get_verification_cost('document')
    if b2b:
        _log_api_call(request, '/verify/document', 'document', 200, latency, bits_charged=cost)

    return Response(
        {
            'detail': 'Document verification completed.',
            'verification': VerificationSerializer(verification).data,
        },
        status=status.HTTP_200_OK,
    )
