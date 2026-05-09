### Direct Debit Flow

The direct debit service works by applying Mandates to an account. A mandate is an authorized instruction that permits an account to be debited up to a specific amount within a defined duration.

**Flow Summary**

- Creating a Mandate on an account
- Account Holder approving the mandate on the account
- Debiting the account using the created mandate

## Get Bank List

**POST**  
`https://sandbox-api-d.squadco.com/transaction/mandate/banklists`

This endpoint retrieves a list of all banks for which the Direct Debit service is available. The list returned is dynamic, and mandates can only be created for returned banks.

### Sample BankList Response

```json
{
    "status": 200,
    "success": true,
    "message": "Success",
    "data": [
        {
            "bank_name": "ACCESS BANK PLC",
            "bank_code": "044",
            "isActive": true
        },
        {
            "bank_name": "ECOBANK NIGERIA PLC",
            "bank_code": "050",
            "isActive": true
        },
        {
            "bank_name": "FIDELITY BANK PLC",
            "bank_code": "070",
            "isActive": true
        },
        {
            "bank_name": "FIRST BANK OF NIGERIA PLC",
            "bank_code": "011",
            "isActive": true
        },
        {
            "bank_name": "GUARANTY TRUST BANK PLC",
            "bank_code": "058",
            "isActive": true
        },
        {
            "bank_name": "Kuda Microfinance Bank",
            "bank_code": "672",
            "isActive": true
        }
    ]
}
```

## Create Mandate

**POST**  
`https://sandbox-api-d.squadco.com/transaction/mandate/create`

This endpoint allows you to create a mandate for an account.

### Parameters

#### Create Mandate

| Field                  | Type     | Description |
|------------------------|----------|-----------|
| `mandate_type`*        | String   | The type of mandate to be used, always set to `emandate` (electronic mandate) |
| `amount`*              | Integer  | The total amount in kobo to be debited throughout the mandate cycle (expressed in the lowest currency value - kobo). 10000 = 100 NGN |
| `account_number`*      | Integer  | The account number of customer to be mandated |
| `bank_code`*           | String   | Unique NIP code that identifies a bank |
| `description`*         | String   | Merchant description of the transaction |
| `start_date`*          | Date     | Start date for the mandate, YYYY-MM-DD |
| `end_date`*            | Date     | End date for the mandate, YYYY-MM-DD |
| `customer_email`*      | String   | Email of customer whose account is to be mandated. A notification will be sent to the customer |
| `transaction_reference`| String   | Unique reference number for each mandate. Where not provided, the system generates one |
| `customerInformation`* | Object   | The customerInformation collects relevant customer information for mandate creation |
| `identity`*            | Object   | Identity is a nested object inside the customerInformation object where value of type is bvn and number is the customer bvn number |
| `firstName`*           | String   | Customer first name, must match with BVN details |
| `lastName`*            | String   | Customer last name, must match with BVN details |
| `address`*             | String   | Customer address |
| `phone`*               | Integer  | Customer phone number, must match with BVN details |

### Responses

**200: Success** - Mandate Created

```json
{
    "status": 200,
    "success": true,
    "message": "Success",
    "data": {
        "message": "Kindly authorise this mandate by transferring N50.00 from your GTB TESTING to Account Number: \"9880218357\" Bank: Paystack Titan or Account Number: \"9020025928\" Bank: Fidelity",
        "mandate_id": "sqaudDD63a5fqsowsy57ic0h5eps25k28e",
        "mandate_type": "emandate",
        "debit_type": "variable",
        "status": "initiated",
        "approved": false,
        "ready_to_debit": false,
        "reference": "livepilot0260118",
        "account_number": "2473064070",
        "description": "20kish pilot slive",
        "start_date": "2025-08-27T00:00:00",
        "end_date": "2026-01-20T00:00:00",
        "date": "2025-08-06T15:19:55.2910043+00:00",
        "transfer_destinations": [
            {
                "bank_name": "Paystack Titan",
                "account_number": "9880218357",
                "icon": "https://mono-public-bucket.s3.eu-west-2.amazonaws.com/images/paystack-icon.png"
            },
            {
                "bank_name": "Fidelity",
                "account_number": "9020025928",
                "icon": "https://mono-public-bucket.s3.eu-west-2.amazonaws.com/images/fidelity-bank-icon.png"
            }
        ]
    }
}
```

