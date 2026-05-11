"""HTML formatting for Telegram bot replies."""

from __future__ import annotations

import html
from django.conf import settings

from apps.verifications.models import Verification


def format_verification_html(verification: Verification) -> str:
    """Build a concise HTML message (Telegram parse_mode=HTML)."""
    score = verification.trust_score
    score_txt = f'{score} / 100' if score is not None else '—'
    verdict = verification.verdict or 'inconclusive'
    verdict_label = verdict.replace('_', ' ').title()

    lines = [
        '🔍 <b>Verification result</b>',
        '',
        f'<b>Trust score:</b> {html.escape(score_txt)}',
        f'<b>Verdict:</b> {html.escape(verdict_label)}',
    ]

    summary = verification.result_summary or {}
    signals = summary.get('top_signals') or summary.get('reasons') or []
    if isinstance(signals, list) and signals:
        lines.append('')
        lines.append('<b>Top signals:</b>')
        for s in signals[:5]:
            if isinstance(s, dict):
                text = s.get('label') or s.get('text') or str(s)
            else:
                text = str(s)
            lines.append(f'• {html.escape(text)}')

    base = getattr(settings, 'FRONTEND_APP_BASE_URL', 'http://localhost:3000').rstrip('/')
    lines.append('')
    lines.append(
        f'<a href="{html.escape(base)}/app/results/{verification.id}">Open full report ↗</a>'
    )
    return '\n'.join(lines)
