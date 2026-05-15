"""
Accounts views — authentication and user management.

Endpoints:
  POST /api/auth/register/        — email/password registration
  POST /api/auth/login/           — email/password session login
  POST /api/auth/logout/          — session logout
  POST /api/auth/google/          — Google OAuth id_token -> session
  GET  /api/auth/me/              — current user profile
  PATCH /api/auth/me/             — update profile
  POST /api/auth/setup-org/       — create org + membership (personal -> business)
  POST /api/auth/forgot-password/ — request a password reset token
  POST /api/auth/reset-password/  — consume token + set new password
"""

from django.conf import settings
from django.contrib.auth import login, logout
from django.contrib.auth.tokens import default_token_generator
from django.db import transaction
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from apps.core.logger import logger

from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests

from .models import User, Organization, Membership
from .serializers import (
    RegisterSerializer,
    LoginSerializer,
    GoogleAuthSerializer,
    UserSerializer,
    UserUpdateSerializer,
    SetupOrgSerializer,
    OrganizationSerializer,
    ForgotPasswordSerializer,
    ResetPasswordSerializer,
)

log = logger.child('accounts')


# ============================================================
# Registration
# ============================================================

@api_view(['POST'])
@permission_classes([AllowAny])
def register_view(request):
    """
    Register a new user with email and password.

    On success, automatically logs the user in via session and returns
    the user object.
    """
    serializer = RegisterSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    user = serializer.save()

    # Auto-login after registration
    login(request, user)
    user.last_login_at = timezone.now()
    user.save(update_fields=['last_login_at'])

    return Response(
        {
            'detail': 'Registration successful.',
            'user': UserSerializer(user).data,
        },
        status=status.HTTP_201_CREATED,
    )


# ============================================================
# Login
# ============================================================

@api_view(['POST'])
@permission_classes([AllowAny])
def login_view(request):
    """
    Authenticate with email and password.

    Sets a session cookie on success. The frontend must include
    `credentials: 'include'` in fetch calls.
    """
    serializer = LoginSerializer(data=request.data, context={'request': request})
    serializer.is_valid(raise_exception=True)

    user = serializer.validated_data['user']
    login(request, user)
    user.last_login_at = timezone.now()
    user.save(update_fields=['last_login_at'])

    return Response(
        {
            'detail': 'Login successful.',
            'user': UserSerializer(user).data,
        },
        status=status.HTTP_200_OK,
    )


# ============================================================
# Logout
# ============================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def logout_view(request):
    """
    Destroy the current session. The frontend should clear any
    cached user state on receiving the response.
    """
    logout(request)
    return Response(
        {'detail': 'Logged out successfully.'},
        status=status.HTTP_200_OK,
    )


# ============================================================
# Google OAuth
# ============================================================

