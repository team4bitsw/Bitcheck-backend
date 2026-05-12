# Bitcheck AI — Frontend Integration Guide

> **Last verified:** 2026-05-10 against the live Django codebase.
> This is the single source of truth for the Next.js frontend team.

---

## 1. Base Setup & Authentication

### Base Configuration

| Key | Value |
|---|---|
| Base URL (dev) | `http://localhost:8000` |
| Base URL (prod) | `https://api.bitcheck.io` |
| Content-Type | `application/json` |
| Auth mechanism | Session cookie (`sessionid`, HttpOnly, `SameSite=Lax`) |
| Session lifetime | 7 days |
| CSRF protection | Not required — handled by `SameSite=Lax` cookies + CORS |
| Rate limits | 60/min (anonymous), 120/min (authenticated) |
| API docs (Swagger) | `/api/docs/` |
| API docs (ReDoc) | `/api/redoc/` |

> [!IMPORTANT]
> **Every `fetch` call MUST include `credentials: 'include'`.**
> Without it, the browser will not send or store the session cookie, and all authenticated requests will return `403`.

### Shared API Client

```typescript
// lib/api.ts
const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export async function api<T = any>(
  endpoint: string,
  options: RequestInit = {},
): Promise<T> {
  const res = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw { status: res.status, ...body };
  }
  return res.json();
}
```

### Auth Endpoints

#### Google OAuth (Primary Flow)

`POST /api/auth/google/`

1. User authenticates via `@react-oauth/google` and receives a `credential` (which is the `id_token`).
2. Frontend POSTs it to this endpoint.
3. Backend verifies with Google, get-or-creates the user, sets the session cookie.

**Request:**
```json
{ "id_token": "eyJhbGciOiJSUzI1NiIs..." }
```

**Response (200):**
```json
{
  "detail": "Google authentication successful.",
  "created": true,
  "user": {
    "id": "a1b2c3d4-e5f6-...",
    "email": "user@example.com",
    "full_name": "John Doe",
    "account_type": "individual",
    "is_active": true,
    "email_verified_at": "2026-05-09T20:00:00Z",
    "last_login_at": "2026-05-09T20:00:00Z",
    "created_at": "2026-05-09T20:00:00Z",
    "updated_at": "2026-05-09T20:00:00Z"
  }
}
```

**Usage:**
```typescript
import { CredentialResponse } from '@react-oauth/google';

const handleGoogleSuccess = async (response: CredentialResponse) => {
  const data = await api('/api/auth/google/', {
    method: 'POST',
    body: JSON.stringify({ id_token: response.credential }),
  });
  // data.user is now the authenticated user. Session cookie is set.
};
```

#### Email/Password Registration

`POST /api/auth/register/`

**B2C (Individual) request:**
```json
{
  "email": "user@example.com",
  "password": "StrongPass123!",
  "full_name": "John Doe",
  "account_type": "individual"
}
```

**B2B (Business) request:**
```json
{
  "email": "cto@acme.com",
  "password": "StrongPass123!",
  "full_name": "Jane Smith",
  "account_type": "business",
  "organization_name": "Acme Corp",
  "organization_description": "AI-powered content verification for media companies."
}
```

| Field | Required | Notes |
|---|---|---|
| `email` | Yes | Must be unique |
| `password` | Yes | Min 8 characters |
| `full_name` | No | User's display name |
| `account_type` | No | `"individual"` (default) or `"business"` |
| `organization_name` | B2B only | **Required** when `account_type` is `"business"` |
| `organization_description` | No | Free-text description of the company |

> [!IMPORTANT]
> When `account_type` is `"business"`, the backend automatically creates:
> 1. The **User** account
> 2. An **Organization** (with auto-generated slug from the name)
> 3. An **admin Membership** linking the user to the org
> 4. A **TokenWallet** for the user (via signal)
>
> This means the user is immediately ready to provision API keys and a virtual account after registration.

**Response (201):** Same `{ "detail", "user" }` shape as Google auth. Session is set automatically.

#### Setup Organization (for existing users)

`POST /api/auth/setup-org/` — **Requires auth.**

