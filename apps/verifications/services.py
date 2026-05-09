"""
Verification services — submission, ML dispatch, and completion.

Orchestrates the full verification lifecycle:
  1. Submit: validate input → check balance → create Verification + Job
  2. Process: Celery task calls ML service → updates results → debits wallet

Ref: database design doc § 5 (state machine), § 6 rule 8.
"""

import logging
import uuid
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Verification, VerificationJob, UploadedFile
from apps.bits.services import (
    check_balance,
    debit_wallet,
    get_wallet_for_user,
    get_wallet_for_organization,
    InsufficientBits,
)

logger = logging.getLogger(__name__)


class VerificationError(Exception):
    """Base exception for verification failures."""
    pass


class InsufficientBitsError(VerificationError):
    """User doesn't have enough bits for this verification."""

    def __init__(self, required, available):
        self.required = required
        self.available = available
        super().__init__(
            f'Insufficient bits: need {required}, have {available}'
        )


def get_verification_cost(modality):
    """
    Get the bit cost for a given modality.

    Returns the cost from settings.BITCHECK_VERIFICATION_COSTS.
    """
    return settings.BITCHECK_VERIFICATION_COSTS.get(modality, 0)


def submit_b2c_verification(
    user,
    modality,
    text_input=None,
    uploaded_file_id=None,
):
    """
    Submit a B2C verification (from the web dashboard).

    Steps:
      1. Validate modality and input
      2. Check balance (pre-flight, no lock)
      3. Create Verification + VerificationJob
      4. Dispatch Celery task

    The actual wallet debit happens ONLY when the ML job completes
    successfully (§ 6 rule 8).

    Returns the created Verification.
    """
    cost = get_verification_cost(modality)
    wallet = get_wallet_for_user(user)

    # Pre-flight balance check (no lock — the debit will re-check)
    if not check_balance(wallet.id, cost):
        raise InsufficientBitsError(required=cost, available=wallet.balance_bits)

    # Validate input
    uploaded_file = None
    if modality == 'text':
        if not text_input:
            raise VerificationError('Text input is required for text modality.')
        uploaded_file_id = None
    else:
        if not uploaded_file_id:
            raise VerificationError(f'An uploaded file is required for {modality} modality.')
        try:
            uploaded_file = UploadedFile.objects.get(
                pk=uploaded_file_id,
                owner_user=user,
            )
        except UploadedFile.DoesNotExist:
            raise VerificationError('Uploaded file not found or not owned by you.')
        text_input = None

    # Create verification + job
    with transaction.atomic():
        verification = Verification.objects.create(
            user=user,
            modality=modality,
            uploaded_file=uploaded_file,
            text_input=text_input,
            status=Verification.Status.QUEUED,
        )

        job = VerificationJob.objects.create(
            verification=verification,
            enqueued_at=timezone.now(),
        )

    # Dispatch to Celery
    from .tasks import process_verification
    task = process_verification.delay(str(verification.id))

    # Store the Celery task ID
    job.celery_task_id = task.id
    job.save(update_fields=['celery_task_id'])

    logger.info(
        f'B2C verification submitted: id={verification.id}, '
        f'modality={modality}, user={user.email}, cost={cost} bits'
    )

    return verification


def submit_b2b_verification(
    organization,
    api_key,
    modality,
    text_input=None,
    uploaded_file_id=None,
    api_call=None,
):
    """
    Submit a B2B verification (from the API).

    Same flow as B2C but with organization ownership and API key tracing.

    Returns the created Verification.
    """
    cost = get_verification_cost(modality)
    wallet = get_wallet_for_organization(organization)

    # Pre-flight balance check
    if not check_balance(wallet.id, cost):
        raise InsufficientBitsError(required=cost, available=wallet.balance_bits)

    # Validate input
    uploaded_file = None
    if modality == 'text':
        if not text_input:
            raise VerificationError('Text input is required for text modality.')
        uploaded_file_id = None
    else:
        if not uploaded_file_id:
            raise VerificationError(f'An uploaded file is required for {modality} modality.')
        try:
            uploaded_file = UploadedFile.objects.get(
                pk=uploaded_file_id,
                owner_organization=organization,
            )
        except UploadedFile.DoesNotExist:
            raise VerificationError('Uploaded file not found or not owned by this organization.')
        text_input = None

    # Create verification + job
    with transaction.atomic():
        verification = Verification.objects.create(
            organization=organization,
            api_key=api_key,
            api_call=api_call,
            modality=modality,
            uploaded_file=uploaded_file,
            text_input=text_input,
            status=Verification.Status.QUEUED,
        )

        job = VerificationJob.objects.create(
            verification=verification,
            enqueued_at=timezone.now(),
        )

    # Dispatch to Celery
    from .tasks import process_verification
    task = process_verification.delay(str(verification.id))

    job.celery_task_id = task.id
    job.save(update_fields=['celery_task_id'])

    logger.info(
        f'B2B verification submitted: id={verification.id}, '
        f'modality={modality}, org={organization.name}, cost={cost} bits'
    )

    return verification


