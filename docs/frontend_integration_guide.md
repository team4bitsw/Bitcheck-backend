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

#### Forgot Password

`POST /api/auth/forgot-password/` — **Public, no auth required.**

Sends a password reset token for the given email. Always returns 200 regardless of whether the email exists (prevents email enumeration).

**Request:**
```json
{ "email": "user@example.com" }
```

**Response (200):**
```json
{
  "detail": "If an account with that email exists, a password reset link has been sent.",
  "reset_url": "https://bitcheckapp.vercel.app/reset-password?uid=MWUyZjNhNGI&token=c5f3a7..."
}
```

> [!NOTE]
> In `DEBUG` mode, the response also includes raw `uid` and `token` fields for testing without an email provider. In production, only `reset_url` is included (and an email would be sent).

**Frontend implementation:**
```javascript
const forgotPassword = async (email) => {
  const response = await fetch('/api/auth/forgot-password/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email }),
  });
  return response.json();
};
```

> [!TIP]
> Always show a success message to the user regardless of the response — "Check your email for a reset link." This matches the backend's anti-enumeration behavior.

#### Reset Password

`POST /api/auth/reset-password/` — **Public, no auth required.**

Consumes a reset token and sets a new password. The `uid` and `token` come from the reset URL query parameters.

**Request:**
```json
{
  "uid": "MWUyZjNhNGI",
  "token": "c5f3a7-abc123def456",
  "new_password": "NewSecurePassword123!"
}
```

**Response (200):**
```json
{ "detail": "Password has been reset successfully. You can now log in." }
```

**Error (400) — invalid or expired token:**
```json
{ "detail": "Invalid or expired reset link." }
```

**Password rules:**
- Minimum 8 characters
- Cannot be entirely numeric

**Frontend implementation:**
```javascript
// Extract uid and token from URL: /reset-password?uid=...&token=...
const params = new URLSearchParams(window.location.search);

const resetPassword = async (newPassword) => {
  const response = await fetch('/api/auth/reset-password/', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      uid: params.get('uid'),
      token: params.get('token'),
      new_password: newPassword,
    }),
  });

  if (!response.ok) {
    const err = await response.json();
    alert(err.detail);  // "Invalid or expired reset link."
    return null;
  }

  return response.json();  // success — redirect to login
};
```