Lets an existing individual user create an organization after signup (e.g., they signed up as individual first, then want to create a business).

**Request:**
```json
{
  "organization_name": "Acme Corp",
  "organization_description": "Optional company description."
}
```

**Response (201):**
```json
{
  "detail": "Organization created.",
  "organization": { "id": "...", "name": "Acme Corp", "slug": "acme-corp", ... },
  "user": { "id": "...", "email": "...", "account_type": "business", ... }
}
```

- **Error (400):** User already has an org membership.

#### Email/Password Login

`POST /api/auth/login/`

**Request:**
```json
{ "email": "user@example.com", "password": "StrongPass123!" }
```

**Response (200):** `{ "detail": "Login successful.", "user": { ... } }`

#### Logout

`POST /api/auth/logout/` — Destroys the session. Requires auth.

**Response (200):** `{ "detail": "Logged out successfully." }`

#### Current User Profile

`GET /api/auth/me/` — Returns `{ "user": { ... } }` with the full user object.

`PATCH /api/auth/me/` — Update profile. Accepts `full_name` and/or `account_type`.

**Request:**
```json
{ "full_name": "Jane Doe" }
```
**Response (200):** `{ "detail": "Profile updated.", "user": { ... } }`

---

## 2. The File Upload Flow (Critical Path)

Files are uploaded directly to S3-compatible object storage to bypass Django's memory limits. The architecture is a 3-step process.

> [!WARNING]
> **The presigned URL endpoint (`POST /api/verifications/upload-url/`) does NOT exist yet.**
> It is designed but not implemented. Until it ships, file-based verifications (image, video, audio, document) cannot be submitted from the frontend.
> **Text verifications work today.** File upload support is blocked on S3 credential provisioning.

### Planned Flow (When Implemented)

```
┌──────────┐    1. Request URL    ┌──────────┐
│ Frontend │ ──────────────────►  │  Django  │  → creates UploadedFile row
└────┬─────┘                      └──────────┘    returns presigned PUT URL
     │
     │  2. PUT file directly
     ▼
┌──────────┐
│    S3    │
└──────────┘
     │
     │  3. Submit verification with uploaded_file_id
     ▼
┌──────────┐
│  Django  │  → creates Verification + dispatches to ML
└──────────┘
```

**Step 1 — Request presigned URL:** `POST /api/verifications/upload-url/` *(not yet implemented)*
```json
{
  "filename": "suspect_video.mp4",
  "mime_type": "video/mp4",
  "size_bytes": 524288000
}
```

**Step 2 — Direct upload to S3:**
```typescript
await fetch(uploadUrl, {
  method: 'PUT',
  body: file,
  headers: { 'Content-Type': file.type },
});
```

**Step 3 — Submit verification** (see Section 3 below), passing the `uploaded_file_id`.

---

## 3. Core Verification API

### Get Verification Costs

`GET /api/verifications/costs/` — **Public, no auth required.**

**Response (200):**
```json
{
  "costs": {
    "text": 1,
    "image": 2,
    "document": 3,
    "audio": 5,
    "video": 8
  }
}
```

Use this to display cost badges next to each modality in the UI.

### Submit a Verification

`POST /api/verifications/` — **Requires auth.**

**Text verification request:**
```json
{
  "modality": "text",
  "text_input": "Breaking: Scientists discover water on the sun!"
}
```

**File verification request:**
```json
{
  "modality": "image",
  "uploaded_file_id": "a1b2c3d4-..."
}
```

**Accepted modalities:** `text`, `image`, `video`, `audio`, `document`.

**Response (202 Accepted):**
```json
{
  "detail": "Verification submitted.",
  "verification": {
    "id": "59fca6f5-e9ed-4c80-aaae-d7b77e499932",
    "modality": "text",
    "status": "queued",
    "trust_score": null,
    "verdict": null,
    "result_summary": {},
    "bits_charged": 0,
    "error_message": null,
    "uploaded_file": null,
    "text_input": "Breaking: Scientists discover water on the sun!",
    "created_at": "2026-05-09T20:09:58Z",
    "started_at": null,
    "completed_at": null
  },
  "cost_bits": 1
}
```

