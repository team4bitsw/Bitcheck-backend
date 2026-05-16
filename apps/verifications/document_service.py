"""
Document verification service — direct upload to ML service with hash-based caching.

Flow:
  1. Accept document upload directly from the user
  2. Validate file type + size
  3. Pre-flight balance check
  4. Compute SHA-256 hash (chunked, memory-safe)
  5. Forward to ML document service
  6. Map the ML response to our Verification model
  7. Debit bits on success

ML API contract (BitCheck Document Verification API):
  - Endpoint: POST {ML_DOCUMENT_SERVICE_BASE_URL}/verify/document
  - Form fields: file (required), document_type, run_ocr, run_forensics,
                  run_qr, run_live_qr_check, run_llm_analysis, max_pages
  - Max upload: 20 MB
  - Accepted: PDF, PNG, JPG, JPEG
  - Cost: 3 bits
"""

import hashlib
import logging
import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .ml_trust_score import extract_ml_trust_score
from .models import Verification, VerificationJob
from .services import (
    get_verification_cost,
    complete_verification,
    fail_verification,
    InsufficientBitsError,
    VerificationError,
)
from apps.bits.services import check_balance, get_wallet_for_user, get_wallet_for_organization

logger = logging.getLogger(__name__)


def _attach_r2_if_completed_document(verification, user, doc_file):
    """After successful verification, store bytes in object storage and link uploaded_file."""
    if verification.status != Verification.Status.COMPLETED:
        return
    if not getattr(settings, 'AWS_ACCESS_KEY_ID', '') or \
       not getattr(settings, 'AWS_SECRET_ACCESS_KEY', ''):
        logger.debug('[DOC-R2] Object storage not configured — skipping upload')
        return
    try:
        from .storage_upload import upload_bytes_for_connector_owner

        doc_file.seek(0)
        data = doc_file.read()
        doc_file.seek(0)
        mime = doc_file.content_type or 'application/octet-stream'
        uploaded_file = upload_bytes_for_connector_owner(
            user=user,
            organization=None,
            data=data,
            original_filename=doc_file.name,
            mime_type=mime,
        )
        verification.uploaded_file = uploaded_file
        verification.save(update_fields=['uploaded_file'])
        logger.info(
            '[DOC-R2] Stored document %s as %s',
            doc_file.name,
            uploaded_file.storage_key,
        )
    except Exception as exc:
        logger.warning(
            '[DOC-R2] Upload failed, continuing without preview: %s',
            exc,
        )


# Allowed document MIME types
ALLOWED_DOCUMENT_TYPES = {
    'application/pdf',
    'image/jpeg', 'image/png', 'image/jpg',
}
ALLOWED_EXTENSIONS = {'.pdf', '.png', '.jpg', '.jpeg'}
MAX_DOCUMENT_SIZE = 20 * 1024 * 1024  # 20 MB (ML service limit)
HASH_CHUNK_SIZE = 65536  # 64 KB chunks for hashing


def compute_file_hash(uploaded_file):
    """
    Compute SHA-256 hash of an uploaded file using chunked reads.

    Reads the file in 64 KB chunks to avoid loading the entire file
    into memory. Resets the file pointer to the beginning after hashing
    so downstream code can read the file normally.

    Args:
        uploaded_file: Django UploadedFile (from request.FILES).

    Returns:
        str: lowercase hex SHA-256 digest (64 characters).
    """
    sha256 = hashlib.sha256()
    uploaded_file.seek(0)

    while True:
        chunk = uploaded_file.read(HASH_CHUNK_SIZE)
        if not chunk:
            break
        sha256.update(chunk)

    file_hash = sha256.hexdigest()
    uploaded_file.seek(0)  # Reset for downstream consumers
    return file_hash


def _validate_file_extension(filename):
    """Check file extension since PDFs may not always have the right MIME type."""
    if not filename:
        return False
    import os
    ext = os.path.splitext(filename)[1].lower()
    return ext in ALLOWED_EXTENSIONS


def _map_ml_response(ml_result, label, doc_file, file_hash, document_type):
    """
    Map the ML document service response to our result_summary format.

    The Document API returns fields like trust.trust_score, fields,
    content_risk, forensics, qr_analysis which we normalize into our schema.
    """
    trust_data = ml_result.get('trust', {})
    trust_score = extract_ml_trust_score(ml_result, log_prefix='[DOC-VERIFY]')

    result_summary = {
        'label': label or '',
        'original_filename': doc_file.name,
        'sha256': file_hash,
        'file_size_bytes': doc_file.size,
        'document_type': document_type,
        'ml_verification_id': ml_result.get('verification_id'),
        'status': ml_result.get('status', ''),
        'processing_time_ms': ml_result.get('processing_time_ms'),
        'fields': ml_result.get('fields', {}),
        'content_risk': ml_result.get('content_risk', {}),
        'forensics': ml_result.get('forensics', {}),
        'qr_analysis': ml_result.get('qr_analysis', {}),
        'trust': trust_data,
        'risk_flags': ml_result.get('risk_flags', []),
        'warnings': ml_result.get('warnings', []),
    }

    return trust_score, result_summary