**400: Bad Request**

```json
{
    "status": 400,
    "success": false,
    "message": "Customer already exists with the same email address.",
    "data": {}
}
```

### Sample Request

```json
{
    "mandate_type": "emandate",
    "amount": "2000000",
    "account_number": "2473064070",
    "bank_code": "050",
    "description": "20kish pilot slive",
    "start_date": "2025-08-27",
    "end_date": "2026-01-20",
    "customer_email": "willia@gmail.com",
    "transaction_reference": "livepilot0260118",
    "customerInformation": {
        "identity": {
            "type": "bvn",
            "number": "22984135000"
        },
        "firstName": "william",
        "lastName": "udousoro",
        "address": "no 11 claytus street sabo yaba",
        "phone": "08132448008"
    }
}
```

### Webhook Notification For Mandate Creation

```json
{
    "Event": "mandates.approved",
    "TransactionRef": "livepilot0260118",
    "Body": {
        "status": "approved",
        "mandate_type": "emandate",
        "debit_type": "variable",
        "ready_to_debit": false,
        "approved": true,
        "reference": "livepilot0260118",
        "account_name": "william udousoro",
        "account_number": "0179088393",
        "bank": "GTB TESTING",
        "message": "Mandate approved",
        "start_date": "2025-08-27T00:00:00Z",
        "end_date": "2026-01-20T22:59:59.999Z",
        "date": "2025-08-06T12:01:40.416Z",
        "amount": 2000000,
        "business": "673c6efe9c0a66056f27b19a",
        "merchantId": "SBBWRX1Z3S",
        "mandate_id": "sqaudDDa27chviz8nwhv3d6w4gy"
    }
}
```

> **Note**: Due to the limitations of the Sandbox environment, 24 hours must be allowed to pass after creating the mandate before the Mandate can be debited. Another Webhook will be sent once the account can be debited.

### Webhook Notification for Approved Mandate

```json
{
    "Event": "mandates.ready",
    "TransactionRef": "livepilot0260118",
    "Body": {
        "status": "approved",
        "mandate_type": "emandate",
        "debit_type": "variable",
        "ready_to_debit": true,
        "approved": true,
        "reference": "livepilot0260118",
        "account_name": "william udousoro",
        "account_number": "0179088393",
        "bank": "GTB TESTING",
        "message": "Mandate is now ready for debiting",
        "start_date": "2025-08-27T00:00:00Z",
        "end_date": "2026-01-22T22:59:59.999Z",
        "date": "2025-08-04T13:45:28.1Z",
        "amount": 20000000,
        "business": "673c6efe9c0a66056f27b19a",
        "merchantId": "SBBWRX1Z3S",
        "mandate_id": "sqaudDD39cf95ohb3702mre87tj23"
    }
}
```

## Debit Mandate

**POST**  
`https://sandbox-api-d.squadco.com/transaction/mandate/debit`

This endpoint allows you to debit an account where a mandate has been created.

### Parameters

#### Debit Mandate

| Field                  | Type      | Description |
|------------------------|-----------|-----------|
| `amount`*              | Integer   | Amount to be debited from account |
| `mandate_id`*          | String    | `mandate_id` gotten in response from Creating the Mandate |
| `transaction_reference`* | String | Narration of debit |
| `pass_charge`*         | Boolean   | Pass charges to customers by setting to True |
| `customer_email`*      | Email     | Customer email address to be notified |

> **Note**: Debits can only occur once a day.

### Responses

**200: Success** - Debit Successful

```json
{
    "status": 200,
    "success": true,
    "message": "Success",
    "data": {
        "status": "Success",
        "aamount": 50000,
        "mandate_id": "sqaudDDf99ae9mtizerna8f",
        "transaction_reference": "super323",
        "date": "2025-08-06T12:00:37.1440078+00:00",
        "account": {
            "bank_code": "044",
            "account_name": "william udousoro",
            "account_number": "0179088393"
        }
    }
}
```

**400: Mandate Not Ready**

```json
{
    "status": 400,
    "success": false,
    "message": "Mandate on account 0179088393 is not ready for debit.",
    "data": {}
}
```