> [!IMPORTANT]
> **Bits are NOT deducted at submission time.** `bits_charged` will be `0` until the ML service completes. The actual wallet debit happens only on successful completion.

**Error — Insufficient Bits (402):**
```json
{
  "detail": "Insufficient bits.",
  "required": 8,
  "available": 2
}
```

### Async Polling for Results

`GET /api/verifications/<uuid:id>/` — **Requires auth.**

The ML analysis is asynchronous. After submission, poll this endpoint every **3 seconds** until `status` transitions away from `queued` / `analyzing`.

**Status lifecycle:** `queued` → `analyzing` → `completed` | `failed`

**Completed response:**
```json
{
  "verification": {
    "id": "59fca6f5-...",
    "modality": "text",
    "status": "completed",
    "trust_score": 85,
    "verdict": "inconclusive",
    "result_summary": {
      "signals": [
        { "key": "factual_consistency", "ok": true, "label": "Claims are consistent" },
        { "key": "source_credibility", "ok": false, "label": "Source not verified", "weight": 15 }
      ],
      "regions": [
        { "x": 0.12, "y": 0.34, "w": 0.20, "h": 0.15, "score": 0.73 }
      ],
      "metadata": {
        "camera": "iPhone 14 Pro",
        "captured_at": "2026-05-08T10:22:11Z"
      }
    },
    "bits_charged": 1,
    "error_message": null,
    "uploaded_file": null,
    "text_input": "Breaking: Scientists discover water on the sun!",
    "created_at": "2026-05-09T20:09:58Z",
    "started_at": "2026-05-09T20:09:59Z",
    "completed_at": "2026-05-09T20:10:02Z"
  }
}
```

**Verdict mapping for UI badges:**

| `verdict` | Color | Emoji | Meaning |
|---|---|---|---|
| `authentic` | Green | ✅ | Trust score 86-100 |
| `inconclusive` | Yellow | ⚠️ | Trust score 61-85 |
| `suspicious` | Orange | 🔶 | Trust score 31-60 |
| `manipulated` | Red | ❌ | Trust score 0-30 |

**Failed response:**
```json
{
  "verification": {
    "status": "failed",
    "trust_score": null,
    "verdict": null,
    "bits_charged": 0,
    "error_message": "ML service is unreachable."
  }
}
```

> No bits are charged on failure.

**Polling example:**
```typescript
const pollVerification = async (id: string): Promise<Verification> => {
  while (true) {
    const { verification } = await api(`/api/verifications/${id}/`);
    if (verification.status === 'completed' || verification.status === 'failed') {
      return verification;
    }
    await new Promise((r) => setTimeout(r, 3000));
  }
};
```

### Verification History

`GET /api/verifications/` — **Requires auth.** Returns the current user's last 50 verifications (most recent first). Note: this is NOT paginated — it uses a hard limit of 50.

**Response (200):**
```json
{
  "verifications": [
    {
      "id": "uuid",
      "modality": "text",
      "status": "completed",
      "trust_score": 85,
      "verdict": "inconclusive",
      "bits_charged": 1,
      "created_at": "2026-05-09T20:09:58Z",
      "completed_at": "2026-05-09T20:10:02Z"
    }
  ]
}
```

> The list view uses a compact serializer — no `result_summary`, `error_message`, `text_input`, or `uploaded_file`. Fetch the detail endpoint for full data.

---

## 4. Dashboards & Token Economy

### B2C Dashboard Endpoints

#### Subscription & Wallet

`GET /api/billing/subscription/` — **Requires auth.**

**Response (200):**
```json
{
  "subscription": {
    "id": "uuid",
    "plan": {
      "id": "uuid",
      "code": "free",
      "name": "Free Tier",
      "recurring_charge_naira": 0,
      "monthly_grant_bits": 3,
      "billing_interval": "month",
      "is_active": true
    },
    "status": "active",
    "current_period_start": "2026-05-09T20:00:00Z",
    "current_period_end": "2026-06-09T20:00:00Z",
    "cancel_at_period_end": false,
    "canceled_at": null,
    "created_at": "2026-05-09T20:00:00Z",
    "updated_at": "2026-05-09T20:00:00Z"
  },
  "wallet": {
    "id": "uuid",
    "balance_bits": 2
  }
}
```

