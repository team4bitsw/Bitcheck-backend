"""Telegram connector — shared bot, own bot, groups, inline, auto-verify (full plan)."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import secrets
from typing import Any, Iterable

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest
from django.utils import timezone

from apps.connectors.adapters.telegram import bot as tg_bot
from apps.connectors.adapters.telegram import files as tg_files
from apps.connectors.adapters.telegram.formatting import format_verification_html
from apps.connectors.adapters.telegram.link import complete_link_with_chat, create_link_code
from apps.connectors.base import ConnectorAdapter, InstallContext, ParsedEvent, VerifiableContent
from apps.connectors.exceptions import CommandHandled, InvalidPayload
from apps.connectors.models import ConnectorEvent, ConnectorInstall, ConnectorType
from apps.connectors.registry import register

logger = logging.getLogger(__name__)


def _cache_incr(key: str, ttl: int, limit: int) -> bool:
    """Return True if rate-limited (at or over limit)."""
    try:
        n = int(cache.get(key, 0))
    except (TypeError, ValueError):
        n = 0
    if n >= limit:
        return True
    cache.set(key, n + 1, ttl)
    return False


def _parse_id_csv(s: str) -> set[int]:
    out: set[int] = set()
    for part in re.split(r'[\s,]+', (s or '').strip()):
        if part.isdigit() or (part.startswith('-') and part[1:].isdigit()):
            out.add(int(part))
    return out


def _start_argument(text: str | None) -> str | None:
    if not text:
        return None
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        return None
    return parts[1].strip() or None


@register
class TelegramAdapter(ConnectorAdapter):
    slug = 'telegram'

    def verify_webhook(self, request: HttpRequest) -> bool:
        secret = (request.headers.get('X-Telegram-Bot-Api-Secret-Token') or '').strip()
        bot = request.GET.get('bot', 'shared')
        if bot == 'shared':
            expected = getattr(settings, 'TELEGRAM_SHARED_BOT_SECRET', '') or ''
            if not expected:
                return False
            return hmac.compare_digest(secret, expected)
        try:
            inst = ConnectorInstall.objects.get(pk=bot, type__slug=self.slug, is_active=True)
        except ConnectorInstall.DoesNotExist:
            return False
        exp = (inst.credentials or {}).get('webhook_secret') or ''
        return bool(exp) and hmac.compare_digest(secret, str(exp))

    def _token_for(self, request: HttpRequest) -> tuple[str, str]:
        bot = request.GET.get('bot', 'shared')
        if bot == 'shared':
            return tg_bot.shared_bot_token(), 'shared'
        inst = ConnectorInstall.objects.get(pk=bot, type__slug=self.slug, is_active=True)
        tok = (inst.credentials or {}).get('bot_token')
        if not tok:
            raise InvalidPayload('Bot token missing on install')
        return str(tok), bot

    def _get_shared_install(self, chat_id: int) -> ConnectorInstall | None:
        return (
            ConnectorInstall.objects.select_related('type')
            .filter(
                type__slug=self.slug,
                external_account_id=f'shared:{chat_id}',
                is_active=True,
            )
            .first()
        )

    def _get_own_install(self, install_pk: str) -> ConnectorInstall:
        return ConnectorInstall.objects.select_related('type').get(
            pk=install_pk,
            type__slug=self.slug,
            is_active=True,
        )

    def _find_install_by_telegram_user(self, tg_user_id: int) -> ConnectorInstall | None:
        return (
            ConnectorInstall.objects.filter(
                type__slug=self.slug,
                is_active=True,
                credentials__contains={'telegram_user_id': tg_user_id},
            )
            .first()
        )

    def _allowed_user(self, install: ConnectorInstall, from_user: dict | None) -> bool:
        if not from_user:
            return False
        raw = (install.settings or {}).get('allowed_user_ids') or ''
        ids = _parse_id_csv(str(raw))
        if not ids:
            return True
        return int(from_user.get('id', 0)) in ids

    def _allowed_chat_type(self, install: ConnectorInstall, chat_type: str) -> bool:
        allowed = (install.settings or {}).get('allowed_chat_types') or [
            'private',
            'group',
            'supergroup',
            'channel',
        ]
        if isinstance(allowed, list):
            return chat_type in allowed
        return True

    def _enforce_daily_cap(self, install: ConnectorInstall) -> bool:
        cap = (install.settings or {}).get('daily_cap')
        if cap is None:
            cap = 100
        try:
            cap_n = int(cap)
        except (TypeError, ValueError):
            cap_n = 100
        start = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        n = ConnectorEvent.objects.filter(install=install, created_at__gte=start).count()
        return n >= cap_n

    def _handle_start(
        self,
        *,
        token: str,
        chat_id: int,
        message: dict,
        bot_param: str,
    ) -> None:
        text = message.get('text') or ''
        arg = _start_argument(text)
        chat = message.get('chat') or {}
        chat_type = chat.get('type', 'private')
        user = message.get('from') or {}

        if bot_param != 'shared':
            tg_bot.send_message(
                token,
                chat_id=chat_id,
                text=f'<b>Linked.</b> Chat type: {chat_type}. Send media or use /verify as a reply in groups.',
            )
            raise CommandHandled()

        if arg:
            install = complete_link_with_chat(code=arg, chat_id=chat_id, telegram_user=user)
            if install:
                tg_bot.send_message(
                    token,
                    chat_id=chat_id,
                    text=(
                        '<b>Linked to your Bitcheck account.</b> Send an image, document, audio, '
                        'video, or text to verify.'
                    ),
                )
            else:
                tg_bot.send_message(
                    token,
                    chat_id=chat_id,
                    text=(
                        'That link code is invalid or expired. Open Bitcheck → Connectors → '
                        'Telegram and try again.'
                    ),
                )
            raise CommandHandled()

        if self._get_shared_install(chat_id):
            tg_bot.send_message(
                token,
                chat_id=chat_id,
                text="You're already linked. Send content to verify or use /help.",
            )
            raise CommandHandled()

        key = f'tg:onboard:{chat_id}'
        if not cache.get(key):
            tg_bot.send_message(
                token,
                chat_id=chat_id,
                text=(
                    'Welcome to Bitcheck on Telegram.\n'
                    'Open the Bitcheck app → Connectors → Telegram → Connect to get a secure link, '
                    'then tap Start here again.'
                ),
            )
            cache.set(key, 1, timeout=86400)
        raise CommandHandled()

    def _handle_inline(self, token: str, update: dict, install_hint: ConnectorInstall | None) -> None:
        iq = update['inline_query']
        qid = iq['id']
        q = (iq.get('query') or '').strip()
        from_u = iq.get('from') or {}
        tg_uid = int(from_u.get('id', 0))
        install = install_hint or self._find_install_by_telegram_user(tg_uid)
        if not install or not q:
            tg_bot.answer_inline_query(token, inline_query_id=qid, results=[], cache_time=10)
            raise CommandHandled()
        hid = hashlib.sha256(q.encode('utf-8')).hexdigest()[:12]
        results = [
            {
                'type': 'article',
                'id': hid,
                'title': 'Verify with Bitcheck',
                'description': (q[:100] + '…') if len(q) > 100 else (q or 'Text / URL'),
                'input_message_content': {
                    'message_text': f'Bitcheck verification:{q}',
                },
            }
        ]
        tg_bot.answer_inline_query(token, inline_query_id=qid, results=results)
        raise CommandHandled()

    def _sync_own_bot_profile(self, token: str) -> None:
        tg_bot.set_my_commands(
            str(token),
            [
                {'command': 'start', 'description': 'Welcome and link'},
                {'command': 'help', 'description': 'How to verify content'},
                {'command': 'verify', 'description': 'In groups: reply to a message, then send /verify'},
            ],
        )
        tg_bot.set_my_description(
            str(token),
            'Verify images, documents, audio, video, and text with Bitcheck.',
        )

    def reconfigure_bot(self, install: ConnectorInstall) -> None:
        creds = install.credentials or {}
        if creds.get('bot_mode') != 'own':
            raise InvalidPayload(
                'Reconfigure is only available for connectors using your own Telegram bot.',
            )
        token = creds.get('bot_token')
        if not token:
            raise InvalidPayload('Bot token missing on this install.')
        self._sync_own_bot_profile(str(token))

    def _handle_callback_query(self, token: str, bot_param: str, cq: dict) -> None:
        cid = cq.get('id')
        data = cq.get('data') or ''
        from_u = cq.get('from') or {}
        user_id = int(from_u.get('id', 0))
        if not data.startswith('m:'):
            if cid:
                tg_bot.answer_callback_query(token, callback_query_id=str(cid))
            raise CommandHandled()
        install_pk = data[2:].strip()
        try:
            install = ConnectorInstall.objects.get(
                pk=install_pk,
                type__slug=self.slug,
                is_active=True,
            )
        except ConnectorInstall.DoesNotExist:
            if cid:
                tg_bot.answer_callback_query(
                    token,
                    callback_query_id=str(cid),
                    text='Unknown install.',
                    show_alert=True,
                )
            raise CommandHandled()
        if bot_param != 'shared' and str(install.pk) != bot_param:
            if cid:
                tg_bot.answer_callback_query(
                    token,
                    callback_query_id=str(cid),
                    text='Callback does not match this bot.',
                    show_alert=True,
                )
            raise CommandHandled()
        msg = cq.get('message')
        if not msg:
            if cid:
                tg_bot.answer_callback_query(token, callback_query_id=str(cid))
            raise CommandHandled()
        chat_id = int(msg['chat']['id'])
        try:
            member = tg_bot.get_chat_member(token, chat_id, user_id)
        except Exception:
            logger.exception('telegram getChatMember failed')
            if cid:
                tg_bot.answer_callback_query(
                    token,
                    callback_query_id=str(cid),
                    text='Could not verify your permissions.',
                    show_alert=True,
                )
            raise CommandHandled()
        status = member.get('status', '')
        if status not in ('creator', 'administrator'):
            if cid:
                tg_bot.answer_callback_query(
                    token,
                    callback_query_id=str(cid),
                    text='Only admins can mute auto-verify here.',
                    show_alert=True,
                )
            raise CommandHandled()
        settings_d = dict(install.settings or {})
        muted = list(settings_d.get('auto_verify_muted_groups') or [])
        muted_ints: list[int] = []
        for x in muted:
            try:
                muted_ints.append(int(x))
            except (TypeError, ValueError):
                continue
        if chat_id not in muted_ints:
            muted_ints.append(chat_id)
        settings_d['auto_verify_muted_groups'] = muted_ints
        install.settings = settings_d
        install.save(update_fields=['settings', 'updated_at'])
        if cid:
            tg_bot.answer_callback_query(
                token,
                callback_query_id=str(cid),
                text='Auto-verify muted in this chat.',
            )
        raise CommandHandled()

    def parse_event(self, request: HttpRequest) -> tuple[InstallContext, ParsedEvent]:
        try:
            update = json.loads(request.body.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise InvalidPayload('Invalid JSON') from e

        token, bot_param = self._token_for(request)
        if 'callback_query' in update:
            self._handle_callback_query(token, bot_param, update['callback_query'])
        if 'inline_query' in update:
            inst = None
            if bot_param != 'shared':
                try:
                    inst = self._get_own_install(bot_param)
                except ConnectorInstall.DoesNotExist:
                    inst = None
            self._handle_inline(token, update, inst)

        message = update.get('message') or update.get('channel_post')
        if not message:
            if 'edited_message' in update:
                raise CommandHandled()
            raise CommandHandled()

        chat = message.get('chat') or {}
        chat_id = int(chat['id'])
        chat_type = chat.get('type', 'private')
        msg_id = int(message.get('message_id', 0))
        from_user = message.get('from') or {}

        text = (message.get('text') or '').strip()
        bot_username = getattr(settings, 'TELEGRAM_SHARED_BOT_USERNAME', 'BitcheckBot').lstrip('@')
        if text.startswith('/start') or text.startswith(f'/start@{bot_username}'):
            self._handle_start(token=token, chat_id=chat_id, message=message, bot_param=bot_param)
        if text.startswith('/help'):
            tg_bot.send_message(
                token,
                chat_id=chat_id,
                text=(
                    '<b>Bitcheck</b> — send an image, PDF, voice, video, or text to verify.\n'
                    'In groups: reply to a message with /verify.\n'
                    'Inline: type @botname plus URL or text (requires linked account).'
                ),
            )
            raise CommandHandled()

        if bot_param == 'shared':
            install = self._get_shared_install(chat_id)
        else:
            install = self._get_own_install(bot_param)

        if not install:
            self._handle_start(
                token=token,
                chat_id=chat_id,
                message={'text': '/start', 'chat': chat, 'from': from_user},
                bot_param=bot_param,
            )

        if not self._allowed_chat_type(install, chat_type):
            raise CommandHandled()
        if not self._allowed_user(install, from_user):
            tg_bot.send_message(token, chat_id=chat_id, text='You are not allowed to use this bot.')
            raise CommandHandled()

        if _cache_incr(f'tg:rl:chat:{install.id}:{chat_id}', 60, 30):
            raise CommandHandled()
        if bot_param == 'shared' and _cache_incr(f'tg:rl:user:{from_user.get("id")}', 86400, 100):
            tg_bot.send_message(token, chat_id=chat_id, text='Rate limit: try again tomorrow.')
            raise CommandHandled()

        if self._enforce_daily_cap(install):
            tg_bot.send_message(
                token,
                chat_id=chat_id,
                text=(
                    'Daily verification cap reached for this connection. Adjust in Bitcheck or try tomorrow.'
                ),
            )
            raise CommandHandled()

        target = message
        is_verify_cmd = bool(re.match(r'^/verify(?:@\w+)?(?:\s|$)', text or ''))
        if chat_type in ('group', 'supergroup', 'channel'):
            reply_to = message.get('reply_to_message')
            settings_auto = bool((install.settings or {}).get('auto_verify_media'))
            groups_csv = str((install.settings or {}).get('auto_verify_groups') or '')
            allowed_gids = _parse_id_csv(groups_csv) if groups_csv.strip() else None

            if reply_to and is_verify_cmd:
                target = reply_to
            elif settings_auto and bot_param != 'shared':
                muted = (install.settings or {}).get('auto_verify_muted_groups') or []
                muted_set: set[int] = set()
                for x in muted:
                    try:
                        muted_set.add(int(x))
                    except (TypeError, ValueError):
                        continue
                if chat_id in muted_set:
                    raise CommandHandled()
                if allowed_gids is None or chat_id in allowed_gids:
                    if any(
                        k in message
                        for k in ('photo', 'document', 'video', 'audio', 'voice', 'video_note', 'sticker')
                    ):
                        target = message
                    else:
                        raise CommandHandled()
                else:
                    raise CommandHandled()
            elif is_verify_cmd and not reply_to:
                tg_bot.send_message(
                    token,
                    chat_id=chat_id,
                    text='Reply to the message to verify with /verify.',
                )
                raise CommandHandled()
            elif not is_verify_cmd and not (
                settings_auto
                and bot_param != 'shared'
                and any(
                    k in message
                    for k in ('photo', 'document', 'video', 'audio', 'voice', 'video_note', 'sticker')
                )
            ):
                raise CommandHandled()
        elif is_verify_cmd:
            tg_bot.send_message(
                token,
                chat_id=chat_id,
                text='In private chat, send the file or text directly (no /verify needed).',
            )
            raise CommandHandled()

        if text.startswith('Bitcheck verification:'):
            inner = text.split(':', 1)[1].strip()
            target = {
                **message,
                'text': inner,
            }
            for k in ('photo', 'document', 'video', 'audio', 'voice', 'video_note', 'sticker'):
                target.pop(k, None)

        uid = str(update.get('update_id', ''))
        ctx = InstallContext(
            install_id=str(install.id),
            credentials=install.credentials or {},
            settings=install.settings or {},
            org_id=str(install.organization_id) if install.organization_id else None,
            user_id=str(install.user_id) if install.user_id else None,
        )
        raw_payload = {
            'telegram_message': target,
            'chat_id': chat_id,
            'chat_type': chat_type,
            'message_id': int(target.get('message_id', msg_id)),
            'user_id': int(from_user.get('id', 0)),
            'reply_to_message_id': msg_id if target is not message else None,
            'token_param': bot_param,
        }
        parsed = ParsedEvent(
            external_event_id=uid,
            event_type='telegram_message',
            raw_payload=raw_payload,
        )
        return ctx, parsed

    def extract_content(
        self,
        ctx: InstallContext,
        event: ParsedEvent,
    ) -> Iterable[VerifiableContent]:
        raw = event.raw_payload or {}
        msg = raw.get('telegram_message') or {}
        tok_param = raw.get('token_param', 'shared')
        token = tg_bot.shared_bot_token() if tok_param == 'shared' else (ctx.credentials or {}).get('bot_token')
        if not token:
            return []

        def _yield_file(tg_kind: str, file_id: str, filename: str | None) -> Iterable[VerifiableContent]:
            try:
                data, name, mime = tg_files.download_telegram_file(str(token), file_id)
            except Exception as e:  # noqa: BLE001
                logger.exception('telegram download failed')
                yield VerifiableContent(kind='text', payload=f'Could not download file: {e}')
                return
            _kind_map = {
                'telegram_photo': 'image',
                'telegram_sticker': 'image',
                'telegram_document': 'document',
                'telegram_video': 'video',
                'telegram_audio': 'audio',
                'telegram_voice': 'audio',
                'telegram_video_note': 'video',
            }
            vk = _kind_map.get(tg_kind, 'document')
            yield VerifiableContent(
                kind=vk,
                payload=data,
                filename=filename or name,
                mime_type=mime,
                source_locator={'telegram_file_id': file_id},
            )

        if msg.get('photo'):
            photos = msg['photo']
            best = max(photos, key=lambda p: p.get('file_size', 0) or 0)
            yield from _yield_file('telegram_photo', best['file_id'], 'photo.jpg')

        elif msg.get('document'):
            d = msg['document']
            yield from _yield_file('telegram_document', d['file_id'], d.get('file_name'))

        elif msg.get('video'):
            v = msg['video']
            yield from _yield_file('telegram_video', v['file_id'], v.get('file_name'))

        elif msg.get('audio'):
            a = msg['audio']
            yield from _yield_file('telegram_audio', a['file_id'], a.get('file_name'))

        elif msg.get('voice'):
            v = msg['voice']
            yield from _yield_file('telegram_voice', v['file_id'], 'voice.ogg')

        elif msg.get('video_note'):
            vn = msg['video_note']
            yield from _yield_file('telegram_video_note', vn['file_id'], 'video_note.mp4')

        elif msg.get('sticker'):
            st = msg['sticker']
            fid = st.get('file_id')
            if st.get('thumb'):
                fid = st['thumb']['file_id']
            yield from _yield_file('telegram_sticker', fid, 'sticker.webp')

        txt = (msg.get('text') or '').strip()
        if txt:
            yield VerifiableContent(kind='text', payload=txt)

    def acknowledge_event(self, ctx: InstallContext, event: ParsedEvent) -> None:
        raw = event.raw_payload or {}
        tok_param = raw.get('token_param', 'shared')
        token = tg_bot.shared_bot_token() if tok_param == 'shared' else (ctx.credentials or {}).get('bot_token')
        if not token:
            return
        chat_id = raw.get('chat_id')
        msg_id = raw.get('message_id')
        if not chat_id:
            return
        try:
            tg_bot.send_message(
                str(token),
                chat_id=int(chat_id),
                text='Checking this for you, hang on a moment...',
                reply_to_message_id=msg_id,
            )
        except Exception:
            logger.exception('telegram acknowledge failed')

    def send_result(
        self,
        ctx: InstallContext,
        event: ParsedEvent,
        verification,
    ) -> dict[str, Any]:
        raw = event.raw_payload or {}
        tok_param = raw.get('token_param', 'shared')
        token = tg_bot.shared_bot_token() if tok_param == 'shared' else (ctx.credentials or {}).get('bot_token')
        if not token:
            return {}
        chat_id = int(raw['chat_id'])
        reply_to = raw.get('reply_to_message_id') or raw['message_id']
        chat_type = raw.get('chat_type', 'private')
        user_id = int(raw.get('user_id', 0))
        visibility = (ctx.settings or {}).get('group_result_visibility', 'public')
        html_text = format_verification_html(verification)
        reply_markup: dict | None = None
        if (
            chat_type in ('group', 'supergroup')
            and visibility == 'public'
            and (ctx.settings or {}).get('auto_verify_media')
            and (ctx.credentials or {}).get('bot_mode') == 'own'
        ):
            reply_markup = {
                'inline_keyboard': [
                    [{'text': '⚙ Mute auto-verify here', 'callback_data': f'm:{ctx.install_id}'}],
                ],
            }

        if chat_type == 'private' or visibility == 'public':
            r = tg_bot.send_message(
                str(token),
                chat_id=chat_id,
                text=html_text,
                reply_to_message_id=reply_to if chat_type != 'private' else None,
                reply_markup=reply_markup,
            )
            mid = r.get('result', {}).get('message_id', '')
            return {'message_id': mid}
        if visibility == 'private':
            tg_bot.send_message(str(token), chat_id=user_id, text=html_text)
            tg_bot.send_message(
                str(token),
                chat_id=chat_id,
                text='Verification result sent to you in a direct message.',
            )
            return {'message_id': 'dm'}
        tg_bot.send_message(str(token), chat_id=user_id, text=html_text)
        return {'message_id': 'dm_silent'}

    def begin_install(
        self,
        user,
        *,
        organization=None,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        options = options or {}
        mode = options.get('mode', 'shared')
        ct = ConnectorType.objects.get(slug=self.slug)
        if mode == 'own_bot' and ct.auth_type != ConnectorType.AuthType.TELEGRAM_DUAL:
            mode = 'shared'
        if ct.auth_type == ConnectorType.AuthType.TELEGRAM_DUAL and mode == 'own_bot':
            return {
                'requires_input': [
                    {
                        'key': 'bot_token',
                        'label': 'Bot token from @BotFather',
                        'secret': True,
                        'help_md': 'Paste the token like 123456:ABC-DEF…',
                    }
                ]
            }

        code = create_link_code(user, organization)
        uname = getattr(settings, 'TELEGRAM_SHARED_BOT_USERNAME', 'BitcheckBot').lstrip('@')
        https_link = f'https://t.me/{uname}?start={code}'
        tg_link = f'tg://resolve?domain={uname}&start={code}'
        return {
            'deep_link': https_link,
            'telegram_deeplink': tg_link,
            'poll_code': code,
        }

    def complete_install(
        self,
        user,
        payload: dict[str, Any],
        *,
        organization=None,
    ) -> ConnectorInstall:
        token = (payload.get('bot_token') or payload.get('token') or '').strip()
        if not token:
            raise InvalidPayload('bot_token is required')
        me = tg_bot.get_me(token)
        bid = me['id']
        uname = me.get('username') or str(bid)
        wh_secret = secrets.token_urlsafe(32)
        ct = ConnectorType.objects.get(slug=self.slug)
        install, _created = ConnectorInstall.objects.update_or_create(
            type=ct,
            external_account_id=f'own:{bid}',
            defaults={
                'user': None if organization else user,
                'organization': organization,
                'external_account_label': f'@{uname}'[:255],
                'credentials': {
                    'bot_token': token,
                    'webhook_secret': wh_secret,
                    'telegram_bot_id': bid,
                    'bot_username': uname,
                    'bot_mode': 'own',
                },
                'settings': {
                    'group_result_visibility': 'public',
                    'allowed_chat_types': ['private', 'group', 'supergroup', 'channel'],
                    'allowed_user_ids': '',
                    'auto_verify_media': False,
                    'auto_verify_groups': '',
                    'daily_cap': 200 if organization else 30,
                },
                'is_active': True,
                'last_error_message': '',
            },
        )
        base = settings.CONNECTORS_PUBLIC_BASE_URL.rstrip('/')
        wh_url = f'{base}/api/connectors/webhook/telegram/?bot={install.pk}'
        tg_bot.set_webhook(str(token), url=wh_url, secret_token=wh_secret)
        self._sync_own_bot_profile(str(token))
        return install
