"""
Webhook services — signature verification and event processing.

Processing rule (§ 4.8):
  The HTTP handler does ONLY two things:
    1. Verify signature
    2. Insert row
  Actual processing happens in a Celery worker that picks up
  status='received' rows.

Ref: database design doc § 4.8, § 5.3
"""

import hashlib
import hmac
import json
import logging
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import WebhookEvent
from apps.bits.models import TopUp, VirtualAccount
from apps.bits.services import credit_wallet, get_wallet_for_organization

logger = logging.getLogger(__name__)


# ============================================================
# Signature Verification
# ============================================================

def verify_squad_signature(payload_body, signature_header):
    """
    Verify the Squad webhook signature using HMAC-SHA512.

    Squad sends the signature in the `x-squad-encrypted-body` header.
    We compute HMAC-SHA512 of the raw body using our webhook secret
    and compare.

    Returns True if valid, False otherwise.
    """
    if not signature_header:
        print('[SIGNATURE] No signature header provided')
        return False

    secret = settings.SQUAD_WEBHOOK_SECRET
    if not secret:
        print('[SIGNATURE] ❌ SQUAD_WEBHOOK_SECRET is not configured!')
        logger.warning('SQUAD_WEBHOOK_SECRET is not configured.')
        return False

    print(f'[SIGNATURE] Secret key (first 15 chars): {secret[:15]}...')
    print(f'[SIGNATURE] Received sig (first 20 chars): {signature_header[:20]}...')

    expected = hmac.new(
        secret.encode('utf-8'),
        payload_body,
        hashlib.sha512,
    ).hexdigest()

    print(f'[SIGNATURE] Computed sig (first 20 chars): {expected[:20]}...')
    match = hmac.compare_digest(expected, signature_header)
    print(f'[SIGNATURE] Match: {match}')
    return match


# ============================================================
# Event Ingestion
# ============================================================

def ingest_webhook_event(source, event_type, payload, headers, external_id=None, signature=None):
    """
    Insert a webhook event into the inbox.

    This is the ONLY thing the HTTP handler should do after
    signature verification. Processing is deferred to Celery.

    Returns the created WebhookEvent.
    """
    event = WebhookEvent.objects.create(
        source=source,
        event_type=event_type,
        external_id=external_id,
        signature=signature,
        payload=payload,
        headers=headers,
        status=WebhookEvent.Status.RECEIVED,
    )

    logger.info(f'Webhook event ingested: {event.source}:{event.event_type} ({event.id})')
    return event


# ============================================================
# Event Processing (called by Celery worker)
# ============================================================

def process_webhook_event(event_id):
    """
    Process a webhook event from the inbox.

    Dispatches to the appropriate handler based on source + event_type.
    Updates the event status to 'processed' or 'failed'.
    """
    print(f'[PROCESS] Starting processing for event {event_id}')
    try:
        event = WebhookEvent.objects.get(pk=event_id)
    except WebhookEvent.DoesNotExist:
        print(f'[PROCESS] ❌ Event {event_id} not found in DB!')
        logger.error(f'Webhook event {event_id} not found.')
        return

    print(f'[PROCESS] Event found: source={event.source}, type={event.event_type}, status={event.status}')

    # Guard: skip if already processed
    if event.status != WebhookEvent.Status.RECEIVED:
        print(f'[PROCESS] ⚠️ Event already in state "{event.status}", skipping.')
        logger.info(f'Event {event_id} already in state {event.status}, skipping.')
        return

    try:
        if event.source == 'squad':
            print(f'[PROCESS] Routing to Squad handler...')
            _process_squad_event(event)
        else:
            print(f'[PROCESS] ⚠️ Unknown source: {event.source}')
            event.status = WebhookEvent.Status.IGNORED
            event.processing_error = f'Unknown source: {event.source}'
            event.processed_at = timezone.now()
            event.save(update_fields=['status', 'processing_error', 'processed_at'])

    except Exception as e:
        print(f'[PROCESS] ❌ FAILED: {e}')
        event.status = WebhookEvent.Status.FAILED
        event.processing_error = str(e)[:2000]
        event.processed_at = timezone.now()
        event.save(update_fields=['status', 'processing_error', 'processed_at'])

        logger.error(
            f'Failed to process webhook event {event_id}: {e}',
            exc_info=True,
        )
        raise  # Re-raise so Celery can retry


