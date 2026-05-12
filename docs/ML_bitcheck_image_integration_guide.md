# BitCheck API — Backend Integration Guide

## 🔗 Links

| Resource | URL |
|---|---|
| **Live API (HF Spaces)** | `https://jaykay73-bitcheck-image.hf.space` |
| **Swagger/OpenAPI Docs** | `https://jaykay73-bitcheck-image.hf.space/docs` |
| **Health Check** | `https://jaykay73-bitcheck-image.hf.space/health` |
| **GitHub Repo** | `https://github.com/Jaykay73/bitcheck` |
| **HF Space Repo** | `https://huggingface.co/spaces/Jaykay73/Bitcheck-image` |

---

## 📡 API Endpoints

### 1. Service Status
```
GET /
```
Returns `{ "service": "BitCheck Image Verification API", "status": "running" }`

### 2. Health Check
```
GET /health
```
Returns API status and whether the ML model is loaded.

### 3. Verify Image ⭐ (Main Endpoint)
```
POST /verify/image
Content-Type: multipart/form-data
```

**Form Fields:**

| Field | Type | Required | Description |
|---|---|---|---|
| `user_gmail` | `string` | ✅ | Gmail address of the requesting user (must be `@gmail.com` or `@googlemail.com`) |
| `file` | `file` | ✅ | Image file (JPG, JPEG, PNG, or WEBP, max 12 MB) |

**Example cURL:**
```bash
curl -X POST "https://jaykay73-bitcheck-image.hf.space/verify/image" \
  -F "user_gmail=user@gmail.com" \
  -F "file=@photo.jpg"
```

**Example JavaScript (fetch):**
```javascript
const formData = new FormData();
formData.append('user_gmail', 'user@gmail.com');
formData.append('file', imageFile);

const response = await fetch('https://jaykay73-bitcheck-image.hf.space/verify/image', {
  method: 'POST',
  body: formData,
});
const report = await response.json();
```

### 4. Get Report by ID
```
GET /reports/{verification_id}
```
Returns a previously generated verification report.

### 5. Get Output Artifacts
```
GET /outputs/{filename}
```
Serves generated heatmaps, boxed images, etc.

---

## 📦 Response Schema (`VerificationReport`)

```json
{
  "verification_id": "abc123...",
  "service": "BitCheck",
  "file_type": "image",
  "status": "completed",
  "user_gmail": "user@gmail.com",
  "input": {
    "filename": "photo.jpg",
    "sha256": "...",
    "width": 1920,
    "height": 1080,
    "format": "JPEG",
    "size_bytes": 245000
  },
  "model_result": {
    "label": "real" | "ai_generated",
    "confidence": 0.92,
    "model_status": "loaded" | "missing"
  },
  "provenance": { "status": "checked" | "not_available", ... },
  "metadata": { "exif": {...}, "software_flags": [...], ... },
  "visible_watermark": { "ocr_status": "...", ... },
  "forensics": { "sharpness": ..., "noise_inconsistency": ..., ... },
  "explainability": {
    "status": "generated" | "failed",
    "method": "Grad-CAM",
    "heatmap_url": "/outputs/abc123_heatmap.png",
    "boxed_image_url": "/outputs/abc123_boxed.png",
    "hotspots": [{ "x": 100, "y": 200, "width": 50, "height": 50, "score": 0.85, "label": "high influence region" }],
    "disclaimer": "..."
  },
  "trust": {
    "score": 72.5,
    "label": "moderate_risk" | "low_risk" | "high_risk",
    "breakdown": { ... }
  },
  "risk_flags": ["AI editing software detected in metadata", ...],
  "limitations": ["BitCheck does not make absolute claims...", ...]
}
```

---

## ⚙️ Key Integration Notes

1. **CORS**: Currently set to `allow_origins=["*"]` — open to all origins. Lock down in production via `CORS_ORIGINS` env var.
2. **Max Upload**: 12 MB (`MAX_UPLOAD_BYTES=12582912`).
3. **Accepted Formats**: JPG, JPEG, PNG, WEBP only.
4. **Gmail Validation**: The `user_gmail` field is validated server-side — only `@gmail.com` and `@googlemail.com` domains are accepted.
5. **Heatmap/Output URLs**: URLs like `/outputs/abc123_heatmap.png` are **relative** to the API base. Prefix with the base URL when displaying in frontend.
6. **Model Threshold**: Default `0.5` — `prob_real >= 0.5` = real, `< 0.5` = AI-generated.
7. **Graceful Degradation**: If any analysis stage fails (model, OCR, C2PA, forensics), the API still returns a report with the remaining layers. Check individual `status` / `error` fields.

---

## 🛡️ Error Responses

| Status | Meaning |
|---|---|
| `400` | Invalid image, unreadable file, bad Gmail format, or unsupported file type |
| `404` | Report not found (for `GET /reports/{id}`) |
| `422` | Missing required form fields |

---

## 🚀 Environment Variables (for self-hosting)

```env
SERVICE_NAME="BitCheck Image Verification API"
MAX_UPLOAD_BYTES=12582912
MODEL_PATH="models/deepfake_detector_efficientnetb0.keras"
MODEL_ARCH="keras_efficientnetb0"
MODEL_INPUT_SIZE=224
MODEL_THRESHOLD=0.5
LOG_LEVEL="INFO"
CORS_ORIGINS='["https://yourfrontend.com"]'
```
