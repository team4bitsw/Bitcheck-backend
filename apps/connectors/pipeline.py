"""
Inline connector pipeline — runs the full event → verify → reply flow
in the current thread (no Celery worker required).

Called from the webhook view inside a daemon thread so the HTTP response
is returned immediately while processing continues in the background.

For images  → sends bytes directly to ML_IMAGE_SERVICE_BASE_URL/verify/image
For text    → sends JSON directly to ML_TEXT_SERVICE_BASE_URL/verify/text
For others  → falls back to mock until a general ML endpoint is available
"""

from __future__ import annotations

import io
import logging
from typing import TYPE_CHECKING

import requests as http_lib
from django.conf import settings
from django.utils import timezone

from apps.connectors.base import InstallContext, ParsedEvent
from apps.connectors.exceptions import QuotaExceeded
from apps.connectors.models import ConnectorEvent
from apps.connectors.registry import get as get_adapter
from apps.verifications.models import Verification, VerificationJob
from apps.verifications.services import (
    InsufficientBitsError,
    complete_verification,
    fail_verification,
    get_verification_cost,
)

if TYPE_CHECKING:
    from apps.connectors.models import ConnectorInstall
    from apps.connectors.base import VerifiableContent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Quota helper
# ---------------------------------------------------------------------------

def _enforce_quota(install: ConnectorInstall, required_bits: int) -> None:
    from apps.bits.services import (
        check_balance,
        get_wallet_for_organization,
        get_wallet_for_user,
    )
    if install.user_id:
        wallet = get_wallet_for_user(install.user)
    elif install.organization_id:
        wallet = get_wallet_for_organization(install.organization)
    else:
        raise QuotaExceeded('Connector install has no owner')
    if not check_balance(wallet.id, required_bits):
        raise QuotaExceeded(f'Insufficient bits: need {required_bits}')


# ---------------------------------------------------------------------------
# Per-modality ML callers (mirror image_service.py / text_service.py)
# ---------------------------------------------------------------------------

def _make_absolute_url(path: str, base: str) -> str:
    """Turn a relative ML-service path into a full URL."""
    if not path:
        return path
    if path.startswith('http://') or path.startswith('https://'):
        return path
    return base.rstrip('/') + ('/' if not path.startswith('/') else '') + path


def _call_image_ml(content: VerifiableContent, user_email: str) -> tuple[int, dict]:
    """Send image bytes to the real image ML service. Returns (trust_score, result_summary)."""
    ml_base = settings.ML_IMAGE_SERVICE_BASE_URL
    ml_url = f'{ml_base}/verify/image'
    filename = content.filename or 'photo.jpg'
    mime = content.mime_type or 'image/jpeg'

    resp = http_lib.post(
        ml_url,
        files={'file': (filename, io.BytesIO(content.payload), mime)},
        data={'user_email': user_email},
        timeout=120,
    )
    resp.raise_for_status()
    ml = resp.json()

    # Make heatmap / boxed-image URLs absolute so the frontend can load them.
    explainability = ml.get('explainability') or {}
    if explainability.get('heatmap_url'):
        explainability['heatmap_url'] = _make_absolute_url(explainability['heatmap_url'], ml_base)
    if explainability.get('boxed_image_url'):
        explainability['boxed_image_url'] = _make_absolute_url(explainability['boxed_image_url'], ml_base)

    trust_score = int(round(ml.get('trust', {}).get('score', 50)))
    result_summary = {
        'original_filename': filename,
        'mime_type': mime,
        'ml_verification_id': ml.get('verification_id'),
        'user_email': ml.get('user_email', ''),
        'input': ml.get('input', {}),
        'model_result': ml.get('model_result', {}),
        'metadata': ml.get('metadata', {}),
        'provenance': ml.get('provenance', {}),
        'visible_watermark': ml.get('visible_watermark', {}),
        'forensics': ml.get('forensics', {}),
        'explainability': explainability,
        'trust': ml.get('trust', {}),
        'risk_flags': ml.get('risk_flags', []),
        'limitations': ml.get('limitations', []),
    }
    return trust_score, result_summary


