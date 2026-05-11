from rest_framework import serializers

from .models import ConnectorEvent, ConnectorInstall, ConnectorType


class ConnectorTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConnectorType
        fields = (
            'id',
            'slug',
            'name',
            'description',
            'icon_url',
            'category',
            'status',
            'auth_type',
            'supports_b2c',
            'supports_b2b',
            'supports_auto_verify',
            'settings_schema',
            'created_at',
            'updated_at',
        )
        read_only_fields = fields


class ConnectorInstallSerializer(serializers.ModelSerializer):
    type = ConnectorTypeSerializer(read_only=True)

    class Meta:
        model = ConnectorInstall
        fields = (
            'id',
            'type',
            'organization',
            'user',
            'external_account_id',
            'external_account_label',
            'settings',
            'is_active',
            'last_event_at',
            'last_error_at',
            'last_error_message',
            'created_at',
            'updated_at',
        )
        read_only_fields = fields


class ConnectorInstallWriteSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConnectorInstall
        fields = ('settings',)


class ConnectorEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConnectorEvent
        fields = (
            'id',
            'external_event_id',
            'event_type',
            'status',
            'created_at',
            'processed_at',
        )
        read_only_fields = fields


class ConnectorInstallBeginResponseSerializer(serializers.Serializer):
    webhook_url = serializers.URLField(required=False, allow_null=True)
    redirect_url = serializers.URLField(required=False, allow_null=True)
    state = serializers.CharField(required=False, allow_blank=True)
    requires_input = serializers.ListField(required=False, child=serializers.DictField())
    deep_link = serializers.URLField(required=False, allow_null=True)
    telegram_deeplink = serializers.CharField(required=False, allow_blank=True)
    poll_code = serializers.CharField(required=False, allow_blank=True)