def complete_verification(verification_id, trust_score, result_summary, ml_response_raw=None):
    """
    Mark a verification as completed with results.

    This is called by the Celery task after the ML service returns.
    It debits the wallet and records the result.

    Ref: database design doc § 6 rule 8 — bits debited only on success.

    Args:
        verification_id: UUID of the Verification.
        trust_score:     Integer 0-100.
        result_summary:  Dict matching the frontend contract.
        ml_response_raw: Optional full ML response for debugging.
    """
    with transaction.atomic():
        verification = Verification.objects.select_for_update().get(
            pk=verification_id,
        )

        # Guard: skip if already completed/failed
        if verification.status not in (
            Verification.Status.QUEUED,
            Verification.Status.ANALYZING,
        ):
            logger.warning(
                f'Verification {verification_id} already in state '
                f'{verification.status}, skipping completion.'
            )
            return verification

        # Derive verdict from trust score
        verdict = Verification.derive_verdict(trust_score)

        # Get the cost and wallet
        cost = get_verification_cost(verification.modality)

        if verification.user_id:
            wallet = get_wallet_for_user(verification.user)
        else:
            wallet = get_wallet_for_organization(verification.organization)

        # Debit the wallet (this is the real charge — § 6 rule 8)
        try:
            debit_wallet(
                wallet_id=wallet.id,
                amount=cost,
                entry_type='usage',
                reference_type='verification',
                reference_id=str(verification.id),
                note=f'{verification.modality} verification',
            )
        except InsufficientBits:
            # Edge case: balance dropped between submission and completion
            verification.status = Verification.Status.FAILED
            verification.error_message = 'Insufficient bits at completion time.'
            verification.save(update_fields=[
                'status', 'error_message', 'completed_at',
            ])
            logger.error(
                f'Insufficient bits at completion for verification {verification_id}'
            )
            return verification

        # Update verification with results
        verification.status = Verification.Status.COMPLETED
        verification.trust_score = trust_score
        verification.verdict = verdict
        verification.result_summary = result_summary
        verification.bits_charged = cost
        verification.completed_at = timezone.now()
        verification.save(update_fields=[
            'status', 'trust_score', 'verdict', 'result_summary',
            'bits_charged', 'completed_at',
        ])

        # Update the job record
        try:
            job = verification.job
            job.completed_at = timezone.now()
            if ml_response_raw:
                job.ml_response_raw = ml_response_raw
            job.save(update_fields=['completed_at', 'ml_response_raw', 'updated_at'])
        except VerificationJob.DoesNotExist:
            pass

    logger.info(
        f'Verification {verification_id} completed: '
        f'score={trust_score}, verdict={verdict}, charged={cost} bits'
    )

    return verification


def fail_verification(verification_id, error_message):
    """
    Mark a verification as failed. No bits are charged.

    Ref: database design doc § 6 rule 8 — no debit on failure.
    """
    with transaction.atomic():
        verification = Verification.objects.select_for_update().get(
            pk=verification_id,
        )

        verification.status = Verification.Status.FAILED
        verification.error_message = error_message
        verification.completed_at = timezone.now()
        verification.save(update_fields=[
            'status', 'error_message', 'completed_at',
        ])

        try:
            job = verification.job
            job.last_error = error_message
            job.completed_at = timezone.now()
            job.save(update_fields=['last_error', 'completed_at', 'updated_at'])
        except VerificationJob.DoesNotExist:
            pass

    logger.info(
        f'Verification {verification_id} failed: {error_message}. '
        f'0 bits charged.'
    )

    return verification
