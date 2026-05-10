Virtual Accounts
The Squad Virtual Accounts API allows you to create customized fly-through accounts for receiving payments from your customers. The virtual accounts help businesses reserve their corporate bank account numbers.
caution

You must create a Sandbox account to test all integrations before going live.

    Create an account on our sandbox environment
    Retrieve keys from the Merchant settings Page, under the API & Webhook tab.

Authorization: Any request made without the authorization key will fail with a 401 (Service Not Authorized) response code.
info

Environment base URL:

Test: https://sandbox-api-d.squadco.com

Production: https://api-d.squadco.com

Authorization keys are to be passed via Headers as a Bearer token.

Example: Authorization: Bearer sandbox_sk_94f2b798466408ef4d19e848ee1a4d1a3e93f104046f
Explore

Virtual accounts serve as an additional payment channel for your business, allowing customers to pay directly to the account number assigned to them. Whenever money is sent to a dedicated virtual account, you will receive a notification through your webhook URL, and the amount will be instantly credited to your specified GTBank physical account.

These notifications will be sent to your webhook URL, enabling your servers to take the necessary actions related to the payment within your system.

To explore all the possibilities available with the Virtual Accounts API, please refer to our API documentation.

---

API Specifications
Specification For Virtual Accounts

The Squad Virtual Accounts API allows you to create customized fly-through accounts for receiving payments from your customers. The virtual accounts help businesses reserve their corporate bank account numbers.

Each account is assigned a unique customer identifier to facilitate the identification of payments and ensure smooth reconciliation.
caution

Please note that to create virtual accounts, your settlement account must be a GTBank Account.

Additionally, kindly provide your preferred prefix to your Technical Account Manager for account configuration before going live. The prefix should be a part or abbreviation of your business name written as one word.
Customer Model

This is a Business to Customer(B2C) model used to create virtual accounts for individuals or customers on your platform. It's important to note that there is a strict validation process for the Bank Verification Number (BVN) against the provided name, date of birth, gender, and phone number.

This means that if any of the details mentioned do not match what is registered on the BVN portal, an account will not be created.
POST
https://sandbox-api-d.squadco.com/virtual-account
Creating Virtual Accounts for Customers

Fields marked with an asterisk (*) are mandatory.
Parameters
Body

first_name*

String

customer first name

last_name*

String

customer last name

middle_name

String

customer middle name

mobile_num*

String

08012345678 (doesn't take more than 11 digits)

dob*

Date

mm/dd/yyyy

email

String

customer email

bvn*

String

BVN is compulsory

gender*

String

'1' - Male, '2' -Female

address*

String

customer address

customer_identifier*

String

unique customer identifier as given by merchant

beneficiary_account

String

Beneficiary Account is the 10 Digit Bank Account Number (GTBank) provided by the Merchant where money sent to this Virtual account is paid into. Please note that when beneficiary account is not provided, money paid into this virtual account go into your wallet and will be paid out/settled in T+1 settlement time.
Sample Request

{
    "customer_identifier": "SQUAD_101",
    "first_name": "Joesph",
    "last_name": "Ayodele",
    "mobile_num": "08123456789",
    "email": "ayo@squadco.com",
    "bvn": "22343211654",
    "dob": "07/19/1990",
    "address": "22 Kota street, UK",
    "gender": "1",
    "beneficiary_account": "4920299492"
}

Responses
200:OK
Success Response

{
    "success": true,
    "message": "Success",
    "data": {
        "first_name": "Joesph",
        "last_name": "Ayodele",
        "bank_code": "058",
        "virtual_account_number": "7834927713",
        "beneficiary_account": "4920299492",
        "customer_identifier": "CCC",
        "created_at": "2022-03-29T13:17:52.832Z",
        "updated_at": "2022-03-29T13:17:52.832Z"
    }
}

401:Validation Error
Validation Error

{
    "status": 400,
    "success": false,
    "message": "Validation Failure, Customer identifier is required",
    "data": {}
}

401:Unauthorized
No Authorization

{
            "success": false,
            "message": "",
            "data": {}
}

403:Forbidden
Invalid/Wrong API keys

{
            "success": false,
            "message": "Merchant authentication failed",
            "data": {}
}

Business Model

The Business to Business(B2B) model enables you to create virtual accounts specifically for your business customers, rather than individual users. In other words, these customers are businesses (B2B) or other merchants.

Please be aware that, in accordance with the CBN's guidelines regarding validation prior to account creation, as well as concerns related to fraud, you must request profiling before you can create accounts for businesses.

Once you have completed the profiling process, you will be able to proceed with creating accounts for your business clients.
Sample Request

{
    "customer_identifier": "SQUAD_101,
    "business_name": "Habaripay Limited",
    "mobile_num": "08139011943",
    "bvn": "22110011001",
    "beneficiary_account": "4920299492"
}

POST
https://sandbox-api-d.squadco.com/virtual-account/business
Creating Virtual Account for businesses
Parameters
Body

bvn*

String

Bank Verification Number

business_name*

String

Name of Business/Customer

customer_identifier*

String

An alphanumeric string used to identify a customer/business in your system which will be tied to the virtual account being created

mobile_num*

String

Customer's Phone Number Sample: 08012345678 (doesn't take more than 11 digits)

beneficiary_account

Date

Beneficiary Account is your 10 Digit Bank Account Number (GTBank) where money sent to this Virtual account is paid into. Please note that when beneficiary account is not provided, money paid into this virtual account go into your wallet and will be paid out/settled in T+1 settlement time.
Responses
200:OK
Success

