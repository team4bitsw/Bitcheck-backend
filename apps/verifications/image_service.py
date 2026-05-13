"""
Image verification service — direct upload to ML service.

Handles the image verification flow without requiring S3:
  1. Accept image upload directly from the user
  2. Compute SHA256 hash
  3. Forward to ML service's POST /verify/image with user_gmail + file
  4. Map the ML response to our Verification model
  5. Debit bits on success

ML API contract (BitCheck Image Verification API):
  - Endpoint: POST {ML_SERVICE_BASE_URL}/verify/image
  - Form fields: user_gmail (required), file (required)
  - Max upload: 12 MB
  - Accepted: JPG, JPEG, PNG, WEBP
"""

import hashlib
import logging
import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Verification, VerificationJob
from .services import (
    get_verification_cost,
    complete_verification,
    fail_verification,
    InsufficientBitsError,
    VerificationError,
)
from apps.bits.services import check_balance, get_wallet_for_user

logger = logging.getLogger(__name__)

# Allowed image MIME types
ALLOWED_IMAGE_TYPES = {
    'image/jpeg', 'image/png', 'image/webp', 'image/jpg',
}
MAX_IMAGE_SIZE = 12 * 1024 * 1024  # 12 MB (ML service limit)


def _map_ml_response(ml_result, label, image_file, file_hash):
    """
    Map the ML service response to our result_summary format.

    The ML API returns fields like trust.score and model_result.label/confidence
    which we normalize into our internal schema.
    """
    trust_data = ml_result.get('trust', {})
    # ML returns trust.score (float), we store as int trust_score
    trust_score_raw = trust_data.get('score', 50)
    trust_score = int(round(trust_score_raw))

    result_summary = {
        'label': label or '',
        'original_filename': image_file.name,
        'sha256': file_hash,
        'file_size_bytes': image_file.size,
        'ml_verification_id': ml_result.get('verification_id'),
        'user_gmail': ml_result.get('user_gmail', ''),
        'input': ml_result.get('input', {}),
        'model_result': ml_result.get('model_result', {}),
        'metadata': ml_result.get('metadata', {}),
        'provenance': ml_result.get('provenance', {}),
        'visible_watermark': ml_result.get('visible_watermark', {}),
        'forensics': ml_result.get('forensics', {}),
        'explainability': ml_result.get('explainability', {}),
        'trust': trust_data,
        'risk_flags': ml_result.get('risk_flags', []),
        'limitations': ml_result.get('limitations', []),
    }

    return trust_score, result_summary


