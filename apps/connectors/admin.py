from django.contrib import admin

from .models import (
    ConnectorEvent,
    ConnectorInstall,
    ConnectorMessage,
    ConnectorType,
    ConnectorTypeInterest,
)


@admin.register(ConnectorType)
class ConnectorTypeAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'slug',
        'category',
        'status',
        'auth_type',
        'supports_b2c',
        'supports_b2b',
        'updated_at',
    )
    list_filter = ('status', 'category', 'auth_type')
    search_fields = ('slug', 'name')


@admin.register(ConnectorInstall)
class ConnectorInstallAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'type',
        'user',
        'organization',
        'external_account_label',
        'is_active',
        'last_event_at',
        'created_at',
    )
    list_filter = ('is_active', 'type')
    raw_id_fields = ('user', 'organization', 'type')


@admin.register(ConnectorEvent)
class ConnectorEventAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'install',
        'external_event_id',
        'event_type',
        'status',
        'created_at',
        'processed_at',
    )
    list_filter = ('status', 'event_type')
    raw_id_fields = ('install',)


@admin.register(ConnectorMessage)
class ConnectorMessageAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'install',
        'kind',
        'status',
        'verification',
        'created_at',
        'sent_at',
    )
    list_filter = ('status', 'kind', 'direction')
    raw_id_fields = ('install', 'event', 'verification')


@admin.register(ConnectorTypeInterest)
class ConnectorTypeInterestAdmin(admin.ModelAdmin):
    list_display = ('user', 'connector_type', 'created_at')
    list_filter = ('connector_type',)