{
            "status": 200,
            "success": true,
            "message": "Success",
            "data": {
                "first_name": "Techzilla-Will",
                "last_name": "Okoye",
                "bank_code": "058",
                "virtual_account_number": "2474681469",
                "beneficiary_account": null,
                "customer_identifier": "Tech910260",
                "created_at": "2023-08-07T13:18:21.287Z",
                "updated_at": "2023-08-07T13:18:21.287Z"
            }
}

400:Bad Request
Bad Request

{
            "status": 400,
            "success": false,
            "message": ""customer_identifier" is required",
            "data": {}
}

401:Unauthorized
No API key

{
            "success": false,
            "message": "",
            "data": {}
}

403:Forbidden
Invalid Authorization key or token

{
            "success": false,
            "message": "Merchant authentication failed",
            "data": {}
}

424: Failed Dependency
Wrong Account Number

{
      "success": false,
      "message": "Validation Failure No record found for Account number- 1237398433",
      "data": {
        "first_name": null,
        "last_name": null,
        "bank_code": null,
        "virtual_account_number": null,
        "beneficiary_account": null,
        "customer_identifier": null,
        "created_at": "0001-01-01T00:00:00",
        "updated_at": "0001-01-01T00:00:00"
      },
      "status": "424"
}

Transaction Notification Service

After registering and verifying your account as a merchant, you need to create a POST Webhook endpoint. Then, enter the URL for this webhook in the "Webhook URL" field under the API & Webhook tab in the Merchant Settings of your Squad Dashboard. This will allow you to receive notifications about payments.
caution

Ensure that you have a duplicate transaction checker when implementing webhooks to prevent double transactions.

WEBHOOK: If a webhook is not provided, notifications won't be sent.

You are required to confirm receipt of the webhook request. If you do not respond, the notification will be logged in the error log service.
Expected webhook response

    200: Successful
    400: Validation Failure
    500: System Malfunction

{
    response_code:200,
    transaction_reference: 'unique reference sent through the post',
    response_description: 'Success'
}

Webhook Validation --version 1
Method 1 (Hash Comparison)

The webhook notification sent includes the x-squad-signature in the header. This signature is an HMAC of the notification body, created using your secret key.

You need to generate a hash and compare it to the value of the hash included in the header of the POST request sent to your webhook URL.

To create the hash, use the entire notification body that is sent via the webhook.
Sample Implementations

    C#
    Javascript (Node)
    PHP
    Java

using System;
using System.Security.Cryptography;
using System.Text;
using Newtonsoft.Json.Linq;
namespace HMacExample
{
  class Program {
    static void Main(string[] args) {
      String key = "YOUR_SECRET_KEY"; //replace with your squad secret_key

      //Replace with the body of the notification received
      String webhookPayload = "THE_BODY_OF_THE_WEBHOOK_PAYLOAD YOU RECEIVED";
      String jsonInput = JsonConvert.SerializeObject(webhookPayload);
      String result = "";
      byte[] secretkeyBytes = Encoding.UTF8.GetBytes(key);
      byte[] inputBytes = Encoding.UTF8.GetBytes(jsonInput);
      using (var hmac = new HMACSHA512(secretkeyBytes))
      {
          byte[] hashValue = hmac.ComputeHash(inputBytes);
          result = BitConverter.ToString(hashValue).Replace("-", string.Empty);;
      }
      Console.WriteLine(result);
      String x-squad-signature = "Request's header value for x-squad-signature" //replace with the request's header value for x-squad-signature here
      if(result.Equals(x-squad-signature)) {
          // you can trust the event came from squad and so you can give value to customer
      } else {
          // this request didn't come from Squad, ignore it
      }
    }
  }
}

Method 2 (Decryption of Encrypted Body)

To validate the webhook you received, you need to decrypt the hashed body (encrypted_body) of the data sent via the webhook. To do this, use the Public and Secret Key found on your squad dashboard.

After decrypting the hashed body, compare the result with the original body of data sent from the webhook. If they match, you can trust that the notification is from Squad. If they do not match, it indicates that the notification did not originate from Squad, and you should disregard such notifications.

For assistance with decrypting the hashed body, please visit our encryption and decryption page, where you can find sample decryption functions in various programming languages.
Sample Webhook Notification

{
  "transaction_reference": "REF2023022815174720339_1",
  "virtual_account_number": "0733848693",
  "principal_amount": "0.20",
  "settled_amount": "0.20",
  "fee_charged": "0.00",
  "transaction_date": "2023-02-28T00:00:00.000Z",
  "customer_identifier": "5UMKKK3R",
  "transaction_indicator": "C",
  "remarks": "Transfer FROM WILLIAM JAMES | [5UM2B63R] TO CHIZOBA ANTHONY OKOYE",
  "currency": "NGN",
  "channel": "virtual-account",
  "sender_name": "WILLIAM JAMES",
  "meta": {
    "freeze_transaction_ref": null,
    "reason_for_frozen_transaction": null
  },
  "encrypted_body": "DiPEa8Z4Cbfiqulhs3Q8lVJXGjMIFzbWwI2g7utVGbiI96TjcbjW+64iQrDR+kbZBwisMLMfB5l+Bn0/9kchGjB+xj6bLc6SnyCaku3pCMKmiVSkr/US1lsk+dBBI53nkGcUFkhige35wBYtXC7IpB/N2DCrzXTW5kEGnr9lCvpEFvDhZzDIUVeUCxV14V92vYYP/8O8Zjj3WR9keUc7Qq0H+fl/jmm7VwCtKMSp0OXNGMVPk5TJkLR52hQ8Rap+oorORLoNau1FRLzA24AW0d+nQfqbI+B4hf5+RztP7F1PpiRlo5qR7EthNpaHW6EMYp9fFUQdJRzsQNLbU/IfnH5oK9zFjHaOfKAa5rnoWP3N5IQjz6wobLq9T2KHei3UpCioFMcKYoigtJxple26auq0vCDkDoalPF6+YaqpuKFWdjX0mLz9+Xh5OCq4AI4u3GhioYFbpAvkrzk/Eyh5OdrEvDDLsbSu8lnXymOoiYXuS1Y4Y5jVZpzAArJ7wX7rdi1KLawHu8/m6fBkQLq/82olUuGLtGdPKF1JZnbv3eAXa7+IMhF4QUvsd52uMRnBdEHXfij+WHp7mz4jMP4Gxsx19Xzt7gyWqBhyswEJobDMSZhk/9GRcETwnT0dlSlWxVOL2pVSzKhc73ASxEQCZCO3/5/i1Nq6qSTjsbplLKuwP2Qr/15rP6TvVWAIpxa8"
}

