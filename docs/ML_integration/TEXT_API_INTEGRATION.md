# BitCheck Text Verification - Backend Integration Guide

This document is intended for backend engineers integrating the **BitCheck Text Verification Service** into your existing system.

## Overview

The BitCheck Text Service is a RESTful API designed to evaluate text for fraud signals, AI generation likelihood, manipulation pressure, and source URL reputation. It returns a comprehensive JSON report including a unified **Trust Score** and **Risk Level**.

### Base URL
Depending on your deployment, the base URL will be:
- **Local:** `http://127.0.0.1:7860`
- **Hugging Face Space:** `https://jaykay73-bitcheck-text.hf.space` (or the specific Space direct URL)

---

## 1. Endpoints

### 1.1 Health Check
**Endpoint:** `GET /health`
**Purpose:** Verify the service is running and check if the LLM provider is successfully configured.

**Response:**
```json
{
  "status": "healthy",
  "service": "BitCheck Text Verification API",
  "version": "1.0.0",
  "llm_available": true,
  "model": "deepseek-chat"
}
```

### 1.2 Full Verification (Recommended)
**Endpoint:** `POST /verify/text`
**Purpose:** Submit text for full analysis with all toggleable checks.

**Request Body (`application/json`):**
```json
{
  "text": "URGENT! The Federal Government is giving ₦500,000 grants to all students. Click this link and submit your BVN before midnight.",
  "source_url": "http://bit.ly/free-grant-now",
  "context": "WhatsApp broadcast",
  "language": "en",
  "check_ai_likelihood": true,
  "check_fraud_signals": true,
  "check_claims": true,
  "check_source_url": true
}
```

**Field Details:**
- `text` (string, required): The text to analyze. Must be between 5 and 8000 characters.
- `source_url` (string, optional): The URL where the text was found, or a link included within the text. The API validates and formats this automatically.
- `context` (string, optional): Contextual hint for the LLM (e.g., "WhatsApp broadcast", "Email").
- `language` (string, optional): Default `"en"`.
- `check_*` (boolean, optional): Default `true`. You can disable specific modules to speed up processing or reduce LLM token usage.

### 1.3 Simple Verification
**Endpoint:** `POST /verify/text/simple`
**Purpose:** A stripped-down version of the endpoint requiring fewer parameters. Under the hood, it calls the full verification with default settings.

**Request Body (`application/json`):**
```json
{
  "text": "Your text here...",
  "source_url": "https://example.com"
}
```

---

## 2. Understanding the Response

The API responds with a structured JSON object. The most critical part for your backend logic is the `trust` object and the `risk_flags`.

**Example Response Payload:**
```json
{
  "verification_id": "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d",
  "service": "BitCheck",
  "file_type": "text",
  "status": "completed",
  "processing_time_ms": 1450,
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
    "summary": "This text exhibits multiple high-risk fraud signals and relies on a shortened URL."
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
  // Detailed module breakdowns:
  "ai_likelihood": { ... },
  "claims": [ ... ],
  "fraud_signals": { ... },
  "manipulation_signals": { ... },
  "source_analysis": { ... },
  "warnings": [],
  "limitations": [...]
}
```

### Key Integration Points
When consuming this API in your backend, you should generally route your logic based on the `trust.decision` or `trust.risk_level` fields:

| `trust_score` | `risk_level` | `decision` | Recommended Backend Action |
|---------------|--------------|------------|----------------------------|
| 80–100 | Likely Authentic | `approve` | Allow content automatically. |
| 60–79 | Low Risk | `approve` | Allow content. |
| 40–59 | Suspicious | `review` | Flag for human moderation; warn user. |
| 20–39 | High Risk | `block_or_manual_review` | Shadow-ban or block publication; require admin review. |
| 0–19 | Very High Risk | `block_or_manual_review` | Hard block content; potential automated account suspension. |

---

## 3. Example Code Snippets

### Node.js / TypeScript Example
```typescript
async function verifyText(text: string, sourceUrl?: string) {
  try {
    const response = await fetch('http://127.0.0.1:7860/verify/text', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        text: text,
        source_url: sourceUrl,
        context: "User comment submission"
      }),
    });

    if (!response.ok) {
      throw new Error(`BitCheck API error: ${response.status}`);
    }

    const data = await response.json();
    
    // Example moderation logic
    if (data.trust.decision === 'block_or_manual_review') {
      console.warn('Content blocked. Risk Level:', data.trust.risk_level);
      return false; 
    }
    
    return true; // Content is safe
  } catch (error) {
    console.error('Verification failed:', error);
    // Fail open or fail closed depending on your system's risk tolerance
    return true; 
  }
}
```

### Python Example
```python
import requests

def check_content_safety(text: str, source_url: str = None) -> dict:
    url = "http://127.0.0.1:7860/verify/text"
    payload = {
        "text": text,
        "source_url": source_url,
        "check_claims": False  # Disable if you only care about fraud/scam to save time
    }
    
    response = requests.post(url, json=payload, timeout=10)
    response.raise_for_status()
    
    result = response.json()
    
    return {
        "is_safe": result["trust"]["decision"] == "approve",
        "score": result["trust"]["trust_score"],
        "flags": result["risk_flags"]
    }
```

## 4. Error Handling
The API handles validation internally using Pydantic.
- If the `text` is missing, too short (< 5 chars), or too long (> 8000 chars), the API will return an HTTP `422 Unprocessable Entity` with a detailed `detail` array explaining the validation failure.
- In case of internal LLM failures, the API returns a structured error object with an appropriate 500-level status code. Ensure your backend implements fallback logic (fail open vs. fail closed).
