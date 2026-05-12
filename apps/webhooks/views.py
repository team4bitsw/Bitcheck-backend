"""
Webhook views — HTTP endpoints for receiving webhooks.

Processing rule: the handler does ONLY two things:
  1. Verify signature
  2. Insert row into webhook_events

All business logic is deferred to Celery.

Ref: database design doc § 4.8
"""

import json
import logging
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .services import verify_squad_signature, ingest_webhook_event
from .tasks import process_webhook_event_task

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def squad_webhook_view(request):
    """
    Receive a webhook from Squad payment gateway.

    1. Read raw body
    2. Verify HMAC-SHA512 signature
    3. Insert into webhook_events inbox
    4. Dispatch Celery task for async processing
    5. Return 200 immediately (Squad expects this)

    The endpoint MUST return 200 quickly. Never do business
    logic here — that's the Celery worker's job.
    """
    try:
        body = request.body
        signature = request.headers.get('X-Squad-Encrypted-Body', '')

        # Verify signature
        if not verify_squad_signature(body, signature):
            logger.warning('Squad webhook signature verification failed.')
            return JsonResponse(
                {'detail': 'Invalid signature.'},
                status=401,
            )

        # Parse payload
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return JsonResponse(
                {'detail': 'Invalid JSON body.'},
                status=400,
            )

        # Extract event type and external ID
        # Card webhooks: {Event: "charge_successful", Body: {transaction_ref: ...}}
        # VA webhooks:   {transaction_reference: ..., channel: "virtual-account", ...}
        if 'Event' in payload or 'event' in payload:
            # Card charge webhook
            event_type = payload.get('Event', payload.get('event', 'unknown'))
            transaction_data = payload.get('Body', payload.get('data', {}))
            external_id = transaction_data.get('transaction_ref', None) if isinstance(transaction_data, dict) else None
        elif payload.get('channel') == 'virtual-account':
            # Virtual account transfer webhook
            event_type = 'transfer.successful'
            external_id = payload.get('transaction_reference', None)
        else:
            event_type = 'unknown'
            external_id = None

        # Capture relevant headers for replay
        headers = {
            'x-squad-encrypted-body': signature,
            'x-squad-signature': request.headers.get('X-Squad-Signature', ''),
            'content-type': request.content_type or '',
            'user-agent': request.headers.get('User-Agent', ''),
        }

        # Ingest into inbox
        event = ingest_webhook_event(
            source='squad',
            event_type=event_type,
            payload=payload,
            headers=headers,
            external_id=external_id,
            signature=signature,
        )

        # Process the event synchronously (inline).
        # On Cloud Run we only run gunicorn — no Celery worker. So we
        # process right here to guarantee the payment/top-up is handled.
        # Squad's timeout is generous enough for our DB operations.
        try:
            from .services import process_webhook_event
            process_webhook_event(str(event.id))
            logger.info(f'Webhook event {event.id} processed inline.')
        except Exception as proc_err:
            logger.error(
                f'Inline webhook processing failed for {event.id}: {proc_err}',
                exc_info=True,
            )
            # Event is saved in the inbox with status='failed'.
            # retry_failed_webhooks periodic task will pick it up later.

        return JsonResponse({'status': 'received', 'event_id': str(event.id)})

    except Exception as e:
        logger.error(f'Squad webhook handler error: {e}', exc_info=True)
        # Still return 200 so Squad doesn't retry endlessly
        return JsonResponse({'status': 'error'}, status=200)
