"""Gmail API helpers — thin wrappers over the Google API client library."""

from __future__ import annotations

import base64
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from django.conf import settings
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

# MIME types we are willing to extract for verification
VERIFIABLE_MIME_TYPES = {
    'image/jpeg', 'image/jpg', 'image/png', 'image/webp', 'image/gif',
    'application/pdf',
}


def _build_service(access_token: str, refresh_token: str | None = None):
    """Return an authenticated Gmail API service object."""
    creds = Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri='https://oauth2.googleapis.com/token',
        client_id=settings.GOOGLE_OAUTH_CLIENT_ID,
        client_secret=settings.GOOGLE_OAUTH_CLIENT_SECRET,
    )
    return build('gmail', 'v1', credentials=creds, cache_discovery=False)


def register_watch(access_token: str, refresh_token: str | None, topic_name: str) -> dict:
    """
    Register a Gmail push notification watch.
    Returns {'historyId': ..., 'expiration': ...}
    Expires after ~7 days — must be renewed.
    """
    service = _build_service(access_token, refresh_token)
    return service.users().watch(
        userId='me',
        body={
            'topicName': topic_name,
            'labelIds': ['INBOX'],
            'labelFilterAction': 'include',
        },
    ).execute()


def stop_watch(access_token: str, refresh_token: str | None) -> None:
    """Stop push notifications for this account."""
    try:
        service = _build_service(access_token, refresh_token)
        service.users().stop(userId='me').execute()
    except Exception:
        logger.exception('gmail stop_watch failed')


def get_history(
    access_token: str,
    refresh_token: str | None,
    start_history_id: str,
    history_types: list[str] | None = None,
) -> list[dict]:
    """
    Return list of history records since start_history_id.
    Each record may contain messagesAdded, labelsAdded, etc.
    """
    service = _build_service(access_token, refresh_token)
    results = []
    page_token = None
    params: dict[str, Any] = {
        'userId': 'me',
        'startHistoryId': start_history_id,
        'historyTypes': history_types or ['messageAdded'],
        'labelId': 'INBOX',
    }
    while True:
        if page_token:
            params['pageToken'] = page_token
        try:
            resp = service.users().history().list(**params).execute()
        except HttpError as e:
            if e.resp.status == 404:
                logger.warning('gmail history not found start=%s — full sync needed', start_history_id)
                return []
            raise
        results.extend(resp.get('history', []))
        page_token = resp.get('nextPageToken')
        if not page_token:
            break
    return results


def get_message(access_token: str, refresh_token: str | None, message_id: str) -> dict:
    """Fetch a full Gmail message."""
    service = _build_service(access_token, refresh_token)
    return service.users().messages().get(
        userId='me',
        id=message_id,
        format='full',
    ).execute()


def get_attachment_bytes(
    access_token: str,
    refresh_token: str | None,
    message_id: str,
    attachment_id: str,
) -> bytes:
    """Download an attachment and return its raw bytes."""
    service = _build_service(access_token, refresh_token)
    att = service.users().messages().attachments().get(
        userId='me',
        messageId=message_id,
        id=attachment_id,
    ).execute()
    data = att.get('data', '')
    return base64.urlsafe_b64decode(data + '==')


def extract_attachments(message: dict) -> list[dict]:
    """
    Walk the message parts tree and return verifiable attachments.
    Each item: {filename, mime_type, attachment_id, size, part_id}
    """
    attachments = []

    def _walk(parts: list[dict]) -> None:
        for part in parts:
            mime = part.get('mimeType', '')
            body = part.get('body', {})
            att_id = body.get('attachmentId')
            filename = part.get('filename', '')
            size = body.get('size', 0)

            if att_id and mime in VERIFIABLE_MIME_TYPES and size > 0:
                attachments.append({
                    'filename': filename or f'attachment.{mime.split("/")[-1]}',
                    'mime_type': mime,
                    'attachment_id': att_id,
                    'size': size,
                    'part_id': part.get('partId', ''),
                })

            sub_parts = part.get('parts', [])
            if sub_parts:
                _walk(sub_parts)

    payload = message.get('payload', {})
    top_parts = payload.get('parts', [])
    if top_parts:
        _walk(top_parts)

    return attachments


def get_message_headers(message: dict) -> dict[str, str]:
    """Return {header_name_lower: value} for the top-level headers."""
    headers = {}
    for h in message.get('payload', {}).get('headers', []):
        headers[h['name'].lower()] = h['value']
    return headers


def send_reply(
    access_token: str,
    refresh_token: str | None,
    to: str,
    subject: str,
    html_body: str,
    thread_id: str,
    in_reply_to: str | None = None,
    references: str | None = None,
) -> None:
    """Send a reply email on the given thread."""
    msg = MIMEMultipart('alternative')
    msg['To'] = to
    msg['Subject'] = subject
    if in_reply_to:
        msg['In-Reply-To'] = in_reply_to
    if references:
        msg['References'] = references

    msg.attach(MIMEText(html_body, 'html'))

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode('utf-8')
    service = _build_service(access_token, refresh_token)
    service.users().messages().send(
        userId='me',
        body={'raw': raw, 'threadId': thread_id},
    ).execute()
