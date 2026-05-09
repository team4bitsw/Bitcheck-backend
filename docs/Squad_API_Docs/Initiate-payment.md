### Initiate Payment

This API lets you initiate transactions by making server calls that return a checkout URL. When visited, this URL will display our payment modal.

**Environment Base URLs**

- **Test**: `https://sandbox-api-d.squadco.com`
- **Production**: `https://api-d.squadco.com`

Authorization keys are to be passed via Headers as a Bearer token.  
**Example**: `Authorization: Bearer sandbox_sk_94f2b798466408ef4d19e848ee1a4d1a3e93f104046f`

> The transaction reference used to initiate transactions must be unique.

## Initiate Transaction

**POST**  
`https://sandbox-api-d.squadco.com/transaction/initiate`

This endpoint returns a checkout URL that when visited calls up the modal with the various payment channels.

### Parameters

#### Headers

| Field          | Type   | Description |
|----------------|--------|-----------|
| `Authorization`* | String | API keys (Secret Key) that authorize your transactions and gotten from your Squad dashboard |

#### Body

| Field                | Type     | Description |
|----------------------|----------|-----------|
| `email`*             | String   | Customer's email address |
| `amount`*            | String   | The amount you are debiting customer (expressed in the lowest currency value - kobo for NGN). 10000 = 100 NGN |
| `initiate_type`*     | String   | This states the method by which the transaction is initiated. At the moment, this can only take the value `'inline'` |
| `currency`*          | String   | The currency you want the amount to be charged in. Allowed values: `NGN` or `USD` |
| `transaction_ref`    | String   | The merchant defined reference, unique for each transaction (where none is passed, a system-generated reference will be created) |
| `customer_name`      | String   | Name of Customer carrying out the transaction |
| `callback_url`       | String   | A web address where customers are redirected after payment completion |
| `payment_channels`   | Array    | An array of payment channels to control what channels you want to make available. Available: `['card', 'bank', 'ussd', 'transfer']` |
| `metadata`           | Object   | Object that contains any additional information that you want to record with the transaction |
| `pass_charge`        | Boolean  | `True` or `False`. When `True`, charges are passed to the customer. Default is `False` |
| `sub_merchant_id`    | String   | ID of a sub-merchant (for aggregators only) |

### Responses

**200: OK** - Successful

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
        "is_recurring": false,
        "plan_code": null,
        "callback_url": "http://squadco.com",
        "transaction_ref": "4678388588350909090AH",
        "transaction_memo": null,
        "transaction_amount": 43000,
        "authorized_channels": ["card", "ussd", "bank"],
        "checkout_url": "https://sandbox-pay.squadco.com/4678388588350909090AH"
    }
}
```

**401: Unauthorized**

```json
{
    "status": 401,
    "message": "Initiate transaction Unauthorized",
    "data": null
}
```

**400: Bad Request**

```json
{
    "status": 400,
    "success": false,
    "message": "email is required",
    "data": {}
}
```

### Sample Request

```json
{
    "amount": 43000,
    "email": "henimastic@gmail.com",
    "currency": "NGN",
    "initiate_type": "inline",
    "transaction_ref": "4678388588350909090AH",
    "callback_url": "http://squadco.com"
}
```

## Simulate Test Payment (Transfer)

In the test environment, when the transfer option is selected on the payment modal, a dynamic virtual account is created. To complete the transaction, a simulated payment is required.

**POST**  
`https://sandbox-api-d.squadco.com/virtual-account/simulate/payment`

This endpoint allows you to simulate a payment into an account.

### Parameters

#### Headers

- `Authorization`* — API Secret Key

#### Body

| Field                     | Type    | Description |
|---------------------------|---------|-----------|
| `virtual_account_number`* | Integer | Generated Dynamic Virtual Account from the Transfer modal |
| `amount`*                 | Integer | The amount to be paid |

### Responses

**200: OK** - Successful

```json
{
    "status": 200,
    "success": true,
    "message": "Success",
    "data": "Payment successful"
}
```

**400: Bad Request**

```json
{
    "status": 400,
    "success": false,
    "message": "amount is required",
    "data": {}
}
```

### Sample Request

```json
{
    "virtual_account_number": "9279755518",
    "amount": "20000"
}
```

## Recurring Payment (Charge Authorization on Card)

This allows you to charge a card without collecting the card information each time.

> **Tip**: For recurring Payments test on Sandbox, ensure to use the test card: `5200000000000007`

### Card Tokenization

To tokenize a card, add `"is_recurring": true` to the initiate payload. The unique token code will be returned in the webhook notification.

