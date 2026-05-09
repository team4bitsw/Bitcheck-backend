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
        return False

    secret = settings.SQUAD_WEBHOOK_SECRET
    if not secret:
        logger.warning('SQUAD_WEBHOOK_SECRET is not configured.')
        return False

    expected = hmac.new(
        secret.encode('utf-8'),
        payload_body,
        hashlib.sha512,
    ).hexdigest()

    return hmac.compare_digest(expected, signature_header)


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
    try:
        event = WebhookEvent.objects.get(pk=event_id)
    except WebhookEvent.DoesNotExist:
        logger.error(f'Webhook event {event_id} not found.')
        return

    # Guard: skip if already processed
    if event.status != WebhookEvent.Status.RECEIVED:
        logger.info(f'Event {event_id} already in state {event.status}, skipping.')
        return

    try:
        if event.source == 'squad':
            _process_squad_event(event)
        else:
            event.status = WebhookEvent.Status.IGNORED
            event.processing_error = f'Unknown source: {event.source}'
            event.processed_at = timezone.now()
            event.save(update_fields=['status', 'processing_error', 'processed_at'])

    except Exception as e:
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
      - charge.successful:    Subscription payment succeeded
      - transfer.successful:  Virtual account credit (B2B top-up)
    """
    event_type = event.event_type
    payload = event.payload

    if event_type == 'transfer.successful':
        _handle_virtual_account_credit(event, payload)
    elif event_type == 'charge.successful':
        _handle_subscription_charge(event, payload)
    else:
        # Unknown event type — mark as ignored
        event.status = WebhookEvent.Status.IGNORED
        event.processing_error = f'Unhandled Squad event type: {event_type}'
        event.processed_at = timezone.now()
        event.save(update_fields=['status', 'processing_error', 'processed_at'])
        logger.info(f'Ignored Squad event type: {event_type}')


def _handle_virtual_account_credit(event, payload):
    """
    Handle a B2B virtual account credit (bank transfer received).

    Flow:
      1. Look up the virtual account by Squad reference
      2. Calculate bits from naira amount
      3. Create a TopUp record
      4. Credit the org's wallet
      5. Mark the event as processed

    Ref: database design doc § 4.4, § 5.3, § 6 rules 1-4.
    """
    # Extract fields from Squad payload
    # Squad sends amounts in kobo — we convert to naira at the boundary (§ 6 rule 3)
    transaction_data = payload.get('data', payload)
    amount_kobo = transaction_data.get('amount', 0)
    amount_naira = amount_kobo // 100  # kobo → naira at boundary

    squad_reference = transaction_data.get('transaction_reference', '')
    account_number = transaction_data.get('virtual_account_number', '')
    merchant_ref = transaction_data.get('merchant_ref', '')

    if not squad_reference:
        raise ValueError('Missing transaction_reference in Squad payload')

    # Idempotency check — squad_transaction_reference is UNIQUE
    if TopUp.objects.filter(squad_transaction_reference=squad_reference).exists():
        event.status = WebhookEvent.Status.PROCESSED
        event.processing_error = 'Duplicate: already processed this transaction.'
        event.processed_at = timezone.now()
        event.save(update_fields=['status', 'processing_error', 'processed_at'])
        logger.info(f'Duplicate Squad transaction {squad_reference}, skipping.')
        return

    # Look up virtual account
    try:
        va = VirtualAccount.objects.select_related('organization').get(
            account_number=account_number,
        )
    except VirtualAccount.DoesNotExist:
        # Try by squad reference
        try:
            va = VirtualAccount.objects.select_related('organization').get(
                squad_account_reference=merchant_ref,
            )
        except VirtualAccount.DoesNotExist:
            raise ValueError(
                f'Virtual account not found for account_number={account_number} '
                f'or merchant_ref={merchant_ref}'
            )

    organization = va.organization
    rate = settings.BITCHECK_NAIRA_PER_BIT

    # Edge case: sub-rate transfer — too small to convert to bits
    if amount_naira < rate:
        event.status = WebhookEvent.Status.PROCESSED
        event.processing_error = (
            f'Sub-rate transfer: ₦{amount_naira} < rate of ₦{rate}/bit. '
            f'No bits credited. Ref: {squad_reference}'
        )
        event.processed_at = timezone.now()
        event.save(update_fields=['status', 'processing_error', 'processed_at'])
        logger.warning(f'Sub-rate transfer ₦{amount_naira} for org {organization.name}')
        return

    # Calculate bits
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
            note=f'Bank transfer: ₦{amount_naira} → {bits} bits',
        )

        # Mark event as processed
        event.status = WebhookEvent.Status.PROCESSED
        event.processed_at = timezone.now()
        event.save(update_fields=['status', 'processed_at'])

    logger.info(
        f'Virtual account credit processed: org={organization.name}, '
        f'₦{amount_naira} → {bits} bits (topup={topup.id})'
    )


def _handle_subscription_charge(event, payload):
    """
    Handle a successful subscription charge from Squad.

    For the hackathon, this is a simplified flow:
      1. Find the user by Squad customer ID
      2. If they're on free, upgrade to Pro
      3. If they're on Pro, this is a renewal — handled by the rollover task

    Full implementation would handle mandate creation, cancellation, etc.
    """
    from apps.billing.models import Plan, Subscription
    from apps.bits.services import credit_wallet, get_wallet_for_user
    from datetime import timedelta

    transaction_data = payload.get('data', payload)
    squad_customer_id = transaction_data.get('customer_id', '')
    squad_subscription_id = transaction_data.get('subscription_id', '')

    if not squad_customer_id:
        event.status = WebhookEvent.Status.IGNORED
        event.processing_error = 'No customer_id in payload.'
        event.processed_at = timezone.now()
        event.save(update_fields=['status', 'processing_error', 'processed_at'])
        return

    # Find existing subscription by Squad customer ID
    subscription = Subscription.objects.select_related('user', 'plan').filter(
        squad_customer_id=squad_customer_id,
        status__in=['active', 'past_due', 'incomplete'],
    ).first()

    if not subscription:
        event.status = WebhookEvent.Status.IGNORED
        event.processing_error = f'No subscription found for customer {squad_customer_id}.'
        event.processed_at = timezone.now()
        event.save(update_fields=['status', 'processing_error', 'processed_at'])
        return

    with transaction.atomic():
        # If incomplete → activate
        if subscription.status == Subscription.Status.INCOMPLETE:
            pro_plan = Plan.objects.get(code='pro')
            now = timezone.now()

            subscription.plan = pro_plan
            subscription.status = Subscription.Status.ACTIVE
            subscription.squad_subscription_id = squad_subscription_id or subscription.squad_subscription_id
            subscription.current_period_start = now
            subscription.current_period_end = now + timedelta(days=30)
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

        elif subscription.status == Subscription.Status.PAST_DUE:
            subscription.status = Subscription.Status.ACTIVE
            subscription.save(update_fields=['status', 'updated_at'])

        # Mark event as processed
        event.status = WebhookEvent.Status.PROCESSED
        event.processed_at = timezone.now()
        event.save(update_fields=['status', 'processed_at'])

    logger.info(
        f'Subscription charge processed for user {subscription.user.email}'
    )
