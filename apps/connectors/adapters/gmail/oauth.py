"""Google OAuth helpers for the Gmail connector install flow."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
import requests
from django.conf import settings
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from apps.connectors.exceptions import InvalidPayload

logger = logging.getLogger(__name__)

STATE_ALGORITHM = 'HS256'
STATE_TTL = timedelta(minutes=15)

GMAIL_INSTALL_SCOPES = [
    'openid',
    'https://www.googleapis.com/auth/userinfo.email',
    # Google often grants this with openid/email; omitting it makes oauthlib reject the token response.
    'https://www.googleapis.com/auth/userinfo.profile',
    # Read emails and attachments for verification
    'https://www.googleapis.com/auth/gmail.readonly',
    # Modify labels (mark processed messages)
    'https://www.googleapis.com/auth/gmail.modify',
    # Send reply emails with verification results
    'https://www.googleapis.com/auth/gmail.send',
]


def _require_google_oauth_config() -> None:
    if not settings.GOOGLE_OAUTH_CLIENT_ID or not settings.GOOGLE_OAUTH_CLIENT_SECRET:
        raise InvalidPayload('Google OAuth is not configured (missing client id or secret).')


def _web_client_config() -> dict[str, Any]:
    return {
        'web': {
            'client_id': settings.GOOGLE_OAUTH_CLIENT_ID,
            'client_secret': settings.GOOGLE_OAUTH_CLIENT_SECRET,
            'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
            'token_uri': 'https://oauth2.googleapis.com/token',
            'redirect_uris': [settings.GOOGLE_OAUTH_REDIRECT_URI],
        }
    }


def build_oauth_state(user, organization, *, slug: str) -> str:
    """Sign a short-lived JWT tying this OAuth round-trip to a user (and optional org)."""
    now = datetime.now(timezone.utc)
    exp = now + STATE_TTL
    payload = {
        'slug': slug,
        'user_id': str(user.pk),
        'org_id': str(organization.pk) if organization is not None else None,
        'iat': int(now.timestamp()),
        'exp': int(exp.timestamp()),
    }
    secret = settings.CONNECTORS_OAUTH_STATE_SECRET
    if not secret:
        raise InvalidPayload('CONNECTORS_OAUTH_STATE_SECRET is not configured.')
    return jwt.encode(payload, secret, algorithm=STATE_ALGORITHM)


def parse_oauth_state(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(
            token,
            settings.CONNECTORS_OAUTH_STATE_SECRET,
            algorithms=[STATE_ALGORITHM],
        )
    except jwt.PyJWTError as e:
        logger.warning('Invalid OAuth state JWT: %s', e)
        raise InvalidPayload('Invalid or expired OAuth state.') from e


def verify_oauth_state_for_install(
    state_token: str,
    *,
    expected_slug: str,
    user,
    organization,
) -> None:
    claims = parse_oauth_state(state_token)
    if claims.get('slug') != expected_slug:
        raise InvalidPayload('OAuth state slug mismatch.')
    if str(claims.get('user_id')) != str(user.pk):
        raise InvalidPayload('OAuth state user mismatch.')
    claim_org = claims.get('org_id')
    if organization is not None:
        if claim_org is None or str(claim_org) != str(organization.pk):
            raise InvalidPayload('OAuth state organization mismatch.')
    else:
        if claim_org is not None:
            raise InvalidPayload('OAuth state organization mismatch.')


def build_auth_url(state: str) -> str:
    _require_google_oauth_config()
    flow = Flow.from_client_config(
        _web_client_config(),
        scopes=GMAIL_INSTALL_SCOPES,
    )
    flow.redirect_uri = settings.GOOGLE_OAUTH_REDIRECT_URI
    authorization_url, _state_returned = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent',
        state=state,
    )
    return authorization_url


def exchange_code(code: str) -> dict[str, Any]:
    _require_google_oauth_config()
    flow = Flow.from_client_config(
        _web_client_config(),
        scopes=GMAIL_INSTALL_SCOPES,
    )
    flow.redirect_uri = settings.GOOGLE_OAUTH_REDIRECT_URI
    flow.fetch_token(code=code)
    creds = flow.credentials
    expires_in: int | None = None
    if creds.expiry is not None:
        delta = creds.expiry.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)
        expires_in = max(0, int(delta.total_seconds()))
    return {
        'access_token': creds.token,
        'refresh_token': getattr(creds, 'refresh_token', None),
        'expires_in': expires_in,
        'token_type': 'Bearer',
        'id_token': getattr(creds, 'id_token', None),
    }


def get_user_email(access_token: str) -> str:
    resp = requests.get(
        'https://www.googleapis.com/oauth2/v3/userinfo',
        headers={'Authorization': f'Bearer {access_token}'},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    email = data.get('email')
    if not email:
        raise InvalidPayload('Google did not return an email address.')
    return str(email)


def exchange_refresh_token(refresh_token_value: str) -> dict[str, Any]:
    _require_google_oauth_config()
    creds = Credentials(
        token=None,
        refresh_token=refresh_token_value,
        token_uri='https://oauth2.googleapis.com/token',
        client_id=settings.GOOGLE_OAUTH_CLIENT_ID,
        client_secret=settings.GOOGLE_OAUTH_CLIENT_SECRET,
    )
    creds.refresh(GoogleAuthRequest())
    expires_in: int | None = None
    if creds.expiry is not None:
        delta = creds.expiry.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)
        expires_in = max(0, int(delta.total_seconds()))
    return {
        'access_token': creds.token,
        'expires_in': expires_in,
    }


def revoke_google_token(token: str) -> None:
    """Best-effort revoke (refresh or access token)."""
    try:
        requests.post(
            'https://oauth2.googleapis.com/revoke',
            data={'token': token},
            headers={'Content-Type': 'application/x-www-form-urlencoded'},
            timeout=10,
        )
    except requests.RequestException:
        logger.exception('Google token revoke request failed')
