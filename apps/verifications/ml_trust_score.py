"""
Normalize trust score (0–100) from ML JSON payloads.

Image HF Space and other runners may expose the overall trust figure as
``trust.trust_score``, ``trust.trust_score_out_of_100``, or legacy ``trust.score``.
We avoid ``or`` chains so a legitimate score of ``0`` is preserved.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

logger = logging.getLogger(__name__)

_TRUST_BLOCK_KEYS = ('trust_score_out_of_100', 'trust_score', 'score')


def _coerce_score(val: Any, *, log_prefix: str, source: str) -> int | None:
    try:
        score = int(round(float(val)))
        logger.info('%s Using %s -> %s', log_prefix, source, score)
        return score
    except (TypeError, ValueError):
        logger.warning('%s Ignoring non-numeric %s=%r', log_prefix, source, val)
        return None


def extract_ml_trust_score(
    ml_result: Mapping[str, Any] | None,
    *,
    default: int = 50,
    log_prefix: str = '[ML-TRUST]',
) -> int:
    """
    Extract the verification trust score from an ML response dict.

    Order:
      1. ``trust.trust_score_out_of_100``
      2. ``trust.trust_score`` (e.g. Hugging Face image API)
      3. ``trust.score`` (legacy float 0–100)
      4. Top-level ``trust_score`` (some text/async payloads)
    """
    if not isinstance(ml_result, Mapping):
        logger.warning(
            '%s ML payload missing or not a mapping; default=%s',
            log_prefix,
            default,
        )
        return default

    trust = ml_result.get('trust')
    if isinstance(trust, Mapping):
        for key in _TRUST_BLOCK_KEYS:
            val = trust.get(key)
            if val is None:
                continue
            got = _coerce_score(val, log_prefix=log_prefix, source=f'trust.{key}')
            if got is not None:
                return got

    top = ml_result.get('trust_score')
    if top is not None:
        got = _coerce_score(
            top,
            log_prefix=log_prefix,
            source='trust_score (top-level)',
        )
        if got is not None:
            return got

    logger.warning(
        '%s No usable trust score (tried trust[%s] + top-level trust_score); '
        'default=%s',
        log_prefix,
        ', '.join(_TRUST_BLOCK_KEYS),
        default,
    )
    return default
