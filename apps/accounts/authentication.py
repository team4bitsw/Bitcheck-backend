"""
Custom DRF authentication classes.

CsrfExemptSessionAuthentication:
  Identical to DRF's SessionAuthentication but skips CSRF enforcement.

  Why? DRF's built-in SessionAuthentication calls Django's CSRF middleware
  on EVERY request — even unauthenticated ones like register/login. This
  breaks Postman, mobile apps, and any non-browser client.

  Our CSRF protection comes from:
    - SameSite=Lax session cookies (browsers won't send cross-origin)
    - CORS whitelist (only our frontend origin is allowed)

  This is the standard approach for DRF APIs consumed by SPAs.
"""

from rest_framework.authentication import SessionAuthentication


class CsrfExemptSessionAuthentication(SessionAuthentication):
    """Session auth without CSRF enforcement."""

    def enforce_csrf(self, request):
        # Skip CSRF check — protection handled by SameSite cookies + CORS
        return
