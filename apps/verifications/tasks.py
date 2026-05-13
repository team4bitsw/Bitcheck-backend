"""
Verification Celery tasks — ML service dispatch.

The process_verification task:
  1. Marks the verification as 'analyzing'
  2. Calls the FastAPI ML service
  3. On success: calls complete_verification (debits wallet, stores results)
  4. On failure: calls fail_verification (no charge)

Ref: database design doc § 5, § 6 rule 8.
"""

import logging
import requests
from celery import shared_task
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    acks_late=True,
)
def process_verification(self, verification_id):
    """
    Process a verification by calling the ML service.

    This task is dispatched by submit_b2c/b2b_verification().
    """
    from .models import Verification, VerificationJob
    from .services import complete_verification, fail_verification

    try:
        verification = Verification.objects.select_related('job').get(
            pk=verification_id,
        )
    except Verification.DoesNotExist:
        logger.error(f'Verification {verification_id} not found.')
        return

    # Guard: skip if not in a processable state
    if verification.status not in (
        Verification.Status.QUEUED,
        Verification.Status.ANALYZING,
    ):
        logger.info(
            f'Verification {verification_id} already in state '
            f'{verification.status}, skipping.'
        )
        return

    # Mark as analyzing
    verification.status = Verification.Status.ANALYZING
    verification.started_at = timezone.now()
    verification.save(update_fields=['status', 'started_at'])

    # Update job
    try:
        job = verification.job
        job.attempts += 1
        job.started_at = timezone.now()
        job.ml_endpoint = f'{settings.ML_SERVICE_BASE_URL}/api/v1/verify'
        job.save(update_fields=['attempts', 'started_at', 'ml_endpoint', 'updated_at'])
    except VerificationJob.DoesNotExist:
        job = None

    # Build the ML request payload
    payload = _build_ml_payload(verification)

    # --- Mock mode (ML_MOCK_RESPONSE=True) ---
    if getattr(settings, 'ML_MOCK_RESPONSE', False):
        from .mock_ml import generate_mock_ml_response
        uf = verification.uploaded_file
        mock = generate_mock_ml_response(
            filename=uf.original_filename if uf else 'unknown',
            file_size_bytes=uf.size_bytes if uf else 0,
            sha256_hash=uf.sha256 if uf else '',
            user_gmail=verification.user.email if verification.user else '',
        )
        trust_score = mock['trust']['score']
        complete_verification(
            verification_id=verification.id,
            trust_score=trust_score,
            result_summary=mock,
            ml_response_raw=mock,
        )
        logger.info(f'Verification {verification_id} completed via mock. Score: {trust_score}')
        return

    try:
        # Call the ML service
        response = requests.post(
            f'{settings.ML_SERVICE_BASE_URL}/api/v1/verify',
            json=payload,
            timeout=120,  # 2 min timeout for heavy modalities like video
        )

        if response.status_code == 200:
            ml_result = response.json()

            trust_score = ml_result.get('trust_score', 50)
            result_summary = ml_result.get('result_summary', {})

            complete_verification(
                verification_id=verification.id,
                trust_score=trust_score,
                result_summary=result_summary,
                ml_response_raw=ml_result,
            )

            logger.info(
                f'Verification {verification_id} completed via ML. '
                f'Score: {trust_score}'
            )
        else:
            error_msg = f'ML service returned {response.status_code}: {response.text[:500]}'
            logger.error(error_msg)

            # Retry on 5xx
            if response.status_code >= 500:
                raise self.retry(exc=Exception(error_msg))

            fail_verification(verification_id, error_msg)

    except requests.exceptions.ConnectionError:
        error_msg = 'ML service is unreachable.'
        logger.error(f'Verification {verification_id}: {error_msg}')

        if self.request.retries < self.max_retries:
            raise self.retry(exc=Exception(error_msg))

        fail_verification(verification_id, error_msg)

    except requests.exceptions.Timeout:
        error_msg = 'ML service request timed out.'
        logger.error(f'Verification {verification_id}: {error_msg}')

        if self.request.retries < self.max_retries:
            raise self.retry(exc=Exception(error_msg))

        fail_verification(verification_id, error_msg)

    except Exception as e:
        # Don't retry on unexpected errors
        if not isinstance(e, self.MaxRetriesExceededError):
            error_msg = f'Unexpected error: {str(e)}'
            logger.error(
                f'Verification {verification_id}: {error_msg}',
                exc_info=True,
            )
            fail_verification(verification_id, error_msg)


def _build_ml_payload(verification):
    """
    Build the request payload for the ML service.

    The ML team expects:
    {
        "verification_id": "uuid",
        "modality": "image|video|audio|document|text",
        "input": {
            "type": "file|text",
            "storage_key": "...",     // for file types
            "bucket": "...",          // for file types
            "text": "...",            // for text type
            "mime_type": "...",
        }
    }
    """
    payload = {
        'verification_id': str(verification.id),
        'modality': verification.modality,
    }

    if verification.modality == 'text':
        payload['input'] = {
            'type': 'text',
            'text': verification.text_input,
        }
    elif verification.uploaded_file:
        payload['input'] = {
            'type': 'file',
            'storage_key': verification.uploaded_file.storage_key,
            'bucket': verification.uploaded_file.bucket,
            'mime_type': verification.uploaded_file.mime_type,
        }
    else:
        payload['input'] = {'type': 'unknown'}

    return payload
