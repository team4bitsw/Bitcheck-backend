"""Download Telegram files for verification."""

from __future__ import annotations

from apps.connectors.adapters.telegram import bot as tg_bot

MAX_BYTES = 50 * 1024 * 1024


def download_telegram_file(token: str, file_id: str) -> tuple[bytes, str, str]:
    """
    Return (data, filename_hint, mime_guess).
    """
    file_path = tg_bot.get_file_path(token, file_id)
    data = tg_bot.download_file_bytes(token, file_path)
    if len(data) > MAX_BYTES:
        raise ValueError('File exceeds maximum size for this bot.')
    name = file_path.rsplit('/', 1)[-1] if '/' in file_path else 'file.bin'
    mime = 'application/octet-stream'
    lower = name.lower()
    if lower.endswith(('.jpg', '.jpeg')):
        mime = 'image/jpeg'
    elif lower.endswith('.png'):
        mime = 'image/png'
    elif lower.endswith('.webp'):
        mime = 'image/webp'
    elif lower.endswith('.pdf'):
        mime = 'application/pdf'
    elif lower.endswith('.ogg'):
        mime = 'audio/ogg'
    elif lower.endswith('.mp4'):
        mime = 'video/mp4'
    return data, name, mime
