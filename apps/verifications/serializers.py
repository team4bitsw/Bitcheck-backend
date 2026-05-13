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


def _generate_r2_presigned_url(uploaded_file, expiry: int = 3600) -> str | None:
    """
    Generate a short-lived presigned URL for an R2-stored file.
    Returns None if credentials are not configured or the upload fails.
    """
    from django.conf import settings
    import boto3
    from botocore.config import Config

    key_id = getattr(settings, 'AWS_ACCESS_KEY_ID', '')
    secret = getattr(settings, 'AWS_SECRET_ACCESS_KEY', '')
    endpoint = getattr(settings, 'AWS_S3_ENDPOINT_URL', '')
    region = getattr(settings, 'AWS_S3_REGION_NAME', 'auto')

    if not key_id or not secret or not endpoint:
        return None

    try:
        client = boto3.client(
            's3',
            aws_access_key_id=key_id,
            aws_secret_access_key=secret,
            endpoint_url=endpoint,
            region_name=region,
            config=Config(signature_version='s3v4', s3={'addressing_style': 'path'}),
        )
        return client.generate_presigned_url(
            'get_object',
            Params={'Bucket': uploaded_file.bucket, 'Key': uploaded_file.storage_key},
            ExpiresIn=expiry,
        )
    except Exception:
        return None


class VerificationSerializer(serializers.ModelSerializer):
    """Full verification result for the detail view."""

    uploaded_file = UploadedFileSerializer(read_only=True)
    original_filename = serializers.SerializerMethodField()
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = Verification
        fields = [
            'id', 'modality', 'status',
            'trust_score', 'verdict', 'result_summary',
            'bits_charged', 'error_message',
            'uploaded_file', 'text_input',
            'original_filename', 'file_url',
            'created_at', 'started_at', 'completed_at',
        ]
        read_only_fields = fields

    def get_original_filename(self, obj):
        if obj.result_summary and isinstance(obj.result_summary, dict):
            return obj.result_summary.get('original_filename', '')
        return ''

    def get_file_url(self, obj):
        if not obj.uploaded_file:
            return None
        return _generate_r2_presigned_url(obj.uploaded_file)


class VerificationListSerializer(serializers.ModelSerializer):
    """Compact list view (no result_summary to save bandwidth)."""

    original_filename = serializers.SerializerMethodField()

    class Meta:
        model = Verification
        fields = [
            'id', 'modality', 'status',
            'trust_score', 'verdict', 'bits_charged',
            'original_filename',
            'created_at', 'completed_at',
        ]
        read_only_fields = fields

    def get_original_filename(self, obj):
        if obj.result_summary and isinstance(obj.result_summary, dict):
            return obj.result_summary.get('original_filename', '')
        return ''

