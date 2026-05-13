"""Gmail connector — full implementation: OAuth, Pub/Sub push, verification, email reply."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from typing import TYPE_CHECKING, Any, Iterable

from django.conf import settings
from django.http import HttpRequest
from django.utils import timezone

from apps.connectors.adapters.gmail.oauth import (
    build_auth_url,
    build_oauth_state,
    exchange_code,
    exchange_refresh_token,
    get_user_email,
    verify_oauth_state_for_install,
)
from apps.connectors.adapters.gmail import gmail_api
from apps.connectors.base import ConnectorAdapter, InstallContext, ParsedEvent, VerifiableContent
from apps.connectors.exceptions import AuthExpired, CommandHandled, InvalidPayload
from apps.connectors.models import ConnectorInstall, ConnectorType
from apps.connectors.registry import register

if TYPE_CHECKING:
    from apps.verifications.models import Verification

logger = logging.getLogger(__name__)


def _creds(install: ConnectorInstall) -> tuple[str, str | None]:
    """Return (access_token, refresh_token) from stored credentials."""
    creds = install.credentials or {}
    return str(creds.get('access_token', '')), creds.get('refresh_token')


@register
class GmailAdapter(ConnectorAdapter):
    slug = 'gmail'

    # -------------------------------------------------------------------------
    # Install lifecycle
    # -------------------------------------------------------------------------

    def begin_install(
        self,
        user,
        *,
        organization=None,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        state = build_oauth_state(user, organization, slug=self.slug)
        return {'redirect_url': build_auth_url(state)}

    def complete_install(
        self,
        user,
        payload: dict[str, Any],
        *,
        organization=None,
    ) -> ConnectorInstall:
        code = payload.get('code')
        state = payload.get('state')
        if not code or not state:
            raise InvalidPayload('Missing code or state.')

        verify_oauth_state_for_install(
            str(state),
            expected_slug=self.slug,
            user=user,
            organization=organization,
        )

        tokens = exchange_code(str(code))
        access_token = tokens['access_token']
        refresh_token = tokens.get('refresh_token')
        email = get_user_email(access_token)

        ct = ConnectorType.objects.get(slug=self.slug)
        install, _created = ConnectorInstall.objects.update_or_create(
            type=ct,
            external_account_id=email,
            defaults={
                'user': None if organization else user,
                'organization': organization,
                'external_account_label': email,
                'credentials': {
                    'access_token': access_token,
                    'refresh_token': refresh_token,
                    'expires_in': tokens.get('expires_in'),
                    'token_type': tokens.get('token_type', 'Bearer'),
                },
                'settings': {
                    'auto_verify': True,
                    'attachment_kinds': ['image', 'document'],
                    'min_attachment_bytes': 10_000,
                    'daily_cap': 100,
                },
                'is_active': True,
                'last_error_message': '',
            },
        )

        # Register Gmail push notifications via Pub/Sub.
        topic = getattr(settings, 'GMAIL_PUBSUB_TOPIC', '')
        if topic:
            try:
                result = gmail_api.register_watch(access_token, refresh_token, topic)
                history_id = str(result.get('historyId', ''))
                s = dict(install.settings or {})
                s['watch_history_id'] = history_id
                s['watch_expiration'] = result.get('expiration', '')
                install.settings = s
                install.save(update_fields=['settings', 'updated_at'])
                logger.info('gmail watch registered email=%s historyId=%s', email, history_id)
            except Exception:
                logger.exception('gmail register_watch failed email=%s — push will not work', email)
        else:
            logger.warning('GMAIL_PUBSUB_TOPIC not set — Gmail push notifications disabled')

        return install

    def refresh_credentials(self, install: ConnectorInstall) -> None:
        creds = install.credentials or {}
        refresh = creds.get('refresh_token')
        if not refresh:
            raise AuthExpired('No refresh token stored for this Gmail install.')
        new_tokens = exchange_refresh_token(str(refresh))
        creds['access_token'] = new_tokens['access_token']
        if new_tokens.get('expires_in') is not None:
            creds['expires_in'] = new_tokens['expires_in']
        install.credentials = creds
        install.save(update_fields=['credentials', 'updated_at'])

    # -------------------------------------------------------------------------
    # Webhook (Pub/Sub push)
    # -------------------------------------------------------------------------

    def verify_webhook(self, request: HttpRequest) -> bool:
        """
        Pub/Sub push requests must carry our secret token as ?token=...
        Set in the subscription's push endpoint URL.
        """
        expected = getattr(settings, 'GMAIL_PUBSUB_PUSH_TOKEN', '')
        if not expected:
            logger.warning('GMAIL_PUBSUB_PUSH_TOKEN not set — rejecting gmail webhook')
            return False
        received = request.GET.get('token', '')
        return hmac.compare_digest(expected, received)

    def parse_event(self, request: HttpRequest) -> tuple[InstallContext, ParsedEvent]:
        """
        Decode the Pub/Sub push payload, resolve the install, and return
        a ParsedEvent containing the Gmail message IDs to process.
        """
        try:
            body = json.loads(request.body.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise InvalidPayload('Invalid JSON body') from e

        message = body.get('message') or {}
        data_b64 = message.get('data', '')
        if not data_b64:
            raise CommandHandled()  # empty ping — acknowledge and ignore

        try:
            notification = json.loads(base64.b64decode(data_b64).decode('utf-8'))
        except Exception as e:
            raise InvalidPayload('Could not decode Pub/Sub data') from e

        gmail_address = notification.get('emailAddress', '')
        new_history_id = str(notification.get('historyId', ''))

        if not gmail_address or not new_history_id:
            raise CommandHandled()

        # Find the ConnectorInstall for this Gmail address.
        install = (
            ConnectorInstall.objects.select_related('type')
            .filter(
                type__slug=self.slug,
                external_account_id=gmail_address,
                is_active=True,
            )
            .first()
        )
        if not install:
            logger.warning('gmail push: no install for %s', gmail_address)
            raise CommandHandled()

        # Get new message IDs from history since last known historyId.
        old_history_id = str((install.settings or {}).get('watch_history_id', ''))
        message_ids = []
        if old_history_id:
            try:
                access_token, refresh_token = _creds(install)
                history = gmail_api.get_history(access_token, refresh_token, old_history_id)
                for record in history:
                    for added in record.get('messagesAdded', []):
                        msg_id = added.get('message', {}).get('id')
                        if msg_id:
                            message_ids.append(msg_id)
            except Exception:
                logger.exception('gmail get_history failed install=%s', install.id)

        # Advance the stored historyId regardless of whether we got messages.
        s = dict(install.settings or {})
        s['watch_history_id'] = new_history_id
        install.settings = s
        install.save(update_fields=['settings', 'updated_at'])

        if not message_ids:
            raise CommandHandled()

        ctx = InstallContext(
            install_id=str(install.id),
            credentials=install.credentials or {},
            settings=install.settings or {},
            org_id=str(install.organization_id) if install.organization_id else None,
            user_id=str(install.user_id) if install.user_id else None,
        )
        pubsub_message_id = message.get('messageId', '') or new_history_id
        parsed = ParsedEvent(
            external_event_id=f'gmail:{gmail_address}:{pubsub_message_id}',
            event_type='gmail_message',
            raw_payload={
                'gmail_message_ids': message_ids,
                'gmail_address': gmail_address,
                'history_id': new_history_id,
            },
        )
        return ctx, parsed

    # -------------------------------------------------------------------------
    # Content extraction
    # -------------------------------------------------------------------------

    def extract_content(
        self,
        ctx: InstallContext,
        event: ParsedEvent,
    ) -> Iterable[VerifiableContent]:
        raw = event.raw_payload or {}
        message_ids: list[str] = raw.get('gmail_message_ids', [])
        creds = ctx.credentials or {}
        access_token = str(creds.get('access_token', ''))
        refresh_token = creds.get('refresh_token')
        settings_d = ctx.settings or {}
        allowed_kinds: list[str] = settings_d.get('attachment_kinds', ['image', 'document'])
        min_bytes: int = int(settings_d.get('min_attachment_bytes', 10_000))

        for msg_id in message_ids[:10]:  # safety cap: max 10 messages per push
            try:
                message = gmail_api.get_message(access_token, refresh_token, msg_id)
            except Exception:
                logger.exception('gmail get_message failed id=%s', msg_id)
                continue

            headers = gmail_api.get_message_headers(message)
            attachments = gmail_api.extract_attachments(message)

            for att in attachments:
                if att['size'] < min_bytes:
                    continue
                kind = 'image' if att['mime_type'].startswith('image/') else 'document'
                if kind not in allowed_kinds:
                    continue

                try:
                    data = gmail_api.get_attachment_bytes(
                        access_token, refresh_token, msg_id, att['attachment_id'],
                    )
                except Exception:
                    logger.exception('gmail get_attachment failed msg=%s att=%s', msg_id, att['attachment_id'])
                    continue

                yield VerifiableContent(
                    kind=kind,
                    payload=data,
                    filename=att['filename'],
                    mime_type=att['mime_type'],
                    source_locator={
                        'gmail_message_id': msg_id,
                        'gmail_thread_id': message.get('threadId', ''),
                        'gmail_from': headers.get('from', ''),
                        'gmail_subject': headers.get('subject', ''),
                        'gmail_message_id_header': headers.get('message-id', ''),
                        'gmail_references': headers.get('references', ''),
                    },
                )

    # -------------------------------------------------------------------------
    # Send result back as email reply
    # -------------------------------------------------------------------------

    def acknowledge_event(self, ctx: InstallContext, event: ParsedEvent) -> None:
        """No immediate acknowledgment for Gmail — reply comes with the full result."""
        return None

    def send_result(
        self,
        ctx: InstallContext,
        event: ParsedEvent,
        verification: Verification,
    ) -> dict[str, Any]:
        creds = ctx.credentials or {}
        access_token = str(creds.get('access_token', ''))
        refresh_token = creds.get('refresh_token')

        raw = event.raw_payload or {}
        message_ids: list[str] = raw.get('gmail_message_ids', [])
        if not message_ids:
            return {}

        # Fetch the first message to get reply headers.
        try:
            message = gmail_api.get_message(access_token, refresh_token, message_ids[0])
        except Exception:
            logger.exception('gmail send_result: could not fetch original message')
            return {}

        headers = gmail_api.get_message_headers(message)
        thread_id = message.get('threadId', '')
        from_addr = headers.get('from', '')
        subject = headers.get('subject', 'Bitcheck Verification Result')
        msg_id_header = headers.get('message-id', '')
        references = headers.get('references', '')
        if msg_id_header:
            references = f'{references} {msg_id_header}'.strip()

        html = _format_result_email(verification)
        reply_subject = subject if subject.lower().startswith('re:') else f'Re: {subject}'

        try:
            gmail_api.send_reply(
                access_token=access_token,
                refresh_token=refresh_token,
                to=from_addr,
                subject=reply_subject,
                html_body=html,
                thread_id=thread_id,
                in_reply_to=msg_id_header or None,
                references=references or None,
            )
            logger.info('gmail reply sent verification=%s thread=%s', verification.id, thread_id)
        except Exception:
            logger.exception('gmail send_reply failed verification=%s', verification.id)

        return {'thread_id': thread_id}


# -------------------------------------------------------------------------
# Email formatting
# -------------------------------------------------------------------------

def _score_emoji(score: int | None) -> str:
    if score is None:
        return '⚪'
    if score >= 75:
        return '✅'
    if score >= 45:
        return '⚠️'
    return '🚨'


def _format_result_email(verification: Verification) -> str:
    """Build the HTML body for the verification result reply email."""
    score = verification.trust_score
    score_txt = f'{score} / 100' if score is not None else '—'
    verdict = (verification.verdict or 'inconclusive').replace('_', ' ').title()
    emoji = _score_emoji(score)
    summary = verification.result_summary or {}
    base = getattr(settings, 'FRONTEND_APP_BASE_URL', 'https://bitcheckapp.vercel.app').rstrip('/')
    report_url = f'{base}/app/results/{verification.id}'

    model = summary.get('model_result', {})
    risk_flags: list[str] = summary.get('risk_flags', [])
    provenance = summary.get('provenance', {})
    metadata = summary.get('metadata', {})

    rows = []

    # Model result
    label = model.get('label', '')
    confidence = model.get('confidence')
    if label:
        label_txt = 'AI-generated' if 'ai' in label.lower() else 'Likely real'
        conf_txt = f' ({int(confidence * 100)}% confidence)' if confidence else ''
        rows.append(('AI detection', label_txt + conf_txt))

    # Provenance
    c2pa = provenance.get('c2pa_found')
    if c2pa is True:
        rows.append(('Provenance', '✅ Verified (C2PA found)'))
    elif c2pa is False:
        rows.append(('Provenance', '❌ No verified provenance'))

    # Metadata
    software = metadata.get('software_flags', [])
    if software:
        rows.append(('Editing software', ', '.join(software[:3])))

    detail_rows = ''.join(
        f'<tr><td style="padding:6px 12px;color:#6b7280;font-size:13px;">{k}</td>'
        f'<td style="padding:6px 12px;font-size:13px;font-weight:500;">{v}</td></tr>'
        for k, v in rows
    )

    flags_html = ''
    if risk_flags:
        items = ''.join(f'<li style="margin:4px 0;font-size:13px;">{f}</li>' for f in risk_flags[:5])
        flags_html = f'<p style="margin:16px 0 4px;font-weight:600;font-size:14px;">Risk signals</p><ul style="margin:0;padding-left:20px;">{items}</ul>'

    return f"""<!DOCTYPE html>
