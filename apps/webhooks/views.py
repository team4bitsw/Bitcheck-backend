"""
Webhook views — HTTP endpoints for receiving webhooks.

Processing rule: the handler does ONLY two things:
  1. Verify signature
  2. Insert row into webhook_events

Business logic is processed inline (synchronous) so it works on
Cloud Run without a Celery worker.

Ref: database design doc § 4.8
"""

import json
import logging
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .services import verify_squad_signature, ingest_webhook_event

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def squad_webhook_view(request):
    """
    Receive a webhook from Squad payment gateway.

    1. Read raw body
    2. Verify HMAC-SHA512 signature
    3. Insert into webhook_events inbox
    4. Process the event inline (sync)
    5. Return 200 immediately (Squad expects this)
    """
    # === STEP 0: Log that we received something ===
    print(f'\n{"="*60}')
    print(f'[WEBHOOK] Squad webhook received!')
    print(f'[WEBHOOK] Method: {request.method}')
    print(f'[WEBHOOK] Path: {request.path}')
    print(f'[WEBHOOK] Content-Type: {request.content_type}')
    print(f'[WEBHOOK] Headers: X-Squad-Encrypted-Body present = '
          f'{bool(request.headers.get("X-Squad-Encrypted-Body", ""))}')

    try:
        body = request.body
        signature = request.headers.get('X-Squad-Encrypted-Body', '')

        # === STEP 1: Log raw payload ===
        print(f'[WEBHOOK] Raw body length: {len(body)} bytes')
        try:
            body_preview = json.loads(body)
            print(f'[WEBHOOK] Parsed payload keys: {list(body_preview.keys())}')
            # Log the full payload for debugging (be careful in prod with PII)
            print(f'[WEBHOOK] Full payload: {json.dumps(body_preview, indent=2)[:2000]}')
        except Exception:
            print(f'[WEBHOOK] Raw body (first 500 chars): {body[:500]}')

        # === STEP 2: Verify signature ===
        print(f'[WEBHOOK] Signature present: {bool(signature)}')
        if not verify_squad_signature(body, signature):
            print(f'[WEBHOOK] ❌ SIGNATURE VERIFICATION FAILED')
            print(f'[WEBHOOK] Signature received: {signature[:20]}...' if signature else '[WEBHOOK] No signature')
            logger.warning('Squad webhook signature verification failed.')
            return JsonResponse(
                {'detail': 'Invalid signature.'},
                status=401,
            )
        print(f'[WEBHOOK] ✅ Signature verified')

        # Parse payload
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            print(f'[WEBHOOK] ❌ Invalid JSON body')
            return JsonResponse(
                {'detail': 'Invalid JSON body.'},
                status=400,
            )

        # === STEP 3: Detect event type ===
        # Card webhooks: {Event: "charge_successful", Body: {transaction_ref: ...}}
        # VA webhooks:   {transaction_reference: ..., channel: "virtual-account", ...}
        # Some VA webhooks may not have 'channel' but will have 'virtual_account_number'
        if 'Event' in payload or 'event' in payload:
            # Card charge webhook
            event_type = payload.get('Event', payload.get('event', 'unknown'))
            transaction_data = payload.get('Body', payload.get('data', {}))
            external_id = transaction_data.get('transaction_ref', None) if isinstance(transaction_data, dict) else None
            print(f'[WEBHOOK] Detected CARD event: type={event_type}, ref={external_id}')
        elif (payload.get('channel') == 'virtual-account'
              or payload.get('virtual_account_number')
              or (payload.get('transaction_reference') and payload.get('principal_amount'))):
            # Virtual account transfer webhook — detect by channel OR by VA-specific fields
            event_type = 'transfer.successful'
            external_id = payload.get('transaction_reference', None)
            print(f'[WEBHOOK] Detected VA event: type={event_type}, ref={external_id}')
            print(f'[WEBHOOK] VA fields: channel={payload.get("channel")}, '
                  f'va_num={payload.get("virtual_account_number")}, '
                  f'amount={payload.get("principal_amount")}, '
                  f'customer={payload.get("customer_identifier")}')
        else:
            event_type = 'unknown'
            external_id = None
            print(f'[WEBHOOK] ⚠️ UNKNOWN event type! Payload keys: {list(payload.keys())}')

        # Capture relevant headers for replay
        headers = {
            'x-squad-encrypted-body': signature,
            'x-squad-signature': request.headers.get('X-Squad-Signature', ''),
            'content-type': request.content_type or '',
            'user-agent': request.headers.get('User-Agent', ''),
        }

        # === STEP 4: Ingest into inbox ===
        event = ingest_webhook_event(
            source='squad',
            event_type=event_type,
            payload=payload,
            headers=headers,
            external_id=external_id,
            signature=signature,
        )
        print(f'[WEBHOOK] ✅ Event ingested: id={event.id}, type={event_type}')

        # === STEP 5: Process inline ===
        print(f'[WEBHOOK] Processing event inline...')
        try:
            from .services import process_webhook_event
            process_webhook_event(str(event.id))
            print(f'[WEBHOOK] ✅ Event {event.id} processed successfully!')
            logger.info(f'Webhook event {event.id} processed inline.')
        except Exception as proc_err:
            print(f'[WEBHOOK] ❌ PROCESSING FAILED: {proc_err}')
            import traceback
            traceback.print_exc()
            logger.error(
                f'Inline webhook processing failed for {event.id}: {proc_err}',
                exc_info=True,
            )

        print(f'[WEBHOOK] Returning 200 to Squad')
        print(f'{"="*60}\n')
        return JsonResponse({'status': 'received', 'event_id': str(event.id)})

    except Exception as e:
        print(f'[WEBHOOK] ❌ UNHANDLED ERROR: {e}')
        import traceback
        traceback.print_exc()
        logger.error(f'Squad webhook handler error: {e}', exc_info=True)
        # Still return 200 so Squad doesn't retry endlessly
        return JsonResponse({'status': 'error'}, status=200)
