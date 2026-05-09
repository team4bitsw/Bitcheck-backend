"""
Verification serializers.
"""

from rest_framework import serializers
from .models import Verification, UploadedFile


class UploadedFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UploadedFile
        fields = ['id', 'mime_type', 'size_bytes', 'original_filename', 'created_at']
        read_only_fields = fields


class VerificationSerializer(serializers.ModelSerializer):
    """Full verification result for the detail view."""

    uploaded_file = UploadedFileSerializer(read_only=True)

    class Meta:
        model = Verification
        fields = [
            'id', 'modality', 'status',
            'trust_score', 'verdict', 'result_summary',
            'bits_charged', 'error_message',
            'uploaded_file', 'text_input',
            'created_at', 'started_at', 'completed_at',
        ]
        read_only_fields = fields


class VerificationListSerializer(serializers.ModelSerializer):
    """Compact list view (no result_summary to save bandwidth)."""

    class Meta:
        model = Verification
        fields = [
            'id', 'modality', 'status',
            'trust_score', 'verdict', 'bits_charged',
            'created_at', 'completed_at',
        ]
        read_only_fields = fields


class VerificationSubmitSerializer(serializers.Serializer):
    """Submit a new verification (B2C)."""

    modality = serializers.ChoiceField(choices=Verification.Modality.choices)
    text_input = serializers.CharField(required=False, allow_blank=True)
    uploaded_file_id = serializers.UUIDField(required=False)

    def validate(self, attrs):
        modality = attrs.get('modality')
        text_input = attrs.get('text_input')
        uploaded_file_id = attrs.get('uploaded_file_id')

        if modality == 'text':
            if not text_input:
                raise serializers.ValidationError(
                    {'text_input': 'Text input is required for text modality.'}
                )
        else:
            if not uploaded_file_id:
                raise serializers.ValidationError(
                    {'uploaded_file_id': f'An uploaded file is required for {modality} modality.'}
                )

        return attrs