def _call_text_ml(content: VerifiableContent) -> tuple[int, dict]:
    """Send text to the real text ML service. Returns (trust_score, result_summary)."""
    ml_url = f'{settings.ML_TEXT_SERVICE_BASE_URL}/verify/text'
    text = content.payload if isinstance(content.payload, str) else content.payload.decode('utf-8')

    resp = http_lib.post(
        ml_url,
        json={'text': text},
        timeout=60,
    )
    resp.raise_for_status()
    ml = resp.json()

    trust_score = int(ml.get('trust', {}).get('trust_score', 50))
    result_summary = {
        'text_preview': text[:200],
        'text_length': len(text),
        'ml_verification_id': ml.get('verification_id'),
        'trust': ml.get('trust', {}),
        'risk_flags': ml.get('risk_flags', []),
        'ai_likelihood': ml.get('ai_likelihood', {}),
        'claims': ml.get('claims', []),
        'fraud_signals': ml.get('fraud_signals', {}),
        'manipulation_signals': ml.get('manipulation_signals', {}),
        'source_analysis': ml.get('source_analysis', {}),
        'recommended_actions': ml.get('recommended_actions', []),
    }
    return trust_score, result_summary


def _call_mock_ml(content: VerifiableContent, user_email: str) -> tuple[int, dict]:
    """Fallback mock for modalities without a real ML endpoint yet."""
    from apps.verifications.mock_ml import generate_mock_ml_response
    mock = generate_mock_ml_response(
        filename=content.filename or 'file',
        file_size_bytes=len(content.payload) if isinstance(content.payload, bytes) else 0,
        sha256_hash='',
        user_email=user_email,
    )
    trust_score = int(round(mock['trust']['score']))
    return trust_score, mock


# ---------------------------------------------------------------------------
# Verification runner — no Celery, no R2 required
# ---------------------------------------------------------------------------

def _upload_to_r2(install: ConnectorInstall, content: VerifiableContent) -> 'UploadedFile | None':
    """Upload file bytes to R2 and return the UploadedFile record, or None on failure."""
    from apps.verifications.storage_upload import upload_bytes_for_connector_owner

    body: bytes = (
        content.payload
        if isinstance(content.payload, bytes)
        else content.payload.encode('utf-8')
    )
    filename = content.filename or 'telegram-file.bin'
    mime = content.mime_type or 'application/octet-stream'

    logger.info('[R2] uploading %s (%d bytes) for install=%s', filename, len(body), install.id)
    try:
        uf = upload_bytes_for_connector_owner(
            user=install.user,
            organization=install.organization,
            data=body,
            original_filename=filename,
            mime_type=mime,
        )
        logger.info('[R2] upload OK → bucket=%s key=%s uploaded_file=%s', uf.bucket, uf.storage_key, uf.id)
        return uf
    except Exception:
        logger.exception('[R2] upload FAILED for install=%s file=%s', install.id, filename)
        return None


def _run_verification_inline(
    install: ConnectorInstall,
    content: VerifiableContent,
) -> Verification:
    """
    Upload to R2, call the appropriate ML service with the content bytes,
    create a Verification record, and return it completed.
    """
    modality_map = {
        'text': Verification.Modality.TEXT,
        'image': Verification.Modality.IMAGE,
        'document': Verification.Modality.DOCUMENT,
        'audio': Verification.Modality.AUDIO,
        'video': Verification.Modality.VIDEO,
    }
    modality = modality_map.get(content.kind)
    if modality is None:
        raise ValueError(f'Unsupported modality: {content.kind}')

    user_email = install.user.email if install.user else ''

    # Upload to R2 for all file types (text stays in DB only)
    uploaded_file = None
    if modality != Verification.Modality.TEXT:
        uploaded_file = _upload_to_r2(install, content)

    # Create Verification record (uploaded_file may be None if R2 failed — that's OK)
    verification = Verification.objects.create(
        user=install.user if install.user_id else None,
        organization=install.organization if install.organization_id else None,
        modality=modality,
        uploaded_file=uploaded_file,
        text_input=str(content.payload) if modality == Verification.Modality.TEXT else None,
        status=Verification.Status.ANALYZING,
        started_at=timezone.now(),
    )
    VerificationJob.objects.create(
        verification=verification,
        enqueued_at=timezone.now(),
        started_at=timezone.now(),
        attempts=1,
    )

    try:
        logger.info('[ML] calling service modality=%s verification=%s', modality, verification.id)
        if modality == Verification.Modality.IMAGE:
            trust_score, result_summary = _call_image_ml(content, user_email)
        elif modality == Verification.Modality.TEXT:
            trust_score, result_summary = _call_text_ml(content)
        else:
            # Document / audio / video — mock until general ML endpoint exists
            trust_score, result_summary = _call_mock_ml(content, user_email)

        logger.info('[ML] result verification=%s score=%s', verification.id, trust_score)
        verification = complete_verification(
            verification_id=verification.id,
            trust_score=trust_score,
            result_summary=result_summary,
            ml_response_raw=result_summary,
        )
    except Exception as exc:
        fail_verification(str(verification.id), str(exc))
        logger.exception('[ML] call FAILED verification=%s error=%s', verification.id, exc)
        verification.refresh_from_db()

    return verification


