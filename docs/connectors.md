# Connectors -- Platform Integration Layer

Connectors let users pipe external content (Telegram messages, Gmail attachments, etc.) into the Bitcheck verification pipeline automatically. Instead of manually uploading files through the dashboard or API, a user installs a connector once and all incoming content is verified in real time, with results delivered back to the source platform.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Data Model](#2-data-model)
3. [Adapter Contract](#3-adapter-contract)
4. [Event Pipeline](#4-event-pipeline)
5. [Adapters](#5-adapters)
   - [Telegram](#51-telegram)
   - [Gmail](#52-gmail)
   - [Echo (test harness)](#53-echo-test-harness)
6. [Security](#6-security)
7. [Rate Limiting](#7-rate-limiting)
8. [API Endpoints](#8-api-endpoints)
9. [Management Commands](#9-management-commands)
10. [Environment Variables](#10-environment-variables)
11. [Adding a New Connector](#11-adding-a-new-connector)

---

## 1. Architecture Overview

```
External platform (Telegram, Gmail, ...)
         |  webhook POST
         v
ConnectorWebhookView
  1. Resolve adapter by slug
  2. Rate-limit check (per-type + per-install)
  3. Verify webhook signature
  4. adapter.parse_event() -> (InstallContext, ParsedEvent)
  5. Idempotent event creation (ConnectorEvent)
  6. adapter.acknowledge_event() -> immediate reply (e.g. "Checking...")
         |
         v  (daemon thread -- no Celery required)
process_event_inline(event_id)
  1. Load ConnectorEvent + adapter
  2. adapter.extract_content() -> [VerifiableContent, ...]
  3. For each content item:
     a. Enforce quota (check owner wallet balance)
     b. Create Verification + VerificationJob
     c. Call ML service (image or text)
     d. complete_verification() -> debit wallet, store results
  4. adapter.send_result() -> reply on source platform
  5. Mark ConnectorEvent as processed
```

The entire flow runs **without Celery workers**. The webhook HTTP response (`{"status": "queued"}`) is returned immediately; the pipeline runs in a background daemon thread. This gives sub-second acknowledgment while keeping the deployment simple (no worker process, no broker dependency).

---

## 2. Data Model

All tables are in `apps/connectors/models.py`.

### ConnectorType

The catalogue of available connector kinds. Seeded by migrations.

| Field | Description |
|---|---|
| `slug` | Unique identifier (`telegram`, `gmail`, `echo`) |
| `name` | Display name |
| `category` | `email`, `chat`, `social`, `productivity`, `browser`, `other` |
| `status` | `coming_soon`, `alpha`, `beta`, `ga` |
| `auth_type` | `oauth2`, `bot_token`, `webhook_signature`, `api_key`, `telegram_shared`, `telegram_dual` |
| `supports_b2c` / `supports_b2b` | Visibility filters for account types |
| `supports_auto_verify` | Whether the connector can auto-verify without explicit user action |
| `settings_schema` | JSON schema describing per-install configurable settings |

### ConnectorInstall

One per external account linked by a user or org. XOR ownership: exactly one of `user` or `organization`.

| Field | Description |
|---|---|
| `type` | FK to ConnectorType |
| `user` / `organization` | XOR ownership (DB constraint: `connector_install_xor_owner`) |
| `external_account_id` | Platform-specific ID (e.g. `shared:12345` for Telegram, `user@gmail.com` for Gmail) |
| `credentials` | **Fernet-encrypted** JSON blob (tokens, secrets) -- never stored in plaintext |
| `settings` | User-configurable JSON (daily cap, allowed chat types, auto-verify toggle, etc.) |
| `is_active` | Soft-delete flag |
| `last_event_at` / `last_error_at` | Monitoring timestamps |

**Unique constraint:** `(type, external_account_id)` -- prevents duplicate installs for the same external account.

### ConnectorEvent

One row per inbound webhook. Idempotent on `(install, external_event_id)`.

| Field | Description |
|---|---|
| `install` | FK to ConnectorInstall |
| `external_event_id` | Upstream event identifier (e.g. Telegram `update_id`) |
| `event_type` | e.g. `telegram_message`, `gmail_message` |
| `raw_payload` | Full JSON payload for debugging |
| `status` | `received` -> `processing` -> `processed` / `ignored` / `failed` |
| `verifications` | M2M link to Verification records created from this event |

### ConnectorMessage

Outbound delivery audit trail (e.g. the Telegram reply or Gmail email sent back with results).

| Field | Description |
|---|---|
| `install` | FK to ConnectorInstall |
| `event` | FK to the triggering ConnectorEvent |
| `verification` | FK to the Verification result being delivered |
| `direction` | Always `outbound` |
| `kind` | e.g. `telegram_reply`, `email_reply` |
| `status` | `pending` -> `sent` / `failed` / `retrying` |
| `attempts` | Delivery retry count |

### TelegramLinkCode

One-time deep-link codes for the shared Telegram bot's `/start` flow.

| Field | Description |
|---|---|
| `code` | URL-safe random string (48 chars max) |
| `user` | Who requested the link |
| `organization` | Optional -- links to org if B2B |
| `expires_at` | 30-minute TTL |
| `used_at` | Set when the code is claimed by a `/start` in Telegram |

### ConnectorTypeInterest

Demand capture for coming-soon tiles. Users click "Notify me" on connector types that aren't live yet. Unique per `(connector_type, user)`.

---

## 3. Adapter Contract

Every connector implements `ConnectorAdapter` (defined in `base.py`). The base class defines:

```python
class ConnectorAdapter(ABC):
    slug: str

    def verify_webhook(request) -> bool
    def parse_event(request) -> (InstallContext, ParsedEvent)
    def extract_content(ctx, event) -> Iterable[VerifiableContent]
    def send_result(ctx, event, verification) -> dict
    def begin_install(user, organization?, options?) -> dict
    def complete_install(user, payload, organization?) -> ConnectorInstall
    def refresh_credentials(install) -> None          # default: no-op
    def acknowledge_event(ctx, event) -> None          # default: no-op
```

### Typed payloads

| Dataclass | Purpose |
|---|---|
| `VerifiableContent` | Normalized input: `kind` (text/image/document/audio/video), `payload` (str or bytes), optional `filename`, `mime_type`, `source_locator` |
| `InstallContext` | Resolved install with decrypted credentials + settings |
| `ParsedEvent` | Normalized event: `external_event_id`, `event_type`, `raw_payload` |

### Adapter registry

Adapters register via the `@register` decorator (in `registry.py`):

```python
@register
class TelegramAdapter(ConnectorAdapter):
    slug = 'telegram'
    ...
```

At runtime: `get_adapter('telegram')` returns a fresh `TelegramAdapter()` instance.

---

## 4. Event Pipeline

The pipeline (`pipeline.py`) runs in `process_event_inline(event_id)`:

```
1. Load ConnectorEvent + ConnectorInstall
2. Get adapter via registry
3. Build InstallContext (decrypt credentials)
4. Reconstruct ParsedEvent from stored raw_payload
5. adapter.extract_content(ctx, event)
   -> yields VerifiableContent items (files, text)
6. For each content item:
   a. Determine modality (image/text/document/audio/video)
   b. Check balance: _enforce_quota(install, cost)
   c. Create Verification + VerificationJob rows
   d. Call ML service:
      - image: POST to ML_IMAGE_SERVICE_BASE_URL/verify/image (multipart)
      - text:  POST to ML_TEXT_SERVICE_BASE_URL/verify/text (JSON)
      - other: mock result (until more ML endpoints are available)
   e. complete_verification() -> debit wallet, store trust_score + results
7. adapter.send_result(ctx, event, verification)
   -> deliver result on source platform
8. Record ConnectorMessage (outbound audit)
9. Mark ConnectorEvent.status = 'processed'
```

**Wallet routing:** The pipeline uses the install's owner to determine which wallet to debit:
- `install.user_id` set -> `get_wallet_for_user(install.user)` (B2C)
- `install.organization_id` set -> `get_wallet_for_organization(install.organization)` (B2B)

**Error handling:** If the ML call or wallet debit fails, the verification is marked `failed` and the event status is set to `failed` with the error message stored.

---

## 5. Adapters

### 5.1 Telegram

**Slug:** `telegram`
**Auth type:** `telegram_dual` (shared bot or own bot)
**Files:** `adapters/telegram/adapter.py`, `bot.py`, `files.py`, `formatting.py`, `link.py`

#### Two connection modes

| Mode | How it works | Webhook URL |
|---|---|---|
| **Shared bot** | Users link via deep-link code (`/start <code>` in `@BitcheckBot`). No bot token needed from user. | `/api/connectors/webhook/telegram/?bot=shared` |
| **Own bot** | User creates a bot via BotFather, pastes the token. Bitcheck registers the webhook on their bot. | `/api/connectors/webhook/telegram/?bot=<install_uuid>` |

#### Supported content types

| Telegram type | Bitcheck modality |
|---|---|
| Photo | `image` |
| Document (PDF, etc.) | `document` |
| Video | `video` |
| Audio | `audio` |
| Voice message | `audio` |
| Video note (circle) | `video` |
| Sticker | `image` |
| Text / forwarded text | `text` |

#### Bot commands

| Command | Behavior |
|---|---|
| `/start` | Welcome + onboarding. With link code: completes linking. |
| `/start <code>` | Claims a shared-bot link code and creates the install. |
| `/help` | Shows usage instructions. |
| `/verify` (reply in group) | Verifies the replied-to message. |

#### Group behavior

- **Private chats:** Send content directly, no command needed.
- **Groups/supergroups:** Reply to a message with `/verify` to verify it.
- **Own-bot auto-verify:** When `auto_verify_media` is enabled in install settings, the bot automatically verifies all media posted in the group (no command needed). Admins can mute this per-group via an inline button.

#### Install settings

| Key | Type | Default | Description |
|---|---|---|---|
| `group_result_visibility` | string | `public` | `public` (reply in group), `private` (DM to requester), `silent` (DM, no group notification) |
| `allowed_chat_types` | list | `[private, group, supergroup, channel]` | Which chat types to respond in |
| `allowed_user_ids` | string | `""` (all) | CSV of Telegram user IDs allowed to use the bot |
| `auto_verify_media` | bool | `false` | Own-bot only: auto-verify all media without `/verify` |
| `auto_verify_groups` | string | `""` | CSV of group IDs where auto-verify is active (empty = all) |
| `auto_verify_muted_groups` | list | `[]` | Groups where auto-verify was muted by an admin |
| `daily_cap` | int | `100` (shared) / `200` (own) | Max events per day per install |

#### Rate limits

- Per-chat: 30 events/minute (cache-based)
- Per-user on shared bot: 100 events/day
- Daily cap per install: configurable (default 100)

#### Result formatting

Results are sent as HTML messages using `formatting.py`. For image verifications, the headline score is the model confidence (0-100), not the composite trust score -- this matches the consumer app's `ResultExplainer` component. Every result includes a "Open full report" deep-link to the web dashboard.

---

### 5.2 Gmail

**Slug:** `gmail`
**Auth type:** `oauth2`
**Files:** `adapters/gmail/adapter.py`, `gmail_api.py`, `oauth.py`

#### Connection flow

```
1. Frontend: POST /api/connectors/install/gmail/begin/
   -> returns { redirect_url: "https://accounts.google.com/o/oauth2/..." }
2. Frontend: opens OAuth popup
3. Google redirects to /api/connectors/oauth/gmail/callback/?code=...&state=...
4. Backend: exchanges code for tokens
5. Backend: creates ConnectorInstall with encrypted credentials
6. Backend: registers Gmail Pub/Sub push notifications (watch)
7. Frontend: popup closes, postMessage('ok') to opener
```

#### How email monitoring works

Gmail uses Google Cloud Pub/Sub push notifications:

1. When the install is created, `gmail_api.register_watch()` subscribes to inbox changes.
2. Google sends a push to `POST /api/connectors/webhook/gmail/?token=<GMAIL_PUBSUB_PUSH_TOKEN>`.
3. The adapter decodes the Pub/Sub notification, extracts the `historyId`.
4. `gmail_api.get_history()` fetches new messages since the last known `historyId`.
5. For each new message, attachments are downloaded and piped through the verification pipeline.
6. Results are sent back as an email reply in the same thread.

#### Attachment filtering

| Setting | Default | Description |
|---|---|---|
| `auto_verify` | `true` | Whether to process incoming emails |
| `attachment_kinds` | `[image, document]` | Which attachment types to verify |
| `min_attachment_bytes` | `10000` | Ignore tiny attachments (signatures, logos) |
| `daily_cap` | `100` | Max emails processed per day |

#### Result delivery

Results are sent as a threaded email reply using `gmail_api.send_reply()`. The reply contains:
- Trust score with emoji indicator
- Verdict (authentic / suspicious / manipulated)
- AI detection result + confidence
- Provenance (C2PA)
- Risk flags
- "Open full report" button linking to the dashboard

#### Token refresh

Gmail access tokens expire after ~1 hour. `refresh_credentials()` uses the stored refresh token to obtain a new access token via Google's token endpoint.

---

### 5.3 Echo (test harness)

**Slug:** `echo`
**Auth type:** N/A (no signature verification)
**File:** `adapters/echo/adapter.py`

A no-op connector for development and testing. It accepts any JSON POST with `{id, text}`, runs the text through the verification pipeline, and logs the result without delivering it anywhere.

```bash
# Install the echo connector
curl -X POST http://localhost:8000/api/connectors/install/echo/begin/ \
  -H "Cookie: sessionid=..."

# Complete the install
curl -X POST http://localhost:8000/api/connectors/install/echo/complete/ \
  -H "Cookie: sessionid=..."

# Send a test event
curl -X POST http://localhost:8000/api/connectors/webhook/echo/ \
  -H "Content-Type: application/json" \
  -d '{"id": "test-1", "text": "Suspicious message to verify"}'
```

---

## 6. Security

### Credential encryption

All connector credentials (OAuth tokens, bot tokens, webhook secrets) are encrypted at rest using **Fernet symmetric encryption** (`crypto.py`).

- Credentials are stored as a `BinaryField` via `EncryptedJSONField`.
- Encryption key: `CONNECTOR_CREDENTIALS_KEY` (Fernet base64 key in env).
- On read: `from_db_value()` decrypts automatically.
- On write: `get_prep_value()` encrypts automatically.
- Invalid tokens (corruption, key rotation) gracefully return `{}`.

### Webhook verification

Each adapter implements `verify_webhook(request)`:

| Adapter | Method |
|---|---|
| Telegram (shared) | HMAC compare of `X-Telegram-Bot-Api-Secret-Token` header vs `TELEGRAM_SHARED_BOT_SECRET` |
| Telegram (own bot) | HMAC compare of header vs per-install `webhook_secret` stored in credentials |
| Gmail | Query parameter `?token=` compared to `GMAIL_PUBSUB_PUSH_TOKEN` |
| Echo | Always returns `True` (test only) |

### OAuth state integrity

Gmail OAuth uses HMAC-signed state tokens (`CONNECTORS_OAUTH_STATE_SECRET`) to prevent CSRF and session fixation during the install flow.

---

## 7. Rate Limiting

Rate limits are enforced at two levels using Redis/cache fixed-window counters (`rate_limit.py`):

| Level | Key pattern | Default | Window |
|---|---|---|---|
| **Per connector type** | `connectors:rl:type:{slug}` | 1000 req/min | 60s |
| **Per install** | `connectors:rl:install:{id}` | 60 req/min | 60s |

Rate limits fail open on cache errors (so webhooks aren't dropped in development without Redis).

Telegram adds additional per-chat and per-user rate limits on top of the system-wide ones.

---

## 8. API Endpoints

All mounted at `/api/connectors/`.

| Method | URL | Auth | Description |
|---|---|---|---|
| `POST` | `/webhook/<slug>/` | Webhook signature | Inbound webhook (platform-specific verification) |
| `GET` | `/types/` | Session | List available connector types (filtered by B2C/B2B) |
| `POST` | `/types/<slug>/interest/` | Session | Toggle "notify me" interest for coming-soon connectors |
| `GET` | `/installs/` | Session | List user's/org's active installs |
| `PATCH` | `/installs/<id>/` | Session + owner | Update install settings (e.g. daily cap, visibility) |
| `DELETE` | `/installs/<id>/` | Session + owner | Soft-deactivate an install (`is_active = false`) |
| `GET` | `/installs/<id>/events/` | Session + owner | Paginated event history for an install |
| `POST` | `/install/<slug>/begin/` | Session | Start the install flow (returns deep-link, redirect URL, or input requirements) |
| `GET` | `/install/telegram/poll/?code=` | Session | Poll shared-bot link status (for UI polling during onboarding) |
| `POST` | `/installs/<id>/telegram/reconfigure/` | Session + owner | Re-apply BotFather commands/description (own-bot only) |
| `GET` | `/oauth/<slug>/callback/` | Public (state-signed) | OAuth return URL (Google redirects here) |

---

## 9. Management Commands

| Command | Description |
|---|---|
| `python manage.py register_telegram_webhook` | Register/update the shared bot's webhook URL with Telegram |
| `python manage.py show_telegram_webhook` | Display the current webhook info for the shared bot |

---

## 10. Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `CONNECTOR_CREDENTIALS_KEY` | Yes (prod) | Dev fallback key | Fernet key for encrypting credential blobs |
| `CONNECTORS_PUBLIC_BASE_URL` | Yes (prod) | `http://localhost:8000` | Public URL for webhook endpoints |
| `CONNECTORS_OAUTH_STATE_SECRET` | No | `SECRET_KEY` | HMAC key for signing OAuth state tokens |
| `CONNECTORS_DEFAULT_RATE_LIMIT_PER_INSTALL` | No | `60` | Max events per install per minute |
| `CONNECTORS_DEFAULT_RATE_LIMIT_PER_TYPE` | No | `1000` | Max events per connector type per minute |
| `TELEGRAM_SHARED_BOT_TOKEN` | For Telegram | `""` | Shared bot token from BotFather |
| `TELEGRAM_SHARED_BOT_SECRET` | For Telegram | `""` | Webhook secret for shared bot |
| `TELEGRAM_SHARED_BOT_USERNAME` | For Telegram | `BitcheckBot` | Bot's @username (without @) |
| `GOOGLE_OAUTH_CLIENT_ID` | For Gmail | `""` | Google Cloud OAuth client ID |
| `GOOGLE_OAUTH_CLIENT_SECRET` | For Gmail | `""` | Google Cloud OAuth client secret |
| `GOOGLE_OAUTH_REDIRECT_URI` | For Gmail | `localhost` callback | OAuth redirect URI |
| `GMAIL_PUBSUB_TOPIC` | For Gmail | `""` | Google Cloud Pub/Sub topic for Gmail push |
| `GMAIL_PUBSUB_PUSH_TOKEN` | For Gmail | `""` | Secret token for Pub/Sub push verification |
| `FRONTEND_APP_BASE_URL` | No | `http://localhost:3000` | Base URL for deep-links in result messages |

---

## 11. Adding a New Connector

1. **Create the adapter directory:**
   ```
   apps/connectors/adapters/your_platform/
       __init__.py
       adapter.py
   ```

2. **Implement the adapter:**
   ```python
   from apps.connectors.base import ConnectorAdapter, ...
   from apps.connectors.registry import register

   @register
   class YourAdapter(ConnectorAdapter):
       slug = 'your_platform'

       def verify_webhook(self, request): ...
       def parse_event(self, request): ...
       def extract_content(self, ctx, event): ...
       def send_result(self, ctx, event, verification): ...
       def begin_install(self, user, *, organization=None, options=None): ...
       def complete_install(self, user, payload, *, organization=None): ...
   ```

3. **Register the import** in `adapters/__init__.py`:
   ```python
   from . import your_platform  # noqa: F401
   ```

4. **Seed the ConnectorType** via a data migration or the admin panel:
   ```python
   ConnectorType.objects.create(
       slug='your_platform',
       name='Your Platform',
       category='chat',
       status='alpha',
       auth_type='bot_token',
   )
   ```

5. **Test with the echo pattern** -- the echo adapter is a minimal reference implementation that exercises the full pipeline without external dependencies.

---

## File Map

```
apps/connectors/
    base.py              Adapter contract (ABC) + typed payloads
    registry.py          slug -> adapter class lookup
    models.py            ConnectorType, Install, Event, Message, TelegramLinkCode, Interest
    crypto.py            EncryptedJSONField (Fernet)
    pipeline.py          Inline event -> verify -> reply pipeline (no Celery)
    exceptions.py        ConnectorError, AuthExpired, RateLimited, InvalidPayload, QuotaExceeded, CommandHandled
    rate_limit.py        Fixed-window Redis/cache rate limits
    views.py             Webhook view + DRF REST endpoints
    urls.py              URL routing
    serializers.py       DRF serializers for API responses
    permissions.py       IsConnectorInstallOwner permission
    signals.py           Django signals
    tasks.py             Celery task wrappers (optional, not used by default)
    admin.py             Django admin registration
    adapters/
        echo/adapter.py          Test harness (no external deps)
        telegram/
            adapter.py           Full Telegram adapter (shared + own bot)
            bot.py               Telegram Bot API client (raw HTTP)
            files.py             File download helper
            formatting.py        HTML formatting for result messages
            link.py              One-time link codes for shared bot
        gmail/
            adapter.py           Full Gmail adapter (OAuth + Pub/Sub)
            gmail_api.py         Gmail API client (messages, attachments, watch, reply)
            oauth.py             OAuth2 code exchange + state signing
    management/commands/
        register_telegram_webhook.py
        show_telegram_webhook.py
```
