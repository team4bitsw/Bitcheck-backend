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

## 2. Core Verification API

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

### Direct Image Verification (Recommended)

`POST /api/verifications/verify/image/` — **Requires auth. Content-Type: `multipart/form-data`.**

Uploads an image directly and runs it through the BitCheck ML pipeline. Returns the full AI analysis inline — no polling needed. Costs **2 bits** on success.

> [!TIP]
> This is the simplest way to verify images. The backend sends `user_gmail` (from your session) + the file to the ML service automatically. All analysis layers (model, forensics, metadata, provenance, explainability) run by default.

**Request (multipart/form-data):**

| Field | Type | Required | Description |
|---|---|---|---|
| `file` | image file | **Yes** | `.jpg`, `.jpeg`, `.png`, `.webp` — max **12 MB** |
| `label` | string | No | User/data identifier — e.g., `"invoice_q4"`, `"user_john_avatar"`, a slug, or any tracking ref |

**cURL example:**
```bash
curl -X POST "https://bitscheck-849221325853.europe-west1.run.app/api/verifications/verify/image/" \
  -H "Cookie: sessionid=YOUR_SESSION_COOKIE" \
  -F "file=@suspicious_image.jpg" \
  -F "label=audit_report_may2026"
```

**Response (200):**
```json
{
  "detail": "Image verification completed.",
  "verification": {
    "id": "uuid",
    "modality": "image",
    "status": "completed",
    "trust_score": 31,
    "verdict": "suspicious",
    "bits_charged": 2,
    "result_summary": {
      "label": "audit_report_may2026",
      "original_filename": "suspicious_image.jpg",
      "sha256": "b1ddf2f9f25c0f9adf...",
      "file_size_bytes": 248391,
      "ml_verification_id": "8d53cf77-2b2d-4d55-b6a9-...",
      "user_gmail": "user@gmail.com",
      "input": {
        "filename": "suspicious_image.jpg",
        "sha256": "...",
        "width": 1920,
        "height": 1080,
        "format": "JPEG",
        "size_bytes": 248391
      },
      "model_result": {
        "label": "ai_generated",
        "confidence": 0.87,
        "model_status": "loaded"
      },
      "metadata": {
        "exif": {},
        "software_flags": ["Adobe Photoshop"],
        "camera_metadata_found": false
      },
      "provenance": {
        "status": "not_available",
        "c2pa_found": false
      },
      "forensics": {
        "sharpness": 118.6,
        "noise_inconsistency": 0.48,
        "compression_artifacts": 0.33
      },
      "explainability": {
        "status": "generated",
        "method": "Grad-CAM",
        "heatmap_url": "/outputs/8d53cf77_heatmap.png",
        "boxed_image_url": "/outputs/8d53cf77_boxed.png",
        "hotspots": [
          { "x": 114, "y": 88, "width": 50, "height": 50, "score": 0.85, "label": "high influence region" }
        ],
        "disclaimer": "Hotspots show regions that influenced the model's prediction..."
      },
      "trust": {
        "score": 31.2,
        "label": "high_risk",
        "breakdown": { "model_weight": 0.5, "metadata_weight": 0.2, "forensics_weight": 0.15, "provenance_weight": 0.15 }
      },
      "risk_flags": [
        "AI-generated content detected by model.",
        "No trusted C2PA provenance metadata found."
      ],
      "limitations": [
        "BitCheck does not make absolute claims about image authenticity.",
        "AI-generated image detection is probabilistic and may produce false positives or false negatives."
      ]
    },
    "error_message": null,
    "created_at": "2026-05-13T00:00:00Z",
    "completed_at": "2026-05-13T00:00:03Z"
  }
}
```

**Key fields for the UI:**

