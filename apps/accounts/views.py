"""
Accounts views — authentication and user management.

Endpoints:
  POST /api/auth/register/       — email/password registration
  POST /api/auth/login/          — email/password session login
  POST /api/auth/logout/         — session logout
  POST /api/auth/google/         — Google OAuth id_token → session
  GET  /api/auth/me/             — current user profile
  PATCH /api/auth/me/            — update profile
  POST /api/auth/setup-org/      — create org + membership (personal → business)
"""

import logging
from django.conf import settings
from django.contrib.auth import login, logout
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

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
)

logger = logging.getLogger(__name__)


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
        logger.warning(f'Google OAuth token verification failed: {e}')
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