def verify_image_direct(
    user,
    image_file,
    label=None,
):
    """
    Submit an image for verification directly (no S3 upload needed).

    The ML service requires user_gmail (pulled from user.email) and the image file.
    All analysis layers (model, forensics, metadata, provenance, explainability)
    run automatically — no optional flags needed.

    Args:
        user:               The authenticated User.
        image_file:         Django UploadedFile (from request.FILES).
        label:              Optional user-provided label/identifier for this check.

    Returns:
        (Verification, ml_result_dict) — the saved verification + full ML response.

    Raises:
        InsufficientBitsError: Not enough bits.
        VerificationError:     Invalid file or ML service error.
    """
    # --- Validate file ---
    content_type = image_file.content_type or ''
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise VerificationError(
            f'Unsupported file type: {content_type}. '
            f'Allowed: .jpg, .jpeg, .png, .webp'
        )

    if image_file.size > MAX_IMAGE_SIZE:
        raise VerificationError(
            f'File too large: {image_file.size / 1024 / 1024:.1f} MB. '
            f'Maximum: {MAX_IMAGE_SIZE / 1024 / 1024:.0f} MB.'
        )

    # --- Pre-flight balance check ---
    cost = get_verification_cost('image')
    wallet = get_wallet_for_user(user)
    if not check_balance(wallet.id, cost):
        raise InsufficientBitsError(required=cost, available=wallet.balance_bits)

    # --- Compute SHA256 ---
    sha256 = hashlib.sha256()
    image_file.seek(0)
    for chunk in image_file.chunks():
        sha256.update(chunk)
    file_hash = sha256.hexdigest()
    image_file.seek(0)  # Reset for forwarding

    # --- Create Verification + Job ---
    with transaction.atomic():
        verification = Verification.objects.create(
            user=user,
            modality=Verification.Modality.IMAGE,
            status=Verification.Status.ANALYZING,
            started_at=timezone.now(),
            result_summary={
                'label': label or '',
                'original_filename': image_file.name,
                'sha256': file_hash,
                'file_size_bytes': image_file.size,
                'mime_type': content_type,
            },
        )
        job = VerificationJob.objects.create(
            verification=verification,
            enqueued_at=timezone.now(),
            started_at=timezone.now(),
            ml_endpoint=f'{settings.ML_IMAGE_SERVICE_BASE_URL}/verify/image',
            attempts=1,
        )

    print(f'[IMAGE-VERIFY] Created verification {verification.id}')
    print(f'[IMAGE-VERIFY] File: {image_file.name}, size={image_file.size}, hash={file_hash[:16]}...')
    print(f'[IMAGE-VERIFY] Label: {label or "(none)"}, user: {user.email}')

    # --- Mock or Real ML call ---
    if getattr(settings, 'ML_MOCK_RESPONSE', False):
        from .mock_ml import generate_mock_ml_response
        print(f'[IMAGE-VERIFY] ⚠️ ML_MOCK_RESPONSE=True — returning mock result')

        ml_result = generate_mock_ml_response(
            filename=image_file.name,
            file_size_bytes=image_file.size,
            sha256_hash=file_hash,
            user_gmail=user.email,
        )

        trust_score, result_summary = _map_ml_response(
            ml_result, label, image_file, file_hash,
        )
        result_summary['_mock'] = True

        verification = complete_verification(
            verification_id=verification.id,
            trust_score=trust_score,
            result_summary=result_summary,
            ml_response_raw=ml_result,
        )

        print(f'[IMAGE-VERIFY] ✅ Mock verification {verification.id} completed: '
              f'score={trust_score}, verdict={verification.verdict}')

        return verification, ml_result

    # --- Real ML service call ---
    ml_url = f'{settings.ML_IMAGE_SERVICE_BASE_URL}/verify/image'

    # ML API requires: user_gmail + file (multipart/form-data)
    files = {
        'file': (image_file.name, image_file, content_type),
    }
    form_data = {
        'user_gmail': user.email,
    }

    print(f'[IMAGE-VERIFY] Sending to ML: {ml_url} (user_gmail={user.email})')

    try:
        resp = requests.post(
            ml_url,
            files=files,
            data=form_data,
            timeout=120,
        )

        print(f'[IMAGE-VERIFY] ML response status: {resp.status_code}')

        if resp.status_code == 200:
            ml_result = resp.json()

            trust_score, result_summary = _map_ml_response(
                ml_result, label, image_file, file_hash,
            )

            print(f'[IMAGE-VERIFY] ML trust_score: {trust_score}, '
                  f'model_label: {ml_result.get("model_result", {}).get("label")}')

            # Complete the verification (debits wallet)
            verification = complete_verification(
                verification_id=verification.id,
                trust_score=trust_score,
                result_summary=result_summary,
                ml_response_raw=ml_result,
            )

            print(f'[IMAGE-VERIFY] ✅ Verification {verification.id} completed: '
                  f'score={trust_score}, verdict={verification.verdict}')

            return verification, ml_result

        else:
            error_msg = f'ML service returned {resp.status_code}: {resp.text[:500]}'
            print(f'[IMAGE-VERIFY] ❌ ML error: {error_msg}')
            fail_verification(str(verification.id), error_msg)
            raise VerificationError(error_msg)

    except requests.exceptions.ConnectionError:
        error_msg = f'ML service unreachable at {ml_url}'
        print(f'[IMAGE-VERIFY] ❌ Connection error: {error_msg}')
        fail_verification(str(verification.id), error_msg)
        raise VerificationError(error_msg)

    except requests.exceptions.Timeout:
        error_msg = 'ML service request timed out (120s).'
        print(f'[IMAGE-VERIFY] ❌ Timeout: {error_msg}')
        fail_verification(str(verification.id), error_msg)
        raise VerificationError(error_msg)
