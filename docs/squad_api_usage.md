# Squad API Usage Reference

> Complete reference of every Squad payment gateway API endpoint used by the Bitcheck backend — includes the official Squad API specifications, why each is used, and how it integrates into our system.

**Base URLs:**
- **Sandbox:** `https://sandbox-api-d.squadco.com`
- **Production:** `https://api-d.squadco.com`

**Authentication:** All requests require `Authorization: Bearer {SQUAD_SECRET_KEY}` header.

---

## APIs Used

| # | Squad API Endpoint | Method | What It Does |
|---|---|---|---|
| 1 | `/transaction/initiate` | POST | Initiate a payment and get a checkout URL |
| 2 | `/transaction/charge_card` | POST | Charge a tokenized card (recurring billing) |
| 3 | `/transaction/cancel/recurring` | PATCH | Cancel a card tokenization authorization |
| 4 | `/virtual-account/business` | POST | Create a dedicated virtual account for a business |
| 5 | `/virtual-account/simulate/payment` | POST | Simulate a bank transfer to a VA (sandbox only) |

---

## 1. Initiate Payment

`POST https://sandbox-api-d.squadco.com/transaction/initiate`

This endpoint initiates a transaction and returns a checkout URL. When visited, this URL displays Squad's payment modal where the customer enters their card details.

**Why we use it:** To start the Pro subscription upgrade flow. We pass `is_recurring: true` so that Squad tokenizes the card on successful payment, giving us a `token_id` we can use for future automatic charges without the user re-entering card details.

**Where it's called:** `apps/billing/services.py` → `initiate_pro_checkout()`

### Parameters

**Headers:**

| Field | Type | Required | Description |
|---|---|---|---|
| `Authorization` | String | Yes | API secret key as Bearer token |

**Body:**

| Field | Type | Required | Description |
|---|---|---|---|
| `email` | String | Yes | Customer's email address |
| `amount` | Integer | Yes | Amount to charge in lowest currency unit (kobo). 10000 = NGN 100 |
| `initiate_type` | String | Yes | Must be `"inline"` — returns a checkout URL |
| `currency` | String | Yes | `"NGN"` or `"USD"` |
| `transaction_ref` | String | No | Unique merchant reference. Auto-generated if omitted |
| `customer_name` | String | No | Name of the customer |
| `callback_url` | String | No | URL to redirect customer after payment |
| `payment_channels` | Array | No | Restrict channels: `["card", "bank", "ussd", "transfer"]` |
| `metadata` | Object | No | Any additional data to attach to the transaction |
| `pass_charge` | Boolean | No | When `true`, charges are passed to customer. Default: `false` |
| `is_recurring` | Boolean | No | When `true`, tokenizes the card and returns `token_id` in webhook |

### Sample Request

```json
{
    "amount": 200000,
    "email": "user@example.com",
    "currency": "NGN",
    "initiate_type": "inline",
    "transaction_ref": "bck_pro_a1b2c3d4e5f6g7h8",
    "callback_url": "https://app.bitcheck.ai/billing/success",
    "payment_channels": ["card"],
    "is_recurring": true
}
```

### Responses

**200 OK — Success:**

```json
{
    "status": 200,
    "message": "success",
    "data": {
        "auth_url": null,
        "access_token": null,
        "merchant_info": {
            "merchant_response": null,
            "merchant_name": null,
            "merchant_logo": null,
            "merchant_id": "SBN1EBZEQ8"
        },
        "currency": "NGN",
        "recurring": {
            "frequency": null,
            "duration": null,
            "type": 0,
            "plan_code": null,
            "customer_name": null
        },
        "is_recurring": true,
        "callback_url": "https://app.bitcheck.ai/billing/success",
        "transaction_ref": "bck_pro_a1b2c3d4e5f6g7h8",
        "transaction_amount": 200000,
        "authorized_channels": ["card"],
        "checkout_url": "https://sandbox-pay.squadco.com/bck_pro_a1b2c3d4e5f6g7h8"
    }
}
```

**401 Unauthorized:**

```json
{
    "status": 401,
    "message": "Initiate transaction Unauthorized",
    "data": null
}
```

**400 Bad Request:**

```json
{
    "status": 400,
    "success": false,
    "message": "email is required",
    "data": {}
}
```

### Webhook Response (After Successful Tokenized Payment)

When the user completes payment on the checkout page, Squad sends a webhook to our endpoint with the card token:

