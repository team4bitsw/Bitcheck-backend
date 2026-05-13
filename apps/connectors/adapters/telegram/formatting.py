"""HTML formatting for Telegram bot replies."""

from __future__ import annotations

import html
from django.conf import settings

from apps.verifications.models import Verification

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
    """Build a detailed HTML message for Telegram (parse_mode=HTML)."""
    score = verification.trust_score
    score_txt = f'{score} / 100' if score is not None else '—'
    verdict = verification.verdict or 'inconclusive'
    verdict_label = verdict.replace('_', ' ').title()
    emoji = _score_emoji(score)
    summary = verification.result_summary or {}

    lines = [
        f'{emoji} <b>Verification result</b>',
        '',
        f'<b>Trust score:</b> {html.escape(score_txt)}',
        f'<b>Verdict:</b> {html.escape(verdict_label)}',
    ]

    # --- Model result (AI detection) ---
    model = summary.get('model_result', {})
    if model:
        label = model.get('label', '')
        confidence = model.get('confidence')
        if label:
            label_txt = 'AI-generated' if 'ai' in label.lower() else 'Likely real'
            conf_txt = f' ({int(confidence * 100)}% confidence)' if confidence is not None else ''
            lines.append(f'<b>AI detection:</b> {html.escape(label_txt + conf_txt)}')

    # --- Provenance ---
    provenance = summary.get('provenance', {})
    if provenance:
        c2pa = provenance.get('c2pa_found')
        if c2pa is True:
            lines.append('<b>Provenance:</b> ✅ Verified (C2PA found)')
        elif c2pa is False:
            lines.append('<b>Provenance:</b> ❌ No verified provenance')

    # --- Metadata signals ---
    metadata = summary.get('metadata', {})
    software_flags = metadata.get('software_flags') or []
    camera_found = metadata.get('camera_metadata_found')
    meta_notes = []
    if software_flags:
        meta_notes.append(f'Edited with {html.escape(", ".join(software_flags[:2]))}')
    if camera_found is False:
        meta_notes.append('No camera EXIF data')
    elif camera_found is True:
        meta_notes.append('Camera EXIF present')
    if meta_notes:
        lines.append(f'<b>Metadata:</b> {" · ".join(meta_notes)}')

    # --- Watermark ---
    wm = summary.get('visible_watermark', {})
    if wm.get('visible_watermark_found'):
        kw = wm.get('detected_keywords') or []
        wm_txt = f'Watermark detected' + (f': {html.escape(", ".join(kw[:3]))}' if kw else '')
        lines.append(f'<b>Watermark:</b> {wm_txt}')

    # --- Risk flags ---
    risk_flags = summary.get('risk_flags') or []
    if risk_flags:
        lines.append('')
        lines.append('<b>Risk signals:</b>')
        for flag in risk_flags[:4]:
            lines.append(f'• {html.escape(str(flag))}')

    # --- Forensics ---
    forensics = summary.get('forensics', {})
    noise = forensics.get('noise_inconsistency')
    if noise is not None and noise > 0.4:
        lines.append(f'• High noise inconsistency ({noise:.2f})')

    # --- Full report link ---
    base = getattr(settings, 'FRONTEND_APP_BASE_URL', 'http://localhost:3000').rstrip('/')
    lines.append('')
    lines.append(
        f'<a href="{html.escape(base)}/app/results/{verification.id}">Open full report ↗</a>'
    )
    return '\n'.join(lines)