Webhook Validation --version 2

The Webhook Version 2 (V2) is an upgraded version of the existing webhook. It maintains the same structure but includes two critical updates:

    Addition of a new field: Version Number.
    Method of Hash Validation: Unlike previous versions that required hashing of the entire payload, Webhook V2 only requires hashing of six (6) specific fields. These fields should be separated by a pipe (|). The values to be hashed are:

  transaction_reference
  virtual_account_number
  currency
  principal_amount
  settled_amount
  customer_identifier

Webhook Validation --version 3

The Webhook Version 3 (V3) is an upgrade to the existing version, maintaining the same overall structure but introducing three critical updates:

    The format of the Transaction Reference has changed. Please note that re-queries must still be performed using the previous format.

    A new field, the Version Number, has been added.

    The method of hash validation has also changed. Unlike previous versions, which required hashing the entire payload, Webhook V3 only requires hashing six specific fields, each separated by a pipe (|). The values to be hashed are as follows:

  transaction_reference
  virtual_account_number
  currency
  principal_amount
  settled_amount
  customer_identifier

Sample signature string

signature = `${payload.transaction_reference}|${payload.virtual_account_number}|${payload.currency}|${payload.principal_amount}|${payload.settled_amount}|${payload.customer_identifier}`;


The webhook notification you receive includes an x-squad-signature in the header. This signature is an HMAC (Hash-based Message Authentication Code) that is generated from the webhook payload using your secret key. To verify the integrity of the request, you need to create your own hash of the payload and compare it with the x-squad-signature sent in the header of the POST request to your webhook URL.

    Version 2
    Version 3

{
  "transaction_reference": "REF20260424S67978035_M01682015_9013151600",
  "virtual_account_number": "9013151600",
  "principal_amount": "1.00",
  "settled_amount": "1.00",
  "fee_charged": "0.00",
  "transaction_date": "2026-04-24T11:29:10+01:00",
  "customer_identifier": "newva1",
  "transaction_indicator": "C",
  "remarks": "000001260424112858828788701428-ONEBANK TRANSFER FROM AKINOLA MOBOLAJI NIFEMI TOTAM WILLIA M  UDOUSORO -STERLING-AKINOLAMOBOLAJI NIFEMI | [newva1]",
  "currency": "NGN",
  "channel": "virtual-account",
  "sender_name": "AKINOLA MOBOLAJI NIFEMI",
  "meta": {
    "freeze_transaction_ref": null,
    "reason_for_frozen_transaction": null
  },
  "first_name": "William",
  "last_name": "Udousoro",
  "prefix": "TAM",
  "session_id": "000001260424112858828788701400",
  "masked_sender_account_number": "009****919",
  "version": "v2",
  "transaction_uuid": "019DBF094ABEA366",
  "encrypted_body": "iJeFVV1hvWt2BjT/4wi3Rr0fMR7dlBkXM2I1hu/9ojZQdOAXH9trrSLgSNpMZ0Hx1iQtz6n/bMUjlGNZZGegIlJw69rPTvnsUi0I3pLgY9ix/lz9L6hdJ6DQ7X3E1AIRC3ZxyxlK/nuC4MtFex0bUKrSBnVMNE9zHQBXJMTA8NKNIGq/6bPnLeSe+36DHf01Pu1WiT0jL4fLhtB9QbAMOdk1tsp9wEsZgVQvPOPhc1xApVkfER/gBlDQdE7otfHhcfM6AugmmC7S1aJRNdsHwjdu86cmuOUycxLYByISt8w9QheW4rciUKOeatj7i7oHjkofnjLmut2s2ae2tA5sNsBY2N6rpv1ljturegkA8IHTTwMAkjew7qKjVC/XGwodgWUSa+ATJ5mGerbgYDtIgFXbjlL+D1mrHruQQOjzLz6rqrpWoti2brZniFMmiA+8VYKgwHpMLdKWLtLcmMgImRDlfXUSPARjHcrmCb+uk0FOzJnSErpvLqZ0C3nU/L0+Fyx/U7BSWXLzsZ6zZHWhwp5Tk4DBTtGWoDANmS2wk6OD8igaNUOECENxzcPSdpf6IwxNBBMHdTU0V1RcPJGias0ATsjbA0swRsnm9gowA+brOR4yNiC0Ksd3cPkON86TxIn6zBbCnWxz7ugfUcAwJWElp06J+xUVX1oEhqrhYJTo/w3/hy6GFI0ukgp9wSHB8OWq/lnx97m3J4kRXtGh12rI7ukpX5o3hj62HGFQy67NWgmtwME7KOfpjzm2NKSCkiFh7Jtv0cEaF5uJ/9j0N9H5kIQaPI1Qxh6ag8sIKrFt/ermGqDo2SQwi2KzRmt3rsoAhHVyi+QXzqVFIHBIzh0MXigCqrO/B2IobxbL7doRe9mPyWOhxioSG8TGZY5D3eiGovz5Tq+mI/UtCvZFwJrg2KC3Dw0H8rvcElSsFQKnwZN0qov5eUJS3oBl+XQghjDQopiTEXsgyxUrCfigDa3AbnCWREmalIWhXRwpeCzVma6SlAedieRiU75VkByN5P+iZMbtpDpbgBn4Ip+dIUxzZ80U1G+bMX8GFaR2RFLXDbfZ90JpBCAvvvicFeHtj9CtAUo0tMUbnhULB5qfeA=="
}


