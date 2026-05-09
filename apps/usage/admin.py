"""
Usage admin — API call logs.
"""

from django.contrib import admin
from .models import ApiCall


@admin.register(ApiCall)
class ApiCallAdmin(admin.ModelAdmin):
    list_display = ('request_id', 'endpoint', 'organization', 'http_status', 'bits_charged', 'latency_ms', 'created_at')
    list_filter = ('http_status', 'modality', 'created_at')
    search_fields = ('request_id', 'idempotency_key', 'organization__name')
    readonly_fields = (
        'id', 'organization', 'api_key', 'endpoint', 'modality',
        'http_status', 'bits_charged', 'latency_ms', 'request_id',
        'idempotency_key', 'client_ip', 'user_agent', 'created_at',
    )
    ordering = ('-created_at',)

    def has_add_permission(self, request):
        return False  # API calls are created by the system

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