| Field | What to display |
|---|---|
| `verification.trust_score` | Trust gauge (0–100). Higher = more trustworthy. |
| `verification.verdict` | Badge: `authentic` / `inconclusive` / `suspicious` / `manipulated` |
| `result_summary.model_result.label` | `"real"` or `"ai_generated"` |
| `result_summary.model_result.confidence` | Confidence score (0–1), e.g., "87% confident" |
| `result_summary.trust.label` | `"low_risk"` / `"moderate_risk"` / `"high_risk"` |
| `result_summary.risk_flags` | Bullet list of red flags |
| `result_summary.explainability.hotspots` | Overlay boxes on the image |
| `result_summary.explainability.heatmap_url` | Grad-CAM heatmap (relative to ML base URL) |

**Error responses:**
- **400** — Missing file, unsupported type, file too large (>12 MB), or ML service error
- **402** — Insufficient bits: `{ "detail": "Insufficient bits for image verification.", "required": 2, "available": 0 }`

**Frontend implementation (JavaScript FormData):**
```javascript
const verifyImage = async (file, label = '') => {
  const form = new FormData();
  form.append('file', file);     // File object from <input type="file">
  form.append('label', label);   // Optional tracking identifier

  const response = await fetch('/api/verifications/verify/image/', {
    method: 'POST',
    credentials: 'include',  // sends session cookie
    body: form,              // NO Content-Type header — browser sets it with boundary
  });

  if (response.status === 402) {
    const err = await response.json();
    alert(`Need ${err.required} bits, you have ${err.available}.`);
    return null;
  }

  return response.json();
};
```

> [!IMPORTANT]
> Do NOT set `Content-Type: application/json` for this endpoint. Use `FormData` and let the browser set the correct `multipart/form-data` boundary automatically.

---

### Direct Text Verification

`POST /api/verifications/verify/text/` — **Requires auth. Content-Type: `application/json`.**

Submit text for fraud, AI-generation, manipulation, and source URL analysis. Returns the full AI analysis inline. Costs **1 bit** on success.

> [!TIP]
> Text verification checks for: AI generation likelihood, fraud signals, manipulation pressure, claim validity, and source URL reputation. All checks run by default — you can disable individual modules to speed up processing.

**Request (JSON):**

| Field | Type | Required | Description |
|---|---|---|---|
| `text` | string | **Yes** | The text to verify (5–8000 characters) |
| `source_url` | string | No | URL where the text was found, or a link within the text |
| `context` | string | No | Context hint for the LLM (e.g., `"WhatsApp broadcast"`, `"Email"`) |
| `label` | string | No | Your tracking identifier |
| `check_ai_likelihood` | boolean | No | Check if text is AI-generated (default: `true`) |
| `check_fraud_signals` | boolean | No | Check for fraud/scam signals (default: `true`) |
| `check_claims` | boolean | No | Check factual claims (default: `true`) |
| `check_source_url` | boolean | No | Analyze the source URL (default: `true`) |

**cURL example:**
```bash
curl -X POST "https://bitscheck-849221325853.europe-west1.run.app/api/verifications/verify/text/" \
  -H "Cookie: sessionid=YOUR_SESSION_COOKIE" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "URGENT! The Federal Government is giving ₦500,000 grants to all students. Click this link and submit your BVN before midnight.",
    "source_url": "http://bit.ly/free-grant-now",
    "context": "WhatsApp broadcast",
    "label": "suspicious_broadcast_may2026"
  }'
```

