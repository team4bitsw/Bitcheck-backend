# Squad API Usage Reference

> Complete reference of every Squad payment gateway endpoint used by the Bitcheck backend, why it's used, where it's called from, and how it fits into the system.

**Base URL (sandbox):** `https://sandbox-api-d.squadco.com`
**Base URL (production):** `https://api-d.squadco.com`
**Auth header (all calls):** `Authorization: Bearer {SQUAD_SECRET_KEY}`

---

## Table of Contents

1. [Initiate Payment](#1-initiate-payment)
2. [Charge Card (Recurring)](#2-charge-card-recurring)
3. [Cancel Recurring Authorization](#3-cancel-recurring-authorization)
4. [Create Business Virtual Account](#4-create-business-virtual-account)
5. [Simulate Payment (Sandbox Only)](#5-simulate-payment-sandbox-only)
6. [Webhook Reception](#6-webhook-reception)
7. [Environment Variables](#7-environment-variables)

---

## 1. Initiate Payment

**Squad endpoint:** `POST /transaction/initiate`

**Purpose:** Start a card-tokenization checkout for B2C Pro plan upgrades. The user is redirected to Squad's hosted checkout page where they enter their card details. On successful payment, Squad tokenizes the card and sends a webhook with the `token_id` for future recurring charges.

**Why we use it:** This is the entry point for our subscription billing. We need Squad to collect the initial payment AND tokenize the card so we can auto-renew subscriptions monthly without the user re-entering card details.

**Called from:** `apps/billing/services.py` → `initiate_pro_checkout()`

**Request payload:**
```json
{
  "email": "user@example.com",
  "amount": 200000,
  "currency": "NGN",
  "initiate_type": "inline",
  "transaction_ref": "bck_pro_a1b2c3d4e5f6g7h8",
  "customer_name": "John Doe",
  "callback_url": "https://app.bitcheck.ai/billing/success",
  "payment_channels": ["card"],
  "is_recurring": true,
  "metadata": {
    "user_id": "uuid",
    "plan_code": "pro",
    "purpose": "pro_upgrade"
  }
}
```

**Key fields:**
| Field | Value | Why |
|---|---|---|
| `is_recurring` | `true` | Tells Squad to tokenize the card — returns `token_id` in webhook |
| `initiate_type` | `inline` | Returns a `checkout_url` for Squad's hosted payment modal |
| `payment_channels` | `["card"]` | Restrict to card-only (no bank transfer for subscriptions) |
| `amount` | kobo (NGN * 100) | Squad uses lowest currency unit (e.g., 200000 = N2,000) |
| `transaction_ref` | `bck_pro_{uuid}` | Our unique reference for idempotent processing |

**Response (success):**
```json
{
  "status": 200,
  "data": {
    "checkout_url": "https://checkout.squadco.com/pay/..."
  }
}
```

**Flow after this call:**
1. Frontend redirects user to `checkout_url`
2. User enters card details on Squad's hosted page
3. Squad processes payment and sends `charge_successful` webhook
4. Our webhook handler activates the subscription and stores the `token_id`

**Dev mock:** Set `SQUAD_CHECKOUT_DEV_MOCK=True` + `DEBUG=True` to skip the Squad API and return a mock checkout URL for local testing.

---

## 2. Charge Card (Recurring)

**Squad endpoint:** `POST /transaction/charge_card`

**Purpose:** Charge a previously tokenized card for subscription renewals. This is called automatically by our Celery-based billing cycle to renew Pro subscriptions without user interaction.

**Why we use it:** After the initial payment tokenizes the card, we need a way to charge it again each billing cycle. This endpoint lets us do server-to-server charges using the stored `token_id` — no checkout page needed.

**Called from:** `apps/billing/services.py` → `charge_card_recurring()`

**Request payload:**
```json
{
  "amount": 200000,
  "token_id": "AUTH_lBlGESHDLMX_60049043",
  "transaction_ref": "bck_renew_a1b2c3d4e5f6g7h8"
}
```

**Key fields:**
| Field | Value | Why |
|---|---|---|
| `token_id` | `AUTH_...` | The card token received from the initial payment webhook |
| `amount` | kobo | Must match the plan's recurring charge |
| `transaction_ref` | `bck_renew_{uuid}` | Unique per charge for idempotency |

**Response (success):**
```json
{
  "status": 200,
  "data": {
    "transaction_ref": "bck_renew_...",
    "amount": 200000,
    "status": "success"
  }
}
```

**When it's called:**
- Celery beat task runs on the subscription renewal schedule
- Task checks if subscription is active + has a stored card token
- Calls this endpoint to charge the card
- On success: extends subscription period + grants new bit allocation

---

## 3. Cancel Recurring Authorization

**Squad endpoint:** `PATCH /transaction/cancel/recurring`

**Purpose:** Revoke our authorization to charge a user's tokenized card. Called when a user cancels their Pro subscription, ensuring we can no longer charge their card.

**Why we use it:** When a user cancels, we must tell Squad to invalidate the card token. This is both a security requirement and a user trust measure — we should not retain the ability to charge a card after cancellation.

**Called from:** `apps/billing/services.py` → `cancel_card_token()`

**Request payload:**
```json
{
  "auth_code": ["AUTH_lBlGESHDLMX_60049043"]
}
```

**Key fields:**
| Field | Value | Why |
|---|---|---|
| `auth_code` | array of token IDs | Squad accepts batch cancellation; we send one at a time |

**Response (success):**
```json
{
  "status": 200,
  "message": "Authorization cancelled successfully"
}
```

**When it's called:**
- User hits `POST /api/billing/subscription/cancel/`
- Backend cancels the subscription (sets `cancel_at_period_end = True`)
- Calls this endpoint to revoke the card token with Squad
- Returns `True`/`False` — failure is logged but doesn't block the cancellation

---

## 4. Create Business Virtual Account

**Squad endpoint:** `POST /virtual-account/business`

**Purpose:** Provision a dedicated virtual bank account number for a B2B organization. When anyone sends a bank transfer to this account number, Squad forwards a webhook to our backend, which converts the NGN deposit to bits and credits the organization's wallet.

**Why we use it:** Our B2B clients need a way to top up their bit wallets via bank transfer (not card). Virtual accounts give each organization a permanent, dedicated account number that maps directly to their Bitcheck wallet.

**Called from:** `apps/bits/va_services.py` → `provision_virtual_account()`

**Request payload:**
```json
{
  "customer_identifier": "acme-corp",
  "business_name": "Acme Corp Ltd",
  "mobile_num": "08012345678",
  "bvn": "22110011001",
  "beneficiary_account": "4920299492"
}
```

**Key fields:**
| Field | Value | Why |
|---|---|---|
| `customer_identifier` | org slug | Links the VA to our organization record |
| `business_name` | org name (min 2 words) | Squad requires multi-word names; we append "Ltd" if needed |
| `mobile_num` | from frontend | Required by Squad for KYC |
| `bvn` | from frontend | Bank Verification Number — required by Squad for VA provisioning |
| `beneficiary_account` | from env var | Squad sandbox requires this; set via `SQUAD_BENEFICIARY_ACCOUNT` |

**Response (success):**
```json
{
  "success": true,
  "message": "Success",
  "data": {
    "virtual_account_number": "6742152514",
    "bank_code": "058",
    "customer_identifier": "acme-corp"
  }
}
```

**After provisioning:**
- The virtual account number and bank name are stored in our `VirtualAccount` model
- The frontend displays the account details for the org admin to share with their finance team
- Any transfer to this account triggers a Squad webhook → bit credit

**Common errors:**
| Status | Cause | Fix |
|---|---|---|
| 400 | "Beneficiary account is required" | Set `SQUAD_BENEFICIARY_ACCOUNT` in `.env` |
| 403 | Merchant not profiled for B2B | Contact Squad support to enable virtual account access for your sandbox merchant |

---

## 5. Simulate Payment (Sandbox Only)

**Squad endpoint:** `POST /virtual-account/simulate/payment`

**Purpose:** Simulate an inbound bank transfer to a virtual account in the sandbox environment. This triggers Squad to send a webhook as if a real bank transfer occurred, allowing end-to-end testing of the VA top-up flow.

**Why we use it:** In sandbox mode, no real bank transfers can be made. This endpoint lets us test the complete flow: simulate payment → Squad sends webhook → our backend credits bits to the org wallet.

**Called from:** `apps/bits/views.py` → `simulate_payment_view()`

**Our API wrapper:** `POST /api/bits/virtual-account/simulate-payment/`

**Request payload (to Squad):**
```json
{
  "virtual_account_number": "6742152514",
  "amount": "20000"
}
```

**Key fields:**
| Field | Value | Why |
|---|---|---|
| `virtual_account_number` | from our VA record | Auto-filled from the org's provisioned VA |
| `amount` | naira string | Amount to simulate (e.g., "20000" = N20,000) |

**Response (success):**
```json
{
  "success": true,
  "message": "Success",
  "data": {}
}
```

**What happens after:**
1. Squad sends a webhook to our configured webhook URL (`/api/webhooks/squad/`)
2. Webhook payload contains `virtual_account_number`, `principal_amount`, `customer_identifier`
3. Our backend looks up the org by `customer_identifier`, converts NGN to bits, and credits the wallet

**Safety:** This endpoint is blocked in production — it only works when `SQUAD_BASE_URL` contains "sandbox".

---

## 6. Webhook Reception

**Our endpoint:** `POST /api/webhooks/squad/`

**Purpose:** Receive and process payment notifications from Squad. This is not a Squad API we call — it's a Squad API that calls us. Configured in the Squad dashboard under webhook settings.

**Why we use it:** Squad communicates payment results (successful charges, failed payments, VA deposits) via webhooks. We must receive and process these to activate subscriptions, credit wallets, and track transactions.

**Called by:** Squad's servers (server-to-server)

**Webhook types we handle:**

| Event | Source | What we do |
|---|---|---|
| Card payment success | `POST /transaction/initiate` checkout | Activate Pro subscription, store card `token_id`, grant bits |
| Recurring charge success | `POST /transaction/charge_card` | Extend subscription period, grant new bit cycle |
| VA deposit received | Bank transfer to virtual account | Convert NGN to bits, credit org wallet |

**Signature verification:**
- **Card webhooks:** HMAC-SHA512 of the raw request body, compared against `X-Squad-Encrypted-Body` header
- **VA webhooks:** HMAC-SHA512 of the raw body, compared against the `encrypted_body` field inside the JSON payload
- Both use `SQUAD_WEBHOOK_SECRET` as the HMAC key

**Idempotency:** We track `transaction_reference` to prevent duplicate processing. If the same reference arrives twice, the second is acknowledged (200 OK) but not processed.

**Handler location:** `apps/webhooks/views.py` → `squad_webhook_view()`
**Business logic:** `apps/webhooks/services.py` → `ingest_webhook_event()`

---

## 7. Environment Variables

All Squad-related configuration is loaded from environment variables:

| Variable | Required | Description | Example |
|---|---|---|---|
| `SQUAD_SECRET_KEY` | Yes | API secret key (format: `sandbox_sk_...`) | `sandbox_sk_abc123...` |
| `SQUAD_WEBHOOK_SECRET` | Yes | HMAC key for webhook verification | `your_webhook_secret` |
| `SQUAD_BASE_URL` | Yes | API base URL (sandbox vs production) | `https://sandbox-api-d.squadco.com` |
| `SQUAD_BENEFICIARY_ACCOUNT` | Sandbox | Required for VA provisioning in sandbox | `4920299492` |
| `SQUAD_VA_DEV_MOCK` | No | Mock VA provisioning locally (no Squad call) | `True` |
| `SQUAD_CHECKOUT_DEV_MOCK` | No | Mock checkout URL locally (no Squad call) | `True` |

**Sandbox vs Production:**
| Setting | Sandbox | Production |
|---|---|---|
| `SQUAD_BASE_URL` | `https://sandbox-api-d.squadco.com` | `https://api-d.squadco.com` |
| `SQUAD_SECRET_KEY` | `sandbox_sk_...` | `squad_sk_...` |
| `SQUAD_WEBHOOK_SECRET` | Sandbox webhook secret | Production webhook secret |
| Simulate payment | Available | Blocked by code |

---

## Summary

| # | Squad API | Method | Our Code Location | Purpose |
|---|---|---|---|---|
| 1 | `/transaction/initiate` | POST | `billing/services.py` | Start card-tokenization checkout for Pro subscriptions |
| 2 | `/transaction/charge_card` | POST | `billing/services.py` | Auto-charge tokenized card for subscription renewals |
| 3 | `/transaction/cancel/recurring` | PATCH | `billing/services.py` | Revoke card token when user cancels subscription |
| 4 | `/virtual-account/business` | POST | `bits/va_services.py` | Provision dedicated VA for B2B org bank transfers |
| 5 | `/virtual-account/simulate/payment` | POST | `bits/views.py` | Test VA deposits in sandbox (triggers webhook) |
| 6 | `/api/webhooks/squad/` (inbound) | POST | `webhooks/views.py` | Receive payment notifications from Squad |
