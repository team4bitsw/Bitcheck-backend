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
    """Build a detailed HTML message for Telegram (parse_mode=HTML)."""
    display_score, verdict_label, score_title, use_model_primary = _primary_display(
        verification,
    )
    score_txt = f'{display_score} / 100' if display_score is not None else '—'
    emoji = _score_emoji(display_score)
    summary = verification.result_summary or {}

    lines = [
        f'{emoji} <b>Verification result</b>',
        '',
        f'<b>{html.escape(score_title)}:</b> {html.escape(score_txt)}',
        f'<b>Verdict:</b> {html.escape(verdict_label)}',
    ]

    # Secondary: show composite trust when it differs (helps explain risk metadata vs model headline)
    if use_model_primary:
        ts = verification.trust_score
        if ts is not None and ts != display_score:
            lines.append(
                f'<b>Other checks:</b> {html.escape(str(ts))} / 100'
            )

    # --- Model result detail (only when not already the primary headline) ---
    model = summary.get('model_result', {})
    if model and not use_model_primary:
        lbl = str(model.get('label', ''))
        confidence = model.get('confidence')
        if lbl:
            label_txt = 'AI-generated' if 'ai' in lbl.lower() else 'Likely real'
            conf_txt = (
                f' ({int(confidence * 100)}% confidence)'
                if isinstance(confidence, (int, float))
                else ''
            )
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
        wm_txt = 'Watermark detected' + (f': {html.escape(", ".join(kw[:3]))}' if kw else '')
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
