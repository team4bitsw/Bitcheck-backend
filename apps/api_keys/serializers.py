"""
API Keys serializers.
"""

from rest_framework import serializers
from .models import ApiKey


class ApiKeySerializer(serializers.ModelSerializer):
    """Read-only representation of an API key (no secret shown)."""

    is_active = serializers.BooleanField(read_only=True)

    class Meta:
        model = ApiKey
        fields = [
            'id', 'name', 'environment', 'prefix',
            'is_active', 'last_used_at', 'revoked_at', 'created_at',
        ]
        read_only_fields = fields


class ApiKeyCreateSerializer(serializers.Serializer):
    """Create a new API key — returns the raw secret once."""

    name = serializers.CharField(max_length=255)
    environment = serializers.ChoiceField(
        choices=ApiKey.Environment.choices,
        default=ApiKey.Environment.TEST,
    )


class ApiKeyCreatedSerializer(serializers.Serializer):
    """Response after creating a key — includes the raw secret."""

    key = ApiKeySerializer()
    raw_secret = serializers.CharField()
