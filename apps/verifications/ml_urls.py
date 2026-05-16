"""
Normalize media URLs returned by the image ML service for storage and API responses.

Handles common model quirks: leading/trailing whitespace, protocol-relative URLs,
and paths relative to ML_IMAGE_SERVICE_BASE_URL.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def normalize_ml_media_url(path: str | None, base: str) -> str:
    """
    Turn ML asset paths into browser-loadable absolute URLs.

    - Full http(s) URLs are returned unchanged (after stripping whitespace).
    - Protocol-relative ``//host/path`` becomes ``https://host/path``.
    - Other relative paths are joined with ``base`` (ML_IMAGE_SERVICE_BASE_URL).
    """
    if path is None:
        return path  # type: ignore[return-value]
    if not isinstance(path, str):
        path = str(path)

    raw = path
    t = path.strip()
    if not t:
        return t

    if t.startswith("http://") or t.startswith("https://"):
        if raw != t:
            logger.info(
                "[ML-URL] Stripped whitespace on absolute URL (len diff=%d)",
                len(raw) - len(t),
            )
        return t

    if t.startswith("//"):
        out = f"https:{t}"
        logger.info("[ML-URL] Protocol-relative absolute URL: %r -> %s", raw, out)
        return out

    b = (base or "").strip().rstrip("/")
    joined = b + ("" if t.startswith("/") else "/") + t
    logger.debug("[ML-URL] Joined relative ML path: %r -> %s", raw, joined)
    return joined
