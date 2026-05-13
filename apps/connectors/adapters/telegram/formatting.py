"""HTML formatting for Telegram bot replies.

Matches the consumer app (ResultExplainer): for image checks with a model label +
confidence, the headline score is model confidence (0–100), not the composite
trust score from the ML 'trust' object — those can differ (e.g. 98 vs 50).
"""

from __future__ import annotations

import html
from django.conf import settings

from apps.verifications.models import Verification


def _humanize_model_label(raw: str) -> str:
    t = raw.strip()
    if not t:
        return t
    s = (
        t.replace('_', ' ')
        .lower()
        .title()
        .replace(' Ai ', ' AI ')
    )
    return s


def _model_confidence_01(model: dict) -> float:
    """Same logic as ResultExplainer (modelConfidence01)."""
    conf = model.get('confidence')
    if isinstance(conf, (int, float)) and conf > 0:
        return float(conf) if float(conf) <= 1 else float(conf) / 100.0
    real_p = float(model.get('real_probability') or 0)
    ai_p = float(model.get('ai_generated_probability') or 0)
    return max(real_p, ai_p, 0.0)


def _primary_display(verification: Verification) -> tuple[int | None, str, str, bool]:
    """
    Return (display_score_0_100, verdict_label, score_line_title, use_model_primary).

    For images with model_result label + confidence, mirror the app’s
    useModelPrimary path (model confidence + humanized label).
    """
    summary = verification.result_summary or {}
    model = summary.get('model_result') or {}
    label = str(model.get('label') or model.get('predicted_label') or '').strip()
    modality = verification.modality

    if modality == Verification.Modality.IMAGE and label:
        c01 = _model_confidence_01(model)
        if c01 > 0:
            score = min(100, max(0, int(round(c01 * 100))))
            verdict_label = _humanize_model_label(label)
            return score, verdict_label, 'Model confidence', True

    ts = verification.trust_score
    verdict = (verification.verdict or 'inconclusive').replace('_', ' ').title()
    return ts, verdict, 'Trust score', False


# Score → emoji band
def _score_emoji(score: int | None) -> str:
    if score is None:
        return '⚪'
    if score >= 75:
        return '🟢'
    if score >= 45:
        return '🟡'
    return '🔴'


def format_verification_html(verification: Verification) -> str:
    """Build an HTML message for Telegram (parse_mode=HTML).

    Mirrors the app result card: headline score + verdict only.
    Full breakdown is always one tap away via the report link.
    """
    display_score, verdict_label, score_title, _ = _primary_display(
        verification,
    )
    score_txt = f'{display_score} / 100' if display_score is not None else '—'
    emoji = _score_emoji(display_score)

    lines = [
        f'{emoji} <b>Verification result</b>',
        '',
        f'<b>{html.escape(score_title)}:</b> {html.escape(score_txt)}',
        f'<b>Verdict:</b> {html.escape(verdict_label)}',
    ]

    if display_score is not None:
        lines.append(
            f'{html.escape(str(display_score))}.0% {html.escape(score_title.lower())} for <b>{html.escape(verdict_label)}</b>.'
        )

    base = getattr(settings, 'FRONTEND_APP_BASE_URL', 'http://localhost:3000').rstrip('/')
    lines.append('')
    lines.append(
        f'<a href="{html.escape(base)}/app/results/{verification.id}">Open full report ↗</a>'
    )
    return '\n'.join(lines)
