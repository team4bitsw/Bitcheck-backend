"""
Mock ML response for image verification.

Returns a realistic response matching the ML service's /verify/image schema.
Used when ML_MOCK_RESPONSE=True in settings (e.g., when the ML service is down).
"""

import uuid
import hashlib
import random


def generate_mock_ml_response(filename, file_size_bytes, sha256_hash):
    """
    Generate a realistic mock ML response for an image verification.

    Args:
        filename:        Original filename of the uploaded image.
        file_size_bytes: Size of the file in bytes.
        sha256_hash:     SHA256 hex digest of the file.

    Returns:
        Dict matching the ML service's /verify/image response schema.
    """
    verification_id = str(uuid.uuid4())
    short_id = verification_id[:8]

    # Randomize the result slightly so each call looks different
    ai_prob = round(random.uniform(0.55, 0.95), 4)
    real_prob = round(1.0 - ai_prob, 4)
    trust_score = int((1 - ai_prob) * 100)
    manipulation_risk = round(random.uniform(0.25, 0.65), 2)
    sharpness = round(random.uniform(80.0, 200.0), 1)
    compression_risk = round(random.uniform(0.15, 0.55), 2)
    noise_risk = round(random.uniform(0.20, 0.60), 2)

    if trust_score >= 86:
        risk_level = "Low Risk"
        decision = "pass"
        predicted_label = "likely_real"
    elif trust_score >= 61:
        risk_level = "Medium Risk"
        decision = "review"
        predicted_label = "uncertain"
    elif trust_score >= 31:
        risk_level = "High Risk"
        decision = "block_or_manual_review"
        predicted_label = "likely_ai_generated"
    else:
        risk_level = "Critical Risk"
        decision = "block"
        predicted_label = "likely_ai_generated"

    # Build risk flags based on values
    risk_flags = []
    if ai_prob > 0.6:
        risk_flags.append("AI-generated probability is high.")
    risk_flags.append("No trusted C2PA provenance metadata found.")
    risk_flags.append("Camera EXIF metadata is missing.")
    if compression_risk > 0.3:
        risk_flags.append("Moderate compression artifacts detected.")
    if noise_risk > 0.4:
        risk_flags.append("Noise inconsistency detected in image regions.")

    return {
        "verification_id": verification_id,
        "service": "BitCheck",
        "file_type": "image",
        "status": "completed",
        "processing_time_ms": random.randint(800, 3500),
        "input": {
            "filename": filename,
            "sha256": sha256_hash,
            "width": 1024,
            "height": 768,
            "format": "JPEG",
            "mode": "RGB",
            "file_size_bytes": file_size_bytes,
            "mime_type": "image/jpeg"
        },
        "model_result": {
            "model_name": "bitcheck_efficientnet_b0",
            "model_version": "v1.0",
            "model_status": "loaded",
            "predicted_label": predicted_label,
            "real_probability": real_prob,
            "ai_generated_probability": ai_prob,
            "threshold": 0.62,
            "inference_time_ms": random.randint(200, 600)
        },
        "metadata": {
            "metadata_found": True,
            "camera_metadata_found": False,
            "software": "Adobe Photoshop",
            "creation_date": None,
            "modification_date": None,
            "gps_found": False,
            "known_ai_tool_detected": False,
            "detected_ai_tool": None,
            "editing_software_detected": True
        },
        "provenance": {
            "c2pa_checked": True,
            "c2pa_found": False,
            "signature_valid": None,
            "issuer": None,
            "claim_generator": None,
            "ingredients": [],
            "actions": [],
            "status": "missing",
            "summary": "No trusted C2PA provenance metadata found."
        },
        "visible_watermark": {
            "ocr_checked": True,
            "ocr_status": "available",
            "visible_watermark_found": False,
            "detected_keywords": [],
            "ocr_text_excerpt": ""
        },
        "forensics": {
            "manipulation_risk_score": manipulation_risk,
            "sharpness_score": sharpness,
            "compression_risk": compression_risk,
            "noise_inconsistency_risk": noise_risk,
            "artifact_flags": [
                f for f in [
                    "Moderate compression artifacts detected" if compression_risk > 0.3 else None,
                    "Camera EXIF metadata is missing",
                    "Noise inconsistency in image regions" if noise_risk > 0.4 else None,
                ] if f
            ],
            "summary": "The image shows moderate artifact risk but no single forensic signal is conclusive."
        },
        "explainability": {
            "status": "available",
            "method": "Grad-CAM",
            "heatmap_url": f"/outputs/{short_id}_heatmap.jpg",
            "boxed_image_url": f"/outputs/{short_id}_boxed.jpg",
            "hotspots": [
                {
                    "x": random.randint(50, 200),
                    "y": random.randint(50, 200),
                    "width": random.randint(100, 300),
                    "height": random.randint(80, 200),
                    "score": round(random.uniform(0.65, 0.90), 2),
                    "label": "high influence region"
                },
                {
                    "x": random.randint(300, 600),
                    "y": random.randint(200, 500),
                    "width": random.randint(80, 200),
                    "height": random.randint(60, 150),
                    "score": round(random.uniform(0.55, 0.80), 2),
                    "label": "high influence region"
                }
            ],
            "disclaimer": "Hotspots show regions that influenced the model's prediction. They are not definitive proof of manipulation."
        },
        "trust": {
            "trust_score": trust_score,
            "risk_score": round(ai_prob, 2),
            "risk_level": risk_level,
            "decision": decision,
            "summary": f"The image has a {'high' if ai_prob > 0.7 else 'moderate'} probability of being AI-generated or manipulated based on model prediction, missing provenance, and forensic indicators."
        },
        "risk_flags": risk_flags,
        "limitations": [
            "BitCheck provides a risk-based estimate, not an absolute truth claim.",
            "Missing metadata or C2PA provenance does not prove the image is fake.",
            "AI-generated image detection is probabilistic and may produce false positives or false negatives.",
            "Explainability hotspots represent model influence, not confirmed fake regions.",
            "Google SynthID and other proprietary invisible watermark detectors are not included unless official API access is available."
        ]
    }
