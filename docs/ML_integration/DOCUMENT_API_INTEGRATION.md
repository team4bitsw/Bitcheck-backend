# BitCheck Document Verification API Integration Guide

This guide provides everything you need to integrate the BitCheck Document Verification API into your backend services.

## Overview

The Document Verification Service analyzes documents (PDFs and images) to verify authenticity, extract fields, decode QR codes, perform forensic analysis (tampering detection), and assess content risk using LLMs.

**Base URLs:**
- Local Development: `http://localhost:8000`
- Production (HuggingFace): `https://jaykay73-bitcheck-document.hf.space`

---

## 1. Verify Document Endpoint

The primary endpoint for processing and verifying documents.

**Endpoint:** `POST /verify/document`  
**Content-Type:** `multipart/form-data`

### Request Parameters (Form Data)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `file` | File | **Yes** | - | The document to analyze (PDF, PNG, JPG, JPEG). Max size is 20MB by default. |
| `document_type` | String | No | `"general"` | The expected type of document (e.g., "invoice", "id_card", "general"). Used for context in LLM analysis and field extraction. |
| `run_ocr` | Boolean | No | `true` | Extract text from images using OCR. |
| `run_forensics` | Boolean | No | `true` | Run visual tampering and forensics checks (noise inconsistency, clone detection, etc.). |
| `run_qr` | Boolean | No | `true` | Scan for and decode QR codes/barcodes in the document. |
| `run_live_qr_check` | Boolean | No | `false` | If a QR code contains a URL, perform a live network request to verify the destination. |
| `run_llm_analysis` | Boolean | No | `true` | Use DeepSeek LLM to perform deep content risk analysis and semantic field extraction. |
| `max_pages` | Integer | No | `5` | Maximum number of pages to process (for multi-page PDFs). |

### Example Request (cURL)

```bash
curl -X POST "http://localhost:8000/verify/document" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@/path/to/invoice.pdf" \
  -F "document_type=invoice" \
  -F "run_live_qr_check=true"
```

### Response Model

The API returns a highly detailed JSON report of type `DocumentVerificationReport`. 
Key fields your backend should look out for:

```json
{
  "verification_id": "uuid-string",
  "status": "completed", // or "completed_with_warnings"
  "processing_time_ms": 1250,
  
  "trust": {
    "trust_score": 85,           // 0-100 score indicating document trustworthiness
    "risk_score": 0.15,          // 0.0-1.0 combined risk score
    "risk_level": "LOW",         // "LOW", "MEDIUM", "HIGH"
    "decision": "APPROVE"        // "APPROVE", "REVIEW", "REJECT"
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
}
```

#### Important Objects for Integration:
1. **`trust.decision`**: The quickest way to automate backend flows. Route logic based on `APPROVE`, `REVIEW`, or `REJECT`.
2. **`fields.extracted_fields`**: Useful for automatically populating your database with the document's contents.
3. **`risk_flags`**: An array of human-readable strings if any specific subsystem caught an anomaly (e.g. "Metadata wiped", "Inconsistent fonts detected").

---

## 2. Health & Status Endpoints

Use these to ensure the service is running before routing requests.

### Root Status
**Endpoint:** `GET /`

```json
{
  "service": "BitCheck Document Verification API",
  "status": "running",
  "version": "1.0.0"
}
```

### Detailed Health
**Endpoint:** `GET /health`

Provides details on which subsystems are active (useful if LLM keys or OCR dependencies are missing).

```json
{
  "status": "ok",
  "service": "BitCheck Document Verification API",
  "version": "1.0.0",
  "ocr_available": true,
  "qr_available": true,
  "deepseek_available": true,
  "model": "deepseek-chat"
}
```

---

## Best Practices for Integration

1. **Timeouts**: Document analysis (especially with LLMs and OCR) can take between 2-10 seconds depending on page count. Ensure your backend HTTP client timeout is set to at least 30 seconds.
2. **Asynchronous Processing**: For user-facing apps, consider accepting the document in your backend, returning a 202 Accepted, and polling or using a webhook after the BitCheck API returns its response.
3. **Error Handling**: The API returns standard HTTP error codes:
   - `400 Bad Request`: If the file format is unsupported or the file is corrupted.
   - `422 Unprocessable Entity`: If form data parameters are invalid.
   - `500 Internal Server Error`: For unexpected crashes.
