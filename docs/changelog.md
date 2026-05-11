# Bitcheck backend changelog

Living doc: append a dated section when adding or changing API or account/org behavior.

## 2026-05-11 — Org setup for existing personal users

### Added

- **`POST /api/auth/setup-org/`** (session auth required)
  - **Body:** `{ "organization_name": string, "organization_description"?: string }`
  - **Success (201):** `{ "detail", "organization": OrganizationSerializer shape, "user": UserSerializer shape }`
  - **Errors:** `400` if user already has any `Membership`; validation errors on missing/blank name
  - **Effect:** Creates `Organization`, admin `Membership`, sets `User.account_type` to `business`

### Fixed (coordinate with frontend)

- **Business registration:** Django expects `account_type: "business"` (not `"organization"`). Frontend signup was updated to match and to send `organization_name` / `organization_description` on business signup.

### Files touched

- `apps/accounts/serializers.py` — `SetupOrgSerializer`
- `apps/accounts/views.py` — `setup_org_view`
- `apps/accounts/urls.py` — `setup-org/`

## 2026-05-11 — Structured app logging (singleton + HTTP middleware)

### Added

- **`apps.core`** — `logger` singleton ([`apps/core/logger.py`](apps/core/logger.py)): JSON lines on stdout, namespaces via `logger.child("area")`, `debug` / `info` / `warning` / `error` / `exception`, redacted `meta` via `safe_meta`.
- **`RequestLoggingMiddleware`** — logs `http_request_complete` with `request_id`, method, path, status, `duration_ms`, optional user id, optional body previews (see env below).
- **Cursor rule** [`.cursor/rules/app-logger.mdc`](.cursor/rules/app-logger.mdc) — agents must use the shared logger on new backend work.

### Env (see `.env.example`)

- `APP_LOG_LEVEL` — optional override.
- `APP_LOG_HTTP_BODIES` — `1` to log truncated request/response previews; defaults on when `DEBUG` is true in env, else off.
- `APP_LOG_RESPONSE_BODY` — `1` to log response previews for success paths too (when bodies logging is on).
- `APP_LOG_MAX_BODY` — max chars per body preview (default 4096).

### Files touched

- `apps/core/` (new), `config/settings.py` — `INSTALLED_APPS`, `MIDDLEWARE`
- `apps/accounts/views.py` — example migration to `logger.child('accounts')`

## 2026-05-11 — Neon PostgreSQL via `DATABASE_URL`

- **`DATABASE_URL`** in `.env` (gitignored) points Django at Neon instead of the default SQLite fallback.
- **`.env.example`** documents Neon / pooled URLs and notes `sslmode=require`. Separate `DB_*` keys are not used by `settings.py` (only `dj-database-url` + `DATABASE_URL`).