Sample v2 and v3 notifications

    C#
    PHP
    Javascript

using System;
using System.Text;
using System.Security.Cryptography;
using System.Text.Json;

// Expected signature from the header
const string ExpectedSignature = "64cab69cecb62ad24da041789847a070e93621071fcbd84ccf975150b820dcb1a1eaeae00bb9be976007cad4eeaa83e01d201b3fc28c7dfeb27834939a5bc755";

// Secret key for HMAC
const string SecretKey = "user_sk_sample-secret-key-1";

// Sample payload
var payload = new
{
    transaction_reference = "0196F220EA4148F3",
    virtual_account_number = "0712714141",
    principal_amount = "45000.00",
    settled_amount = "44955.00",
    fee_charged = "45.00",
    transaction_date = "2025-05-21T10:16:05+01:00",
    customer_identifier = "RRRR",
    transaction_indicator = "C",
    remarks = "100004230823134654105988596264|090701365374||EUSTACE UGOCHUKWU NJOKU || REF:989898999888998898989899 | [RRRR]",
    currency = "NGN",
    channel = "virtual-account",
    sender_name = "Transfer",
    meta = new
    {
        freeze_transaction_ref = (string)null,
        reason_for_frozen_transaction = (string)null
    },
    version = "v3",
    encrypted_body = "4eDIvGkwNhH+u0HgAJB2c3GKIKnweltSZso1o/otX3x+8LXQti6+FtCqbHhrSy8RNk1wB3oWswWbY1qq5+C2QN2kA9ogIM4P0uGqciTClxQVtKaAZCaAGjWr0vmqt928oyop6WJ3jzqTGnQwheAm9ITNAnbXgShfPtmOMtJyWAKwR+QNQyoZjdArQKqJzm5RxbI/iHp2ZmJpgr0229AREiahdIhy80sRO7ztHD4M1QmYBXrzElrcJ85ZtAFM41DsUtqojeW0eR8kWw8ghTHmL5rmCD0sselidmC7NFpiIpn3RuHOBNYXfcVU38+LVdBPmNygFd9iX2n0kxxLMBX9X4ngQDiaR6faKo2rOJ0/KXg44YM/y/dYVHsjBHqZXuB252FoZk7bUKbW6ebPXIuEkgjB63El/BcbLXtbjrw0w3ybXqY6pVahi8SuURJe7DcglS8IITacYybcjfoZYsiKCJKZqlb2pkLCCoNpaEEEqa8dP0b3QdisDiTy3vvWB1nGuxPjk9kPWr/IxqP9/NbPoWN4MRVU6PsmPHhHyd3tiUWfPCMBAT9EB7ldjHl8tpVGjKRkGzvVuuc9tm8c6gPPotW9/M3SnKgm23becDp/hGMaA0PbFwVs7h+JjWMu3UcHlujFUqHRDA/TZ5Vvp8uT2ZDc5y+wisUntKW3F+gBv0mL+ifagi/PJRXOYXdG4oIEUw/Jy7bdY+JrGbBmsS8RhOkbIcFf4ClU2cnHB5h/6TA="
};

// formatted string with pipe separators
string dataToHash = $"{payload.transaction_reference}|{payload.virtual_account_number}|{payload.currency}|{payload.principal_amount}|{payload.settled_amount}|{payload.customer_identifier}";

Console.WriteLine($"Data to hash (with pipe separators): {dataToHash}");

// hash using HMAC-SHA512 with the secret key
string generatedHash = GenerateHmacSHA512(dataToHash, SecretKey);

Console.WriteLine($"Generated hash: {generatedHash}");
Console.WriteLine($"Expected hash:  {ExpectedSignature}");
Console.WriteLine($"Hashes match: {generatedHash == ExpectedSignature}");


// HMAC-SHA512 with secret key
static string GenerateHmacSHA512(string input, string key)
{
    byte[] keyBytes = Encoding.UTF8.GetBytes(key);
    byte[] inputBytes = Encoding.UTF8.GetBytes(input);

    using HMACSHA512 hmac = new HMACSHA512(keyBytes);
    byte[] hashBytes = hmac.ComputeHash(inputBytes);

    // Convert the byte array to a hexadecimal string
    StringBuilder sb = new StringBuilder();
    for (int i = 0; i < hashBytes.Length; i++)
    {
        sb.Append(hashBytes[i].ToString("x2"));
    }

    return sb.ToString();
}


Webhook Error Log