```json
{
    "Event": "charge_successful",
    "TransactionRef": "SQTECH6389058547434300003",
    "Body": {
        "amount": 200000,
        "transaction_ref": "bck_pro_a1b2c3d4e5f6g7h8",
        "gateway_ref": "SQTECH6389058547434300003_1_6_1",
        "transaction_status": "Success",
        "email": "user@example.com",
        "merchant_id": "SBSJ3KMH",
        "currency": "NGN",
        "transaction_type": "Card",
        "merchant_amount": 198000,
        "created_at": "2026-05-12T10:51:14.368",
        "meta": {},
        "payment_information": {
            "payment_type": "card",
            "pan": "509983******3911|1027",
            "card_type": "mastercard",
            "token_id": "AUTH_lBlGESHDLMX_60049043"
        },
        "is_recurring": true
    }
}
```

The `token_id` (`AUTH_lBlGESHDLMX_60049043`) is what we store for future recurring charges.

---

## 2. Charge Card (Recurring)

`POST https://sandbox-api-d.squadco.com/transaction/charge_card`

This endpoint debits a previously tokenized card using the `token_id` received from the initial payment webhook. No checkout page is needed — it's a server-to-server charge.

**Why we use it:** To auto-renew Pro subscriptions each billing cycle without the user re-entering card details.

**Where it's called:** `apps/billing/services.py` → `charge_card_recurring()`

> For recurring payment testing on Sandbox, use the test card: `5200000000000007`

### Parameters

**Body:**

| Field | Type | Required | Description |
|---|---|---|---|
| `amount` | Integer | Yes | Amount to charge in lowest currency unit (kobo) |
| `token_id` | String | Yes | Tokenization code returned via webhook from initial payment |
| `transaction_ref` | String | No | Unique transaction reference |

### Sample Request

```json
{
    "amount": 200000,
    "token_id": "AUTH_lBlGESHDLMX_60049043",
    "transaction_ref": "bck_renew_a1b2c3d4e5f6g7h8"
}
```

### Responses

**200 OK — Success:**

```json
{
    "status": 200,
    "success": true,
    "message": "Success",
    "data": {
        "transaction_amount": 200000,
        "transaction_ref": "bck_renew_a1b2c3d4e5f6g7h8",
        "email": "user@example.com",
        "transaction_status": "success",
        "transaction_currency_id": "NGN",
        "created_at": "2026-05-12T10:51:14.368",
        "transaction_type": "Card",
        "merchant_name": "Bitcheck AI",
        "gateway_transaction_ref": "SQTECH638905854743430003"
    }
}
```

**400 Bad Request:**

```json
{
    "status": 400,
    "success": false,
    "message": "amount cannot be < 0",
    "data": {}
}
```

---

## 3. Cancel Recurring Authorization

`PATCH https://sandbox-api-d.squadco.com/transaction/cancel/recurring`

This endpoint cancels active card token authorizations, revoking the ability to charge the card in the future.

**Why we use it:** When a user cancels their Pro subscription, we revoke the card token so we can no longer charge their card.

**Where it's called:** `apps/billing/services.py` → `cancel_card_token()`

### Parameters

**Body:**

| Field | Type | Required | Description |
|---|---|---|---|
| `auth_code` | Array | Yes | Array of token IDs to cancel (from the initial tokenized payment webhook) |

### Sample Request

```json
{
    "auth_code": [
        "AUTH_lBlGESHDLMX_60049043"
    ]
}
```

### Responses

**200 OK — Success:**

```json
{
    "status": 200,
    "success": true,
    "message": "Success",
    "data": {
        "auth_code": [
            "AUTH_lBlGESHDLMX_60049043"
        ]
    }
}
```

**400 Bad Request:**

```json
{
    "status": 400,
    "success": false,
    "message": "Recurring Payment was not cancelled",
    "data": {}
}
```

---

## 4. Create Business Virtual Account

`POST https://sandbox-api-d.squadco.com/virtual-account/business`

This endpoint creates a dedicated virtual bank account for a business. The B2B model is designed for merchant-to-merchant use cases where businesses (not individual consumers) need a permanent account number for receiving bank transfers.

**Why we use it:** Our B2B organizations need a dedicated account number to top up their bit wallets via bank transfer. When funds are sent to the virtual account, Squad sends a webhook and we convert the deposit to bits.

**Where it's called:** `apps/bits/va_services.py` → `provision_virtual_account()`

> You must request profiling from Squad before you can create business virtual accounts. Contact Squad support for sandbox access.

### Parameters

**Body:**

| Field | Type | Required | Description |
|---|---|---|---|
| `bvn` | String | Yes | Bank Verification Number |
| `business_name` | String | Yes | Name of the business/customer |
| `customer_identifier` | String | Yes | Alphanumeric string to identify the customer/business in your system, tied to the virtual account |
| `mobile_num` | String | Yes | Customer's phone number (max 11 digits). Example: `08012345678` |
| `beneficiary_account` | String | No | 10-digit GTBank account where funds are settled. If not provided, funds go to your Squad wallet (T+1 settlement) |

