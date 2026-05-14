# BitCheck Image Verification API Integration Guide

This document outlines the endpoints available in the BitCheck Image Verification API to help backend engineers integrate the image analysis features.

## Base URL
The API is typically hosted at `http://localhost:8000` locally, or the appropriate production URL (e.g., your Hugging Face Space URL).

---

## Endpoints

### 1. Verify Image
Analyze an uploaded image for AI generation, forensics, and metadata/provenance.

**Endpoint:** `POST /verify/image`

**Content-Type:** `multipart/form-data`

**Request Parameters (Form Data):**
- `file` **(Required)**: The image file to analyze (e.g., `.jpg`, `.png`, `.webp`).
- `user_email` *(Optional)*: Email address of the user who owns this image and report. Useful for retrieving reports later.
- `run_explainability` *(Optional, Default: true)*: Generate a Grad-CAM heatmap showing which parts of the image influenced the AI prediction.
- `run_ocr` *(Optional, Default: true)*: Run OCR to detect visible AI tool watermarks.
- `run_forensics` *(Optional, Default: true)*: Run lightweight forensic analysis (noise, blur, edge inconsistencies).
- `run_c2pa` *(Optional, Default: true)*: Analyze C2PA provenance data (Content Credentials).
- `threshold` *(Optional)*: Override the default confidence threshold for the classifier model.

**cURL Example:**
```bash
curl -X POST "http://localhost:8000/verify/image" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@/path/to/your/image.jpg" \
  -F "user_email=user@example.com"
```

**Success Response (200 OK):**
Returns a comprehensive `VerificationReport` JSON object containing:
- `verification_id`: A unique ID for this report.
- `status`: Verification status (`completed`, `error`).
- `trust`: The final trust score and classification (e.g., `real`, `ai_generated`).
- Sections for `input`, `filename_analysis`, `metadata`, `provenance`, `visible_watermark_ocr`, `visible_watermark_template`, `classifier`, `forensics`, and `explainability`.

---

### 2. Retrieve a Specific Report
Fetch a previously generated verification report by its ID.

**Endpoint:** `GET /reports/{verification_id}`

**Path Parameters:**
- `verification_id` **(Required)**: The unique ID returned from the `/verify/image` endpoint.

**cURL Example:**
```bash
curl -X GET "http://localhost:8000/reports/b8f9e..." \
  -H "accept: application/json"
```

**Success Response (200 OK):**
Returns the same `VerificationReport` JSON object generated during the upload.

---

### 3. List Reports
Retrieve a list of past verification reports, optionally filtered by user email.

**Endpoint:** `GET /reports`

**Query Parameters:**
- `user_email` *(Optional)*: Filter the reports by the user's email address.

**cURL Example:**
```bash
curl -X GET "http://localhost:8000/reports?user_email=user@example.com" \
  -H "accept: application/json"
```

**Success Response (200 OK):**
```json
{
  "count": 1,
  "reports": [
    {
      "verification_id": "...",
      "user_email": "user@example.com",
      "filename": "image.jpg",
      "status": "completed",
      "trust": {
        "final_decision": "real",
        "trust_score_out_of_100": 95,
        ...
      },
      "processing_time_ms": 1205.4
    }
  ]
}
```

---

### 4. Health Check
Check if the API and its underlying services (OCR, C2PA, AI Models) are running correctly.

**Endpoint:** `GET /health`

**cURL Example:**
```bash
curl -X GET "http://localhost:8000/health" \
  -H "accept: application/json"
```

**Success Response (200 OK):**
```json
{
  "status": "ok",
  "service": "BitCheck Image Verification API",
  "classifier_loaded": true,
  "ocr_available": true,
  "c2pa_available": true,
  "device": "cpu"
}
```

---

## Static Assets (Explainability & Forensics)
If `run_explainability` or `run_forensics` are true, the JSON response will include URLs to generated images (e.g., heatmaps or annotated images). These are served via the static `/outputs/` directory.
Example: `http://localhost:8000/outputs/b8f9e..._gradcam_overlay.jpg`
