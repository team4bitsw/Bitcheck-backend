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

## 2026-05-11 — Neon PostgreSQL via `DATABASE_URL`

- **`DATABASE_URL`** in `.env` (gitignored) points Django at Neon instead of the default SQLite fallback.
- **`.env.example`** documents Neon / pooled URLs and notes `sslmode=require`. Separate `DB_NAME` / `DB_HOST` keys were removed from the template because `config/settings.py` only uses `dj-database-url` + `DATABASE_URL`.
