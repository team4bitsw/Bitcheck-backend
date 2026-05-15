# Bitcheck AI — System Documentation

> **Last verified:** 2026-05-11. This explains every part of the backend.
---

## Table of Contents

1. [Project Structure](#1-project-structure)
2. [How DRF Works (Request Lifecycle)](#2-how-drf-works-the-request-lifecycle)
3. [App-by-App Breakdown](#3-app-by-app-breakdown)
4. [The Token Economy](#4-the-token-economy)
5. [Squad Payment Integration (Deep Dive)](#5-squad-payment-integration-deep-dive)
6. [Background Tasks (Celery)](#6-background-tasks-celery)
7. [Security Decisions](#7-security-decisions)
8. [Infrastructure & Deployment](#8-infrastructure--deployment)
9. [Common Questions](#9-common-questions)

---

## 1. Project Structure

Django organizes code into **apps** — self-contained modules that each own a domain. We have 9 apps inside `apps/`.

Every app follows the same file pattern:

| File | Purpose |
|---|---|
| `models.py` | Database tables (each class = one table) |
| `views.py` | Request handlers (each function = one endpoint) |
| `serializers.py` | Converts Python objects ↔ JSON |
| `urls.py` | Maps URLs to views |
| `services.py` | Business logic (keeps views thin) |
| `tasks.py` | Celery background jobs |
| `signals.py` | Auto-triggered actions (e.g., "when a user is created, do X") |

```
HACKATON/
├── config/                  # Project-wide configuration
│   ├── settings.py          # All settings (DB, auth, CORS, Celery, Squad, etc.)
│   ├── urls.py              # Root URL router — connects all app URLs
│   ├── celery.py            # Celery worker configuration
│   └── wsgi.py / asgi.py    # Entry points for web servers
│
├── apps/
│   ├── core/                # Structured JSON logger + HTTP request logging middleware
│   ├── accounts/            # Users, organizations, login/register
│   ├── billing/             # Plans, subscriptions, Squad card tokenization (B2C)
│   ├── bits/                # Token wallets, ledger, virtual accounts, top-ups (B2B)
│   ├── api_keys/            # B2B API key management
│   ├── connectors/          # Third-party integrations (Gmail, Slack, etc.)
│   ├── verifications/       # Core domain — file uploads, ML verification, direct image analysis
│   ├── usage/               # B2B API call logging
│   └── webhooks/            # External event processing (Squad payments)
│
├── docs/                    # Documentation + Squad API reference
├── Dockerfile               # Production container (Cloud Run)
├── .env                     # Environment variables (gitignored)
└── requirements.txt         # Python dependencies
```

**Key config files:**
- `settings.py` — Database (`DATABASE_URL`), middleware (whitenoise, CORS), Celery beat schedules, Squad credentials, bit economy rates
- `Dockerfile` — Multi-stage build that runs `collectstatic` at build time for Cloud Run

---

## 2. How DRF Works (The Request Lifecycle)

When a frontend sends `POST /api/auth/login/`:

```
1. Browser sends HTTP request
        ↓
2. Middleware: CORS → Whitenoise (static) → Session loading → Request logging
        ↓
3. URL router: config/urls.py → "api/auth/" → apps/accounts/urls.py → "login/"
        ↓
4. DRF: SessionAuthentication reads cookie, AllowAny = anyone can access
        ↓
5. View function: validate input → authenticate → create session → return JSON
        ↓
6. Middleware: set cookies, CORS headers
        ↓
7. Browser receives JSON + session cookie
```

**Key DRF concepts:**
- **Serializers** validate incoming JSON and serialize outgoing model data
- **Views** are functions decorated with `@api_view(['GET'])` that return `Response(...)`
- **Permission classes**: `AllowAny` (public) or `IsAuthenticated` (must have session cookie or API key)
- **Dual authentication** (configured in `DEFAULT_AUTHENTICATION_CLASSES`):
  1. `ApiKeyOrSessionAuthentication` — tries `Authorization: Bearer bk_...` first (B2B), falls back to session cookie (B2C)
  2. `CsrfExemptSessionAuthentication` — session-only fallback
- **B2B requests** (`request.auth` is an `ApiKey`): verification ownership → organization, wallet debit → org wallet, `ApiCall` usage record logged
- **B2C requests** (`request.auth` is not an `ApiKey`): verification ownership → user, wallet debit → personal wallet

---

## 3. App-by-App Breakdown

### 3.1 `accounts` — Identity & Access

**Models:** `User` (email-based, UUID PK), `Organization` (B2B entity with `name`, `description`, and unique `slug`), `Membership` (links users → orgs with roles: admin/member/viewer)

**Key decisions:**
- Custom `User` model with email (not username) — set via `AUTH_USER_MODEL = 'accounts.User'` before first migration
- Custom `EmailBackend` in `backends.py` for email-based login
- `CsrfExemptSessionAuthentication` in `authentication.py` — skips DRF's CSRF enforcement (protection via `SameSite=Lax` cookies + CORS instead)
- Google OAuth: frontend handles popup, backend just verifies `id_token` with Google's API
- `account_type` uses `"business"` (not `"organization"`) — this is a UX hint, NOT a security boundary

**B2B Registration:** When `account_type='business'` is sent to `POST /api/auth/register/`, the serializer also accepts `organization_name` (required) and `organization_description` (optional). It creates the User, Organization, and admin Membership in one transaction.

**Existing User Org Setup:** `POST /api/auth/setup-org/` lets an existing individual user create an organization after signup. Takes `organization_name` and optional `organization_description`, creates the org + admin membership, and updates `account_type` to `business`.

**Password Reset (token-based):**
- `POST /api/auth/forgot-password/` — accepts `{ "email" }`, generates a time-limited token via Django's `PasswordResetTokenGenerator`. Always returns 200 (anti-enumeration). In DEBUG mode, returns `uid` + `token` + `reset_url` in the response for dev testing; in production, would send an email.
- `POST /api/auth/reset-password/` — accepts `{ "uid", "token", "new_password" }`, validates the token, sets the new password. Tokens are cryptographic (HMAC-SHA256 over user PK + password hash + timestamp), single-use (invalidated when password changes), and expire per `PASSWORD_RESET_TIMEOUT` (default 3 days).
- The `reset_url` points to `{FRONTEND_APP_BASE_URL}/reset-password?uid=...&token=...` — the frontend reads query params and POSTs to the reset endpoint.

**Auto-provisioning signal (`billing/signals.py`):** When a user is created (any method), `post_save` automatically creates a TokenWallet, a free Subscription, and credits 3 initial bits.

### 3.2 `billing` — Plans & Subscriptions (B2C)

**Models:**
- `Plan` — Static catalog (`free`/`pro`), seeded via data migration. Never user-created.
- `Subscription` — Links user → plan with billing period. Has Squad fields: `squad_subscription_id`, `squad_customer_id`, `squad_card_token_id`

**Endpoints:**
| Method | URL | Purpose |
|---|---|---|
| `GET` | `/api/billing/plans/` | List plans (public) |
| `GET` | `/api/billing/subscription/` | Current subscription + wallet |
| `POST` | `/api/billing/subscription/upgrade/` | Initiate Pro checkout via Squad |
| `POST` | `/api/billing/subscription/cancel/` | Cancel at period end |

**Pro Upgrade Flow (Card Tokenization):** See [Section 5.1](#51-b2c-card-tokenization-pro-upgrade) for the full Squad integration.

### 3.3 `bits` — The Financial Core (The Bank)

**Models:**
- `TokenWallet` — One per user (B2C) or org (B2B). `balance_bits` with `CHECK >= 0` constraint. XOR ownership enforced at DB level.
- `TokenLedgerEntry` — Append-only audit trail. Every credit/debit = one row. You can reconstruct balance at any point by summing deltas.
- `VirtualAccount` — 1:1 with Organization. A permanent Squad bank account number for B2B top-ups.
- `TopUp` — Records bank transfer → bits conversion. `squad_transaction_reference` is unique for idempotency.

**Critical code — `services.py`:**
```python
def debit_wallet(wallet_id, amount, ...):
    with transaction.atomic():                     # DB transaction
        wallet = TokenWallet.objects
                 .select_for_update()              # Row lock (prevents races)
                 .get(pk=wallet_id)
        if wallet.balance_bits < amount:           # Check balance
            raise InsufficientBits(...)
        wallet.balance_bits -= amount              # Debit
        wallet.save()
        TokenLedgerEntry.objects.create(...)        # Audit trail
```

**Why `select_for_update()`?** Pessimistic locking. If two requests try to debit simultaneously, one waits. Without it, both could read `balance=10`, both debit 8 → balance goes to `-6`.

**Endpoints:**
| Method | URL | Purpose |
|---|---|---|
| `POST` | `/api/bits/virtual-account/provision/` | Create Squad VA for org (admin only) |
| `GET` | `/api/bits/virtual-account/` | Get org's VA bank details |
| `GET` | `/api/bits/wallet/` | Org wallet balance + top-up history |

### 3.4 `api_keys` — B2B API Key Management

**Security model:** Generate random secret (`bk_live_a8f3...`) → hash with SHA-256 + server pepper → store ONLY hash → return raw secret once → authenticate by prefix lookup + constant-time hash comparison.

### 3.5 `verifications` — Core Domain

**Models:** `UploadedFile` (S3 reference), `Verification` (main entity), `VerificationJob` (ML task tracking), `ImageVerificationCache` (SHA-256 → ML result cache)

**Lifecycle:** `queued` → `analyzing` → `completed`|`failed`. Bits charged on completion only.

**Key files:**

| File | Purpose |
|---|---|
| `services.py` | `submit_b2c_verification()`, `submit_b2b_verification()`, `complete_verification()`, `fail_verification()` — orchestrates the full lifecycle |
| `image_service.py` | `verify_image_direct()` — direct image upload → hash cache check → ML image service → result |
| `text_service.py` | `verify_text_direct()` — direct text submission → ML text service → result |
| `document_service.py` | `verify_document_direct()` — direct document upload → ML document service → result (field extraction, forensics, QR, LLM analysis) |
| `mock_ml.py` | Mock image ML response when ML is down (`ML_MOCK_RESPONSE=True`) |
| `mock_text_ml.py` | Mock text ML response when ML is down (`ML_MOCK_RESPONSE=True`) |
| `tasks.py` | `process_verification` Celery task — async flow (not used for direct endpoints) |
| `views.py` | HTTP endpoints: `verify_image_view()`, `verify_text_view()`, `verify_document_view()`, list, delete |

**ML Services (both hosted on HF Spaces):**

| Service | Live URL | Endpoint | Input |
|---|---|---|---|
| **Image** | `https://jaykay73-bitcheck-image.hf.space` | `POST /verify/image` | `file` (multipart, required) + `user_email` (optional) |
| **Text** | `https://jaykay73-bitcheck-text.hf.space` | `POST /verify/text` | JSON: `text` + optional `source_url`, `context`, check flags |
| **Document** | `https://jaykay73-bitcheck-document.hf.space` | `POST /verify/document` | `file` (multipart) + `document_type`, `run_ocr`, `run_forensics`, `run_qr`, `run_live_qr_check`, `run_llm_analysis`, `max_pages` |

**Direct image flow (`image_service.py`) — with hash-based caching + B2B/B2C routing:**
```
POST /api/verifications/verify/image/  (multipart/form-data: file + optional label)
  Auth: Session cookie (B2C) OR Authorization: Bearer bk_... (B2B)
        ↓
verify_image_view():
  - Parse file + label
  - Detect auth type: request.auth is ApiKey → B2B, else → B2C
  - B2B: pass organization + api_key to service
  - B2C: pass user only
        ↓
verify_image_direct(user, image_file, label, organization?, api_key?):
  1. Validate file type (.jpg/.png/.webp) + size (≤12 MB)
  2. Pre-flight balance check:
     ├── B2B: get_wallet_for_organization(organization) — org wallet
     └── B2C: get_wallet_for_user(user) — personal wallet
  3. Compute SHA-256 hash (chunked 64KB reads, memory-safe)
  4. CACHE CHECK: look up hash in ImageVerificationCache
     ├── HIT:  return cached trust_score + result_summary instantly
     │         (still creates Verification + debits wallet)
     └── MISS: continue to ML service ↓
  5. Create Verification + VerificationJob rows (status=analyzing)
     ├── B2B: Verification.organization = org, api_key = key
     └── B2C: Verification.user = user
  6. If ML_MOCK_RESPONSE=True → return mock response (no HTTP call)
  7. Forward to ML: POST {ML_IMAGE_SERVICE_BASE_URL}/verify/image
     - Form data: user_email=user.email, file=image
  8. Map response: trust.score → trust_score, model_result.label → verdict
  9. Save (hash, trust_score, result_summary, ml_response_raw) → cache
 10. complete_verification() → debit correct wallet, store results
        ↓
  B2B only: log ApiCall (endpoint, modality, status, latency, bits_charged)
        ↓
Return full verification with ML analysis
```

**Cache behavior (`ImageVerificationCache` model):**
- Keyed by SHA-256 hex digest of file contents (unique, indexed)
- On cache hit: `result_summary._cached = true`, `result_summary._cache_hit_count = N`
- `hit_count` field tracks reuse frequency (incremented atomically)
- Cache entries include: `trust_score`, `result_summary`, `ml_response_raw`, `original_filename`
- Race condition safe: duplicate cache writes are silently ignored (unique constraint)

**Direct text flow (`text_service.py`) — with B2B/B2C routing:**
```
POST /api/verifications/verify/text/  (JSON: text + optional source_url, context, label)
  Auth: Session cookie (B2C) OR Authorization: Bearer bk_... (B2B)
        ↓
verify_text_view():
  - Parse text + options
  - Detect auth type: request.auth is ApiKey → B2B, else → B2C
  - B2B: pass organization + api_key to service
  - B2C: pass user only
        ↓
verify_text_direct(user, text_input, ..., organization?, api_key?):
  1. Validate text (5–8000 chars)
  2. Pre-flight balance check:
     ├── B2B: get_wallet_for_organization(organization) — org wallet
     └── B2C: get_wallet_for_user(user) — personal wallet
  3. Compute SHA256 hash of text
  4. Create Verification + VerificationJob rows (status=analyzing)
     ├── B2B: Verification.organization = org, api_key = key
     └── B2C: Verification.user = user
  5. If ML_MOCK_RESPONSE=True → return mock response (no HTTP call)
  6. Forward to ML: POST {ML_TEXT_SERVICE_BASE_URL}/verify/text
     - JSON: text, source_url, context, check_* flags
  7. Map response: trust.trust_score → trust_score, trust.decision → verdict
  8. complete_verification() → debit correct wallet, store results
        ↓
  B2B only: log ApiCall (endpoint, modality, status, latency, bits_charged)
        ↓
Return full verification with text analysis
```

**Image ML response field mapping:**

| ML field | Our field |
|---|---|
| `trust.score` (float, e.g., 72.5) | `trust_score` (int, e.g., 73) |
| `trust.label` (`low_risk`/`moderate_risk`/`high_risk`) | stored in `result_summary.trust.label` |
| `model_result.label` (`real`/`ai_generated`) | stored in `result_summary.model_result.label` |
| `model_result.confidence` (0–1) | stored in `result_summary.model_result.confidence` |

**Text ML response field mapping:**

| ML field | Our field |
|---|---|
| `trust.trust_score` (int, e.g., 15) | `trust_score` |
| `trust.risk_level` (`Very High Risk`/`High Risk`/`Suspicious`/`Low Risk`/`Likely Authentic`) | stored in `result_summary.trust.risk_level` |
| `trust.decision` (`approve`/`review`/`block_or_manual_review`) | stored in `result_summary.trust.decision` |
| `ai_likelihood.confidence` (0–1) | stored in `result_summary.ai_likelihood.confidence` |
| `risk_flags` (array of strings) | stored in `result_summary.risk_flags` |

**Document ML response field mapping:**

| ML field | Our field |
|---|---|
| `trust.trust_score` (int, e.g., 85) | `trust_score` |
| `trust.risk_level` (`LOW`/`MEDIUM`/`HIGH`) | stored in `result_summary.trust.risk_level` |
| `trust.decision` (`APPROVE`/`REVIEW`/`REJECT`) | stored in `result_summary.trust.decision` |
| `trust.risk_score` (0.0–1.0) | stored in `result_summary.trust.risk_score` |
| `fields.extracted_fields` (dict) | stored in `result_summary.fields.extracted_fields` |
| `content_risk.fraud_risk_score` (0.0–1.0) | stored in `result_summary.content_risk.fraud_risk_score` |
| `forensics.visual_tampering_risk_score` (0.0–1.0) | stored in `result_summary.forensics.visual_tampering_risk_score` |
| `qr_analysis.items` (array) | stored in `result_summary.qr_analysis.items` |
| `risk_flags` (array of strings) | stored in `result_summary.risk_flags` |
| `warnings` (array of strings) | stored in `result_summary.warnings` |

**Direct document flow (`document_service.py`) — with B2B/B2C routing:**
```
POST /api/verifications/verify/document/  (multipart/form-data: file + options)
  Auth: Session cookie (B2C) OR Authorization: Bearer bk_... (B2B)
        ↓
verify_document_view():
  - Parse file + label + document_type + analysis toggles
  - Detect auth type: request.auth is ApiKey → B2B, else → B2C
  - B2B: pass organization + api_key to service
  - B2C: pass user only
        ↓
verify_document_direct(user, doc_file, label, document_type, toggles..., organization?, api_key?):
  1. Validate file type (.pdf/.jpg/.png) + size (≤20 MB)
  2. Pre-flight balance check:
     ├── B2B: get_wallet_for_organization(organization) — org wallet
     └── B2C: get_wallet_for_user(user) — personal wallet
  3. Compute SHA-256 hash (chunked 64KB reads, memory-safe)
  4. Create Verification + VerificationJob rows (status=analyzing)
     ├── B2B: Verification.organization = org, api_key = key
     └── B2C: Verification.user = user
  5. If ML_MOCK_RESPONSE=True → return mock response (no HTTP call)
  6. Forward to ML: POST {ML_DOCUMENT_SERVICE_BASE_URL}/verify/document
     - Form data: file, document_type, run_ocr, run_forensics, run_qr,
                  run_live_qr_check, run_llm_analysis, max_pages
  7. Map response: trust.trust_score → trust_score, trust.decision → verdict
  8. complete_verification() → debit correct wallet, store results
        ↓
  B2B only: log ApiCall (endpoint, modality, status, latency, bits_charged)
        ↓
Return full verification with document analysis
```

**Mock mode:** Set `ML_MOCK_RESPONSE=True` in `.env` when ML services are down. Returns randomized but realistic results, still creates DB records and debits bits. Mock responses include `result_summary._mock = true`.

**`label` field:** Optional user-provided identifier stored in `result_summary.label`. Used to associate the verification with a specific user, file, or entity in the client's system.

**Bit costs** (from `settings.BITCHECK_VERIFICATION_COSTS`):

| Modality | Cost |
|---|---|
| text | 1 bit |
| image | 2 bits |
| document | 3 bits |
| audio | 5 bits |
| video | 8 bits |

**Verdict derivation from trust_score:**

| Trust Score | Verdict |
|---|---|
| 86–100 | `authentic` |
| 61–85 | `inconclusive` |
| 31–60 | `suspicious` |
| 0–30 | `manipulated` |


### 3.6 `webhooks` — External Event Processing

**The Inbox Pattern:** HTTP handler: verify HMAC-SHA512 signature (case-insensitive hex comparison) → insert raw event into `webhook_events` table → process inline (synchronous). This ensures:
- Squad gets a fast 200 response
- Failed processing doesn't lose the event
- Events can be replayed for debugging

> **Note:** Processing was originally designed for Celery, but is now done **inline** (synchronous) since Cloud Run only runs Gunicorn without a separate Celery worker. The DB operations (lookup + update) are lightweight enough to fit within Squad's timeout.

**Signature verification (`services.py`):**
```python
# Squad sends uppercase hex, Python's hexdigest() returns lowercase
# We .lower() the incoming signature before comparison
match = hmac.compare_digest(expected, signature_header.lower())
```

**Event type detection in `views.py`:**
```python
# Card webhooks have an 'Event' field
if 'Event' in payload:
    event_type = payload['Event']  # "charge_successful"

# VA webhooks have a 'channel' field
elif payload.get('channel') == 'virtual-account':
    event_type = 'transfer.successful'
```

**Event routing in `services.py`:**
| `event_type` | Handler | Purpose |
|---|---|---|
| `transfer.successful` | `_handle_virtual_account_credit()` | B2B bank transfer → bits |
| `charge_successful` | `_handle_subscription_charge()` | B2C card payment → activate Pro |

**Verbose logging:** Both `views.py` and `services.py` use `print()` statements prefixed with `[WEBHOOK]`, `[SIGNATURE]`, `[CHARGE]`, `[VA]` etc. for real-time debugging in Cloud Run logs.

### 3.7 `connectors` — Third-Party Integrations

Plugin-based architecture for connecting external services (Gmail, Slack, Telegram, etc.) to Bitcheck. Each integration is a **ConnectorAdapter** subclass registered via a decorator.

**Models:**
- `ConnectorType` — Seeded catalog (Gmail, Slack, etc.) with category, auth_type, status (coming_soon/alpha/beta/ga)
- `ConnectorInstall` — A user's or org's connection to one external account. Has encrypted credentials via `EncryptedJSONField` (Fernet encryption)
- `ConnectorEvent` — Inbound webhook events, idempotent on (install, external_event_id)
- `ConnectorMessage` — Outbound delivery audit (replies, notifications)
- `ConnectorTypeInterest` — Demand capture for "coming soon" tiles

**Architecture:**
```
External service (e.g., Gmail push notification)
        ↓
POST /api/connectors/webhook/<slug>/
        ↓
Adapter.verify_webhook() → validate signature
        ↓
Adapter.parse_event() → extract event metadata
        ↓
ConnectorEvent row saved → Celery task dispatched
        ↓
Adapter.extract_content() → pull content for verification
        ↓
submit_b2c_verification() or submit_b2b_verification()
```

**First adapter:** Gmail OAuth2. Uses `google-auth-oauthlib` for the OAuth flow and `google-api-python-client` to fetch emails.

**Endpoints:**
| Method | URL | Purpose |
|---|---|---|
| `POST` | `/api/connectors/webhook/<slug>/` | Receive inbound events |
| `GET` | `/api/connectors/types/` | List available connector types |
| `POST` | `/api/connectors/types/<slug>/interest/` | Express interest in a coming-soon connector |
| `GET/POST` | `/api/connectors/installs/` | List/create installs |
| `GET/PATCH/DELETE` | `/api/connectors/installs/<uuid>/` | Manage a specific install |
| `GET` | `/api/connectors/installs/<uuid>/events/` | List events for an install |
| `POST` | `/api/connectors/install/<slug>/begin/` | Start OAuth/install flow |
| `POST` | `/api/connectors/install/<slug>/complete/` | Complete install (non-OAuth) |
| `GET` | `/api/connectors/oauth/<slug>/callback/` | OAuth callback handler |

**Env vars:** `CONNECTOR_CREDENTIALS_KEY` (Fernet key), `CONNECTORS_PUBLIC_BASE_URL`, `CONNECTORS_OAUTH_STATE_SECRET`, `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_URI`

### 3.8 `core` — Structured Logging

Provides a JSON-line logger singleton and HTTP request logging middleware.

- **`logger.py`** — `logger.child("area")` creates namespaced loggers. All output is JSON on stdout (structured for Cloud Run / Datadog / etc.)
- **`RequestLoggingMiddleware`** — logs every HTTP request with: `request_id`, method, path, status, `duration_ms`, optional user ID, optional body previews. Sits after auth middleware so it has access to `request.user`.

**Env vars:** `APP_LOG_LEVEL`, `APP_LOG_HTTP_BODIES`, `APP_LOG_RESPONSE_BODY`, `APP_LOG_MAX_BODY`

### 3.9 `usage` — B2B API Call Logging

**Models:** `ApiCall` — logs each B2B API verification call with timing, key ID, modality, and response.

**Status:** Models and services (`log_api_call`, `check_idempotency`) are implemented. No user-facing endpoint yet — data visible in Django admin only. See [implementation backlog](implementation_backlog.md) item #6.

---

## 4. The Token Economy

### Currency System

```
Real Money (Naira)  →  Bit Tokens  →  Verification Cost
        ₦100        =    1 bit
        ₦500        =    5 bits
       ₦1,000       =   10 bits
```

**Rules:** Internally everything is in bits (integers, no decimals). Naira appears only at the Squad API boundary. Kobo (100 = ₦1) exists only in Squad's card API payload.

### How B2C Users Get Bits

1. **Sign up** → Free plan → 3 bits auto-credited (one-time, via signal)
2. **Upgrade to Pro** → Squad card payment → webhook → wallet reset to 0 (free bits removed) → 50 Pro bits granted
3. **Monthly renewal** → Squad charges card → webhook → wallet reset to 0 (unused bits forfeited) → 50 fresh Pro bits granted. **Use-it-or-lose-it.**
4. **Cancel** → stays active until period ends, then reverts to free plan (no new bits granted)

### How B2B Organizations Get Bits

1. **Admin provisions virtual account** → `POST /api/bits/virtual-account/provision/` → Squad creates a permanent bank account
2. **Org transfers Naira** to that account via normal bank transfer
3. **Squad webhook fires** → `transfer.successful` → backend converts naira to bits at ₦100/bit → credits org wallet
4. No subscription. Pay-as-you-go. Bits don't expire.

### How Bits Are Spent

| Modality | Cost |
|---|---|
| Text | 1 bit |
| Image | 2 bits |
| Document | 3 bits |
| Audio | 5 bits |
| Video | 8 bits |

Debited on ML completion only. 0 bits on failure.

---

## 5. Squad Payment Integration (Deep Dive)

We use **Squad** (squadco.com) as our payment gateway. Two completely different flows for B2C and B2B.

### Configuration

```python
# settings.py
SQUAD_SECRET_KEY = config('SQUAD_SECRET_KEY')      # Auth for all API calls
SQUAD_WEBHOOK_SECRET = config('SQUAD_WEBHOOK_SECRET')  # HMAC verification
SQUAD_BASE_URL = config('SQUAD_BASE_URL',
    default='https://sandbox-api-d.squadco.com')       # sandbox vs production
```

All Squad API calls use: `Authorization: Bearer {SQUAD_SECRET_KEY}`

### 5.1 B2C Card Tokenization (Pro Upgrade)

**Why tokenization?** We charge users ₦2,500/month. Instead of asking for card details every month, we tokenize the card on first payment and auto-charge it on renewal.

**The full flow:**

```
1. Frontend: POST /api/billing/subscription/upgrade/
   Body: { callback_url: "https://app.bitcheck.io/billing/success" }

2. Backend (billing/services.py → initiate_pro_checkout):
   → Creates 'incomplete' Subscription with squad_subscription_id = transaction_ref
   → Calls Squad: POST /transaction/initiate
     {
       email, amount: 250000 (kobo), currency: "NGN",
       is_recurring: true,         ← THIS IS THE KEY FLAG
       payment_channels: ["card"],
       transaction_ref: "bck_pro_a8f3b2c1d4e5f6g7"
     }
   → Returns checkout_url to frontend

3. Frontend redirects user to checkout_url (Squad's hosted payment page)

4. User enters card details and pays on Squad's page

5. Squad sends webhook: POST /api/webhooks/squad/
   Header: x-squad-encrypted-body: <HMAC-SHA512 signature>
   Body: {
     Event: "charge_successful",
     Body: {
       transaction_ref: "bck_pro_a8f3b2c1d4e5f6g7",
       email: "user@example.com",
       payment_information: {
         token_id: "AUTH_lBlGESHDLMX_60049043"  ← THE CARD TOKEN
       }
     }
   }

6. Webhook handler (_handle_subscription_charge):
   → Finds Subscription by transaction_ref (= squad_subscription_id)
   → Stores token_id as squad_card_token_id
   → Sets status = 'active'
   → Credits 50 bits to user's wallet

7. Frontend polls GET /api/billing/subscription/ until plan.code = "pro"
```

**Squad API calls we make:**

| When | Method | Endpoint | Purpose |
|---|---|---|---|
| User upgrades | `POST` | `/transaction/initiate` | Start card-tokenization payment |
| Monthly renewal | `POST` | `/transaction/charge_card` | Charge stored token (no user input) |
| User cancels | `PATCH` | `/transaction/cancel/recurring` | Revoke card token authorization |

**Recurring charges (`billing/services.py` → `charge_card_recurring`):**
```python
# Called by the rollover Celery task for Pro users
payload = {
    'amount': 250000,  # kobo
    'token_id': subscription.squad_card_token_id,  # e.g., AUTH_lBlGESHDLMX_...
    'transaction_ref': 'bck_renew_<unique>'
}
requests.post(f'{SQUAD_BASE_URL}/transaction/charge_card', json=payload)
```

### 5.2 B2B Virtual Accounts (Bank Transfer Top-Ups)

**Why virtual accounts?** Corporate cards have high failure rates and limits. A permanent bank account lets accounting departments use standard bank transfers.

#### Step 1: Provisioning (One-Time Setup)

The org admin creates a dedicated bank account number via our API. This only happens once per org:

```
Org admin → POST /api/bits/virtual-account/provision/
            Body: { bvn: "22110011001", mobile_num: "08012345678" }
                    ↓
Backend → POST Squad /virtual-account/business
          Body: { customer_identifier: "acme-corp", business_name: "Acme Corp", ... }
                    ↓
Squad returns → { virtual_account_number: "0733848693", bank_code: "058" }
                    ↓
Backend saves → VirtualAccount row in our DB
                account_number="0733848693", squad_account_reference="acme-corp"
                    ↓
API returns → { account_number: "0733848693", bank_name: "GTBank" }
```

The frontend displays this account number on the org dashboard. The org's finance team can now transfer money to it at any time.

> **Dev mode:** If `SQUAD_VA_DEV_MOCK=True` and `DEBUG=True`, the backend skips the Squad API call and creates a fake local VA row. Useful for demos when your sandbox isn't profiled for B2B.

#### Step 2: The Top-Up (Happens Entirely Outside Our System)

The org transfers ₦10,000 to account `0733848693` using their normal banking app (mobile banking, internet banking, USSD — anything). This is a standard Nigerian bank transfer. **Our system does nothing at this point.** We don't know about it yet.

#### Step 3: Squad Pushes a Webhook to Us (This is the Key Part)

**Celery does NOT poll.** There is no cron job, no background task checking "did money arrive?". Instead, **Squad calls us**:

```
Bank transfer lands in the VA at GTBank
        ↓
Squad detects the deposit (within seconds/minutes)
        ↓
Squad makes an HTTP POST to our webhook URL:
  POST https://your-domain.com/api/webhooks/squad/

  Header: x-squad-encrypted-body: <HMAC-SHA512 signature>
  Body: {
    "transaction_reference": "REF20260510..._1",
    "virtual_account_number": "0733848693",
    "principal_amount": "10000.00",       ← naira STRING, not kobo
    "customer_identifier": "acme-corp",   ← our org.slug
    "channel": "virtual-account"
  }
```

**This is the webhook URL you must configure on Squad's dashboard** (`squadco.com/merchant-settings/api-webhooks`). Without it, Squad has nowhere to send the notification and top-ups will never be processed.

#### Step 4: Our Webhook View Receives It

The view (`apps/webhooks/views.py → squad_webhook_view`) does exactly 3 things — nothing more:

```python
# 1. Verify the HMAC-SHA512 signature (is this really from Squad?)
if not verify_squad_signature(body, signature):
    return 401

# 2. Save the raw event to the webhook_events table (the "inbox")
event = ingest_webhook_event(source='squad', event_type='transfer.successful', ...)

# 3. Dispatch a Celery task to process it asynchronously
process_webhook_event_task.delay(str(event.id))

# Return 200 immediately — Squad expects a fast response
return 200
```

**Why not process it inline?** Squad expects a 200 response within seconds. If we did wallet credits, DB lookups, etc. before responding, and it took too long, Squad would think we failed and retry — potentially causing double credits.

#### Step 5: Celery Worker Processes the Event

The Celery task (`apps/webhooks/tasks.py → process_webhook_event_task`) picks up the event and calls the handler:

```
Celery worker picks up task
        ↓
_handle_virtual_account_credit(event, payload) runs:
        ↓
1. Idempotency check: has this transaction_reference been processed before?
   → If yes: mark as duplicate, skip (prevents double-crediting)
        ↓
2. Look up VirtualAccount by customer_identifier ("acme-corp")
   → This finds the org
        ↓
3. Parse amount: "10000.00" → ₦10,000 → 100 bits (at ₦100/bit rate)
        ↓
4. In one atomic DB transaction:
   a. Create TopUp record (amount_naira=10000, bits_credited=100)
   b. Credit org's TokenWallet: balance_bits += 100
   c. Create TokenLedgerEntry (audit trail)
   d. Mark webhook event as 'processed'
        ↓
5. Done. The org's wallet now has 100 more bits.
```

#### Step 6: Frontend Sees the Updated Balance

Next time anyone in the org calls `GET /api/bits/wallet/`, they see:

```json
{
  "wallet": { "balance_bits": 100 },
  "topups": [
    {
      "amount_naira": 10000,
      "bits_credited": 100,
      "rate_naira_per_bit": 100,
      "status": "credited",
      "squad_transaction_reference": "REF20260510..._1",
      "credited_at": "2026-05-10T15:30:00Z"
    }
  ]
}
```

**There's no polling by the frontend either** — the balance just updates whenever they load the page. If you want real-time updates, you could add WebSockets later, but for now a page refresh or periodic fetch is fine.

#### Summary: Who Calls Who?

```
Org's bank app  →  GTBank  →  Squad  →  Our webhook  →  Celery  →  Wallet credited
     (push)         (push)     (push)      (push)        (async)
```

Everything is push-based. Nobody polls. The chain of events is triggered entirely by the bank transfer.

**Critical difference from B2C:** Squad VA webhooks send amounts as **naira strings** (e.g., `"10000.00"`), NOT kobo integers. Card charge webhooks use kobo. Our handler parses with `int(float(principal_amount))`.

**No `beneficiary_account`:** By omitting this field, all incoming transfers pool into our Squad wallet. Squad settles to our bank account on T+1. This gives us control over the funds.

### 5.3 Webhook Security

Both B2C and B2B webhooks go to the same endpoint: `POST /api/webhooks/squad/`

**HMAC-SHA512 verification:**
```python
secret = settings.SQUAD_WEBHOOK_SECRET  # same as SQUAD_SECRET_KEY on Squad's dashboard
expected = hmac.new(secret.encode(), request.body, hashlib.sha512).hexdigest()
valid = hmac.compare_digest(expected, request.headers['X-Squad-Encrypted-Body'])
```

### 5.4 What If the Webhook Fails?

| Scenario | What Happens |
|---|---|
| Our server is down | Squad retries the webhook (their retry policy) |
| Signature fails | We return 401, event is NOT saved. Squad retries. |
| Celery task crashes | Event is saved in DB with status='failed'. Our `retry_failed_webhooks` task re-processes it every 6 hours. Celery also auto-retries 3 times with 30s delay. |
| Same webhook sent twice | Idempotency check: `squad_transaction_reference` is UNIQUE. Second attempt is marked as duplicate and skipped — no double credit. |
| Transfer too small | If ₦amount < ₦100 (1 bit rate), no bits credited. Event marked as processed with a note. |

---

## 6. Background Tasks (Celery)

Celery runs Python functions in the background via Redis as the message broker.

> [!IMPORTANT]
> **Celery does NOT poll external services.** It's a task queue — it processes jobs that are pushed to it.
> Webhooks push tasks. Celery beat pushes scheduled tasks. But Celery itself never reaches out to check anything.

### Task Inventory

| Task | File | Trigger | What It Does |
|---|---|---|---|
| `process_verification` | `verifications/tasks.py` | **On-demand** — dispatched when user submits a verification | Calls ML service, stores results, debits wallet |
| `process_webhook_event_task` | `webhooks/tasks.py` | **On-demand** — dispatched when Squad webhook arrives | Processes payment event, credits wallet |
| `process_subscription_rollovers` | `billing/tasks.py` | **Scheduled** — every hour via Celery beat | Resets wallets, grants new bits, advances periods |
| `retry_failed_webhooks` | `webhooks/tasks.py` | **Scheduled** — every 6 hours via Celery beat | Re-processes failed webhook events from last 24h |

**On-demand** = triggered by a specific user action (submitting a verification, or Squad sending a webhook).
**Scheduled** = runs on a timer regardless of user activity.

### Celery Beat Schedule (settings.py)

```python
CELERY_BEAT_SCHEDULE = {
    'subscription-rollover': {
        'task': 'apps.billing.tasks.process_subscription_rollovers',
        'schedule': 3600,  # every hour
    },
    'webhook-retry': {
        'task': 'apps.webhooks.tasks.retry_failed_webhooks',
        'schedule': 21600,  # every 6 hours
    },
}
```

### Subscription Rollover (Deep Dive)

The hourly task (`billing/tasks.py`) finds all active subscriptions where `current_period_end <= now()`:

```
For each expired subscription:
  1. Lock the row (select_for_update)
  2. If cancel_at_period_end is True:
     → Set status = 'canceled', stop
  3. Otherwise:
     → Reset wallet to 0 (forfeit unused bits)
     → Credit new month's grant (50 for pro)
     → Advance period: start = old end, end = start + 30 days
```

**Note:** For Pro users, both the upgrade and each renewal use `reset_and_grant()` — this creates two ledger entries: a `period_reset` (zeros the balance) and a `subscription_grant` (credits 50 bits). On initial upgrade, this also removes the 3 free bits.

Free plan users do **not** get monthly grants — the 3 bits from signup are a one-time allotment.

### How Celery Works

```python
# Queuing a task (in views/services):
process_verification.delay(str(verification.id))  # .delay() = run async

# Task definition (in tasks.py):
@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def process_verification(self, verification_id):
    try:
        # ... business logic
    except Exception as e:
        raise self.retry(exc=e)  # re-queue with backoff
```

**Without Celery/Redis running:** `.delay()` fails silently. The app works for auth, queries, submission — but verifications stay `queued` and webhooks aren't processed.

---

## 7. Security Decisions

### Session-Based Auth (not JWT)
- Sessions stored server-side (DB) → instant invalidation
- HttpOnly cookies → immune to XSS theft
- No refresh token dance. Django handles everything.

### CSRF Protection
DRF's built-in `SessionAuthentication` enforces Django CSRF on every request — even unauthenticated ones like register/login. This breaks Postman, mobile apps, and any non-browser client.

We use `CsrfExemptSessionAuthentication` (in `apps/accounts/authentication.py`) which overrides `enforce_csrf()` to do nothing. Our actual CSRF protection comes from:
- **`SameSite=Lax` cookies** — browsers won't send session cookies on cross-origin POST requests
- **CORS whitelist** — only our frontend origin can make requests

This is the standard approach for DRF APIs consumed by SPAs.

### API Key Security
Hashed SHA-256 + server pepper → stored hash only → prefix-based lookup → constant-time comparison (`hmac.compare_digest()`) → revealed once on creation.

### Webhook Signature Verification
HMAC-SHA512 with shared secret + constant-time comparison. Raw payload stored for audit/replay.

### Database Constraints (Defense in Depth)
| Constraint | Purpose |
|---|---|
| `CHECK(balance_bits >= 0)` | Wallet can never go negative, even with bugs |
| `UNIQUE(owner_user_id)` | One wallet per user |
| XOR check constraint | Wallet belongs to user OR org, never both |
| Partial unique index | Only one active subscription per user |
| `UNIQUE(squad_transaction_reference)` | Idempotent top-up processing |

---

## 8. Infrastructure & Deployment

### Production Stack
- **Runtime:** Google Cloud Run (containerized)
- **Database:** PostgreSQL (via `DATABASE_URL`)
- **Static files:** Whitenoise (served from Python process, collected at Docker build time)
- **Task queue:** Celery + Redis
- **Payments:** Squad (sandbox → production toggle via `SQUAD_BASE_URL`)

### Dockerfile Key Steps
```dockerfile
RUN python manage.py collectstatic --noinput   # Bake static files into image
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8080"]
```

### Environment Variables

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Django signing key |
| `DATABASE_URL` | PostgreSQL connection (defaults to SQLite if unset) |
| `DEBUG` | `True` for dev, `False` for prod |
| `ALLOWED_HOSTS` | Comma-separated hostnames |
| `SQUAD_SECRET_KEY` | Squad API auth |
| `SQUAD_WEBHOOK_SECRET` | HMAC verification for webhooks |
| `SQUAD_BASE_URL` | `sandbox-api-d.squadco.com` or `api-d.squadco.com` |
| `API_KEY_PEPPER` | Server-side pepper for API key hashing |
| `GOOGLE_CLIENT_ID` | Google OAuth verification |
| `ML_IMAGE_SERVICE_BASE_URL` | BitCheck image ML URL. Live: `https://jaykay73-bitcheck-image.hf.space` |
| `ML_TEXT_SERVICE_BASE_URL` | BitCheck text ML URL. Live: `https://jaykay73-bitcheck-text.hf.space` |
| `ML_MOCK_RESPONSE` | `True` to return mock ML results when ML services are down. `False` for real calls. |
| `CELERY_BROKER_URL` | Redis connection for Celery |

### API Documentation
- **Swagger UI:** `/api/docs/` (interactive, try endpoints live)
- **ReDoc:** `/api/redoc/` (read-only, better for reference)
- **OpenAPI Schema:** `/api/schema/` (JSON, for codegen)

Powered by `drf-spectacular`. Auto-generated from view docstrings and serializers.

---

## 9. Common Questions

**"Why 7 apps?"** — Each owns one domain. Migrations don't conflict. Code is findable. Apps testable independently.

**"Why SQLite in dev?"** — Zero setup. Switch to PostgreSQL by setting `DATABASE_URL`. The code works on both.

**"Why session auth instead of JWT?"** — Simpler, server-side invalidation, Django handles it. For mobile, we'd add JWT.

**"What if two users debit simultaneously?"** — `select_for_update()` locks the row. Second request waits. Pessimistic locking = gold standard for finance.

**"Why hash API keys?"** — If DB leaks, secrets are useless. Same approach as Stripe/GitHub/AWS.

**"What's the pepper?"** — Server-side secret mixed into hashes. Defeats rainbow tables even if attacker has the DB.

**"How does image verification work?"** — `POST /api/verifications/verify/image/` accepts the image directly as `multipart/form-data`. The backend computes SHA256, forwards to the ML service (`/verify/image`), maps the full response (trust score, forensics, provenance, explainability), debits 2 bits, and returns the result inline. No S3 or polling needed.

**"What if ML service is down?"** — For direct image upload: returns 400 immediately with error message, 0 bits charged. For async S3 flow: Celery retries 3x with 30s delay. All retries fail → status `failed`, 0 bits charged.

**"Why is the webhook handler so simple?"** — Inbox Pattern: insert raw event → process inline (synchronous) → return 200. Squad gets fast response. Events are stored for replay/debugging.

**"What happens when Squad VA webhook has different format than card webhook?"** — They're completely different payloads. VA webhooks: amounts as naira strings, `channel: "virtual-account"`, data at root. Card webhooks: `Event: "charge_successful"`, `Body: {...}`, amounts in kobo. Our webhook view detects the format and classifies correctly.

**"Why no beneficiary_account on virtual accounts?"** — Funds pool into our main Squad wallet. This gives us control over settlement and avoids direct payouts we can't track.
