"""
Custom DRF authentication for B2B API keys.

Usage in views:
    from apps.api_keys.authentication import ApiKeyAuthentication

    class MyView(APIView):
        authentication_classes = [ApiKeyAuthentication]

The authenticated request will have:
    request.user  → the key creator (or first org admin) — a real User
    request.auth  → the ApiKey instance
    request.auth.organization → the Organization

Ref: database design doc § 4.5 — auth flow.
"""

from django.utils import timezone
from rest_framework import authentication, exceptions

from .models import ApiKey


class ApiKeyAuthentication(authentication.BaseAuthentication):
    """
    DRF authentication backend for B2B API keys.

    Expects: Authorization: Bearer bk_live_xxxx...full_secret
    """

    keyword = 'Bearer'

    def authenticate(self, request):
        """
        Authenticate the request and return (user, auth) tuple.

        For API key auth:
          - user is None (API keys are org-level)
          - auth is the ApiKey instance

        Returns None if no Bearer token is present (falls through to
        other authenticators). Raises AuthenticationFailed if the token
        is present but invalid.
        """
        auth_header = authentication.get_authorization_header(request)
        if not auth_header:
            return None

        try:
            auth_parts = auth_header.decode('utf-8').split()
        except UnicodeDecodeError:
            return None

        if len(auth_parts) != 2:
            return None

        keyword, raw_key = auth_parts

        if keyword.lower() != self.keyword.lower():
            return None

        # We have a Bearer token that looks like an API key
        if not raw_key.startswith('bk_'):
            return None

        api_key = ApiKey.authenticate(raw_key)

        if api_key is None:
            raise exceptions.AuthenticationFailed(
                'Invalid or revoked API key.'
            )

        # Update last_used_at (non-blocking — we don't need to wait)
        ApiKey.objects.filter(pk=api_key.pk).update(
            last_used_at=timezone.now()
        )

        # Resolve a user for request.user — required by IsAuthenticated
        # and downstream code that does request.user filtering.
        # Priority: created_by → first admin member of the org
        user = api_key.created_by
        if user is None:
            from apps.accounts.models import OrganizationMembership
            membership = OrganizationMembership.objects.filter(
                organization=api_key.organization,
                role='admin',
            ).select_related('user').first()
            if membership:
                user = membership.user

        if user is None:
            raise exceptions.AuthenticationFailed(
                'API key organization has no associated user.'
            )

        # Return (user, auth=api_key)
        # request.auth is the ApiKey; request.auth.organization is the org
        return (user, api_key)

    def authenticate_header(self, request):
        """
        Return the WWW-Authenticate header value for 401 responses.
        """
        return f'{self.keyword} realm="bitcheck-api"'


class ApiKeyOrSessionAuthentication(authentication.BaseAuthentication):
    """
    Composite authenticator: tries API key first, then falls back to
    session authentication. Useful for endpoints that serve both B2B
    and B2C clients.
    """

    def authenticate(self, request):
        # Try API key first
        api_key_auth = ApiKeyAuthentication()
        result = api_key_auth.authenticate(request)
        if result is not None:
            return result

        # Fall back to session auth
        from rest_framework.authentication import SessionAuthentication
        session_auth = SessionAuthentication()
        return session_auth.authenticate(request)

    def authenticate_header(self, request):
        return 'Bearer realm="bitcheck-api"'
