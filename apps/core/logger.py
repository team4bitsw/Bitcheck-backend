"""
Application logger — import the singleton and use namespaces.

    from apps.core.logger import logger
    log = logger.child("billing")
    log.info("payment_ok", ref="abc", amount=100)

Structured JSON lines on stdout (works in dev terminal and Cloud Run / Docker).
Secrets are redacted in `meta`; never pass raw passwords or tokens as message text.

Env:
    APP_LOG_LEVEL — DEBUG, INFO, WARNING, ERROR (default follows Django settings.DEBUG when configured, else env DEBUG)
"""
from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Mapping

_LOG_RECORD_EXTRA_ATTR = 'bitcheck_meta'

_SENSITIVE_KEY_FRAGMENTS = frozenset(
    x.lower()
    for x in (
        'password',
        'pass',
        'secret',
        'token',
        'authorization',
        'cookie',
        'sessionid',
        'csrf',
        'csrftoken',
        'id_token',
        'access_token',
        'refresh_token',
        'api_key',
        'bvn',
        'credit_card',
    )
)


def _is_sensitive_key(key: str) -> bool:
    k = key.lower()
    return k in _SENSITIVE_KEY_FRAGMENTS or any(
        frag in k for frag in ('secret', 'password', 'token', 'authorization')
    )


def safe_meta(meta: Mapping[str, Any] | None, depth: int = 0, max_depth: int = 4) -> dict[str, Any]:
    """Shallow-safe copy of meta dict for logging (redact known secret keys, cap recursion)."""
    if not meta:
        return {}
    out: dict[str, Any] = {}
    for key, value in meta.items():
        if _is_sensitive_key(str(key)):
            out[str(key)] = '[REDACTED]'
            continue
        if depth >= max_depth:
            out[str(key)] = '[TRUNCATED_DEPTH]'
            continue
        if isinstance(value, Mapping) and not isinstance(value, (str, bytes)):
            out[str(key)] = safe_meta(value, depth + 1, max_depth)
        elif isinstance(value, (list, tuple)):
            out[str(key)] = [
                safe_meta(x, depth + 1, max_depth)
                if isinstance(x, Mapping) and not isinstance(x, (str, bytes))
                else x
                for x in value[:50]
            ]
            if len(value) > 50:
                out[str(key)].append('...[truncated]')
        else:
            out[str(key)] = value
    return out


class JsonLineFormatter(logging.Formatter):
    """One JSON object per line — easy to grep and ship to log aggregators."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            'ts': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'level': record.levelname,
            'logger': record.name,
            'msg': record.getMessage(),
        }
        extra = getattr(record, _LOG_RECORD_EXTRA_ATTR, None)
        if isinstance(extra, dict) and extra:
            payload['meta'] = extra
        if record.exc_info:
            payload['exc'] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def _read_min_level() -> int:
    raw = (os.environ.get('APP_LOG_LEVEL') or '').strip().upper()
    mapping = {
        'DEBUG': logging.DEBUG,
        'INFO': logging.INFO,
        'WARNING': logging.WARNING,
        'ERROR': logging.ERROR,
        'WARN': logging.WARNING,
    }
    if raw in mapping:
        return mapping[raw]
    try:
        from django.conf import settings

        if settings.configured:
            return logging.DEBUG if settings.DEBUG else logging.INFO
    except Exception:
        pass
    dbg = os.environ.get('DEBUG', 'True').strip().lower() in ('1', 'true', 'yes', 'on')
    return logging.DEBUG if dbg else logging.INFO


def _bitcheck_json_handler_exists(bitcheck: logging.Logger) -> bool:
    for h in bitcheck.handlers:
        fmt = getattr(h, 'formatter', None)
        if isinstance(h, logging.StreamHandler) and isinstance(fmt, JsonLineFormatter):
            return True
    return False


def configure_root_bitcheck_logging() -> None:
    """Attach JSON stdout handler to the `bitcheck` logger tree. Safe across autoreload."""
    bitcheck = logging.getLogger('bitcheck')
    bitcheck.setLevel(_read_min_level())
    if _bitcheck_json_handler_exists(bitcheck):
        return
    bitcheck.propagate = False
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(JsonLineFormatter())
    bitcheck.addHandler(handler)


class BitcheckLogger:
    """
    Namespace-aware logger writing JSON via the `bitcheck` logging tree.
    Use `logger.child("area")` for feature namespaces (matches frontend pattern).
    """

    __slots__ = ('_namespace', '_log')

    def __init__(self, namespace: str = '') -> None:
        self._namespace = namespace
        self._ensure_config()
        self._log = logging.getLogger('bitcheck.app')

    @staticmethod
    def _ensure_config() -> None:
        configure_root_bitcheck_logging()

    def child(self, name: str) -> 'BitcheckLogger':
        ns = f'{self._namespace}:{name}' if self._namespace else name
        return BitcheckLogger(ns)

    def _emit(self, level: int, message: str, meta: Mapping[str, Any] | None) -> None:
        extra = {'ns': self._namespace or 'app'}
        if meta:
            extra['data'] = safe_meta(dict(meta))
        self._log.log(level, message, extra={_LOG_RECORD_EXTRA_ATTR: extra})

    def debug(self, message: str, **meta: Any) -> None:
        self._emit(logging.DEBUG, message, meta or None)

    def info(self, message: str, **meta: Any) -> None:
        self._emit(logging.INFO, message, meta or None)

    def warning(self, message: str, **meta: Any) -> None:
        self._emit(logging.WARNING, message, meta or None)

    def error(self, message: str, **meta: Any) -> None:
        self._emit(logging.ERROR, message, meta or None)

    def exception(self, message: str, **meta: Any) -> None:
        """Log at ERROR with exception traceback attached."""
        extra_base = {'ns': self._namespace or 'app'}
        if meta:
            extra_base['data'] = safe_meta(dict(meta))
        self._log.exception(message, extra={_LOG_RECORD_EXTRA_ATTR: extra_base})


logger = BitcheckLogger()
