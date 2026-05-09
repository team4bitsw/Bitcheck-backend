"""
API Keys admin.
"""

from django.contrib import admin
from .models import ApiKey


@admin.register(ApiKey)
class ApiKeyAdmin(admin.ModelAdmin):
    list_display = ('name', 'prefix', 'organization', 'environment', 'is_active', 'last_used_at', 'created_at')
    list_filter = ('environment', 'revoked_at')
    search_fields = ('name', 'prefix', 'organization__name')
    readonly_fields = ('id', 'prefix', 'hashed_secret', 'created_at', 'last_used_at')
    ordering = ('-created_at',)

    def is_active(self, obj):
        return obj.is_active
    is_active.boolean = True
