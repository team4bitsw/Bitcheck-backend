"""
HTTP request/response logging — JSON lines, redacted bodies, timing.

Env:
    APP_LOG_HTTP_BODIES — 1/true: log truncated request (+ optional response) bodies
    APP_LOG_RESPONSE_BODY — 1/true: always log response preview (when bodies enabled)
    APP_LOG_MAX_BODY — max characters per body preview (default 4096)

When APP_LOG_HTTP_BODIES is unset, it defaults to on if DEBUG env is true, else off.
"""
from __future__ import annotations

import json
import os
import time
import uuid

from django.http import StreamingHttpResponse

from apps.core.logger import logger, safe_meta

_LOG = logger.child('http')

_MAX = int(os.environ.get('APP_LOG_MAX_BODY', '4096'))


def _env_truthy(key: str, default: str | None = None) -> bool:
    raw = os.environ.get(key, default)
    if raw is None or raw == '':
        return False
    return raw.strip().lower() in ('1', 'true', 'yes', 'on')


_debug_env = os.environ.get('DEBUG', 'True').strip().lower() in ('1', 'true', 'yes', 'on')
_LOG_BODIES = _env_truthy('APP_LOG_HTTP_BODIES', '1' if _debug_env else '0')
_LOG_RESPONSE_BODY = _env_truthy('APP_LOG_RESPONSE_BODY')


def _body_preview(raw: bytes) -> str | dict[str, object]:
    if not raw:
        return ''
    raw = raw[: _MAX * 2] if len(raw) > _MAX * 2 else raw
    try:
        text = raw.decode('utf-8', errors='replace')
    except Exception:
        return '[binary/non-utf8]'
    if len(text) > _MAX:
        text = text[:_MAX] + '...[truncated]'
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return safe_meta(parsed)
        return {'_type': 'json_non_object', 'preview': text[:512]}
    except json.JSONDecodeError:
        return text


class RequestLoggingMiddleware:
    """Log each request as one structured line after the response is ready."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = str(uuid.uuid4())
        request.bitcheck_request_id = request_id
        start = time.perf_counter()

        req_extra: dict[str, object] = {}
        if _LOG_BODIES and request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            try:
                req_extra['request_body'] = _body_preview(request.body)
            except Exception as e:
                req_extra['request_body_error'] = str(e)

        response = self.get_response(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)

        meta: dict[str, object] = {
            'request_id': request_id,
            'method': request.method,
            'path': request.path,
            'query': (request.META.get('QUERY_STRING', '') or '')[:2048],
            'status': response.status_code,
            'duration_ms': duration_ms,
        }
        user = getattr(request, 'user', None)
        if user is not None and getattr(user, 'is_authenticated', False):
            meta['user_id'] = str(user.pk)

        meta.update(req_extra)

        log_response_body = (
            _LOG_BODIES
            and (_LOG_RESPONSE_BODY or response.status_code >= 400)
            and not isinstance(response, StreamingHttpResponse)
            and hasattr(response, 'content')
        )
        if log_response_body:
            try:
                meta['response_body'] = _body_preview(response.content)
            except Exception as e:
                meta['response_body_error'] = str(e)

        msg = 'http_request_complete'
        if response.status_code >= 500:
            _LOG.error(msg, **meta)
        elif response.status_code >= 400:
            _LOG.warning(msg, **meta)
        else:
            _LOG.info(msg, **meta)

        return response
