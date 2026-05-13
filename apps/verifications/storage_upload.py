"""Upload bytes to S3-compatible storage and create UploadedFile rows (connector / server-side)."""

from __future__ import annotations

import hashlib
import logging
import uuid

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings

from apps.verifications.models import UploadedFile

logger = logging.getLogger(__name__)


def upload_bytes_for_connector_owner(
    *,
    user,
    organization,
    data: bytes,
    original_filename: str,
    mime_type: str,
) -> UploadedFile:
    """
    Store ``data`` in the configured bucket and return an ``UploadedFile`` row.

    Raises RuntimeError if AWS credentials are missing or the upload fails.
    """
    if not settings.AWS_ACCESS_KEY_ID or not settings.AWS_SECRET_ACCESS_KEY:
        raise RuntimeError('AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY are not configured')

    bucket = settings.AWS_STORAGE_BUCKET_NAME
    key = f'connectors/{uuid.uuid4()}/{original_filename[:200]}'
    sha256 = hashlib.sha256(data).digest().hex()

    client_kwargs: dict = {
        'aws_access_key_id': settings.AWS_ACCESS_KEY_ID,
        'aws_secret_access_key': settings.AWS_SECRET_ACCESS_KEY,
        'region_name': settings.AWS_S3_REGION_NAME,
    }
    endpoint = getattr(settings, 'AWS_S3_ENDPOINT_URL', '') or ''
    if endpoint:
        client_kwargs['endpoint_url'] = endpoint

    client = boto3.client(
        's3',
        **client_kwargs,
        config=Config(
            signature_version='s3v4',
            s3={'addressing_style': 'path'},
        ),
    )
    try:
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=data,
            ContentType=mime_type,
        )
    except (BotoCoreError, ClientError) as e:
        logger.exception('S3 put_object failed')
        raise RuntimeError(f'Object storage upload failed: {e}') from e

    if user and not organization:
        return UploadedFile.objects.create(
            owner_user=user,
            owner_organization=None,
            bucket=bucket,
            storage_key=key,
            mime_type=mime_type,
            size_bytes=len(data),
            sha256=sha256,
            original_filename=original_filename,
        )
    if organization and not user:
        return UploadedFile.objects.create(
            owner_user=None,
            owner_organization=organization,
            bucket=bucket,
            storage_key=key,
            mime_type=mime_type,
            size_bytes=len(data),
            sha256=sha256,
            original_filename=original_filename,
        )
    raise ValueError('Exactly one of user or organization must be set')
