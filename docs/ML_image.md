**POST /verify/image**

The endpoint accepts `multipart/form-data` for uploading an image file.

### 1. Input Schema

- **Endpoint**: `POST /verify/image`
- **Content-Type**: `multipart/form-data`

#### Required & Optional Fields

| Field                  | Type          | Required | Description |
|------------------------|---------------|----------|-----------|
| `file`                 | image file    | Yes      | Uploaded image: `.jpg`, `.jpeg`, `.png`, `.webp` |
| `run_explainability`   | boolean       | No       | Whether to generate Grad-CAM heatmap and hotspot boxes |
| `run_ocr`              | boolean       | No       | Whether to check visible watermark/text |
| `run_c2pa`             | boolean       | No       | Whether to check C2PA/Content Credentials |
| `threshold`            | float         | No       | Optional custom AI-detection threshold |

**Example form-data:**
- `file`: `suspicious_image.jpg`
- `run_explainability`: `true`
- `run_ocr`: `true`
- `run_c2pa`: `true`
- `threshold`: `0.62`

### 2. Example cURL Requests

**Hugging Face Space:**
```bash
curl -X POST "https://YOUR-USERNAME-bitcheck-image.hf.space/verify/image" \
  -F "file=@sample.jpg" \
  -F "run_explainability=true" \
  -F "run_ocr=true" \
  -F "run_c2pa=true"
```

**Local testing:**
```bash
curl -X POST "http://127.0.0.1:7860/verify/image" \
  -F "file=@sample.jpg" \
  -F "run_explainability=true" \
  -F "run_ocr=true" \
  -F "run_c2pa=true"
```

### 3. Successful Response Schema

```json
{
  "verification_id": "8d53cf77-2b2d-4d55-b6a9-6c98cbbe7421",
  "service": "BitCheck",
  "file_type": "image",
  "status": "completed",
  "processing_time_ms": 2841,
  "input": {
    "filename": "sample.jpg",
    "sha256": "b1ddf2f9f25c0f9adfb1f0d2a7d4f4bcb1aeb8d4f91f9d8e6a0c4e1d6e8f1234",
    "width": 1024,
    "height": 768,
    "format": "JPEG",
    "mode": "RGB",
    "file_size_bytes": 248391,
    "mime_type": "image/jpeg"
  },
  "model_result": {
    "model_name": "bitcheck_efficientnet_b0",
    "model_version": "v1.0",
    "model_status": "loaded",
    "predicted_label": "likely_ai_generated",
    "real_probability": 0.1372,
    "ai_generated_probability": 0.8628,
    "threshold": 0.62,
    "inference_time_ms": 412
  },
  "metadata": {
    "metadata_found": true,
    "camera_metadata_found": false,
    "software": "Adobe Photoshop",
    "creation_date": null,
    "modification_date": null,
    "gps_found": false,
    "known_ai_tool_detected": false,
    "detected_ai_tool": null,
    "editing_software_detected": true
  },
  "provenance": {
    "c2pa_checked": true,
    "c2pa_found": false,
    "signature_valid": null,
    "issuer": null,
    "claim_generator": null,
    "ingredients": [],
    "actions": [],
    "status": "missing",
    "summary": "No trusted C2PA provenance metadata found."
  },
  "visible_watermark": {
    "ocr_checked": true,
    "ocr_status": "available",
    "visible_watermark_found": false,
    "detected_keywords": [],
    "ocr_text_excerpt": ""
  },
  "forensics": {
    "manipulation_risk_score": 0.41,
    "sharpness_score": 118.6,
    "compression_risk": 0.33,
    "noise_inconsistency_risk": 0.48,
    "artifact_flags": [
      "Moderate compression artifacts detected",
      "Camera EXIF metadata is missing"
    ],
    "summary": "The image shows moderate artifact risk but no single forensic signal is conclusive."
  },
  "explainability": {
    "status": "available",
    "method": "Grad-CAM",
    "heatmap_url": "/outputs/8d53cf77_heatmap.jpg",
    "boxed_image_url": "/outputs/8d53cf77_boxed.jpg",
    "hotspots": [
      {
        "x": 114,
        "y": 88,
        "width": 231,
        "height": 166,
        "score": 0.78,
        "label": "high influence region"
      },
      {
        "x": 512,
        "y": 302,
        "width": 154,
        "height": 121,
        "score": 0.69,
        "label": "high influence region"
      }
    ],
    "disclaimer": "Hotspots show regions that influenced the model's prediction. They are not definitive proof of manipulation."
  },
  "trust": {
    "trust_score": 31,
    "risk_score": 0.69,
    "risk_level": "High Risk",
    "decision": "block_or_manual_review",
    "summary": "The image has a high probability of being AI-generated or manipulated based on model prediction, missing provenance, and forensic indicators."
  },
  "risk_flags": [
    "AI-generated probability is high.",
    "No trusted C2PA provenance metadata found.",
    "Camera EXIF metadata is missing.",
    "Image appears to have been processed by editing software.",
    "Moderate compression artifacts detected."
  ],
  "limitations": [
    "BitCheck provides a risk-based estimate, not an absolute truth claim.",
    "Missing metadata or C2PA provenance does not prove the image is fake.",
    "AI-generated image detection is probabilistic and may produce false positives or false negatives.",
    "Explainability hotspots represent model influence, not confirmed fake regions.",
    "Google SynthID and other proprietary invisible watermark detectors are not included unless official API access is available."
  ]
}
```