@api_view(['POST'])
@permission_classes([AllowAny])
def google_auth_view(request):
    """
    Accept a Google id_token from the frontend, verify it using the
    google-auth library, then get-or-create the user and log them in
    via sessions.

    Flow:
    1. Frontend does Google Sign-In, gets an id_token.
    2. Frontend POSTs { "id_token": "..." } here.
    3. We verify the token with Google's servers.
    4. Extract email + name from the token payload.
    5. Get or create the User.
    6. Log them in via Django sessions.
    """
    serializer = GoogleAuthSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    token = serializer.validated_data['id_token']

    # Verify the token with Google
    try:
        idinfo = google_id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            settings.GOOGLE_CLIENT_ID,
        )
    except ValueError as e:
        log.warning('google_token_verify_failed', error=str(e))
        return Response(
            {'detail': 'Invalid Google token.'},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    # Extract user info from the verified token
    email = idinfo.get('email', '').lower().strip()
    full_name = idinfo.get('name', '')

    if not email:
        return Response(
            {'detail': 'Google token did not contain an email.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Get or create the user
    user, created = User.objects.get_or_create(
        email=email,
        defaults={
            'full_name': full_name,
            'account_type': User.AccountType.INDIVIDUAL,
            'email_verified_at': timezone.now(),  # Google has verified this email
        },
    )

    # If existing user, update name if they didn't have one
    if not created and not user.full_name and full_name:
        user.full_name = full_name
        user.save(update_fields=['full_name', 'updated_at'])

    # Mark email as verified if it wasn't already
    if not user.email_verified_at:
        user.email_verified_at = timezone.now()
        user.save(update_fields=['email_verified_at', 'updated_at'])

    # Log them in
    login(request, user)
    user.last_login_at = timezone.now()
    user.save(update_fields=['last_login_at'])

    return Response(
        {
            'detail': 'Google authentication successful.',
            'created': created,
            'user': UserSerializer(user).data,
        },
        status=status.HTTP_200_OK,
    )


# ============================================================
# Current User
# ============================================================

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def setup_org_view(request):
    """
    Create an organization and admin membership for the current user.

    For users who signed up as individual (no Membership). Idempotent guard:
    rejects if the user already has any membership.
    """
    serializer = SetupOrgSerializer(data=request.data, context={'request': request})
    serializer.is_valid(raise_exception=True)

    org_name = serializer.validated_data['organization_name']
    org_description = serializer.validated_data.get('organization_description', '').strip()
    user = request.user

    with transaction.atomic():
        org = Organization.objects.create(
            name=org_name,
            description=org_description,
            created_by=user,
        )
        Membership.objects.create(
            user=user,
            organization=org,
            role=Membership.Role.ADMIN,
        )
        user.account_type = User.AccountType.BUSINESS
        user.save(update_fields=['account_type', 'updated_at'])

    log.info(
        'setup_org_ok',
        user_id=str(user.pk),
        org_id=str(org.pk),
        org_slug=org.slug,
    )

    return Response(
        {
            'detail': 'Organization created.',
            'organization': OrganizationSerializer(org).data,
            'user': UserSerializer(user).data,
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(['GET', 'PATCH'])
@permission_classes([IsAuthenticated])
def me_view(request):
    """
    GET:   Return the current user's profile.
    PATCH: Update editable profile fields (full_name, account_type).
    """
    user = request.user

    if request.method == 'GET':
        return Response(
            {'user': UserSerializer(user).data},
            status=status.HTTP_200_OK,
        )

    # PATCH
    serializer = UserUpdateSerializer(user, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    serializer.save()

    return Response(
        {
            'detail': 'Profile updated.',
            'user': UserSerializer(user).data,
        },
        status=status.HTTP_200_OK,
    )


# ============================================================
# Forgot / Reset Password
# ============================================================

@api_view(['POST'])
@permission_classes([AllowAny])
def forgot_password_view(request):
    """
    Request a password reset.

    Accepts { "email": "user@example.com" }.
    Always returns 200 regardless of whether the email exists
    (prevents email enumeration).

    In development: returns the reset token + uid in the response
    so you can test without an email provider.
    In production: would send an email with a reset link.
    """
    serializer = ForgotPasswordSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    email = serializer.validated_data['email']

    # Generic success message (always, to prevent enumeration)
    success_msg = 'If an account with that email exists, a password reset link has been sent.'

    try:
        user = User.objects.get(email=email, is_active=True)
    except User.DoesNotExist:
        log.info('forgot_password_no_user', email=email)
        return Response({'detail': success_msg}, status=status.HTTP_200_OK)

    # Generate token
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)

    log.info('forgot_password_token_generated', user_id=str(user.pk), uid=uid)

    # Build reset URL for frontend
    frontend_base = getattr(settings, 'FRONTEND_APP_BASE_URL', 'http://localhost:3000').rstrip('/')
    reset_url = f'{frontend_base}/reset-password?uid={uid}&token={token}'

    # TODO: Send email with reset_url in production.
    # For now, include the token in the response for dev/testing.
    response_data = {'detail': success_msg, 'reset_url': reset_url}

    # In dev, also include raw uid/token for easy testing
    if settings.DEBUG:
        response_data['uid'] = uid
        response_data['token'] = token

    return Response(response_data, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([AllowAny])
def reset_password_view(request):
    """
    Reset password using uid + token from the forgot-password flow.

    Accepts:
        {
            "uid": "base64-encoded-user-id",
            "token": "password-reset-token",
            "new_password": "newSecurePassword123"
        }

    Returns 200 on success, 400 on invalid/expired token.
    """
    serializer = ResetPasswordSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    uid_b64 = serializer.validated_data['uid']
    token = serializer.validated_data['token']
    new_password = serializer.validated_data['new_password']

    # Decode uid
    try:
        uid = force_str(urlsafe_base64_decode(uid_b64))
        user = User.objects.get(pk=uid, is_active=True)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        log.warning('reset_password_invalid_uid', uid=uid_b64)
        return Response(
            {'detail': 'Invalid or expired reset link.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Verify token
    if not default_token_generator.check_token(user, token):
        log.warning('reset_password_invalid_token', user_id=str(user.pk))
        return Response(
            {'detail': 'Invalid or expired reset link.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Set new password
    user.set_password(new_password)
    user.save(update_fields=['password'])

    log.info('reset_password_ok', user_id=str(user.pk))

    return Response(
        {'detail': 'Password has been reset successfully. You can now log in.'},
        status=status.HTTP_200_OK,
    )
