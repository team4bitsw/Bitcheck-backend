"""Thin Telegram Bot API client (raw requests)."""

from __future__ import annotations

import logging
from typing import Any

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def _api_base(token: str) -> str:
    return f'https://api.telegram.org/bot{token}/'


def tg_post(token: str, method: str, json: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f'{_api_base(token)}{method}'
    r = requests.post(url, json=json or {}, timeout=30)
    data = r.json()
    if not data.get('ok'):
        logger.exception('Telegram API error method=%s status=%s body=%s', method, r.status_code, data)
        raise RuntimeError(data.get('description') or 'Telegram API error')
    return data


def tg_get(token: str, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f'{_api_base(token)}{method}'
    r = requests.get(url, params=params or {}, timeout=30)
    data = r.json()
    if not data.get('ok'):
        logger.exception('Telegram API error method=%s body=%s', method, data)
        raise RuntimeError(data.get('description') or 'Telegram API error')
    return data


def send_message(
    token: str,
    *,
    chat_id: int,
    text: str,
    parse_mode: str | None = 'HTML',
    reply_to_message_id: int | None = None,
    disable_web_page_preview: bool = True,
    reply_markup: dict | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        'chat_id': chat_id,
        'text': text,
        'disable_web_page_preview': disable_web_page_preview,
    }
    if parse_mode:
        payload['parse_mode'] = parse_mode
    if reply_to_message_id is not None:
        payload['reply_to_message_id'] = reply_to_message_id
    if reply_markup is not None:
        payload['reply_markup'] = reply_markup
    return tg_post(token, 'sendMessage', json=payload)


def edit_message_text(
    token: str,
    *,
    chat_id: int,
    message_id: int,
    text: str,
    parse_mode: str | None = 'HTML',
) -> dict[str, Any]:
    payload = {
        'chat_id': chat_id,
        'message_id': message_id,
        'text': text,
        'disable_web_page_preview': True,
    }
    if parse_mode:
        payload['parse_mode'] = parse_mode
    return tg_post(token, 'editMessageText', json=payload)


def get_file_path(token: str, file_id: str) -> str:
    data = tg_get(token, 'getFile', {'file_id': file_id})
    return str(data['result']['file_path'])


def download_file_bytes(token: str, file_path: str) -> bytes:
    url = f'https://api.telegram.org/file/bot{token}/{file_path}'
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    return r.content


def get_me(token: str) -> dict[str, Any]:
    data = tg_get(token, 'getMe')
    return data['result']


def set_webhook(
    token: str,
    *,
    url: str,
    secret_token: str,
    allowed_updates: list[str] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {'url': url, 'secret_token': secret_token}
    if allowed_updates:
        payload['allowed_updates'] = allowed_updates
    return tg_post(token, 'setWebhook', json=payload)


def delete_webhook(token: str) -> dict[str, Any]:
    return tg_post(token, 'deleteWebhook', json={'drop_pending_updates': False})


def answer_callback_query(
    token: str,
    *,
    callback_query_id: str,
    text: str | None = None,
    show_alert: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {'callback_query_id': callback_query_id}
    if text is not None:
        payload['text'] = text
        payload['show_alert'] = show_alert
    return tg_post(token, 'answerCallbackQuery', json=payload)


def get_chat_member(token: str, chat_id: int, user_id: int) -> dict[str, Any]:
    data = tg_get(token, 'getChatMember', {'chat_id': chat_id, 'user_id': user_id})
    return data['result']


def answer_inline_query(
    token: str,
    *,
    inline_query_id: str,
    results: list[dict[str, Any]],
    cache_time: int = 0,
    is_personal: bool = True,
) -> dict[str, Any]:
    return tg_post(
        token,
        'answerInlineQuery',
        json={
            'inline_query_id': inline_query_id,
            'results': results,
            'cache_time': cache_time,
            'is_personal': is_personal,
        },
    )


def set_my_commands(token: str, commands: list[dict[str, str]]) -> None:
    tg_post(token, 'setMyCommands', json={'commands': commands})


def set_my_description(token: str, description: str) -> None:
    tg_post(token, 'setMyDescription', json={'description': description[:512]})


def shared_bot_token() -> str:
    tok = settings.TELEGRAM_SHARED_BOT_TOKEN
    if not tok:
        raise RuntimeError('TELEGRAM_SHARED_BOT_TOKEN is not configured')
    return tok