def _generate_mock_document_response(filename, file_size_bytes, file_hash, document_type):
    """Generate a mock ML response for document verification (dev/testing)."""
    import uuid
    return {
        'verification_id': str(uuid.uuid4()),
        'status': 'completed',
        'processing_time_ms': 1250,
        'trust': {
            'trust_score': 78,
            'risk_score': 0.22,
            'risk_level': 'LOW',
            'decision': 'APPROVE',
        },
        'fields': {
            'document_type': document_type,
            'extracted_fields': {
                'mock_field': 'This is a mock extraction',
            },
            'field_confidence': 0.85,
        },
        'content_risk': {
            'fraud_risk_score': 0.1,
            'suspicious_claims': [],
            'summary': 'No high-risk content detected (mock).',
        },
        'forensics': {
            'visual_tampering_risk_score': 0.05,
            'suspicious_regions': [],
        },
        'qr_analysis': {
            'qr_found': False,
            'items': [],
        },
        'risk_flags': [],
        'warnings': ['This is a mock response — ML_MOCK_RESPONSE=True'],
    }


def verify_document_direct(
    user,
    doc_file,
    label=None,
    document_type='general',
    run_ocr=True,
    run_forensics=True,
    run_qr=True,
    run_live_qr_check=False,
    run_llm_analysis=True,
    max_pages=5,
    organization=None,
    api_key=None,
):
    """
    Submit a document for verification directly (no S3 upload needed).

    Forwards the document to the ML service, stores the results,
    and debits bits on success.

    Args:
        user:               The authenticated User.
        doc_file:           Django UploadedFile (from request.FILES).
        label:              Optional user-provided label/identifier.
        document_type:      Type hint for the ML service (e.g. "invoice", "id_card", "general").
        run_ocr:            Extract text via OCR (default True).
        run_forensics:      Run visual tampering checks (default True).
        run_qr:             Scan for QR codes (default True).
        run_live_qr_check:  Verify QR URLs live (default False).
        run_llm_analysis:   Use LLM for deep content analysis (default True).
        max_pages:          Max pages to process for multi-page PDFs (default 5).
        organization:       If provided, this is a B2B call — use org wallet.
        api_key:            If provided, the ApiKey used for this B2B call.

    Returns:
        (Verification, ml_result_dict) — the saved verification + full ML response.

    Raises:
        InsufficientBitsError: Not enough bits.
        VerificationError:     Invalid file or ML service error.
    """
    is_b2b = organization is not None

    # --- Validate file ---
    content_type = doc_file.content_type or ''
    has_valid_mime = content_type in ALLOWED_DOCUMENT_TYPES
    has_valid_ext = _validate_file_extension(doc_file.name)

    if not has_valid_mime and not has_valid_ext:
        raise VerificationError(
            f'Unsupported file type: {content_type} ({doc_file.name}). '
            f'Allowed: .pdf, .jpg, .jpeg, .png'
        )

    if doc_file.size > MAX_DOCUMENT_SIZE:
        raise VerificationError(
            f'File too large: {doc_file.size / 1024 / 1024:.1f} MB. '
            f'Maximum: {MAX_DOCUMENT_SIZE / 1024 / 1024:.0f} MB.'
        )

    # --- Pre-flight balance check ---
    cost = get_verification_cost('document')
    if is_b2b:
        wallet = get_wallet_for_organization(organization)
    else:
        wallet = get_wallet_for_user(user)
    if not check_balance(wallet.id, cost):
        raise InsufficientBitsError(required=cost, available=wallet.balance_bits)

    # --- Compute SHA-256 (chunked, memory-safe) ---
    file_hash = compute_file_hash(doc_file)

    owner_label = f'org:{organization.name}' if is_b2b else f'user:{user.email}'
    print(f'[DOC-VERIFY] File: {doc_file.name}, size={doc_file.size}, hash={file_hash[:16]}...')
    print(f'[DOC-VERIFY] Label: {label or "(none)"}, type={document_type}, {owner_label}, b2b={is_b2b}')

    # --- Build ownership kwargs ---
    if is_b2b:
        ownership = {'organization': organization, 'api_key': api_key}
    else:
        ownership = {'user': user}

    # --- Create Verification + Job ---
    with transaction.atomic():
        verification = Verification.objects.create(
            **ownership,
            modality=Verification.Modality.DOCUMENT,
            status=Verification.Status.ANALYZING,
            started_at=timezone.now(),
            result_summary={
                'label': label or '',
                'original_filename': doc_file.name,
                'sha256': file_hash,
                'file_size_bytes': doc_file.size,
                'mime_type': content_type,
                'document_type': document_type,
            },
        )
        job = VerificationJob.objects.create(
            verification=verification,
            enqueued_at=timezone.now(),
            started_at=timezone.now(),
            ml_endpoint=f'{settings.ML_DOCUMENT_SERVICE_BASE_URL}/verify/document',
            attempts=1,
        )

    print(f'[DOC-VERIFY] Created verification {verification.id}')

    # --- Mock or Real ML call ---
    if getattr(settings, 'ML_MOCK_RESPONSE', False):
        print(f'[DOC-VERIFY] ML_MOCK_RESPONSE=True — returning mock result')

        ml_result = _generate_mock_document_response(
            filename=doc_file.name,
            file_size_bytes=doc_file.size,
            file_hash=file_hash,
            document_type=document_type,
        )

        trust_score, result_summary = _map_ml_response(
            ml_result, label, doc_file, file_hash, document_type,
        )
        result_summary['_mock'] = True

        verification = complete_verification(
            verification_id=verification.id,
            trust_score=trust_score,
            result_summary=result_summary,
            ml_response_raw=ml_result,
        )

        _attach_r2_if_completed_document(verification, user, doc_file)

        print(f'[DOC-VERIFY] Mock verification {verification.id} completed: '
              f'score={trust_score}, verdict={verification.verdict}')

        return verification, ml_result

    # --- Real ML service call ---
    ml_url = f'{settings.ML_DOCUMENT_SERVICE_BASE_URL}/verify/document'

    doc_file.seek(0)

    files = {
        'file': (doc_file.name, doc_file, content_type or 'application/octet-stream'),
    }
    form_data = {
        'document_type': document_type,
        'run_ocr': str(run_ocr).lower(),
        'run_forensics': str(run_forensics).lower(),
        'run_qr': str(run_qr).lower(),
        'run_live_qr_check': str(run_live_qr_check).lower(),
        'run_llm_analysis': str(run_llm_analysis).lower(),
        'max_pages': str(max_pages),
    }

    print(f'[DOC-VERIFY] Sending to ML: {ml_url} (type={document_type})')

    try:
        resp = requests.post(
            ml_url,
            files=files,
            data=form_data,
            timeout=120,
        )

        print(f'[DOC-VERIFY] ML response status: {resp.status_code}')

        if resp.status_code == 200:
            try:
                ml_result = resp.json()
            except ValueError:
                error_msg = 'ML document service returned a non-JSON response.'
                print(f'[DOC-VERIFY] {error_msg}')
                fail_verification(str(verification.id), error_msg)
                raise VerificationError(error_msg)

            trust_score, result_summary = _map_ml_response(
                ml_result, label, doc_file, file_hash, document_type,
            )

            print(f'[DOC-VERIFY] ML trust_score: {trust_score}, '
                  f'decision: {ml_result.get("trust", {}).get("decision")}')

            # Complete the verification (debits wallet)
            verification = complete_verification(
                verification_id=verification.id,
                trust_score=trust_score,
                result_summary=result_summary,
                ml_response_raw=ml_result,
            )

            _attach_r2_if_completed_document(verification, user, doc_file)

            print(f'[DOC-VERIFY] Verification {verification.id} completed: '
                  f'score={trust_score}, verdict={verification.verdict}')

            return verification, ml_result

        else:
            error_msg = f'ML document service returned {resp.status_code}: {resp.text[:500]}'
            print(f'[DOC-VERIFY] ML error: {error_msg}')
            fail_verification(str(verification.id), error_msg)
            raise VerificationError(error_msg)

    except requests.exceptions.ConnectionError:
        error_msg = f'ML document service unreachable at {ml_url}'
        print(f'[DOC-VERIFY] Connection error: {error_msg}')
        fail_verification(str(verification.id), error_msg)
        raise VerificationError(error_msg)

    except requests.exceptions.Timeout:
        error_msg = 'ML document service request timed out (120s).'
        print(f'[DOC-VERIFY] Timeout: {error_msg}')
        fail_verification(str(verification.id), error_msg)
        raise VerificationError(error_msg)

    except requests.exceptions.RequestException as exc:
        error_msg = f'ML document request failed: {exc}'
        print(f'[DOC-VERIFY] {error_msg}')
        fail_verification(str(verification.id), error_msg)
        raise VerificationError(error_msg)
