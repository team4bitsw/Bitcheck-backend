"""
Usage services — API call logging and idempotency.

Provides utilities for:
  - Logging API calls with timing, status, and bits charged
  - Checking and enforcing idempotency keys
  - Extracting client IP from requests

Ref: database design doc § 4.7, § 6 rule 7.
"""

import time
import uuid
import logging
from django.db import IntegrityError
from .models import ApiCall

logger = logging.getLogger(__name__)


def generate_request_id():
    """Generate a unique request ID for tracking."""
    return f'req_{uuid.uuid4().hex[:24]}'


def get_client_ip(request):
    """Extract the real client IP, respecting X-Forwarded-For."""
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def check_idempotency(api_key, idempotency_key):
    """
    Check if a request with this idempotency key has already been processed.

    Returns the existing ApiCall if found, None otherwise.

    Ref: database design doc § 6 rule 7.
    """
    if not idempotency_key:
        return None

    try:
        return ApiCall.objects.get(
            api_key=api_key,
            idempotency_key=idempotency_key,
        )
    except ApiCall.DoesNotExist:
        return None


def log_api_call(
    organization,
    api_key,
    endpoint,
    http_status,
    latency_ms,
    request_id,
    modality=None,
    bits_charged=0,
    idempotency_key=None,
    client_ip=None,
    user_agent=None,
):
    """
    Record an API call in the usage log.

    This is called at the end of every B2B API request to create
    an audit trail and usage record.

    Returns the created ApiCall, or None if it was a duplicate
    idempotency key (which shouldn't happen if check_idempotency
    was called first, but we handle it gracefully).
    """
    try:
        return ApiCall.objects.create(
            organization=organization,
            api_key=api_key,
            endpoint=endpoint,
            modality=modality,
            http_status=http_status,
            bits_charged=bits_charged,
            latency_ms=latency_ms,
            request_id=request_id,
            idempotency_key=idempotency_key,
            client_ip=client_ip,
            user_agent=user_agent,
        )
    except IntegrityError as e:
        logger.warning(
            f'Duplicate API call log: request_id={request_id}, '
            f'idempotency_key={idempotency_key}, error={e}'
        )
        return None


class ApiCallTimer:
    """
    Context manager for timing API calls.

    Usage:
        with ApiCallTimer() as timer:
            # ... process request ...
        latency_ms = timer.elapsed_ms
    """

    def __init__(self):
        self.start_time = None
        self.end_time = None

    def __enter__(self):
        self.start_time = time.monotonic()
        return self

    def __exit__(self, *args):
        self.end_time = time.monotonic()

    @property
    def elapsed_ms(self):
        if self.start_time is None or self.end_time is None:
            return 0
        return int((self.end_time - self.start_time) * 1000)