This API allows you to retrieve all your missed webhook notifications, enabling you to update your records without manual input.

By default, an array of the top 100 missed webhooks will always be returned.

The process involves the integration of two APIs. The first API fetches the missed notifications. Once you have updated the record for a specific transaction, you must use the second API to delete the record from the error log. If you fail to do this, the transaction notification will continue to appear in the first 100 transactions until it is deleted.

Additionally, ensure that you implement a transaction duplicate checker to avoid updating a record twice or modifying a record that has already been updated through the webhook or transaction API.
Get Webhook Error Log
GET
https://sandbox-api-d.squadco.com/virtual-account/webhook/logs
This API returns an array of transactions from the webhook error log
Parameters
Query

page

Integer

The page you are on

perPage

Integer

Number of records you want to appear on a page
Responses
200:OK
Response description

{
            "status": 200,
            "success": true,
            "message": "Success",
            "data": {
                "count": 2,
                "rows": [
                    {
                        "id": "229f9f3d-53e4-450e-a9e9-164a8b882a60",
                        "payload": {
                            "hash": "659c24ba0b6c3ac324b587f2f079c8ee876c56609ff11b7106cd868f84674a5c37fcb088373859f8d900713f03c47d819de79623cde67e70bbca945fd20f3cb3",
                            "meta": {
                                "freeze_transaction_ref": null,
                                "reason_for_frozen_transaction": null
                            },
                            "channel": "virtual-account",
                            "remarks": "Transfer FROM OKOYE, CHIZOBA ANTHONY | [CCtyttytC] TO CHIZOBA ANTHONY OKOYE",
                            "currency": "NGN",
                            "fee_charged": "0.05",
                            "sender_name": "OKOYE, CHIZOBA ANTHONY",
                            "encrypted_body": "DiPEa8Z4Cbfiqulhs3Q8lVJXGjMIFzbWwI2g7utVGbhXihbtK3H2xsA/+ZnjOpFA0AU8vAN5LUTEH6elfrK58ub2wydaRk0ngvQXWUFz3iB19qWBcdGQRnppKAT/AB5xyy1iQZvEHP7zq3Y7na5zcx9ttkU1mZIeAIoisM9k+ghVLxkTeql4UvfFcLyDdGzMd/BC4YgJFyrZxifhfhKi073od7xJnz4Hhz08UBE/FAwNYMWkwWD9izlbcaaJtfh1VIN6t9rl1gotlb5qmNq/UytgoSvuN5uaEXxegdB3VWvmsDMHqoYwDs4oEuv0lp8zUUG3cZ9zPQ6xH3shGQjVOWErkuIfCk62fRzkwxya4Gu/x2KHMSQjutbvD4vNDjVGfuCIoHuZEXPThWrq1jpTy7cNMLc8ZZ8IowJnfwWHL+O6fuepxXxfrJHlswMCI35ZHSvef1AEXgbUlx2O7yzytceCogpUkY+QJ1yLddl1FeE1u2JKOM+casP3pfiT+t3Mv55aSCVQO7hUy46gd6H/bIHaSIp2K3CcjfdflZ/bxCZaZoe/sRqfVdVIzpSpTc0Lq5sOXM2gijOdeg+zex/CgnMIKGJdzUT9YUJtaaVrMmhk0EcM0rHRrqs0iM7xaSTdZ7K8hnzl0RPJhDXIhu5a/Y2NxS3ZTC2lYRVZd6I3lerpoMQG69VfmqvaVgW2k03f",
                            "settled_amount": "49.95",
                            "principal_amount": "50.00",
                            "transaction_date": "2023-09-01T00:00:00.000Z",
                            "customer_identifier": "CCtyttytC",
                            "transaction_indicator": "C",
                            "transaction_reference": "REF20230901162737156459_1",
                            "virtual_account_number": "0760640237"
                        },
                        "transaction_ref": "REF20230901162737156459_1"
                    }
                ]
            }
}

401:Unauthorized
No Authorization

{
            "success": false,
            "message": "",
            "data": {}
}

Delete Webhook Error Log
DELETE
https://sandbox-api-d.squadco.com/virtual-account/webhook/logs/:transaction_ref
This API enables you delete a processed transaction from the webhook error log

When you delete the transaction from the log, it won't be returned to you again. Failure to delete a transaction will result in the transaction being returned to you in the top 100 transactions returned each time you retry.
Parameters
Path

transaction_ref*

String

Unique Transaction Ref that identifies each virtual account and gotten from the retrieved webhook error log
Responses
200:OK
Success

{
            "status": 200,
            "success": true,
            "message": "Success",
            "data": 1
}

401:Unauthorized
No Authorization

{
            "success": false,
            "message": "",
            "data": {}
}

403:Forbidden
Wrong/Invalid API Keys

{
            "success": false,
            "message": "Merchant authentication failed",
            "data": {}
}

Query Transactions Using Customer Identifier

This endpoint allows querying the transactions made by a customer using their identifier provided during the creation of the virtual account.
GET
https://sandbox-api-d.squadco.com/virtual-account/customer/transactions/{{customer_identifier}}
Query Customer Transactions

Note: The customer identifier must be included in the endpoint being queried. Specifically, replace {{customer_identifier}} at the end of the endpoint with the identifier for the customer whose transactions you want to query.
Parameters
Path

customer_identifier

String

Unique Customer Identifier that identifies each virtual account

Response expected from the API to show queried Virtual Accounts.

    200: Successful
    400: Validation Failure
    401: Restricted
    404: Not Found