**400: Limit Reached**

```json
{
    "status": 400,
    "success": false,
    "message": "Daily debit limit reached for mandate sqaudDDf99ae9mtizerna8f, please try again tomorrow.",
    "data": {}
}
```

**400: Over Debit**

```json
{
    "status": 400,
    "success": false,
    "message": "Mandate on account 0179088393 balance is lesser than debit amount.",
    "data": {}
}
```

### Sample Request

```json
{
    "amount": 50000,
    "mandate_id": "sqaudDDa27chviz8nwhv3d6w4gy",
    "transaction_reference": "super32333",
    "narration": "test2004",
    "pass_charge": false,
    "customer_email": "willia@gmail.com"
}
```

### Webhook Notification

```json
{
    "Event": "charge_successful",
    "TransactionRef": "super32333",
    "Body": {
        "amount": 50000,
        "transaction_ref": "super32333",
        "gateway_ref": "super32333_2_2_1",
        "transaction_status": "Success",
        "email": "williamudousoro@gmail.com",
        "merchant_id": "SBBWRX1Z3S",
        "currency": "NGN",
        "transaction_type": "Bank",
        "merchant_amount": 49500,
        "created_at": "2025-08-06T13:00:37.128",
        "meta": {},
        "is_recurring": false
    }
}
```

## Cancel Mandate

**POST**  
`https://sandbox-api-d.squadco.com/transaction/mandate/cancel`

This endpoint allows you to cancel a mandate on the account.

### Parameters

#### Cancel Mandate

- `mandateIds`* (Object) — `mandateIds` is an object where a single or multiple mandate Ids can be passed.

### Responses

**Success** - Mandate Cancelled

```json
{
    "status": 200,
    "success": true,
    "message": "Success",
    "data": {
        "canceledMandates": [
            "sqaudDDf99ae9mtizerna8f"
        ],
        "failedMandates": []
    }
}
```

**Failed**

```json
{
    "status": 200,
    "success": true,
    "message": "Success",
    "data": {
        "canceledMandates": [],
        "failedMandates": [
            {
                "mandateId": "sqaudDDf99ae9mtizerna8f",
                "failureReason": "Mandate already cancelled"
            }
        ]
    }
}
```

### Sample Request

```json
{
    "mandateIds": [
        "sqaudDD657al1hrep7m4bc",
        "sqaudDD5c9elxp61u3sju",
        "sqaudDD5c9elxp61u3sju"
    ]
}
```

## Get Mandate By Ref

**GET**  
`https://sandbox-api-d.squadco.com/transaction/mandate/get-mandates/:Ref`

This endpoint allows you to get details of a mandate by passing the Reference of that mandate.

### Responses

**Success** - Mandate Ref Details

```json
{
    "status": 200,
    "success": true,
    "message": "Success",
    "data": [
        {
            "start_date": "2025-08-31T00:00:00",
            "end_date": "2026-01-22T00:00:00",
            "account_number": "0179088393",
            "account_name": "william udousoro",
            "bankName": "Standard Chartered",
            "bank": "068",
            "ready_to_debit": true,
            "is_approved": true,
            "status": "approved",
            "merchant_reference": "workinornot242",
            "mandate_type": "emandate",
            "debit_type": "variable",
            "merchant_id": "SBBWRX1Z3S",
            "amount": 20000000,
            "balance": 20000000,
            "total_debited": 0
        }
    ]
}
```

**404: Not Found**

```json
{
    "status": 400,
    "success": false,
    "message": "No mandate found for reference workinornot242",
    "data": {}
}
```

**403: Forbidden**

```json
{
    "success": false,
    "message": "API key is empty or invalid. Key must start with sandbox_sk_",
    "data": {}
}
```

**401: Unauthorized**

```json
{
    "success": false,
    "message": "",
    "data": {}
}
```

## Go Live

To go live, simply:

1. Change the base URL of your endpoints from `sandbox-api-d.squadco.com` to `api-d.squadco.com`
2. [Sign up on our Live Environment](https://dashboard.squadco.com/login)
3. Complete your KYC
4. Use the secret key provided on the dashboard to replace the test keys gotten from the sandbox environment to authenticate your live transactions.