def _process_squad_event(event):
    """
    Route Squad webhook events to the appropriate handler.

    Squad event types we handle:
      - charge_successful:    B2C card payment succeeded
      - transfer.successful:  B2B virtual account credit (bank transfer)
    """
    event_type = event.event_type
    payload = event.payload

    print(f'[SQUAD] Routing event_type="{event_type}"')

    if event_type == 'transfer.successful':
        print(f'[SQUAD] → _handle_virtual_account_credit()')
        _handle_virtual_account_credit(event, payload)
    elif event_type == 'charge_successful':
        print(f'[SQUAD] → _handle_subscription_charge()')
        _handle_subscription_charge(event, payload)
    else:
        print(f'[SQUAD] ⚠️ Unknown event type: {event_type}')
        event.status = WebhookEvent.Status.IGNORED
        event.processing_error = f'Unhandled Squad event type: {event_type}'
        event.processed_at = timezone.now()
        event.save(update_fields=['status', 'processing_error', 'processed_at'])
        logger.info(f'Ignored Squad event type: {event_type}')


def _handle_virtual_account_credit(event, payload):
    """
    Handle a B2B virtual account credit (bank transfer received).

    Squad VA webhook payload (at root level, NOT nested under 'data'):
      {
        "transaction_reference": "REF20260424..._1",
        "virtual_account_number": "9013151600",
        "principal_amount": "1.00",         <- naira string, NOT kobo
        "settled_amount": "1.00",
        "customer_identifier": "my-org",    <- our org.slug
        "channel": "virtual-account",
        "currency": "NGN",
        ...
      }

    Flow:
      1. Extract customer_identifier -> look up VirtualAccount by squad_account_reference
      2. Parse principal_amount (naira string) -> convert to whole naira integer
      3. Calculate bits from naira
      4. Create idempotent TopUp record
      5. Credit the org's wallet
      6. Mark the event as processed

    Ref: docs/Squad_API_Docs/VIRTUAL_ACCOUNT/api-specifications.mdx
    """
    # Squad VA webhooks put data at root, but also handle nested 'data' for safety
    transaction_data = payload.get('data', payload) if isinstance(payload.get('data'), dict) else payload

    squad_reference = transaction_data.get('transaction_reference', '')
    account_number = transaction_data.get('virtual_account_number', '')
    customer_identifier = transaction_data.get('customer_identifier', '')

    # Squad sends amounts as naira strings (e.g., "50.00"), NOT kobo integers
    principal_amount_str = str(transaction_data.get('principal_amount', '0'))
    try:
        amount_naira = int(float(principal_amount_str))  # "50.00" -> 50
    except (ValueError, TypeError):
        raise ValueError(f'Invalid principal_amount: {principal_amount_str}')

    if not squad_reference:
        raise ValueError('Missing transaction_reference in Squad VA payload')

    # Idempotency check — squad_transaction_reference is UNIQUE
    if TopUp.objects.filter(squad_transaction_reference=squad_reference).exists():
        event.status = WebhookEvent.Status.PROCESSED
        event.processing_error = 'Duplicate: already processed this transaction.'
        event.processed_at = timezone.now()
        event.save(update_fields=['status', 'processing_error', 'processed_at'])
        logger.info(f'Duplicate Squad VA transaction {squad_reference}, skipping.')
        return

    # Look up virtual account — prefer customer_identifier (most reliable)
    va = None
    if customer_identifier:
        va = VirtualAccount.objects.select_related('organization').filter(
            squad_account_reference=customer_identifier,
        ).first()

    # Fallback: try by account number
    if not va and account_number:
        va = VirtualAccount.objects.select_related('organization').filter(
            account_number=account_number,
        ).first()

    if not va:
        raise ValueError(
            f'Virtual account not found: customer_identifier={customer_identifier}, '
            f'account_number={account_number}'
        )

    organization = va.organization
    rate = settings.BITCHECK_NAIRA_PER_BIT

    # Edge case: transfer too small to convert to at least 1 bit
    if amount_naira < rate:
        event.status = WebhookEvent.Status.PROCESSED
        event.processing_error = (
            f'Sub-rate transfer: N{amount_naira} < rate of N{rate}/bit. '
            f'No bits credited. Ref: {squad_reference}'
        )
        event.processed_at = timezone.now()
        event.save(update_fields=['status', 'processing_error', 'processed_at'])
        logger.warning(f'Sub-rate transfer N{amount_naira} for org {organization.name}')
        return

    # Calculate bits (integer division — partial bits are not credited)
    bits = amount_naira // rate

    with transaction.atomic():
        # Create top-up record
        topup = TopUp.objects.create(
            organization=organization,
            virtual_account=va,
            amount_naira=amount_naira,
            bits_credited=bits,
            rate_naira_per_bit=rate,
            status=TopUp.Status.CREDITED,
            squad_transaction_reference=squad_reference,
            webhook_event=event,
            credited_at=timezone.now(),
        )

        # Credit the org's wallet
        wallet = get_wallet_for_organization(organization)
        credit_wallet(
            wallet_id=wallet.id,
            amount=bits,
            entry_type='topup',
            reference_type='top_up',
            reference_id=str(topup.id),
            note=f'Bank transfer: N{amount_naira} -> {bits} bits',
        )

        # Mark event as processed
        event.status = WebhookEvent.Status.PROCESSED
        event.processed_at = timezone.now()
        event.save(update_fields=['status', 'processed_at'])

    logger.info(
        f'VA credit processed: org={organization.name}, '
        f'N{amount_naira} -> {bits} bits (topup={topup.id})'
    )