### Sample Request

```json
{
    "customer_identifier": "acme-corp",
    "business_name": "Acme Corp Limited",
    "mobile_num": "08139011943",
    "bvn": "22110011001",
    "beneficiary_account": "4920299492"
}
```

### Responses

**200 OK — Success:**

```json
{
    "status": 200,
    "success": true,
    "message": "Success",
    "data": {
        "first_name": "Acme-Corp",
        "last_name": "Limited",
        "bank_code": "058",
        "virtual_account_number": "2474681469",
        "beneficiary_account": "4920299492",
        "customer_identifier": "acme-corp",
        "created_at": "2026-05-10T13:18:21.287Z",
        "updated_at": "2026-05-10T13:18:21.287Z"
    }
}
```

**400 Bad Request:**

```json
{
    "status": 400,
    "success": false,
    "message": "\"customer_identifier\" is required",
    "data": {}
}
```

**401 Unauthorized:**

```json
{
    "success": false,
    "message": "",
    "data": {}
}
```

**403 Forbidden (not profiled for B2B):**

```json
{
    "success": false,
    "message": "Merchant authentication failed",
    "data": {}
}
```

**424 Failed Dependency (wrong account number):**

```json
{
    "success": false,
    "message": "Validation Failure No record found for Account number- 1237398433",
    "data": {}
}
```

---

## 5. Simulate Payment (Sandbox Only)

`POST https://sandbox-api-d.squadco.com/virtual-account/simulate/payment`

This endpoint simulates a bank transfer into a virtual account in the sandbox environment. It triggers Squad to send a webhook notification as if a real bank transfer occurred.

**Why we use it:** In sandbox mode, no real bank transfers can happen. This lets us test the end-to-end flow: simulate deposit → Squad fires webhook → our backend credits bits to the org wallet.

**Where it's called:** `apps/bits/views.py` → `simulate_payment_view()`

### Parameters

**Body:**

| Field | Type | Required | Description |
|---|---|---|---|
| `virtual_account_number` | String | Yes | The virtual account number to receive the simulated payment |
| `amount` | String | Yes | Amount in naira (e.g., `"20000"` = NGN 20,000) |

### Sample Request

```json
{
    "virtual_account_number": "2474681469",
    "amount": "20000"
}
```

### Responses

**200 OK — Success:**

```json
{
    "status": 200,
    "success": true,
    "message": "Success",
    "data": "Payment successful"
}
```

**400 Bad Request:**

```json
{
    "status": 400,
    "success": false,
    "message": "amount is required",
    "data": {}
}
```

### Webhook Triggered After Simulate

After a successful simulate call, Squad sends a webhook to our configured URL with this payload:

```json
{
    "transaction_reference": "REF4XFKAVZHT1778630602161",
    "virtual_account_number": "2474681469",
    "principal_amount": "20000.00",
    "settled_amount": "20000.00",
    "fee_charged": "0.00",
    "transaction_date": "2026-05-12T10:30:02.161Z",
    "customer_identifier": "acme-corp",
    "transaction_indicator": "C",
    "remarks": "Simulated Payment",
    "currency": "NGN",
    "channel": "virtual-account",
    "sender_name": "Test Sender",
    "encrypted_body": "hmac_sha512_hash_of_body"
}
```

Our webhook handler (`apps/webhooks/views.py`) receives this, verifies the signature using `encrypted_body`, looks up the organization by `customer_identifier`, converts NGN to bits, and credits the wallet.

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `SQUAD_SECRET_KEY` | Yes | API secret key (`sandbox_sk_...` or `squad_sk_...`) |
| `SQUAD_WEBHOOK_SECRET` | Yes | HMAC key for verifying webhook signatures |
| `SQUAD_BASE_URL` | Yes | `https://sandbox-api-d.squadco.com` (sandbox) or `https://api-d.squadco.com` (production) |
| `SQUAD_BENEFICIARY_ACCOUNT` | Sandbox | Required for VA provisioning in sandbox |
| `SQUAD_VA_DEV_MOCK` | No | Set `True` to mock VA provisioning locally |
| `SQUAD_CHECKOUT_DEV_MOCK` | No | Set `True` to mock checkout URL locally |

---

## Going Live

To switch from sandbox to production:

1. Change `SQUAD_BASE_URL` from `https://sandbox-api-d.squadco.com` to `https://api-d.squadco.com`
2. Sign up on Squad's live environment
3. Complete KYC verification
4. Replace the sandbox secret key with the production secret key from the live dashboard
5. Update `SQUAD_WEBHOOK_SECRET` with the production webhook secret