#### Sample Request for Card Tokenization

```json
{
    "amount": 43000,
    "email": "henimastic@gmail.com",
    "currency": "NGN",
    "initiate_type": "inline",
    "transaction_ref": "bchs4678388588350909090AH",
    "callback_url": "http://squadco.com",
    "is_recurring": true
}
```

#### Sample Webhook Response For Tokenized Card

```json
{
    "Event": "charge_successful",
    "TransactionRef": "SQTECH6389058547434300003",
    "Body": {
        "amount": 11000,
        "transaction_ref": "SQTECH6389058547434300003",
        "gateway_ref": "SQTECH6389058547434300003_1_6_1",
        "transaction_status": "Success",
        "email": "william@gmail.com",
        "merchant_id": "SBSJ3KMH",
        "currency": "NGN",
        "transaction_type": "Card",
        "merchant_amount": 868,
        "created_at": "2025-08-12T10:51:14.368",
        "meta": {
            "details": "level1",
            "location": "Lagos"
        },
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

## Charge Card

**POST**  
`https://sandbox-api-d.squadco.com/transaction/charge_card`

This debits a credit card using the `token_id`.

### Parameters

| Field            | Type    | Description |
|------------------|---------|-----------|
| `amount`*        | Integer | Amount to charge from card (in lowest currency unit) |
| `token_id`*      | String  | Tokenization code returned via webhook |
| `transaction_ref`| String  | Unique transaction reference |

### Responses

**200: OK** - Successful

```json
{
    "status": 200,
    "success": true,
    "message": "Success",
    "data": {
        "transaction_amount": 0,
        "transaction_ref": null,
        "email": null,
        "transaction_status": null,
        "transaction_currency_id": null,
        "created_at": "0001-01-01T00:00:00",
        "transaction_type": null,
        "merchant_name": null,
        "merchant_business_name": null,
        "gateway_transaction_ref": null,
        "recurring": null,
        "merchant_email": null,
        "plan_code": null
    }
}
```

**400: Bad Request**

```json
{
    "status": 400,
    "success": false,
    "message": "amount cannot be < 0",
    "data": {}
}
```

### Sample Request

```json
{
    "amount": 10000,
    "token_id": "tJlYMKcwPd"
}
```

## Cancel Charge Card

**PATCH**  
`https://sandbox-api-d.squadco.com/transaction/cancel/recurring`

This endpoint cancels active tokens.

### Parameters

| Field       | Type   | Description |
|-------------|--------|-----------|
| `auth_code`* | String | Token ID sent via webhook at first tokenized call |

### Responses

**200: OK** - Successful

```json
{
    "status": 200,
    "success": true,
    "message": "Success",
    "data": {
        "auth_code": [
            "AUTH_lBlGXSHDLMX_63749043"
        ]
    }
}
```

**400: Bad Request**

```json
{
    "status": 400,
    "success": false,
    "message": "Recurring Payment was not cancelled",
    "data": {}
}
```

### Sample Request

```json
{
    "auth_code": [
        "AUTH_SlYtufQzy_452037"
    ]
}
```

## Query All Transactions

**GET**  
`https://sandbox-api-d.squadco.com/transaction`

This endpoint allows you to query all transactions and filter using multiple parameters.

> **Caution**: The `start_date` and `end_date` parameters are compulsory and should have a maximum of one month gap.

### Query Parameters

| Parameter     | Type    | Description |
|---------------|---------|-----------|
| `currency`    | String  | Transacting currency |
| `start_date`* | Date    | Start date of transaction |
| `end_date`*   | Date    | End date of transaction |
| `page`        | Integer | Page number |
| `perpage`     | Integer | Number of transactions per page |
| `reference`   | String  | Transaction reference |

### Responses

**200: OK** - Success

```json
{
    "status": 200,
    "success": true,
    "message": "Success",
    "data": [
        {
            "id": 589,
            "transaction_amount": 500000,
            "transaction_ref": "SQDEMO6384411820295800001",
            "email": "demo@merchant.com",
            "merchant_id": "AABBCCDDEEFFGGHHJJKK",
            "merchant_amount": 495000,
            "transaction_status": "success",
            "transaction_type": "Card",
            "created_at": "2024-02-21T13:16:43.012+00:00"
        }
    ]
}
```

## Go Live

To go live, simply:

1. Change the base URL of your endpoints from `sandbox-api-d.squadco.com` to `api-d.squadco.com`
2. Sign up on our Live Environment
3. Complete your KYC
4. Use the secret key provided on the dashboard to replace the test keys gotten from the sandbox environment to authenticate your live transactions