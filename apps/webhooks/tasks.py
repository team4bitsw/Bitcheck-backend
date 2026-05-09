"""
Webhook Celery tasks — process events from the inbox.

The task picks up a WebhookEvent by ID and delegates to the
appropriate handler in services.py.

Ref: database design doc § 4.8 — processing rule.
"""

import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def process_webhook_event_task(self, event_id):
    """
    Process a single webhook event from the inbox.

    This task is dispatched immediately after a webhook is ingested.
    It can also be called manually for retry/replay.
    """
    from .services import process_webhook_event

    try:
        process_webhook_event(str(event_id))
    except Exception as e:
        logger.error(
            f'Webhook event {event_id} processing failed (attempt '
            f'{self.request.retries + 1}/{self.max_retries + 1}): {e}'
        )
        raise self.retry(exc=e)


@shared_task
def retry_failed_webhooks():
    """
    Periodic task: retry all failed webhook events.

    Picks up events with status='failed' that were received
    in the last 24 hours and re-dispatches them.
    """
    from django.utils import timezone
    from datetime import timedelta
    from .models import WebhookEvent

    cutoff = timezone.now() - timedelta(hours=24)

    failed_events = WebhookEvent.objects.filter(
        status=WebhookEvent.Status.FAILED,
        received_at__gte=cutoff,
    )

    count = failed_events.count()
    if count == 0:
        logger.info('No failed webhooks to retry.')
        return {'retried': 0}

    for event in failed_events:
        # Reset status so the processor picks it up
        event.status = WebhookEvent.Status.RECEIVED
        event.processing_error = None
        event.processed_at = None
        event.save(update_fields=['status', 'processing_error', 'processed_at'])

        process_webhook_event_task.delay(str(event.id))

    logger.info(f'Retried {count} failed webhook events.')
    return {'retried': count}
