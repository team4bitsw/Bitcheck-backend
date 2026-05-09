"""
Custom authentication backend for email-based login.

Django's default backend uses `username` to authenticate. Since our
User model uses `email` as the USERNAME_FIELD, we need this backend
to make `authenticate(email=..., password=...)` work correctly.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

User = get_user_model()


class EmailBackend(ModelBackend):
    """
    Authenticate against email + password.

    Falls through to ModelBackend's permission checks.
    """

    def authenticate(self, request, email=None, password=None, **kwargs):
        if email is None:
            email = kwargs.get('username', '')

        try:
            user = User.objects.get(email__iexact=email.strip())
        except User.DoesNotExist:
            # Run the password hasher to prevent timing attacks
            User().set_password(password)
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user

        return None