# ---------------------------------------------------------------------------
# Main entry point — called from webhook view in a daemon thread
# ---------------------------------------------------------------------------

def process_event_inline(event_id: str) -> None:
    """Run the full connector pipeline synchronously in the calling thread."""

    try:
        event = ConnectorEvent.objects.select_related('install', 'install__type').get(pk=event_id)
    except ConnectorEvent.DoesNotExist:
        logger.error('inline pipeline: event %s not found', event_id)
        return

    install = event.install
    event.status = ConnectorEvent.Status.PROCESSING
    event.save(update_fields=['status'])

    adapter = get_adapter(install.type.slug)
    ctx = InstallContext(
        install_id=str(install.id),
        credentials=install.credentials or {},
        settings=install.settings or {},
        org_id=str(install.organization_id) if install.organization_id else None,
        user_id=str(install.user_id) if install.user_id else None,
    )
    parsed = ParsedEvent(
        external_event_id=event.external_event_id,
        event_type=event.event_type,
        raw_payload=event.raw_payload or {},
    )

    # 1. Extract content (downloads file from Telegram into memory)
    try:
        contents = list(adapter.extract_content(ctx, parsed))
    except Exception:
        logger.exception('inline pipeline: extract_content failed event=%s', event_id)
        event.status = ConnectorEvent.Status.FAILED
        event.processed_at = timezone.now()
        event.save(update_fields=['status', 'processed_at'])
        return

    if not contents:
        event.status = ConnectorEvent.Status.PROCESSED
        event.processed_at = timezone.now()
        event.save(update_fields=['status', 'processed_at'])
        return

    # 2. Quota check
    total_bits = sum(get_verification_cost(c.kind) for c in contents)
    try:
        _enforce_quota(install, total_bits)
    except QuotaExceeded:
        event.status = ConnectorEvent.Status.IGNORED
        event.processed_at = timezone.now()
        event.save(update_fields=['status', 'processed_at'])
        return

    # 3. Run ML + send result for each content item
    for item in contents:
        try:
            verification = _run_verification_inline(install, item)
        except InsufficientBitsError:
            event.status = ConnectorEvent.Status.IGNORED
            event.processed_at = timezone.now()
            event.save(update_fields=['status', 'processed_at'])
            return
        except Exception:
            logger.exception('inline pipeline: verification failed event=%s', event_id)
            event.status = ConnectorEvent.Status.FAILED
            event.processed_at = timezone.now()
            event.save(update_fields=['status', 'processed_at'])
            return

        verification.source = 'connector'
        verification.source_install = install
        verification.source_event = event
        verification.save(update_fields=['source', 'source_install', 'source_event'])
        event.verifications.add(verification)

        # 4. Send the result back to Telegram
        try:
            adapter.send_result(ctx, parsed, verification)
        except Exception:
            logger.exception('inline pipeline: send_result failed event=%s', event_id)

    event.status = ConnectorEvent.Status.PROCESSED
    event.processed_at = timezone.now()
    event.save(update_fields=['status', 'processed_at'])
