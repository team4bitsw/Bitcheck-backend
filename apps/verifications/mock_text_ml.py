"""
Mock ML response for text verification.

Returns a realistic response matching the BitCheck Text ML service's /verify/text schema.
Used when ML_MOCK_RESPONSE=True in settings.

Schema matches: https://jaykay73-bitcheck-text.hf.space/docs
"""

import uuid
import random


def generate_mock_text_ml_response(text_input, source_url=None):
    """
    Generate a realistic mock ML response for text verification.
    """
    verification_id = str(uuid.uuid4())
    text_length = len(text_input)

    # Randomize results
    trust_score = random.randint(10, 90)
    risk_score = round(1 - trust_score / 100, 2)

    if trust_score >= 80:
        risk_level = 'Likely Authentic'
        decision = 'approve'
    elif trust_score >= 60:
        risk_level = 'Low Risk'
        decision = 'approve'
    elif trust_score >= 40:
        risk_level = 'Suspicious'
        decision = 'review'
    elif trust_score >= 20:
        risk_level = 'High Risk'
        decision = 'block_or_manual_review'
    else:
        risk_level = 'Very High Risk'
        decision = 'block_or_manual_review'

    # Build risk flags
    risk_flags = []
    if trust_score < 40:
        risk_flags.append('Urgency/Pressure tactics detected')
    if trust_score < 30:
        risk_flags.append('Financial scam keywords found')
    if source_url and ('bit.ly' in source_url or 'tinyurl' in source_url):
        risk_flags.append('Suspicious shortened URL')
    if random.random() > 0.6:
        risk_flags.append('Potential emotional manipulation detected')

    ai_confidence = round(random.uniform(0.3, 0.95), 2)

    return {
        'verification_id': verification_id,
        'service': 'BitCheck',
        'file_type': 'text',
        'status': 'completed',
        'processing_time_ms': random.randint(500, 3000),
        'input': {
            'text_length': text_length,
            'source_url': source_url or '',
            'language': 'en',
            'context': '',
        },
        'trust': {
            'trust_score': trust_score,
            'risk_score': risk_score,
            'risk_level': risk_level,
            'decision': decision,
            'summary': f'Text analysis complete. Risk level: {risk_level}.',
        },
        'risk_flags': risk_flags,
        'recommended_actions': [
            'Verify claims through official sources',
            'Do not share personal information based on this text',
        ] if trust_score < 50 else [],
        'ai_likelihood': {
            'is_ai_generated': ai_confidence > 0.6,
            'confidence': ai_confidence,
            'reasoning': 'Based on linguistic pattern analysis.',
        },
        'claims': [],
        'fraud_signals': {
            'score': round(random.uniform(0.1, 0.8), 2),
            'signals_found': risk_flags[:2] if risk_flags else [],
        },
        'manipulation_signals': {
            'urgency_detected': trust_score < 40,
            'emotional_manipulation': random.random() > 0.5,
            'authority_impersonation': random.random() > 0.7,
        },
        'source_analysis': {
            'url_analyzed': source_url or '',
            'url_safe': source_url is None or trust_score > 50,
            'domain_reputation': 'unknown',
        } if source_url else {},
        'warnings': [],
        'limitations': [
            'BitCheck text analysis is probabilistic and may produce false positives.',
            'AI generation detection is not definitive.',
            'Source URL analysis checks domain reputation, not page content.',
        ],
    }
