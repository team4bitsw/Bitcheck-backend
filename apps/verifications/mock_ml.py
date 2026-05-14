"""
Mock ML response for image verification.

Returns a realistic response matching the BitCheck ML service's /verify/image schema.
Used when ML_MOCK_RESPONSE=True in settings (e.g., when the ML service is down).

Schema matches: https://jaykay73-bitcheck-image.hf.space/docs
"""

import uuid
import random


def generate_mock_ml_response(filename, file_size_bytes, sha256_hash, user_email=''):
    """
    Generate a realistic mock ML response for an image verification.

    Args:
        filename:        Original filename of the uploaded image.
        file_size_bytes: Size of the file in bytes.
        sha256_hash:     SHA256 hex digest of the file.
        user_email:      User's email address.

    Returns:
        Dict matching the ML service's /verify/image response schema.
    """
    verification_id = str(uuid.uuid4())
    short_id = verification_id[:8]

    # Randomize the result slightly so each call looks different
    confidence = round(random.uniform(0.55, 0.95), 4)
    is_ai = confidence > 0.5
    model_label = 'ai_generated' if is_ai else 'real'

    # Trust score: higher = more trustworthy (real)
    # If AI-generated, trust is low; if real, trust is high
    if model_label == 'ai_generated':
        trust_score = round(random.uniform(15.0, 45.0), 1)
    else:
        trust_score = round(random.uniform(70.0, 95.0), 1)

    if trust_score >= 75:
        trust_label = 'low_risk'
    elif trust_score >= 45:
        trust_label = 'moderate_risk'
    else:
        trust_label = 'high_risk'

    # Build risk flags
    risk_flags = []
    if model_label == 'ai_generated':
        risk_flags.append('AI-generated content detected by model.')
    risk_flags.append('No trusted C2PA provenance metadata found.')
    risk_flags.append('Camera EXIF metadata is missing.')
    if random.random() > 0.5:
        risk_flags.append('AI editing software detected in metadata.')

    sharpness = round(random.uniform(80.0, 200.0), 1)
    noise = round(random.uniform(0.20, 0.60), 2)

    return {
        'verification_id': verification_id,
        'service': 'BitCheck',
        'file_type': 'image',
        'status': 'completed',
        'user_email': user_email,
        'input': {
            'filename': filename,
            'sha256': sha256_hash,
            'width': 1024,
            'height': 768,
            'format': 'JPEG',
            'size_bytes': file_size_bytes,
        },
        'model_result': {
            'label': model_label,
            'confidence': confidence,
            'model_status': 'loaded',
        },
        'provenance': {
            'status': 'not_available',
            'c2pa_found': False,
        },
        'metadata': {
            'exif': {},
            'software_flags': ['Adobe Photoshop'] if random.random() > 0.5 else [],
            'camera_metadata_found': False,
        },
        'visible_watermark': {
            'ocr_status': 'completed',
            'visible_watermark_found': False,
            'detected_keywords': [],
        },
        'forensics': {
            'sharpness': sharpness,
            'noise_inconsistency': noise,
            'compression_artifacts': round(random.uniform(0.1, 0.5), 2),
        },
        'explainability': {
            'status': 'generated',
            'method': 'Grad-CAM',
            'heatmap_url': f'/outputs/{short_id}_heatmap.png',
            'boxed_image_url': f'/outputs/{short_id}_boxed.png',
            'hotspots': [
                {
                    'x': random.randint(50, 200),
                    'y': random.randint(50, 200),
                    'width': random.randint(40, 80),
                    'height': random.randint(40, 80),
                    'score': round(random.uniform(0.65, 0.90), 2),
                    'label': 'high influence region',
                },
                {
                    'x': random.randint(300, 600),
                    'y': random.randint(200, 500),
                    'width': random.randint(30, 70),
                    'height': random.randint(30, 70),
                    'score': round(random.uniform(0.55, 0.80), 2),
                    'label': 'high influence region',
                },
            ],
            'disclaimer': 'Hotspots show regions that influenced the model\'s prediction. They are not definitive proof of manipulation.',
        },
        'trust': {
            'score': trust_score,
            'label': trust_label,
            'breakdown': {
                'model_weight': 0.5,
                'metadata_weight': 0.2,
                'forensics_weight': 0.15,
                'provenance_weight': 0.15,
            },
        },
        'risk_flags': risk_flags,
        'limitations': [
            'BitCheck does not make absolute claims about image authenticity.',
            'Missing metadata or C2PA provenance does not prove the image is fake.',
            'AI-generated image detection is probabilistic and may produce false positives or false negatives.',
            'Explainability hotspots represent model influence, not confirmed fake regions.',
        ],
    }