def _handle_subscription_charge(event, payload):
    """
    Handle a successful card charge from Squad (charge_successful webhook).

    Squad's webhook for tokenized payments includes:
      - Event: "charge_successful"
      - Body.transaction_ref: matches what we sent in initiate
      - Body.payment_information.token_id: card token for recurring charges
      - Body.is_recurring: true

    Flow:
      1. Find the 'incomplete' subscription by transaction_ref (squad_subscription_id)
      2. Activate the subscription
      3. Store the token_id for future recurring charges
      4. Credit Pro bits to the user's wallet

    Ref: docs/Squad_API_Docs/Initiate-payment.md — Card Tokenization
    """
    from apps.billing.models import Plan, Subscription
    from apps.bits.services import credit_wallet, get_wallet_for_user
    from datetime import timedelta

    print(f'[CHARGE] Processing charge_successful webhook')

    # Squad nests the data under 'Body' for charge_successful events
    body = payload.get('Body', payload.get('data', payload))
    transaction_ref = body.get('transaction_ref', '')
    email = body.get('email', '')

    # Extract the card token from payment_information
    payment_info = body.get('payment_information', {})
    token_id = payment_info.get('token_id', '')

    print(f'[CHARGE] transaction_ref={transaction_ref}')
    print(f'[CHARGE] email={email}')
    print(f'[CHARGE] token_id={token_id or "(none)"}')
    print(f'[CHARGE] Body keys: {list(body.keys()) if isinstance(body, dict) else "NOT A DICT"}')

    if not transaction_ref:
        print(f'[CHARGE] ❌ No transaction_ref found!')
        event.status = WebhookEvent.Status.IGNORED
        event.processing_error = 'No transaction_ref in charge_successful payload.'
        event.processed_at = timezone.now()
        event.save(update_fields=['status', 'processing_error', 'processed_at'])
        return

    # Find the subscription by the transaction_ref we set as squad_subscription_id
    print(f'[CHARGE] Looking up subscription with squad_subscription_id={transaction_ref}')
    subscription = Subscription.objects.select_related('user', 'plan').filter(
        squad_subscription_id=transaction_ref,
    ).first()

    if subscription:
        print(f'[CHARGE] ✅ Found by transaction_ref: sub={subscription.id}, status={subscription.status}, user={subscription.user.email}')
    else:
        print(f'[CHARGE] ⚠️ No subscription found by transaction_ref, trying email={email}')

    # Fallback: try to find by email if transaction_ref lookup fails
    if not subscription and email:
        subscription = Subscription.objects.select_related('user', 'plan').filter(
            user__email__iexact=email,
            status__in=['incomplete', 'active', 'past_due'],
        ).first()
        if subscription:
            print(f'[CHARGE] ✅ Found by email: sub={subscription.id}, status={subscription.status}')

    if not subscription:
        print(f'[CHARGE] ❌ NO SUBSCRIPTION FOUND for ref={transaction_ref}, email={email}')
        # Log all subscriptions for debugging
        all_subs = Subscription.objects.all().values_list('id', 'squad_subscription_id', 'status', 'user__email')[:10]
        print(f'[CHARGE] All subscriptions (first 10): {list(all_subs)}')
        event.status = WebhookEvent.Status.IGNORED
        event.processing_error = (
            f'No subscription found for transaction_ref={transaction_ref} '
            f'or email={email}.'
        )
        event.processed_at = timezone.now()
        event.save(update_fields=['status', 'processing_error', 'processed_at'])
        return

    if subscription.status == Subscription.Status.CANCELED:
        event.status = WebhookEvent.Status.IGNORED
        event.processing_error = (
            f'Subscription {subscription.id} is canceled; ignoring charge for '
            f'transaction_ref={transaction_ref}.'
        )
        event.processed_at = timezone.now()
        event.save(update_fields=['status', 'processing_error', 'processed_at'])
        return

    with transaction.atomic():
        if subscription.status == Subscription.Status.INCOMPLETE:
            # First payment — activate the subscription
            pro_plan = Plan.objects.get(code=Plan.Code.PRO)
            now = timezone.now()

            subscription.plan = pro_plan
            subscription.status = Subscription.Status.ACTIVE
            subscription.current_period_start = now
            subscription.current_period_end = now + timedelta(days=30)

            # Store the card token for future recurring charges
            if token_id:
                subscription.squad_card_token_id = token_id

            subscription.save()

            # Credit Pro grant
            wallet = get_wallet_for_user(subscription.user)
            credit_wallet(
                wallet_id=wallet.id,
                amount=pro_plan.monthly_grant_bits,
                entry_type='subscription_grant',
                reference_type='subscription',
                reference_id=str(subscription.id),
                note=f'Pro plan activated: {pro_plan.monthly_grant_bits} bits',
            )

            logger.info(
                f'Pro subscription activated for {subscription.user.email}, '
                f'token_id={token_id or "none"}'
            )

        elif subscription.status == Subscription.Status.PAST_DUE:
            # Renewal payment succeeded — reactivate
            subscription.status = Subscription.Status.ACTIVE
            if token_id:
                subscription.squad_card_token_id = token_id
            subscription.save(update_fields=[
                'status', 'squad_card_token_id', 'updated_at',
            ])
            logger.info(f'Subscription reactivated for {subscription.user.email}')

        elif subscription.status == Subscription.Status.ACTIVE:
            # Already active — this is a renewal. Update token if changed.
            if token_id and token_id != subscription.squad_card_token_id:
                subscription.squad_card_token_id = token_id
                subscription.save(update_fields=['squad_card_token_id', 'updated_at'])
            logger.info(f'Renewal charge recorded for {subscription.user.email}')

        # Mark event as processed
        event.status = WebhookEvent.Status.PROCESSED
        event.processed_at = timezone.now()
        event.save(update_fields=['status', 'processed_at'])