{
    "status": 200,
    "success": true,
    "message": "Success",
    "data": [
        {
            "transaction_reference": "74902084jjjfksoi93004891_1",
            "virtual_account_number": "2224449991",
            "principal_amount": "30000.00",
            "settled_amount": "0.00",
            "fee_charged": "0.00",
            "transaction_date": "2022-04-21T09:00:00.000Z",
            "transaction_indicator": "C",
            "remarks": "Payment from 10A2 to 2224449991",
            "currency": "NGN",
            "frozen_transaction": {
                "freeze_transaction_ref": "afbd9b7f-fb98-41c3-bfe8-dc351cfb45c7",
                "reason": "Amount above 20000 when BVN not set"
            },
            "customer": {
                "customer_identifier": "SBN1EBZEQ8"
            }
        },
{
            "transaction_reference": "676767_1",
            "virtual_account_number": "2224449991",
            "principal_amount": "1050.00",
            "settled_amount": "1037.00",
            "fee_charged": "13.00",
            "transaction_date": "2022-03-21T09:00:00.000Z",
            "transaction_indicator": "C",
            "remarks": "Payment from 10A2 to 2224449991",
            "currency": "NGN",
            "froze_transaction": null,
            "customer": {
                "customer_identifier": "SBN1EBZEQ8"
            }
        }
    ]
}

Query All Merchant's Transactions

This is an endpoint to query all the merchant transactions over a period of time.
GET
https://sandbox-api-d.squadco.com/virtual-account/merchant/transactions
Query All Transactions

Note: The endpoint is to be queried using just the authorization key from the dashboard
Parameters
No Parameters

    200: Successful
    400: Validation Failure
    401: Restricted
    404: Not Profiled


{
    "status": 200,
    "success": true,
    "message": "Success",
    "data": [
        {
            "transaction_reference": "4894fe1_1",
            "virtual_account_number": "2244441333",
            "principal_amount": "5000.00",
            "settled_amount": "0.00",
            "fee_charged": "0.00",
            "transaction_date": "2022-04-21T09:00:00.000Z",
            "transaction_indicator": "C",
            "remarks": "Payment from 15B8 to 2244441333",
            "currency": "NGN",
            "frozen_transaction": {
                "freeze_transaction_ref": "afbd9b7f-fb98-41c3-bfe8-dc351cfb45c7",
                "reason": "Amount above 20000 when BVN not set"
            },
            "customer": {
                "customer_identifier": "SBN1EBZEQ8"
            }
        },
{
            "transaction_reference": "676767_1",
            "virtual_account_number": "2224449991",
            "principal_amount": "30000.00",
            "settled_amount": "1037.00",
            "fee_charged": "13.00",
            "transaction_date": "2022-03-21T09:00:00.000Z",
            "transaction_indicator": "C",
            "remarks": "Payment from 10A2 to 2224449991",
            "currency": "NGN",
            "froze_transaction": null,
            "customer": {
                "customer_identifier": "SBN1EBZEQ8"
            }
        }
    ]
}

Query All Merchant Transactions with Multiple Filters

This endpoint allows querying all transactions with multiple filters, including virtual account number, start and end dates, and customer identifier.
GET
https://sandbox-api-d.squadco.com/virtual-account/merchant/transactions/all
Query All Transactions with Multiple Filters

TThis endpoint allows querying all transactions with multiple filters, including virtual account number, start and end dates, and customer identifier.
Parameters
Query

page

Integer

Page Number to Display

perPage

Integer

Number of records per Page

virtualAccount

Integer

a unique 10-digit virtual account number

customerIdentifier

String

Unique Identifier used to create/identify a customer's virtual account

startDate

Date

MM-DD-YYYY E.G: 09-19-2022

endDate

Date

MM-DD-YYYY E.G: 09-19-2022

transactionReference

String

Unique Identifier of a transaction

session_id

String

Unique ID that identifies all NIP transactions

dir

String

Takes two possible values: 'DESC' and 'ASC'. 'DESC' - descending order ,'ASC' - ascending order
Responses
200:OK
Success

