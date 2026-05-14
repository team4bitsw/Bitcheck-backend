"""
Text verification service — direct submission to ML text service.

Handles the text verification flow:
  1. Accept text input from the user
  2. Forward to ML service's POST /verify/text
  3. Map the ML response to our Verification model
  4. Debit bits on success

ML API contract (BitCheck Text Verification API):
  - Endpoint: POST {ML_TEXT_SERVICE_BASE_URL}/verify/text
  - Body (JSON): text (required), source_url, context, language,
                  check_ai_likelihood, check_fraud_signals, check_claims, check_source_url
  - Text: 5–8000 characters
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
from apps.bits.services import check_balance, get_wallet_for_user, get_wallet_for_organization

logger = logging.getLogger(__name__)

MIN_TEXT_LENGTH = 5
MAX_TEXT_LENGTH = 8000


def _map_text_ml_response(ml_result, text_input, label):
    """
    Map the ML text service response to our result_summary format.
    """
    # Log raw ML keys for debugging schema mismatches
    print(f'[TEXT-VERIFY] ML response keys: {list(ml_result.keys()) if ml_result else "None"}')

    # The ML may return trust=None or omit it entirely
    trust_data = ml_result.get('trust') or {}
    # Try trust_score first, then score (image-style), then default 50
    trust_score_raw = (
        trust_data.get('trust_score')
        or trust_data.get('score')
        or ml_result.get('trust_score')
        or 50
    )
    trust_score = int(trust_score_raw)

    result_summary = {
        'label': label or '',
        'text_length': len(text_input),
        'text_preview': text_input[:200],
        'ml_verification_id': ml_result.get('verification_id'),
        'input': ml_result.get('input') or {},
        'trust': trust_data,
        'risk_flags': ml_result.get('risk_flags') or [],
        'recommended_actions': ml_result.get('recommended_actions') or [],
        'ai_likelihood': ml_result.get('ai_likelihood') or {},
        'claims': ml_result.get('claims') or [],
        'fraud_signals': ml_result.get('fraud_signals') or {},
        'manipulation_signals': ml_result.get('manipulation_signals') or {},
        'source_analysis': ml_result.get('source_analysis') or {},
        'warnings': ml_result.get('warnings') or [],
        'limitations': ml_result.get('limitations') or [],
    }

    return trust_score, result_summary


def verify_text_direct(
    user,
    text_input,
    source_url=None,
    context=None,
    label=None,
    check_ai_likelihood=True,
    check_fraud_signals=True,
    check_claims=True,
    check_source_url=True,
    organization=None,
    api_key=None,
):
    """
    Submit text for verification directly.

    Args:
        user:                The authenticated User.
        text_input:          The text to verify (5-8000 chars).
        source_url:          Optional URL where the text was found.
        context:             Optional context hint (e.g., "WhatsApp broadcast").
        label:               Optional user-provided tracking identifier.
        check_ai_likelihood: Whether to check AI generation likelihood.
        check_fraud_signals: Whether to check for fraud signals.
        check_claims:        Whether to check claims in the text.
        check_source_url:    Whether to analyze the source URL.
        organization:        If provided, this is a B2B call - use org wallet.
        api_key:             If provided, the ApiKey used for this B2B call.

    Returns:
        (Verification, ml_result_dict) - the saved verification + full ML response.

    Raises:
        InsufficientBitsError: Not enough bits.
        VerificationError:     Invalid input or ML service error.
    """
    is_b2b = organization is not None

    # --- Validate text ---
    if not text_input or not text_input.strip():
        raise VerificationError('Text input is required.')

    text_input = text_input.strip()

    if len(text_input) < MIN_TEXT_LENGTH:
        raise VerificationError(
            f'Text too short: {len(text_input)} characters. '
            f'Minimum: {MIN_TEXT_LENGTH} characters.'
        )

    if len(text_input) > MAX_TEXT_LENGTH:
        raise VerificationError(
            f'Text too long: {len(text_input)} characters. '
            f'Maximum: {MAX_TEXT_LENGTH} characters.'
        )

    # --- Pre-flight balance check ---
    cost = get_verification_cost('text')
    if is_b2b:
        wallet = get_wallet_for_organization(organization)
    else:
        wallet = get_wallet_for_user(user)
    if not check_balance(wallet.id, cost):
        raise InsufficientBitsError(required=cost, available=wallet.balance_bits)

    # --- Compute text hash for deduplication ---
    text_hash = hashlib.sha256(text_input.encode('utf-8')).hexdigest()

    # --- Build ownership kwargs ---
    if is_b2b:
        ownership = {'organization': organization, 'api_key': api_key}
    else:
        ownership = {'user': user}

    # --- Create Verification + Job ---
    ml_url = f'{settings.ML_TEXT_SERVICE_BASE_URL}/verify/text'
    with transaction.atomic():
        verification = Verification.objects.create(
            **ownership,
            modality=Verification.Modality.TEXT,
            status=Verification.Status.ANALYZING,
            started_at=timezone.now(),
            text_input=text_input,
            result_summary={
                'label': label or '',
                'text_length': len(text_input),
                'text_hash': text_hash,
                'source_url': source_url or '',
            },
        )
        job = VerificationJob.objects.create(
            verification=verification,
            enqueued_at=timezone.now(),
            started_at=timezone.now(),
            ml_endpoint=ml_url,
            attempts=1,
        )

    print(f'[TEXT-VERIFY] Created verification {verification.id}')
    print(f'[TEXT-VERIFY] Text length: {len(text_input)}, hash: {text_hash[:16]}...')
    print(f'[TEXT-VERIFY] Label: {label or "(none)"}, user: {user.email}')
    if source_url:
        print(f'[TEXT-VERIFY] Source URL: {source_url}')

    # --- Mock or Real ML call ---
    if getattr(settings, 'ML_MOCK_RESPONSE', False):
        from .mock_text_ml import generate_mock_text_ml_response
        print(f'[TEXT-VERIFY] ⚠️ ML_MOCK_RESPONSE=True — returning mock result')

        ml_result = generate_mock_text_ml_response(
            text_input=text_input,
            source_url=source_url,
        )

        trust_score, result_summary = _map_text_ml_response(
            ml_result, text_input, label,
        )
        result_summary['_mock'] = True

        verification = complete_verification(
            verification_id=verification.id,
            trust_score=trust_score,
            result_summary=result_summary,
            ml_response_raw=ml_result,
        )

        print(f'[TEXT-VERIFY] ✅ Mock verification {verification.id} completed: '
              f'score={trust_score}, verdict={verification.verdict}')

        return verification, ml_result

    # --- Real ML service call ---
    json_payload = {
        'text': text_input,
        'check_ai_likelihood': check_ai_likelihood,
        'check_fraud_signals': check_fraud_signals,
        'check_claims': check_claims,
        'check_source_url': check_source_url,
    }
    if source_url:
        json_payload['source_url'] = source_url
    if context:
        json_payload['context'] = context

    print(f'[TEXT-VERIFY] Sending to ML: {ml_url}')

    try:
        resp = requests.post(
            ml_url,
            json=json_payload,
            timeout=60,
        )

        print(f'[TEXT-VERIFY] ML response status: {resp.status_code}')

        if resp.status_code == 200:
            ml_result = resp.json()

            trust_score, result_summary = _map_text_ml_response(
                ml_result, text_input, label,
            )

            print(f'[TEXT-VERIFY] ML trust_score: {trust_score}, '
                  f'risk_level: {(ml_result.get("trust") or {}).get("risk_level")}')

            verification = complete_verification(
                verification_id=verification.id,
                trust_score=trust_score,
                result_summary=result_summary,
                ml_response_raw=ml_result,
            )

            print(f'[TEXT-VERIFY] ✅ Verification {verification.id} completed: '
                  f'score={trust_score}, verdict={verification.verdict}')

            return verification, ml_result

        else:
            error_msg = f'ML text service returned {resp.status_code}: {resp.text[:500]}'
            print(f'[TEXT-VERIFY] ❌ ML error: {error_msg}')
            fail_verification(str(verification.id), error_msg)
            raise VerificationError(error_msg)

    except requests.exceptions.ConnectionError:
        error_msg = f'ML text service unreachable at {ml_url}'
        print(f'[TEXT-VERIFY] ❌ Connection error: {error_msg}')
        fail_verification(str(verification.id), error_msg)
        raise VerificationError(error_msg)

    except requests.exceptions.Timeout:
        error_msg = 'ML text service request timed out (60s).'
        print(f'[TEXT-VERIFY] ❌ Timeout: {error_msg}')
        fail_verification(str(verification.id), error_msg)
        raise VerificationError(error_msg)
