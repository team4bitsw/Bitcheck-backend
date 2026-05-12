# Bitcheck backend changelog

Living doc: append a dated section when adding or changing API or account/org behavior.

## 2026-05-11 — B2C Pro upgrade, B2B top-ups, connectors, CSRF fix, logging

### Added

- **B2C Pro Upgrade (Card Tokenization)**
  - `POST /api/billing/subscription/upgrade/` — initiates Squad checkout with `is_recurring: true`, returns `checkout_url`
  - `POST /api/billing/subscription/cancel/` — sets `cancel_at_period_end`, revokes Squad card token
  - `billing/services.py` — `initiate_pro_checkout()`, `charge_card_recurring()`, `cancel_card_token()`
  - Webhook handler `_handle_subscription_charge()` stores `squad_card_token_id` on the Subscription for future recurring charges
  - Dev mock: `SQUAD_CHECKOUT_DEV_MOCK=True` skips Squad API and returns a mock checkout URL

- **B2B Virtual Account Provisioning & Top-Ups**
  - `POST /api/bits/virtual-account/provision/` — creates a Squad bank account for the org
  - `GET /api/bits/virtual-account/` — returns VA bank details
  - `GET /api/bits/wallet/` — org wallet balance + top-up history
  - `bits/va_services.py` — `provision_virtual_account()`, `get_virtual_account_info()`
  - Webhook handler `_handle_virtual_account_credit()` — converts naira bank transfers to bits (push-based, not polling)
  - Dev mock: `SQUAD_VA_DEV_MOCK=True` creates a local VA row without calling Squad

- **Organization description field**
  - Added `Organization.description` (TextField) — set during B2B registration or via `setup-org`

- **B2B Registration in one step**
  - `POST /api/auth/register/` with `account_type: "business"` now also accepts `organization_name` (required) and `organization_description` (optional)
  - Creates User + Organization + admin Membership in one transaction

- **`POST /api/auth/setup-org/`** (session auth required)
  - For existing individual users who want to create an org after signup
  - Body: `{ "organization_name": string, "organization_description"?: string }`
  - Creates Organization, admin Membership, sets `User.account_type` to `business`

- **Connectors app** (`apps.connectors`)
  - Plugin-based architecture for third-party integrations (Gmail, Slack, Telegram, etc.)
  - Models: `ConnectorType`, `ConnectorInstall`, `ConnectorEvent`, `ConnectorMessage`, `ConnectorTypeInterest`
  - Gmail OAuth adapter: `apps/connectors/adapters/gmail/`
  - Endpoints under `POST /api/connectors/webhook/<slug>/`, `GET /api/connectors/types/`, install CRUD at `/api/connectors/installs/`
  - OAuth callback: `GET /api/connectors/oauth/<slug>/callback/`
  - Rate limiting per install and per type
  - Encrypted credential storage via `EncryptedJSONField`

- **Structured app logging** (`apps.core`)
  - JSON-line logger singleton: `apps/core/logger.py`
  - `RequestLoggingMiddleware` — logs method, path, status, duration, request_id
  - Env vars: `APP_LOG_LEVEL`, `APP_LOG_HTTP_BODIES`, `APP_LOG_RESPONSE_BODY`, `APP_LOG_MAX_BODY`

- **CSRF exemption**
  - `CsrfExemptSessionAuthentication` in `apps/accounts/authentication.py`
  - Replaced DRF's default `SessionAuthentication` which enforced CSRF on every request (broke Postman/mobile)
  - Protection via `SameSite=Lax` cookies + CORS whitelist instead

- **Swagger / ReDoc**
  - `/api/docs/` (Swagger UI), `/api/redoc/` (ReDoc), `/api/schema/` (OpenAPI JSON)

### Changed

- **`account_type` renamed:** `"organization"` → `"business"` (Django model enum). Frontend must send `"business"` for B2B signups.
- **Session/CSRF cookies** now configurable via env vars: `SESSION_COOKIE_SAMESITE`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SAMESITE`, `CSRF_COOKIE_SECURE`
- **`_env_truthy()` helper** added to settings for parsing boolean env vars consistently
- **`.env` loading** now uses explicit path (`BASE_DIR / '.env'`) instead of relying on cwd

### New environment variables

| Variable | Purpose |
|---|---|
| `SQUAD_VA_DEV_MOCK` | Skip Squad VA API in dev |
| `SQUAD_CHECKOUT_DEV_MOCK` | Skip Squad checkout API in dev |
| `CONNECTOR_CREDENTIALS_KEY` | Fernet key for encrypting connector credentials |
| `CONNECTORS_PUBLIC_BASE_URL` | Public URL for OAuth callbacks |
| `CONNECTORS_OAUTH_STATE_SECRET` | HMAC secret for OAuth state tokens |
| `GOOGLE_OAUTH_CLIENT_ID` | Google OAuth for Gmail connector |
| `GOOGLE_OAUTH_CLIENT_SECRET` | Google OAuth for Gmail connector |
| `GOOGLE_OAUTH_REDIRECT_URI` | Gmail OAuth callback URL |
| `APP_LOG_LEVEL` | Override log level |
| `APP_LOG_HTTP_BODIES` | Log request/response body previews |
| `SESSION_COOKIE_SAMESITE` | Cookie SameSite policy (default: Lax) |
| `SESSION_COOKIE_SECURE` | Require HTTPS for session cookie (default: False) |

### New dependencies

- `PyJWT` — JWT handling for connector OAuth
- `google-auth-oauthlib` — Google OAuth flow for Gmail connector
- `google-api-python-client` — Gmail API access

## 2026-05-11 — Neon PostgreSQL via `DATABASE_URL`

- **`DATABASE_URL`** in `.env` (gitignored) points Django at Neon instead of the default SQLite fallback.
- **`.env.example`** documents Neon / pooled URLs and notes `sslmode=require`. Separate `DB_*` keys are not used by `settings.py` (only `dj-database-url` + `DATABASE_URL`).
