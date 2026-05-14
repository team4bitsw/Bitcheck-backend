"""
Image verification service — direct upload to ML service with hash-based caching.

Flow:
  1. Accept image upload directly from the user
  2. Validate file type + size
  3. Pre-flight balance check
  4. Compute SHA-256 hash (chunked, memory-safe)
  5. CACHE CHECK: if hash exists in ImageVerificationCache → return cached result
  6. CACHE MISS: forward to ML service, cache the result on success
  7. Map the ML response to our Verification model
  8. Debit bits on success

ML API contract (BitCheck Image Verification API):
  - Endpoint: POST {ML_IMAGE_SERVICE_BASE_URL}/verify/image
  - Form fields: user_gmail (required), file (required)
  - Max upload: 12 MB
  - Accepted: JPG, JPEG, PNG, WEBP
"""

import hashlib
import logging
import requests
from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import Verification, VerificationJob, ImageVerificationCache
from .services import (
    get_verification_cost,
    complete_verification,
    fail_verification,
    InsufficientBitsError,
    VerificationError,
)
from .storage_upload import upload_bytes_for_connector_owner
from apps.bits.services import check_balance, get_wallet_for_user

logger = logging.getLogger(__name__)

# Allowed image MIME types
ALLOWED_IMAGE_TYPES = {
    'image/jpeg', 'image/png', 'image/webp', 'image/jpg',
}
MAX_IMAGE_SIZE = 12 * 1024 * 1024  # 12 MB (ML service limit)
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


def _check_cache(file_hash):
    """
    Look up a file hash in the verification cache.

    Returns the ImageVerificationCache object if found, None otherwise.
    On a hit, increments hit_count atomically.

    Gracefully returns None if the cache table doesn't exist yet
    (migration not run).
    """
    try:
        cache_entry = ImageVerificationCache.objects.get(file_hash=file_hash)
        # Increment hit count atomically
        ImageVerificationCache.objects.filter(pk=cache_entry.pk).update(
            hit_count=F('hit_count') + 1,
        )
        return cache_entry
    except ImageVerificationCache.DoesNotExist:
        return None
    except Exception as e:
        # Table doesn't exist yet (migration not run), or other DB error
        print(f'[IMAGE-CACHE] ⚠️ Cache lookup failed (table may not exist): {e}')
        return None


def _save_to_cache(file_hash, trust_score, result_summary, ml_response_raw, filename):
    """
    Save a new ML result to the verification cache.

    If another request already cached this hash (race condition), just
    ignore the duplicate — the existing entry is equally valid.

    Silently skips if the cache table doesn't exist yet.
    """
    try:
        ImageVerificationCache.objects.create(
            file_hash=file_hash,
            trust_score=trust_score,
            result_summary=result_summary,
            ml_response_raw=ml_response_raw,
            original_filename=filename,
        )
        print(f'[IMAGE-CACHE] 💾 Cached result for hash {file_hash[:16]}...')
    except Exception as e:
        # Unique constraint violation, missing table, or other DB error
        print(f'[IMAGE-CACHE] ⚠️ Cache write skipped for {file_hash[:16]}...: {e}')


def _try_upload_to_r2(user, image_file):
    """
    Upload image bytes to R2 and return an UploadedFile record.

    Returns None gracefully if R2 is not configured or the upload fails,
    so verification can still complete without image preview.
    """
    if not getattr(settings, 'AWS_ACCESS_KEY_ID', '') or \
       not getattr(settings, 'AWS_SECRET_ACCESS_KEY', ''):
        logger.debug('[IMAGE-R2] R2 credentials not configured — skipping upload')
        return None
    try:
        image_file.seek(0)
        data = image_file.read()
        image_file.seek(0)
        uploaded_file = upload_bytes_for_connector_owner(
            user=user,
            organization=None,
            data=data,
            original_filename=image_file.name,
            mime_type=image_file.content_type or 'image/jpeg',
        )
        logger.info('[IMAGE-R2] Uploaded %s to R2 as %s', image_file.name, uploaded_file.storage_key)
        return uploaded_file
    except Exception as exc:
        logger.warning('[IMAGE-R2] Upload failed, continuing without preview: %s', exc)
        return None


def verify_image_direct(
    user,
    image_file,
    label=None,
):
    """
    Submit an image for verification directly (no S3 upload needed).

    Uses SHA-256 hash-based caching: if an identical file was previously
    analyzed, returns the cached ML result instantly without calling the
    ML service. Still creates a new Verification record and debits bits.

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

    # --- Compute SHA-256 (chunked, memory-safe) ---
    file_hash = compute_file_hash(image_file)

    print(f'[IMAGE-VERIFY] File: {image_file.name}, size={image_file.size}, hash={file_hash[:16]}...')
    print(f'[IMAGE-VERIFY] Label: {label or "(none)"}, user: {user.email}')

    # --- CACHE CHECK ---
    cache_entry = _check_cache(file_hash)

    if cache_entry:
        print(f'[IMAGE-CACHE] ✅ CACHE HIT for hash {file_hash[:16]}... '
              f'(hits={cache_entry.hit_count + 1}, score={cache_entry.trust_score})')

        # Build result_summary from cache, overriding user-specific fields
        cached_summary = dict(cache_entry.result_summary)
        cached_summary['label'] = label or ''
        cached_summary['original_filename'] = image_file.name
        cached_summary['_cached'] = True
        cached_summary['_cache_hit_count'] = cache_entry.hit_count + 1

        # Upload to R2 so the results page can show the image
        uploaded_file = _try_upload_to_r2(user, image_file)

        # Create Verification record (still needed for user's history + billing)
        with transaction.atomic():
            verification = Verification.objects.create(
                user=user,
                modality=Verification.Modality.IMAGE,
                status=Verification.Status.ANALYZING,
                started_at=timezone.now(),
                result_summary=cached_summary,
                uploaded_file=uploaded_file,
            )

        # Complete + debit (same as fresh result)
        verification = complete_verification(
            verification_id=verification.id,
            trust_score=cache_entry.trust_score,
            result_summary=cached_summary,
            ml_response_raw=cache_entry.ml_response_raw,
        )

        print(f'[IMAGE-CACHE] ✅ Verification {verification.id} completed from cache: '
              f'score={cache_entry.trust_score}, verdict={verification.verdict}')

        return verification, cache_entry.ml_response_raw

    # --- CACHE MISS ---
    print(f'[IMAGE-CACHE] ❌ Cache miss for hash {file_hash[:16]}...')

    # Upload to R2 before processing so the results page can show the image
    uploaded_file = _try_upload_to_r2(user, image_file)

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
            uploaded_file=uploaded_file,
        )
        job = VerificationJob.objects.create(
            verification=verification,
            enqueued_at=timezone.now(),
            started_at=timezone.now(),
            ml_endpoint=f'{settings.ML_IMAGE_SERVICE_BASE_URL}/verify/image',
            attempts=1,
        )

    print(f'[IMAGE-VERIFY] Created verification {verification.id}')

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

        # Cache the mock result too (consistent behavior)
        _save_to_cache(file_hash, trust_score, result_summary, ml_result, image_file.name)

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

            # Save to cache for future identical files
            _save_to_cache(file_hash, trust_score, result_summary, ml_result, image_file.name)

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