> [!IMPORTANT]
> Reset tokens are single-use. Once the password is changed, the token is automatically invalidated. Tokens also expire after 3 days (Django's `PASSWORD_RESET_TIMEOUT` default).

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
> This is the simplest way to verify images. The backend sends `user_email` (from your session) + the file to the ML service automatically. All analysis layers (classifier, forensics, metadata, provenance, explainability, OCR watermark) run by default — you can disable individual modules via the toggle parameters.

> [!NOTE]
> **Hash-based caching:** The backend computes a SHA-256 hash of every uploaded file. If an identical file was previously analyzed, the cached ML result is returned instantly (no ML call). The response will include `result_summary._cached = true` and `result_summary._cache_hit_count`. Bits are still charged on cache hits — caching optimizes speed, not cost.

**Request (multipart/form-data):**

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `file` | image file | **Yes** | — | `.jpg`, `.jpeg`, `.png`, `.webp` — max **12 MB** |
| `label` | string | No | `""` | User/data identifier — e.g., `"invoice_q4"`, `"user_john_avatar"` |
| `run_explainability` | boolean | No | `true` | Generate Grad-CAM heatmap showing AI-influenced regions |
| `run_ocr` | boolean | No | `true` | Run OCR to detect visible AI tool watermarks |
| `run_forensics` | boolean | No | `true` | Run forensic analysis (noise, blur, edge inconsistencies) |
| `run_c2pa` | boolean | No | `true` | Analyze C2PA provenance data (Content Credentials) |
| `threshold` | float | No | — | Override the default confidence threshold for the classifier |

**cURL example:**
```bash
curl -X POST "https://bitscheck-849221325853.europe-west1.run.app/api/verifications/verify/image/" \
  -H "Cookie: sessionid=YOUR_SESSION_COOKIE" \
  -F "file=@suspicious_image.jpg" \
  -F "label=audit_report_may2026" \
  -F "run_forensics=true" \
  -F "run_c2pa=true"
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
      "user_email": "user@gmail.com",
      "input": {
        "filename": "suspicious_image.jpg",
        "sha256": "...",
        "width": 1920,
        "height": 1080,
        "format": "JPEG",
        "size_bytes": 248391
      },
      "filename_analysis": {
        "ai_tool_keywords_found": [],
        "suspicious_patterns": false
      },
      "classifier": {
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
      "visible_watermark_ocr": {
        "watermarks_found": false,
        "detected_text": []
      },
      "visible_watermark_template": {
        "matches_found": false,
        "matched_templates": []
      },
      "forensics": {
        "sharpness": 118.6,
        "noise_inconsistency": 0.48,
        "compression_artifacts": 0.33,
        "noise_map_url": "https://jaykay73-bitcheck-image.hf.space/outputs/8d53cf77_noise.png"
      },
      "explainability": {
        "status": "generated",
        "method": "Grad-CAM",
        "heatmap_url": "https://jaykay73-bitcheck-image.hf.space/outputs/8d53cf77_heatmap.png",
        "boxed_image_url": "https://jaykay73-bitcheck-image.hf.space/outputs/8d53cf77_boxed.png",
        "hotspots": [
          { "x": 114, "y": 88, "width": 50, "height": 50, "score": 0.85, "label": "high influence region" }
        ],
        "disclaimer": "Hotspots show regions that influenced the model's prediction..."
      },
      "trust": {
        "trust_score_out_of_100": 31,
        "final_decision": "ai_generated",
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
| `result_summary.classifier.label` | `"real"` or `"ai_generated"` |
| `result_summary.classifier.confidence` | Confidence score (0–1), e.g., "87% confident" |
| `result_summary.trust.final_decision` | Final ML decision: `"real"` or `"ai_generated"` |
| `result_summary.trust.trust_score_out_of_100` | Raw ML trust score (0–100) |
| `result_summary.risk_flags` | Bullet list of red flags |
| `result_summary.explainability.hotspots` | Overlay boxes on the image |
| `result_summary.explainability.heatmap_url` | Grad-CAM heatmap (absolute URL) |
| `result_summary.forensics` | Noise/blur/compression metrics + forensic image URLs |
| `result_summary.visible_watermark_ocr` | OCR-detected AI watermarks |

**Error responses:**
- **400** — Missing file, unsupported type, file too large (>12 MB), or ML service error
- **402** — Insufficient bits: `{ "detail": "Insufficient bits for image verification.", "required": 2, "available": 0 }`

**Frontend implementation (JavaScript FormData):**
```javascript
const verifyImage = async (file, label = '', options = {}) => {
  const form = new FormData();
  form.append('file', file);     // File object from <input type="file">
  if (label) form.append('label', label);

  // Optional analysis toggles
  if (options.run_explainability !== undefined) form.append('run_explainability', options.run_explainability);
  if (options.run_ocr !== undefined) form.append('run_ocr', options.run_ocr);
  if (options.run_forensics !== undefined) form.append('run_forensics', options.run_forensics);
  if (options.run_c2pa !== undefined) form.append('run_c2pa', options.run_c2pa);
  if (options.threshold !== undefined) form.append('threshold', options.threshold);

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

### Direct Document Verification

`POST /api/verifications/verify/document/` — **Requires auth. Content-Type: `multipart/form-data`.**

Submit a document (PDF, image) for authenticity analysis, field extraction, forensic tampering detection, QR code scanning, and LLM-powered content risk assessment. Returns the full AI analysis inline. Costs **3 bits** on success.

> [!TIP]
> Document verification combines multiple analysis modules: OCR text extraction, visual forensics (tamper detection), QR/barcode scanning, and LLM-based semantic analysis. You can disable individual modules to reduce processing time.

**Request (multipart/form-data):**

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `file` | File | **Yes** | — | PDF, PNG, JPG, or JPEG. Max 20 MB. |
| `label` | String | No | `""` | User-provided identifier for tracking |
| `document_type` | String | No | `"general"` | Type hint: `"general"`, `"invoice"`, `"id_card"`, `"receipt"`, etc. |
| `run_ocr` | Boolean | No | `true` | Extract text via OCR |
| `run_forensics` | Boolean | No | `true` | Run visual tampering/forgery detection |
| `run_qr` | Boolean | No | `true` | Scan for QR codes and barcodes |
| `run_live_qr_check` | Boolean | No | `false` | Verify QR code URLs with a live HTTP check |
| `run_llm_analysis` | Boolean | No | `true` | Deep semantic analysis via LLM |
| `max_pages` | Integer | No | `5` | Max pages to process (multi-page PDFs). Clamped to 1–20. |

**Response (200):**
```json
{
  "detail": "Document verification completed.",
  "verification": {
    "id": "uuid",
    "modality": "document",
    "status": "completed",
    "trust_score": 85,
    "verdict": "authentic",
    "bits_charged": 3,
    "result_summary": {
      "original_filename": "invoice_q4.pdf",
      "document_type": "invoice",
      "trust": {
        "trust_score": 85,
        "risk_score": 0.15,
        "risk_level": "LOW",
        "decision": "APPROVE"
      },
      "fields": {
        "document_type": "invoice",
        "extracted_fields": {
          "invoice_number": "INV-1029",
          "total_amount": "$1,200.00"
        },
        "field_confidence": 0.95
      },
      "content_risk": {
        "fraud_risk_score": 0.1,
        "suspicious_claims": [],
        "summary": "No high-risk content detected."
      },
      "forensics": {
        "visual_tampering_risk_score": 0.05,
        "suspicious_regions": []
      },
      "qr_analysis": {
        "qr_found": true,
        "items": [
          {
            "data": "https://example.com/verify",
            "live_verification": {
              "eligible": true,
              "status_code": 200,
              "risk_score": 0.0
            }
          }
        ]
      },
      "risk_flags": [],
      "warnings": []
    },
    "created_at": "2026-05-15T14:00:00Z",
    "completed_at": "2026-05-15T14:00:05Z"
  }
}
```

**Key fields for the UI:**

| Field | What to display |
|---|---|
| `trust.decision` | Primary routing: `"APPROVE"` / `"REVIEW"` / `"REJECT"` |
| `trust.trust_score` | Trust gauge (0–100) |
| `trust.risk_level` | Risk badge: `"LOW"` / `"MEDIUM"` / `"HIGH"` |
| `fields.extracted_fields` | Auto-populated document data (invoice number, amounts, etc.) |
| `content_risk.fraud_risk_score` | Fraud likelihood (0.0–1.0) |
| `forensics.visual_tampering_risk_score` | Tampering likelihood (0.0–1.0) |
| `qr_analysis.items` | Decoded QR/barcode data + live verification results |
| `risk_flags` | Bullet list of anomalies (e.g. "Metadata wiped", "Inconsistent fonts") |

**Error responses:**
- **400** — Unsupported file type, file too large (>20 MB), or ML service error
- **402** — Insufficient bits: `{ "detail": "Insufficient bits for document verification.", "required": 3, "available": 0 }`

**Frontend implementation (JavaScript):**
```javascript
const verifyDocument = async (file, documentType = 'general', options = {}) => {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('document_type', documentType);

  // Optional analysis toggles
  if (options.label) formData.append('label', options.label);
  if (options.run_ocr !== undefined) formData.append('run_ocr', options.run_ocr);
  if (options.run_forensics !== undefined) formData.append('run_forensics', options.run_forensics);
  if (options.run_qr !== undefined) formData.append('run_qr', options.run_qr);
  if (options.run_live_qr_check !== undefined) formData.append('run_live_qr_check', options.run_live_qr_check);
  if (options.run_llm_analysis !== undefined) formData.append('run_llm_analysis', options.run_llm_analysis);
  if (options.max_pages) formData.append('max_pages', options.max_pages);

  const response = await fetch('/api/verifications/verify/document/', {
    method: 'POST',
    credentials: 'include',
    body: formData,  // No Content-Type header — browser sets multipart boundary
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
> Document analysis with LLM and OCR can take 2–10 seconds depending on page count. Set appropriate loading states in your UI. The `max_pages` parameter helps control processing time for large PDFs.

---

### B2B API Key Usage (Separate from B2C)

> [!IMPORTANT]
> When the same verification endpoints (`/verify/image/`, `/verify/text/`, `/verify/document/`) are called with an API key instead of a session cookie, the backend automatically routes to the **organization's wallet** instead of the user's personal wallet. B2B and B2C usage are tracked and billed completely separately.

**How it works:**

| Aspect | B2C (Session Cookie) | B2B (API Key) |
|---|---|---|
| **Auth header** | `Cookie: sessionid=...` | `Authorization: Bearer bk_test_...` |
| **Wallet debited** | User's personal wallet | Organization's wallet |
| **Verification ownership** | `verification.user = you` | `verification.organization = your org` |
| **Usage tracking** | None | `ApiCall` record logged per request |
| **List endpoint** | Returns user's verifications | Returns org's verifications |

**B2B Image verification (cURL):**
```bash
curl -X POST "https://bitscheck-849221325853.europe-west1.run.app/api/verifications/verify/image/" \
  -H "Authorization: Bearer bk_test_a8f3b2c1d4e5f6a7b8c9d0e1f2a3b4c5" \
  -F "file=@suspicious_image.jpg" \
  -F "label=org_audit_may2026"
```

**B2B Text verification (cURL):**
```bash
curl -X POST "https://bitscheck-849221325853.europe-west1.run.app/api/verifications/verify/text/" \
  -H "Authorization: Bearer bk_test_a8f3b2c1d4e5f6a7b8c9d0e1f2a3b4c5" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "URGENT! The Federal Government is giving grants...",
    "source_url": "http://bit.ly/free-grant-now"
  }'
```

**B2B JavaScript example:**
```javascript
const API_KEY = 'bk_test_a8f3b2c1d4e5f6a7b8c9d0e1f2a3b4c5';

// Image verification via API key
const verifyImageB2B = async (file, label = '') => {
  const form = new FormData();
  form.append('file', file);
  form.append('label', label);

  const response = await fetch('/api/verifications/verify/image/', {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${API_KEY}` },
    body: form,
  });

  return response.json();
};

// Text verification via API key
const verifyTextB2B = async (text, sourceUrl = '') => {
  const response = await fetch('/api/verifications/verify/text/', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${API_KEY}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ text, source_url: sourceUrl }),
  });

  return response.json();
};
```

> [!NOTE]
> The response format is identical for B2B and B2C. The only difference is which wallet is charged and which entity owns the verification record. B2B callers do NOT need `credentials: 'include'` since they are using Bearer token auth, not cookies.

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
| `POST` | `/api/auth/forgot-password/` | Public | Request password reset token |
| `POST` | `/api/auth/reset-password/` | Public | Reset password with token |
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
| `GET` | `/api/verifications/` | Session or Bearer | List verifications (user's for B2C, org's for B2B) |
| `DELETE` | `/api/verifications/` | Session or Bearer | Soft-delete ALL verifications (scoped to user or org) |
| `GET` | `/api/verifications/<id>/` | Session or Bearer | Get verification detail + full results |
| `DELETE` | `/api/verifications/<id>/` | Session or Bearer | Soft-delete a single verification |
| `POST` | `/api/verifications/verify/image/` | Session or Bearer | Direct image verification (2 bits from user or org wallet) |
| `POST` | `/api/verifications/verify/text/` | Session or Bearer | Direct text verification (1 bit from user or org wallet) |
| `POST` | `/api/verifications/verify/document/` | Session or Bearer | Direct document verification (3 bits from user or org wallet) |
| `POST` | `/api/webhooks/squad/` | HMAC | Squad payment webhook (server-to-server) |
| `GET` | `/api/schema/` | Public | OpenAPI 3.0 JSON schema |
| `GET` | `/api/docs/` | Public | Swagger UI (interactive) |
| `GET` | `/api/redoc/` | Public | ReDoc (read-only docs) |
