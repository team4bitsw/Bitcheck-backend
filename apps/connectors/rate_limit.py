"""Redis / cache rate limits for connector webhook intake."""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


def allow_event(cache_key_suffix: str, limit: int, window_seconds: int = 60) -> bool:
    """
    Fixed-window counter. Returns True if under limit, False if exceeded.
    On cache errors, fails open (allows) so webhooks are not dropped in dev.
    """
    if limit <= 0:
        return True
    full_key = f'connectors:rl:{cache_key_suffix}'
    try:
        if cache.add(full_key, 1, timeout=window_seconds):
            return True
        try:
            count = cache.incr(full_key)
        except ValueError:
            cache.set(full_key, 1, timeout=window_seconds)
            count = 1
        return count <= limit
    except Exception:
        logger.warning('Rate limit cache failure for %s — allowing', full_key, exc_info=True)
        return True


def check_type_limit(slug: str) -> bool:
    return allow_event(
        f'type:{slug}',
        settings.CONNECTORS_DEFAULT_RATE_LIMIT_PER_TYPE,
        60,
    )


def check_install_limit(install_id: str) -> bool:
    return allow_event(
        f'install:{install_id}',
        settings.CONNECTORS_DEFAULT_RATE_LIMIT_PER_INSTALL,
        60,
    )