**404** if the user has no active subscription (edge case — shouldn't happen since one is auto-created on registration).

#### Upgrade to Pro Plan

`POST /api/billing/subscription/upgrade/` — **Requires auth.**

Initiates a Squad checkout session with card tokenization. Returns a `checkout_url` that the frontend should redirect the user to.

**Request:**
```json
{
  "callback_url": "https://app.bitcheck.io/billing/success"
}
```
- `callback_url`: optional. The URL Squad redirects to after the user pays.

**Response (200):**
```json
{
  "checkout_url": "https://sandbox-pay.squadco.com/bck_pro_a8f3b2c1d4e5f6g7",
  "transaction_ref": "bck_pro_a8f3b2c1d4e5f6g7",
  "subscription_id": "uuid"
}
```

**Frontend implementation:**
```typescript
const upgradeToPro = async () => {
  const { checkout_url } = await api('/api/billing/subscription/upgrade/', {
    method: 'POST',
    body: JSON.stringify({
      callback_url: `${window.location.origin}/billing/success`,
    }),
  });
  // Redirect to Squad's payment page
  window.location.href = checkout_url;
};
```

> [!IMPORTANT]
> After the user pays on Squad's checkout page, they are redirected to the `callback_url`.
> The subscription is NOT active yet at this point — Squad sends a `charge_successful` webhook to the backend, which activates the subscription and credits 50 bits.
> **Poll `GET /api/billing/subscription/` every 2 seconds on the success page** until `plan.code` changes from `"free"` to `"pro"`.

**400** if already on Pro.
**502** if Squad API is unreachable.

#### Cancel Subscription

`POST /api/billing/subscription/cancel/` — **Requires auth.**

Sets `cancel_at_period_end = true`. The subscription stays active until the current period ends, then the rollover task cancels it. Also cancels the card token on Squad so we can't charge the card again.

**Response (200):**
```json
{
  "detail": "Subscription will be canceled at the end of the current period.",
  "subscription": { ... }
}
```

**400** if on the free plan (can't cancel free).

#### Available Plans (Pricing Page)

`GET /api/billing/plans/` — **Public, no auth required.**

**Response (200):**
```json
{
  "plans": [
    {
      "id": "uuid",
      "code": "free",
      "name": "Free Tier",
      "recurring_charge_naira": 0,
      "monthly_grant_bits": 3,
      "billing_interval": "month",
      "is_active": true
    },
    {
      "id": "uuid",
      "code": "pro",
      "name": "Pro",
      "recurring_charge_naira": 2500,
      "monthly_grant_bits": 50,
      "billing_interval": "month",
      "is_active": true
    }
  ]
}
```

### B2B Dashboard Endpoints

#### Provision Virtual Account (Create a Dedicated Bank Account)

`POST /api/bits/virtual-account/provision/` — **Requires auth + org admin role.**

Creates a permanent Squad bank account for the organization. Once created, the org can transfer Naira to this account at any time, and the backend will auto-convert to bit tokens.

**Request:**
```json
{
  "bvn": "22110011001",
  "mobile_num": "08012345678"
}
```
- `bvn`: exactly 11 digits. BVN of the org representative.
- `mobile_num`: at most 11 digits.

**Response (201):**
```json
{
  "id": "uuid",
  "account_number": "0733848693",
  "bank_code": "058",
  "bank_name": "GTBank",
  "account_name": "Acme Corp",
  "customer_identifier": "acme-corp"
}
```

**400** if the org already has a virtual account, or if BVN/mobile validation fails.
**403** if not an org admin.

> [!TIP]
> Display the `account_number` and `bank_name` prominently on the B2B dashboard. This is the account number the org's finance team will use for bank transfers to top up their wallet.

#### Get Virtual Account Details

`GET /api/bits/virtual-account/` — **Requires auth + org membership.**

**Response (200):**
```json
{
  "id": "uuid",
  "account_number": "0733848693",
  "bank_name": "GTBank",
  "account_name": "Acme Corp",
  "customer_identifier": "acme-corp",
  "created_at": "2026-05-10T18:00:00Z"
}
```

**404** if no virtual account has been provisioned.

#### Organization Wallet & Top-Up History

`GET /api/bits/wallet/` — **Requires auth + org membership.**

**Response (200):**
```json
{
  "wallet": {
    "id": "uuid",
    "balance_bits": 150
  },
  "topups": [
    {
      "id": "uuid",
      "amount_naira": 10000,
      "bits_credited": 100,
      "rate_naira_per_bit": 100,
      "status": "credited",
      "squad_transaction_reference": "REF20260510..._1",
      "credited_at": "2026-05-10T15:30:00Z",
      "created_at": "2026-05-10T15:30:00Z"
    }
  ],
  "virtual_account": {
    "id": "uuid",
    "account_number": "0733848693",
    "bank_name": "GTBank",
    "account_name": "Acme Corp",
    "customer_identifier": "acme-corp",
    "created_at": "2026-05-10T12:00:00Z"
  }
}
```

> [!NOTE]
> `topups` returns the 25 most recent top-ups. `virtual_account` is `null` if no VA has been provisioned yet.

#### Simulate VA Payment (Sandbox Only)

`POST /api/bits/virtual-account/simulate-payment/` — **Requires auth + org membership. Sandbox only.**

Triggers a simulated bank transfer to the org's virtual account via Squad's sandbox. This fires a real webhook from Squad, so you can test the full top-up flow end-to-end without doing an actual bank transfer.

**Request:**
```json
{
  "amount": "20000"
}
```
- `amount`: Naira amount as a string. The VA account number is auto-filled from the org's record.

**Response (200):**
```json
{
  "transaction_status": "SUCCESS",
  "merchant_reference": "your_custom_reference",
  "merchant_amount": "20000.00",
  "amount_received": "20000.00",
  "transaction_reference": "REF20250321S51557521_M01282553_0855445055",
  "email": "customer@email.com",
  "merchant_id": "SQA...",
  "sub_merchant_id": null,
  "transaction_type": "dynamic_virtual_account"
}
```

**403** if `SQUAD_BASE_URL` is not a sandbox URL.
**404** if no VA has been provisioned.

> [!TIP]
> **Frontend implementation:** Add a small "Test Top-Up" button on the B2B wallet page (only visible when the backend is in sandbox mode). After calling this endpoint, poll `GET /api/bits/wallet/` every 2-3 seconds for ~15 seconds to see the balance update.

#### List API Keys

`GET /api/keys/` — **Requires auth + org membership.**

**Response (200):**
```json
{
  "api_keys": [
    {
      "id": "uuid",
      "name": "Production Key",
      "environment": "live",
      "prefix": "bk_live_a8f3",
      "is_active": true,
      "last_used_at": "2026-05-09T20:00:00Z",
      "revoked_at": null,
      "created_at": "2026-05-09T19:00:00Z"
    }
  ]
}
```

**403** if the user doesn't belong to an organization.

#### Create API Key

`POST /api/keys/` — **Requires auth + org membership.**

**Request:**
```json
{
  "name": "CI Pipeline Key",
  "environment": "test"
}
```
- `environment`: `"test"` or `"live"`. Defaults to `"test"`.

**Response (201):**
```json
{
  "detail": "API key created. Save the secret — it will not be shown again.",
  "key": {
    "id": "uuid",
    "name": "CI Pipeline Key",
    "environment": "test",
    "prefix": "bk_test_b787",
    "is_active": true,
    "last_used_at": null,
    "revoked_at": null,
    "created_at": "2026-05-09T20:04:01Z"
  },
  "raw_secret": "bk_test_b78716eece20052ae890894c2623e620"
}
```

> [!CAUTION]
> **`raw_secret` is returned ONCE and ONLY ONCE.** The backend hashes it immediately.
> Display it in a full-screen modal with a copy button and a hard warning: *"This secret will never be shown again."*
> After the user dismisses the modal, the secret is gone forever.

#### Revoke API Key

`POST /api/keys/<uuid:id>/revoke/` — **Requires auth + org membership.**

**Response (200):**
```json
{
  "detail": "API key revoked.",
  "key": { ... }
}
```

**400** if already revoked. **404** if not found or not owned by the user's org.

---

## 5. Error Handling & HTTP Status Codes

All error responses include a `detail` string. Validation errors may include field-level errors.

### Status Code Reference

| Code | Meaning | Frontend Action |
|---|---|---|
| `200` | Success | Render data |
| `201` | Created | Render data + success toast |
| `202` | Accepted (async) | Start polling |
| `400` | Validation error | Show field errors or toast |
| `401` | Unauthenticated | Redirect to `/login` |
| `402` | Insufficient bits | Show upgrade/top-up modal |
| `403` | Forbidden (no org, no permission) | Show access-denied state |
| `404` | Not found | Show empty state |
| `429` | Rate limited | Show "slow down" toast, retry after delay |
| `502` | Bad gateway (Squad API down) | Show "try again later" message |

### 402 Payment Required — Special Handling

This is the most critical error for the token economy UX.

```json
{
  "detail": "Insufficient bits.",
  "required": 8,
  "available": 2
}
```

**Recommended UI:** Intercept 402 globally in the API client and trigger a Neo-Brutalist modal:
- Display current balance (`available`) vs. the cost (`required`).
- Show a bold CTA: "Upgrade to Pro" (B2C) or "Top Up Wallet" (B2B).
- Do **not** fail silently — this is a revenue conversion moment.

```typescript
// In your api client error handler:
if (error.status === 402) {
  openInsufficientBitsModal({
    required: error.required,
    available: error.available,
  });
}
```

### Validation Errors (400)

DRF returns field-level errors as an object:
```json
{
  "email": ["A user with this email already exists."],
  "password": ["This field is required."]
}
```

Or a single `detail` string:
```json
{ "detail": "Cannot cancel the free plan." }
```

### Authentication Errors (401)

```json
{ "detail": "Authentication credentials were not provided." }
```
or
```json
{ "detail": "Invalid Google token." }
```

---

## Appendix: Complete Endpoint Map

| Method | URL | Auth | Description |
|---|---|---|---|
| `GET` | `/api/health/` | Public | Health check |
| `POST` | `/api/auth/register/` | Public | Email/password registration |
| `POST` | `/api/auth/login/` | Public | Email/password login |
| `POST` | `/api/auth/logout/` | Session | Destroy session |
| `POST` | `/api/auth/google/` | Public | Google OAuth token exchange |
| `GET` | `/api/auth/me/` | Session | Get current user profile |
| `PATCH` | `/api/auth/me/` | Session | Update profile |
| `GET` | `/api/billing/plans/` | Public | List all active plans |
| `GET` | `/api/billing/subscription/` | Session | Current subscription + wallet |
| `POST` | `/api/billing/subscription/upgrade/` | Session | Initiate Pro upgrade (Squad checkout) |
| `POST` | `/api/billing/subscription/cancel/` | Session | Cancel at period end |
| `POST` | `/api/bits/virtual-account/provision/` | Session (admin) | Create Squad VA for org |
| `GET` | `/api/bits/virtual-account/` | Session | Get org's VA details |
| `GET` | `/api/bits/wallet/` | Session | Org wallet balance + top-up history |
| `GET` | `/api/keys/` | Session | List org's API keys |
| `POST` | `/api/keys/` | Session | Create API key (one-time secret) |
| `POST` | `/api/keys/<id>/revoke/` | Session | Revoke an API key |
| `GET` | `/api/verifications/costs/` | Public | Bit costs per modality |
| `GET` | `/api/verifications/` | Session | List user's verifications (last 50) |
| `POST` | `/api/verifications/` | Session | Submit a verification |
| `GET` | `/api/verifications/<id>/` | Session | Get verification detail + results |
| `POST` | `/api/webhooks/squad/` | HMAC | Squad payment webhook (server-to-server) |
| `GET` | `/api/schema/` | Public | OpenAPI 3.0 JSON schema |
| `GET` | `/api/docs/` | Public | Swagger UI (interactive) |
| `GET` | `/api/redoc/` | Public | ReDoc (read-only docs) |