<html>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:560px;margin:0 auto;padding:24px;color:#111;">
  <div style="border-radius:12px;border:1px solid #e5e7eb;overflow:hidden;">
    <div style="background:#f9fafb;padding:20px 24px;border-bottom:1px solid #e5e7eb;">
      <p style="margin:0;font-size:13px;color:#6b7280;">Bitcheck Verification</p>
      <h2 style="margin:4px 0 0;font-size:20px;">{emoji} {verdict}</h2>
    </div>
    <div style="padding:20px 24px;">
      <table style="width:100%;border-collapse:collapse;margin-bottom:8px;">
        <tr>
          <td style="padding:6px 12px;color:#6b7280;font-size:13px;">Trust score</td>
          <td style="padding:6px 12px;font-size:13px;font-weight:600;">{score_txt}</td>
        </tr>
        {detail_rows}
      </table>
      {flags_html}
      <div style="margin-top:24px;">
        <a href="{report_url}"
           style="display:inline-block;background:#111;color:#fff;text-decoration:none;padding:10px 20px;border-radius:8px;font-size:14px;font-weight:500;">
          Open full report ↗
        </a>
      </div>
      <p style="margin-top:20px;font-size:12px;color:#9ca3af;">
        This analysis was performed automatically by Bitcheck. Results are probabilistic and should not be treated as absolute proof.
      </p>
    </div>
  </div>
</body>
</html>"""
