"""
Image verification service — direct upload to ML service.

Handles the image verification flow without requiring S3:
  1. Accept image upload directly from the user
  2. Compute SHA256 hash
  3. Forward to ML service's POST /verify/image
  4. Map the ML response to our Verification model
  5. Debit bits on success

This bypasses the S3-based UploadedFile flow since S3 isn't provisioned yet.
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
MAX_IMAGE_SIZE = 20 * 1024 * 1024  # 20 MB


def verify_image_direct(
    user,
    image_file,
    label=None,
    run_explainability=True,
    run_ocr=True,
    run_c2pa=True,
    threshold=None,
):
    """
    Submit an image for verification directly (no S3 upload needed).

    Args:
        user:               The authenticated User.
        image_file:         Django UploadedFile (from request.FILES).
        label:              Optional user-provided label/identifier for this check.
        run_explainability: Whether to generate Grad-CAM heatmap.
        run_ocr:            Whether to check for visible watermarks.
        run_c2pa:           Whether to check C2PA provenance.
        threshold:          Optional custom AI detection threshold.

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
            ml_endpoint=f'{settings.ML_SERVICE_BASE_URL}/verify/image',
            attempts=1,
        )

    print(f'[IMAGE-VERIFY] Created verification {verification.id}')
    print(f'[IMAGE-VERIFY] File: {image_file.name}, size={image_file.size}, hash={file_hash[:16]}...')
    print(f'[IMAGE-VERIFY] Label: {label or "(none)"}')

    # --- Call ML service ---
    ml_url = f'{settings.ML_SERVICE_BASE_URL}/verify/image'

    # Build multipart form data
    files = {
        'file': (image_file.name, image_file, content_type),
    }
    form_data = {
        'run_explainability': str(run_explainability).lower(),
        'run_ocr': str(run_ocr).lower(),
        'run_c2pa': str(run_c2pa).lower(),
    }
    if threshold is not None:
        form_data['threshold'] = str(threshold)

    print(f'[IMAGE-VERIFY] Sending to ML: {ml_url}')

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
            print(f'[IMAGE-VERIFY] ML trust_score: {ml_result.get("trust", {}).get("trust_score")}')

            # Map ML response to our model
            trust_data = ml_result.get('trust', {})
            trust_score = trust_data.get('trust_score', 50)

            # Build result_summary from ML response
            result_summary = {
                'label': label or '',
                'original_filename': image_file.name,
                'sha256': file_hash,
                'file_size_bytes': image_file.size,
                'ml_verification_id': ml_result.get('verification_id'),
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
