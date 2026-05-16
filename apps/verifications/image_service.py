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
  - Form fields: file (required), user_email, run_explainability, run_ocr,
                  run_forensics, run_c2pa, threshold
  - Max upload: 12 MB
  - Accepted: JPG, JPEG, PNG, WEBP
  - Response: VerificationReport with trust.trust_score_out_of_100 or trust.trust_score,
              trust.final_decision, classifier, filename_analysis,
              visible_watermark_ocr, visible_watermark_template, etc.
"""

import hashlib
import logging
import requests
from django.conf import settings
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .ml_trust_score import extract_ml_trust_score
from .ml_urls import normalize_ml_media_url
from .models import Verification, VerificationJob, ImageVerificationCache
from .services import (
    get_verification_cost,
    complete_verification,
    fail_verification,
    InsufficientBitsError,
    VerificationError,
)
from apps.bits.services import check_balance, get_wallet_for_user, get_wallet_for_organization

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

    The ML API returns trust.trust_score_out_of_100, trust.trust_score (HF), or
    legacy trust.score; see extract_ml_trust_score().
    """
    trust_data = ml_result.get('trust', {})
    trust_score = extract_ml_trust_score(ml_result, log_prefix='[IMAGE-VERIFY]')

    # Make explainability/forensic image URLs absolute
    ml_base = settings.ML_IMAGE_SERVICE_BASE_URL
    explainability = ml_result.get('explainability') or {}
    if explainability.get('heatmap_url'):
        explainability['heatmap_url'] = normalize_ml_media_url(
            explainability['heatmap_url'], ml_base,
        )
    if explainability.get('overlay_url'):
        explainability['overlay_url'] = normalize_ml_media_url(
            explainability['overlay_url'], ml_base,
        )
    if explainability.get('boxed_image_url'):
        explainability['boxed_image_url'] = normalize_ml_media_url(
            explainability['boxed_image_url'], ml_base,
        )

    forensics = ml_result.get('forensics') or {}
    for key in ('noise_map_url', 'ela_url', 'annotated_image_url'):
        if forensics.get(key):
            forensics[key] = normalize_ml_media_url(forensics[key], ml_base)

    result_summary = {
        'label': label or '',
        'original_filename': image_file.name,
        'sha256': file_hash,
        'file_size_bytes': image_file.size,
        'ml_verification_id': ml_result.get('verification_id'),
        'user_email': ml_result.get('user_email', ''),
        'input': ml_result.get('input', {}),
        'filename_analysis': ml_result.get('filename_analysis', {}),
        'classifier': ml_result.get('classifier', {}),
        # Backwards compat: keep model_result if classifier is absent
        'model_result': ml_result.get('classifier') or ml_result.get('model_result', {}),
        'metadata': ml_result.get('metadata', {}),
        'provenance': ml_result.get('provenance', {}),
        'visible_watermark_ocr': ml_result.get('visible_watermark_ocr', {}),
        'visible_watermark_template': ml_result.get('visible_watermark_template', {}),
        # Backwards compat: keep visible_watermark if new fields are absent
        'visible_watermark': ml_result.get('visible_watermark_ocr') or ml_result.get('visible_watermark', {}),
        'forensics': forensics,
        'explainability': explainability,
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


def _attach_r2_if_completed(verification, user, image_file):
    """
    After a successful verification, store bytes in R2 and link uploaded_file.

    Runs only when status is COMPLETED so we do not upload if the job failed.
    """
    if verification.status != Verification.Status.COMPLETED:
        return
    uploaded_file = _try_upload_to_r2(user, image_file)
    if not uploaded_file:
        return
    verification.uploaded_file = uploaded_file
    verification.save(update_fields=['uploaded_file'])


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
        from .storage_upload import upload_bytes_for_connector_owner
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
    run_explainability=True,
    run_ocr=True,
    run_forensics=True,
    run_c2pa=True,
    threshold=None,
    organization=None,
    api_key=None,
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
        run_explainability: Generate Grad-CAM heatmap (default True).
        run_ocr:            Run OCR for AI watermark detection (default True).
        run_forensics:      Run forensic analysis (default True).
        run_c2pa:           Analyze C2PA provenance (default True).
        threshold:          Override classifier confidence threshold (optional).
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
    if is_b2b:
        wallet = get_wallet_for_organization(organization)
    else:
        wallet = get_wallet_for_user(user)
    if not check_balance(wallet.id, cost):
        raise InsufficientBitsError(required=cost, available=wallet.balance_bits)

    # --- Compute SHA-256 (chunked, memory-safe) ---
    file_hash = compute_file_hash(image_file)

    owner_label = f'org:{organization.name}' if is_b2b else f'user:{user.email}'
    print(f'[IMAGE-VERIFY] File: {image_file.name}, size={image_file.size}, hash={file_hash[:16]}...')
    print(f'[IMAGE-VERIFY] Label: {label or "(none)"}, {owner_label}, b2b={is_b2b}')

    # --- Build ownership kwargs ---
    if is_b2b:
        ownership = {'organization': organization, 'api_key': api_key}
    else:
        ownership = {'user': user}

    # --- CACHE CHECK ---
    cache_entry = _check_cache(file_hash)

    if cache_entry:
        print(f'[IMAGE-CACHE] CACHE HIT for hash {file_hash[:16]}... '
              f'(hits={cache_entry.hit_count + 1}, score={cache_entry.trust_score})')

        # Build result_summary from cache, overriding user-specific fields
        cached_summary = dict(cache_entry.result_summary)
        cached_summary['label'] = label or ''
        cached_summary['original_filename'] = image_file.name
        cached_summary['_cached'] = True
        cached_summary['_cache_hit_count'] = cache_entry.hit_count + 1

        # Create Verification record (still needed for history + billing)
        with transaction.atomic():
            verification = Verification.objects.create(
                **ownership,
                modality=Verification.Modality.IMAGE,
                status=Verification.Status.ANALYZING,
                started_at=timezone.now(),
                result_summary=cached_summary,
            )

        # Complete + debit (same as fresh result)
        verification = complete_verification(
            verification_id=verification.id,
            trust_score=cache_entry.trust_score,
            result_summary=cached_summary,
            ml_response_raw=cache_entry.ml_response_raw,
        )
        _attach_r2_if_completed(verification, user, image_file)

        print(f'[IMAGE-CACHE] Verification {verification.id} completed from cache: '
              f'score={cache_entry.trust_score}, verdict={verification.verdict}')

        return verification, cache_entry.ml_response_raw

    # --- CACHE MISS ---
    print(f'[IMAGE-CACHE] Cache miss for hash {file_hash[:16]}...')

    # --- Create Verification + Job ---
    with transaction.atomic():
        verification = Verification.objects.create(
            **ownership,
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

    # --- Mock or Real ML call ---
    if getattr(settings, 'ML_MOCK_RESPONSE', False):
        from .mock_ml import generate_mock_ml_response
        print(f'[IMAGE-VERIFY] ⚠️ ML_MOCK_RESPONSE=True — returning mock result')

        ml_result = generate_mock_ml_response(
            filename=image_file.name,
            file_size_bytes=image_file.size,
            sha256_hash=file_hash,
            user_email=user.email,
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
        _attach_r2_if_completed(verification, user, image_file)

        # Cache the mock result too (consistent behavior)
        _save_to_cache(file_hash, trust_score, result_summary, ml_result, image_file.name)

        print(f'[IMAGE-VERIFY] ✅ Mock verification {verification.id} completed: '
              f'score={trust_score}, verdict={verification.verdict}')

        return verification, ml_result

    # --- Real ML service call ---
    ml_url = f'{settings.ML_IMAGE_SERVICE_BASE_URL}/verify/image'

    image_file.seek(0)

    # ML API accepts: file (required) + user_email + analysis toggles
    files = {
        'file': (image_file.name, image_file, content_type),
    }
    form_data = {
        'user_email': user.email,
        'run_explainability': str(run_explainability).lower(),
        'run_ocr': str(run_ocr).lower(),
        'run_forensics': str(run_forensics).lower(),
        'run_c2pa': str(run_c2pa).lower(),
    }
    if threshold is not None:
        form_data['threshold'] = str(threshold)

    print(f'[IMAGE-VERIFY] Sending to ML: {ml_url} (user_email={user.email})')

    try:
        resp = requests.post(
            ml_url,
            files=files,
            data=form_data,
            timeout=120,
        )

        print(f'[IMAGE-VERIFY] ML response status: {resp.status_code}')

        if resp.status_code == 200:
            try:
                ml_result = resp.json()
            except ValueError:
                error_msg = 'ML service returned a non-JSON response.'
                print(f'[IMAGE-VERIFY] ❌ {error_msg}')
                fail_verification(str(verification.id), error_msg)
                raise VerificationError(error_msg)

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
            _attach_r2_if_completed(verification, user, image_file)

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

    except requests.exceptions.RequestException as exc:
        error_msg = f'ML request failed: {exc}'
        print(f'[IMAGE-VERIFY] ❌ {error_msg}')
        fail_verification(str(verification.id), error_msg)
        raise VerificationError(error_msg)
