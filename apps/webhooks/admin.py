"""
Webhooks admin — WebhookEvent inbox.
"""

from django.contrib import admin
from .models import WebhookEvent


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ('id', 'source', 'event_type', 'status', 'received_at', 'processed_at')
    list_filter = ('source', 'status', 'event_type')
    search_fields = ('external_id', 'event_type')
    readonly_fields = (
        'id', 'source', 'event_type', 'external_id', 'signature',
        'payload', 'headers', 'received_at', 'processed_at', 'processing_error',
    )
    ordering = ('-received_at',)