**Response (200):**
```json
{
  "detail": "Text verification completed.",
  "verification": {
    "id": "uuid",
    "modality": "text",
    "status": "completed",
    "trust_score": 15,
    "verdict": "manipulated",
    "bits_charged": 1,
    "result_summary": {
      "label": "suspicious_broadcast_may2026",
      "text_length": 128,
      "text_preview": "URGENT! The Federal Government is giving ₦500,000...",
      "ml_verification_id": "a1b2c3d4-...",
      "input": {
        "text_length": 128,
        "source_url": "http://bit.ly/free-grant-now",
        "language": "en",
        "context": "WhatsApp broadcast"
      },
      "trust": {
        "trust_score": 15,
        "risk_score": 0.85,
        "risk_level": "Very High Risk",
        "decision": "block_or_manual_review",
        "summary": "This text exhibits multiple high-risk fraud signals..."
      },
      "risk_flags": [
        "Urgency/Pressure tactics detected",
        "Financial scam keywords found",
        "Suspicious shortened URL"
      ],
      "recommended_actions": [
        "Do not click the provided link",
        "Do not share personal information like BVN"
      ],
      "ai_likelihood": {
        "is_ai_generated": true,
        "confidence": 0.73,
        "reasoning": "Based on linguistic pattern analysis."
      },
      "fraud_signals": { "score": 0.85, "signals_found": [...] },
      "manipulation_signals": {
        "urgency_detected": true,
        "emotional_manipulation": true,
        "authority_impersonation": true
      },
      "source_analysis": {
        "url_analyzed": "http://bit.ly/free-grant-now",
        "url_safe": false,
        "domain_reputation": "suspicious"
      },
      "limitations": [
        "BitCheck text analysis is probabilistic and may produce false positives.",
        "AI generation detection is not definitive."
      ]
    },
    "error_message": null,
    "created_at": "2026-05-13T00:30:00Z",
    "completed_at": "2026-05-13T00:30:02Z"
  }
}
```

**Key fields for the UI:**

| Field | What to display |
|---|---|
| `verification.trust_score` | Trust gauge (0–100). Higher = more trustworthy. |
| `verification.verdict` | Badge: `authentic` / `inconclusive` / `suspicious` / `manipulated` |
| `result_summary.trust.risk_level` | Risk label (e.g., "Very High Risk") |
| `result_summary.trust.decision` | `"approve"` / `"review"` / `"block_or_manual_review"` |
| `result_summary.risk_flags` | Bullet list of red flags |
| `result_summary.recommended_actions` | Actionable warnings for the user |
| `result_summary.ai_likelihood.confidence` | AI generation confidence (0–1) |
| `result_summary.fraud_signals` | Fraud analysis details |

**Error responses:**
- **400** — Missing/empty text, text too short (<5) or too long (>8000), or ML service error
- **402** — Insufficient bits: `{ "detail": "Insufficient bits for text verification.", "required": 1, "available": 0 }`

**Frontend implementation (JavaScript):**
```javascript
const verifyText = async (text, sourceUrl = '', context = '') => {
  const response = await fetch('/api/verifications/verify/text/', {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      text,
      source_url: sourceUrl || undefined,
      context: context || undefined,
    }),
  });

  if (response.status === 402) {
    const err = await response.json();
    alert(`Need ${err.required} bit, you have ${err.available}.`);
    return null;
  }

  return response.json();
};
```

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
> The subscription is NOT active yet at this point — Squad sends a `charge_successful` webhook to the backend, which:
> 1. **Resets the wallet to 0** (removes the 3 free bits)
> 2. **Credits 50 Pro bits**
> 3. Activates the subscription
>
> **Poll `GET /api/billing/subscription/` every 2 seconds on the success page** until `plan.code` changes from `"free"` to `"pro"`.
>
> On monthly **renewal**, the same reset-and-grant happens: balance goes to 0, then 50 fresh bits are credited. Unused bits do NOT roll over.

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
| `DELETE` | `/api/verifications/` | Session | Soft-delete ALL user's verifications |
| `DELETE` | `/api/verifications/<id>/` | Session | Soft-delete a single verification |
| `POST` | `/api/verifications/verify/image/` | Session | Direct image verification (2 bits) |
| `POST` | `/api/verifications/verify/text/` | Session | Direct text verification (1 bit) |
| `POST` | `/api/webhooks/squad/` | HMAC | Squad payment webhook (server-to-server) |
| `GET` | `/api/schema/` | Public | OpenAPI 3.0 JSON schema |
| `GET` | `/api/docs/` | Public | Swagger UI (interactive) |
| `GET` | `/api/redoc/` | Public | ReDoc (read-only docs) |