{
    "status": 200,
    "success": true,
    "message": "Success",
    "data": {
        "count": 15,
        "rows": [
            {
                "transaction_reference": "REF20221007130357_1",
                "virtual_account_number": "0713810881",
                "principal_amount": "50.00",
                "settled_amount": "50.00",
                "fee_charged": "0.00",
                "transaction_date": "2022-10-07T00:00:00.000Z",
                "transaction_indicator": "C",
                "remarks": "Transfer FROM Sample | [CCC1234334] TO Sample Name",
                "currency": "NGN",
                "alerted_merchant": false,
                "merchant_settlement_date": "2022-10-07T12:04:11.635Z",
                "frozen_transaction": null,
                "customer": {
                    "customer_identifier": "CCC1234334"
                }
            },
            {
                "transaction_reference": "REF20221004191517_1",
                "virtual_account_number": "0708729381",
                "principal_amount": "50.00",
                "settled_amount": "49.75",
                "fee_charged": "0.25",
                "transaction_date": "2022-10-04T00:00:00.000Z",
                "transaction_indicator": "C",
                "remarks": "Transfer FROM Sample Name4 | [OPPO] TO Sample Name",
                "currency": "NGN",
                "alerted_merchant": false,
                "merchant_settlement_date": "2022-10-04T18:15:29.463Z",
                "frozen_transaction": null,
                "customer": {
                    "customer_identifier": "OPPO"
                }
            },
            {
                "transaction_reference": "REF20220913181048_1",
                "virtual_account_number": "0709108705",
                "principal_amount": "50.00",
                "settled_amount": "49.75",
                "fee_charged": "0.25",
                "transaction_date": "2022-09-13T18:10:48.000Z",
                "transaction_indicator": "C",
                "remarks": "Transfer FROM Sample Name4 | [TSP/00008786500] TO Sample Name",
                "currency": "NGN",
                "alerted_merchant": false,
                "merchant_settlement_date": "2022-09-20T09:51:04.999Z",
                "frozen_transaction": null,
                "customer": {
                    "customer_identifier": "TSP/00008786500"
                }
            },
            {
                "transaction_reference": "REF20220713143436_1",
                "virtual_account_number": "0713694755",
                "principal_amount": "50.00",
                "settled_amount": "49.75",
                "fee_charged": "0.25",
                "transaction_date": "2022-07-13T14:34:36.000Z",
                "transaction_indicator": "C",
                "remarks": "Transfer from Sample Name | [123CCC] to Sample Name5",
                "currency": "NGN",
                "alerted_merchant": false,
                "merchant_settlement_date": "2022-07-13T13:35:13.410Z",
                "frozen_transaction": null,
                "customer": {
                    "customer_identifier": "123CCC"
                }
            },
            {
                "transaction_reference": "REF20220707162950_1",
                "virtual_account_number": "0710954717",
                "principal_amount": "50.00",
                "settled_amount": "49.75",
                "fee_charged": "0.25",
                "transaction_date": "2022-07-07T16:29:50.000Z",
                "transaction_indicator": "C",
                "remarks": "Transfer from Sample Name4 | [12345] to Sample Name",
                "currency": "NGN",
                "alerted_merchant": false,
                "merchant_settlement_date": "2022-07-07T15:30:06.761Z",
                "frozen_transaction": null,
                "customer": {
                    "customer_identifier": "12345"
                }
            },
            {
                "transaction_reference": "REF20220624160230_1",
                "virtual_account_number": "0710954717",
                "principal_amount": "30.00",
                "settled_amount": "29.85",
                "fee_charged": "0.15",
                "transaction_date": "2022-06-24T16:02:30.000Z",
                "transaction_indicator": "C",
                "remarks": "Transfer from Sample Name5 | [12345] to Sample Name",
                "currency": "NGN",
                "alerted_merchant": false,
                "merchant_settlement_date": "2022-06-24T15:03:29.054Z",
                "frozen_transaction": null,
                "customer": {
                    "customer_identifier": "12345"
                }
            },
            {
                "transaction_reference": "REF20220624155515_1",
                "virtual_account_number": "0710954717",
                "principal_amount": "30.00",
                "settled_amount": "29.85",
                "fee_charged": "0.15",
                "transaction_date": "2022-06-24T15:55:15.000Z",
                "transaction_indicator": "C",
                "remarks": "Transfer from Sample Name4 | [12345] to Sample Name",
                "currency": "NGN",
                "alerted_merchant": false,
                "merchant_settlement_date": "2022-06-24T14:56:23.266Z",
                "frozen_transaction": null,
                "customer": {
                    "customer_identifier": "12345"
                }
            },
            {
                "transaction_reference": "REF20220623095446_1",
                "virtual_account_number": "0710954717",
                "principal_amount": "30.00",
                "settled_amount": "29.85",
                "fee_charged": "0.15",
                "transaction_date": "2022-06-23T09:54:46.000Z",
                "transaction_indicator": "C",
                "remarks": "Transfer from Sample Name3 | [12345] to Sample Name",
                "currency": "NGN",
                "alerted_merchant": false,
                "merchant_settlement_date": "2022-06-23T08:55:06.599Z",
                "frozen_transaction": null,
                "customer": {
                    "customer_identifier": "12345"
                }
            },
            {
                "transaction_reference": "REF20220617131121_1",
                "virtual_account_number": "0708729381",
                "principal_amount": "30.00",
                "settled_amount": "29.85",
                "fee_charged": "0.15",
                "transaction_date": "2022-06-17T13:11:21.000Z",
                "transaction_indicator": "C",
                "remarks": "Transfer from Sample Name3 | [OPPO] to Sample Name",
                "currency": "NGN",
                "alerted_merchant": false,
                "merchant_settlement_date": "2022-06-17T12:11:38.228Z",
                "frozen_transaction": null,
                "customer": {
                    "customer_identifier": "OPPO"
                }
            },
            {
                "transaction_reference": "REF20220617130949_1",
                "virtual_account_number": "0708729381",
                "principal_amount": "50.00",
                "settled_amount": "49.75",
                "fee_charged": "0.25",
                "transaction_date": "2022-06-17T13:09:49.000Z",
                "transaction_indicator": "C",
                "remarks": "Transfer from Sample Name3 | [OPPO] to Sample Name",
                "currency": "NGN",
                "alerted_merchant": false,
                "merchant_settlement_date": "2022-06-17T12:10:14.605Z",
                "frozen_transaction": null,
                "customer": {
                    "customer_identifier": "OPPO"
                }
            },
            {
                "transaction_reference": "REF20220617125618_1",
                "virtual_account_number": "0708729381",
                "principal_amount": "50.00",
                "settled_amount": "49.75",
                "fee_charged": "0.25",
                "transaction_date": "2022-06-17T12:56:18.000Z",
                "transaction_indicator": "C",
                "remarks": "Transfer from sample Name1 | [OPPO] to Sample Name",
                "currency": "NGN",
                "alerted_merchant": false,
                "merchant_settlement_date": "2022-06-17T11:56:42.868Z",
                "frozen_transaction": null,
                "customer": {
                    "customer_identifier": "OPPO"
                }
            },
            {
                "transaction_reference": "REF20220617115436_1",
                "virtual_account_number": "0709056301",
                "principal_amount": "50.00",
                "settled_amount": "49.75",
                "fee_charged": "0.25",
                "transaction_date": "2022-06-17T11:54:36.000Z",
                "transaction_indicator": "C",
                "remarks": "Transfer from Sample Name3 | [TSP/00002900] to Sample Name",
                "currency": "NGN",
                "alerted_merchant": false,
                "merchant_settlement_date": "2022-06-17T10:54:54.837Z",
                "frozen_transaction": null,
                "customer": {
                    "customer_identifier": "TSP/00002900"
                }
            }
        ],
        "query": {}
    }
}

