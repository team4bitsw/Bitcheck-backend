"""
Billing services — Squad payment integration for B2C subscriptions.

Implements the Card Tokenization flow from Squad's Initiate Payment API:
  1. Initiate a payment with is_recurring=True → get checkout URL
  2. User pays on Squad's modal → Squad sends charge_successful webhook
  3. Webhook contains token_id → store for future recurring charges
  4. Renewal: call Squad's charge_card API with the stored token_id

Ref: docs/Squad_API_Docs/Initiate-payment.md
"""

import logging
import uuid
import requests

from django.conf import settings

logger = logging.getLogger(__name__)


# ============================================================
# Squad API Client
# ============================================================

def _squad_headers():
    """Common headers for Squad API calls."""
    return {
        'Authorization': f'Bearer {settings.SQUAD_SECRET_KEY}',
        'Content-Type': 'application/json',
    }


def initiate_pro_checkout(user, callback_url=None):
    """
    Call Squad's /transaction/initiate to start a card-tokenization payment
    for the Pro plan upgrade.

    Returns:
        dict with 'checkout_url' and 'transaction_ref' on success
        raises ValueError on failure

    The key difference from a normal payment: `is_recurring: True`.
    This tells Squad to tokenize the card and return a token_id in the
    charge_successful webhook, which we store for future recurring charges.
    """
    from apps.billing.models import Plan

    pro_plan = Plan.objects.get(code=Plan.Code.PRO)
    transaction_ref = f'bck_pro_{uuid.uuid4().hex[:16]}'

    # Squad expects amounts in kobo (lowest currency unit)
    amount_kobo = pro_plan.recurring_charge_naira * 100

    payload = {
        'email': user.email,
        'amount': amount_kobo,
        'currency': 'NGN',
        'initiate_type': 'inline',
        'transaction_ref': transaction_ref,
        'customer_name': user.full_name or user.email,
        'callback_url': callback_url or '',
        'payment_channels': ['card'],
        'is_recurring': True,
        'metadata': {
            'user_id': str(user.id),
            'plan_code': 'pro',
            'purpose': 'pro_upgrade',
        },
    }

    url = f'{settings.SQUAD_BASE_URL}/transaction/initiate'

    try:
        resp = requests.post(url, json=payload, headers=_squad_headers(), timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.error(f'Squad initiate_payment failed for {user.email}: {e}')
        raise ValueError(f'Payment gateway error: {e}')

    if data.get('status') != 200:
        msg = data.get('message', 'Unknown error')
        logger.error(f'Squad initiate_payment rejected: {msg}')
        raise ValueError(f'Payment gateway rejected: {msg}')

    checkout_url = data['data'].get('checkout_url', '')
    if not checkout_url:
        raise ValueError('No checkout URL returned from payment gateway.')

    return {
        'checkout_url': checkout_url,
        'transaction_ref': transaction_ref,
    }


def charge_card_recurring(token_id, amount_kobo, transaction_ref=None):
    """
    Charge a tokenized card using Squad's /transaction/charge_card API.

    Used by the subscription rollover Celery task to auto-charge
    Pro users for the next billing period.

    Args:
        token_id: The card token from Squad (e.g., AUTH_lBlGESHDLMX_60049043)
        amount_kobo: Amount to charge in kobo
        transaction_ref: Optional unique reference (auto-generated if not provided)

    Returns:
        dict with Squad's response data on success
        raises ValueError on failure
    """
    if not transaction_ref:
        transaction_ref = f'bck_renew_{uuid.uuid4().hex[:16]}'

    payload = {
        'amount': amount_kobo,
        'token_id': token_id,
        'transaction_ref': transaction_ref,
    }

    url = f'{settings.SQUAD_BASE_URL}/transaction/charge_card'

    try:
        resp = requests.post(url, json=payload, headers=_squad_headers(), timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.error(f'Squad charge_card failed: {e}')
        raise ValueError(f'Recurring charge failed: {e}')

    if data.get('status') != 200:
        msg = data.get('message', 'Unknown error')
        logger.error(f'Squad charge_card rejected: {msg}')
        raise ValueError(f'Recurring charge rejected: {msg}')

    logger.info(f'Recurring charge successful: {transaction_ref}')
    return data.get('data', {})


def cancel_card_token(token_id):
    """
    Cancel a tokenized card using Squad's /transaction/cancel/recurring API.

    Called when a user cancels their Pro subscription, so we stop
    being authorized to charge their card.

    Args:
        token_id: The card token to cancel

    Returns:
        True on success, False on failure
    """
    payload = {
        'auth_code': [token_id],
    }

    url = f'{settings.SQUAD_BASE_URL}/transaction/cancel/recurring'

    try:
        resp = requests.patch(url, json=payload, headers=_squad_headers(), timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.error(f'Squad cancel_recurring failed for token {token_id}: {e}')
        return False

    if data.get('status') != 200:
        logger.error(f'Squad cancel_recurring rejected: {data.get("message")}')
        return False

    logger.info(f'Card token {token_id} canceled successfully.')
    return True
