# Bitcheck backend changelog

Living doc: append a dated section when adding or changing API or account/org behavior.

## 2026-05-12 — Image verification, webhook fixes, sandbox tooling, bit economy changes

### Added

- **Direct Image Verification**
  - `POST /api/verifications/verify/image/` — accepts `multipart/form-data` image upload
  - New `image_service.py` — validates file, computes SHA256, forwards to ML service's `/verify/image`, maps full response (model_result, forensics, provenance, explainability, trust), debits 2 bits
  - `label` field for user/data identifiers — track which user, file, or entity each verification belongs to
  - Options: `run_explainability`, `run_ocr`, `run_c2pa`, `threshold`
  - Synchronous (inline) — returns full result immediately, no polling needed

- **Sandbox VA Payment Simulation**
  - `POST /api/bits/virtual-account/simulate-payment/` — proxies to Squad's sandbox simulate endpoint
  - Auto-fills VA account number from org record, only requires `amount`
  - Only available when `SQUAD_BASE_URL` contains "sandbox"

- **Verbose Webhook Logging**
  - `print()` statements throughout `views.py` and `services.py` with `[WEBHOOK]`, `[SIGNATURE]`, `[CHARGE]`, `[VA]`, `[SIMULATE]` prefixes
  - Logs full payload, signature verification steps, subscription lookup, and processing result

### Fixed

- **Webhook HMAC signature comparison** — Squad sends uppercase hex, Python computes lowercase. Added `.lower()` before `hmac.compare_digest()`. This was the root cause of all webhook 401 failures.

### Changed

- **B2C bit economy — reset-and-grant on upgrade + renewal:**
  - **Upgrade (free → pro):** Wallet is reset to 0 (removes the 3 free bits), then 50 Pro bits are granted. Users no longer keep free bits after upgrading.
  - **Monthly renewal:** Wallet is reset to 0 (unused bits forfeited), then 50 fresh Pro bits are granted. Use-it-or-lose-it.
  - **Reactivation (past_due → active):** Same reset-and-grant behavior.
  - Free plan 3 bits are now a **one-time allotment** at signup. No monthly renewal for free users.
  - All three cases use `reset_and_grant()` which writes two ledger entries: `period_reset` + `subscription_grant`.

- **Admin theme** — now supports both light and dark modes via CSS custom properties + Django's `data-theme` attribute.
- **Webhook processing** — confirmed inline (synchronous) mode as the production pattern.

---

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

- **Connectors base architecture**
  - Plugin-based adapter system for Gmail, Slack, Telegram integrations
  - Models: `ConnectorType`, `ConnectorInstall`, `ConnectorEvent`, `ConnectorMessage`, `ConnectorTypeInterest`

### Fixed

- **CSRF on webhooks** — ensured `CsrfExemptSessionAuthentication` on Squad webhook endpoint to prevent 403s during payment callbacks

### Changed

- **Structured logging** — `core/middleware.py` now logs all HTTP requests as JSON with request_id, user, duration, status