400:Bad Request
Wrong/ Invalid Input

{
        "status": 400,
        "success": false,
        "message": ""virtualAccount" is not allowed to be empty",
        "data": {}
}

401:Unauthorized
No API Keys

{
            "success": false,
            "message": "",
            "data": {}
}

403:Forbidden
Invalid Keys/Token

{
            "success": false,
            "message": "Merchant authentication failed",
            "data": {}
}

Get Customer Details by Virtual Account Number

This endpoint retrieves customer details using the Virtual Account Number.
GET
https://sandbox-api-d.squadco.com/virtual-account/customer/{{virtual_account_number}}
Retrieve Virtual Account Details

Note: The virtual account number is to be passed via the endpoint being queried. Specifically, replace {{virtual_account_number}} on the end point with the virtual account number.
Parameters
Path

virtual_account_number*

String

Unique 10-digit virtual account number assigned to a customer
Responses
200:OK
Valid Virtual Account Number

{
            "status": 200,
            "success": true,
            "message": "Success",
            "data": {
                "first_name": "Timothy",
                "last_name": "Oke",
                "mobile_num": "08000000000",
                "email": "atioke@gmail.com",
                "customer_identifier": "CCtyttytC",
                "virtual_account_number": "0686786837"
            }
}

404:Not Found
Invalid Virtual Account Number

{
            "status": 404,
            "success": false,
            "message": "Virtual account not found",
            "data": {}
}

Get Customer Details Using Customer Identifier

This endpoint retrieves customer details using the Virtual Account Number.
GET
https://sandbox-api-d.squadco.com/virtual-account/{{customer_identifier}}
Retrieve Virtual Account Details

Note: The customer identifier must be passed through the queried endpoint. Specifically, replace {{customer_identifier}} in the endpoint with the identifier of the customer whose virtual account you wish to retrieve.
Parameters
Path

customer_identifier

String

Unique Customer Identifier that identifies each virtual account

    200: Successful
    400: Validation Failure
    404: Not Profiled

{
    "status": 200,
    "success": true,
    "message": "Success",
    "data": {
        "first_name": "Wisdom",
        "last_name": "Trudea",
        "bank_code": "737",
        "virtual_account_number": "555666777",
        "customer_identifier": "10D2",
        "created_at": "2022-01-13T11:03:54.252Z",
        "updated_at": "2022-01-13T11:09:51.657Z"
    }
}

Query All Merchant's Virtual Accounts

This endpoint retrieves all virtual account numbers for a merchant.
GET
https://sandbox-api-d.squadco.com/virtual-account/merchant/accounts
Find All Virtual Account Number by Merchant

This is an endpoint for merchants to query and retrieve all their virtual account.
Parameters
Query

page

String

Number of Pages

perPage

String

Number of Accounts to be returned per page

startDate

Date

YY-MM-DD

EndDate

Date

YY-MM-DD

    200: Successful
    404: Not Profiled

{
    "status": 200,
    "success": true,
    "message": "Success",
    "data": [
        {
            "bank_code": "058",
            "virtual_account_number": "2224449991",
            "beneficiary_account": "4829023412",
            "created_at": "2022-02-09T16:02:39.170Z",
            "updated_at": "2022-02-09T16:02:39.170Z",
            "customer": {
                "first_name": "Ifeanyi",
                "last_name": "Igweh",
                "customer_identifier": "10A2"
            }
        },
        {
            "bank_code": "058",
            "virtual_account_number": "111444999",
            "beneficiary_account": "9829023411",
            "created_at": "2022-02-09T16:02:39.170Z",
            "updated_at": "2022-02-09T16:02:39.170Z",
            "customer": {
                "first_name": "Paul",
                "last_name": "Aroso",
                "customer_identifier": "10B2"
            }
        }
    ]
}

Simulate Payment

This is an endpoint to simulate payments
POST
https://sandbox-api-d.squadco.com/virtual-account/simulate/payment
Simulate Payment

This is an endpoint to simulate payment *asterisks are required and mandatory.
Parameters
Header

content-type*

String

application/json

Authorization*

String

Private Key or Secret Key (Gotten from your dashboard)
Body

virtual_account_number*

String

Virtual Account number of customer that wants to make payment.

amount

String

Simulated Amount
Responses
200:OK
Successful

{
            "success": true,
            "message": "Success",
            "data": {}
}

Going Live

To go live, follow these steps:

    Change the base URL for your endpoints from https://sandbox-api-d.squadco.com to https://api-d.squadco.com.
    Sign up for our Live Environment.
    Complete your Know Your Customer (KYC) process.
    Share your Merchant ID with the Technical Account Manager for profiling.
    Use the credentials provided on the live dashboard for authentication.
