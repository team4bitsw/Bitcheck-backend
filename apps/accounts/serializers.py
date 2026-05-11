"""
Accounts serializers — auth endpoints and user data.
"""

from django.contrib.auth import authenticate
from rest_framework import serializers
from .models import User, Organization, Membership


# ============================================================
# User
# ============================================================

class UserSerializer(serializers.ModelSerializer):
    """Read-only representation of the current user."""

    class Meta:
        model = User
        fields = [
            'id', 'email', 'full_name', 'account_type',
            'is_active', 'email_verified_at', 'last_login_at',
            'created_at', 'updated_at',
        ]
        read_only_fields = fields


class UserUpdateSerializer(serializers.ModelSerializer):
    """Allow users to update their own profile fields."""

    class Meta:
        model = User
        fields = ['full_name', 'account_type']


# ============================================================
# Registration
# ============================================================

class RegisterSerializer(serializers.Serializer):
    """
    Register a new user with email + password.

    For B2B signups (account_type='business'), also accepts
    organization_name and organization_description to create the
    Organization + admin Membership in one step.
    """

    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    full_name = serializers.CharField(required=False, default='', allow_blank=True)
    account_type = serializers.ChoiceField(
        choices=User.AccountType.choices,
        default=User.AccountType.INDIVIDUAL,
    )

    # B2B fields — required when account_type='business'
    organization_name = serializers.CharField(
        required=False, max_length=255, allow_blank=True, default='',
    )
    organization_description = serializers.CharField(
        required=False, allow_blank=True, default='',
    )

    def validate_email(self, value):
        email = value.lower().strip()
        if User.objects.filter(email__iexact=email).exists():
            raise serializers.ValidationError('A user with this email already exists.')
        return email

    def validate(self, attrs):
        """Ensure org fields are provided for business accounts."""
        if attrs.get('account_type') == User.AccountType.BUSINESS:
            org_name = attrs.get('organization_name', '').strip()
            if not org_name:
                raise serializers.ValidationError({
                    'organization_name': 'Organization name is required for B2B accounts.',
                })
        return attrs

    def create(self, validated_data):
        # Pop org fields before creating the user
        org_name = validated_data.pop('organization_name', '').strip()
        org_description = validated_data.pop('organization_description', '').strip()

        user = User.objects.create_user(
            email=validated_data['email'],
            password=validated_data['password'],
            full_name=validated_data.get('full_name', ''),
            account_type=validated_data.get('account_type', 'individual'),
        )

        # If B2B, create Organization + admin Membership
        if validated_data.get('account_type') == User.AccountType.BUSINESS and org_name:
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

        return user


# ============================================================
# Login
# ============================================================

class LoginSerializer(serializers.Serializer):
    """
    Authenticate with email + password.
    Returns the user object on success; raises ValidationError on failure.
    """

    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        email = attrs['email'].lower().strip()
        password = attrs['password']

        user = authenticate(
            request=self.context.get('request'),
            email=email,
            password=password,
        )

        if user is None:
            raise serializers.ValidationError(
                {'detail': 'Invalid email or password.'}
            )

        if not user.is_active:
            raise serializers.ValidationError(
                {'detail': 'This account has been deactivated.'}
            )

        attrs['user'] = user
        return attrs


# ============================================================
# Google OAuth
# ============================================================

class GoogleAuthSerializer(serializers.Serializer):
    """
    Accept a Google id_token from the frontend.
    The view will verify it using the google-auth library.
    """

    id_token = serializers.CharField()


# ============================================================
# Organization
# ============================================================

class OrganizationSerializer(serializers.ModelSerializer):
    """Read/write representation of an Organization."""

    class Meta:
        model = Organization
        fields = ['id', 'name', 'description', 'slug', 'created_by', 'created_at', 'updated_at']
        read_only_fields = ['id', 'slug', 'created_by', 'created_at', 'updated_at']


class OrganizationDetailSerializer(serializers.ModelSerializer):
    """Detailed org view including member count."""

    member_count = serializers.SerializerMethodField()

    class Meta:
        model = Organization
        fields = ['id', 'name', 'description', 'slug', 'created_by', 'member_count', 'created_at', 'updated_at']
        read_only_fields = fields

    def get_member_count(self, obj):
        return obj.memberships.count()


# ============================================================
# Membership
# ============================================================

class MembershipSerializer(serializers.ModelSerializer):
    """Membership representation for org member listings."""

    user_email = serializers.CharField(source='user.email', read_only=True)
    user_full_name = serializers.CharField(source='user.full_name', read_only=True)
    organization_name = serializers.CharField(source='organization.name', read_only=True)

    class Meta:
        model = Membership
        fields = [
            'id', 'user', 'user_email', 'user_full_name',
            'organization', 'organization_name', 'role', 'created_at',
        ]
        read_only_fields = ['id', 'created_at']


# ============================================================
# Setup organization (post-signup)
# ============================================================


class SetupOrgSerializer(serializers.Serializer):
    """
    Create an Organization + admin Membership for an authenticated user
    who does not already belong to an organization.
    """

    organization_name = serializers.CharField(max_length=255)
    organization_description = serializers.CharField(
        required=False, allow_blank=True, default='',
    )

    def validate_organization_name(self, value):
        text = value.strip()
        if not text:
            raise serializers.ValidationError('Organization name is required.')
        return text

    def validate(self, attrs):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            raise serializers.ValidationError({'detail': 'Authentication required.'})
        user = request.user
        if Membership.objects.filter(user=user).exists():
            raise serializers.ValidationError({
                'detail': 'You already belong to an organization.',
            })
        return attrs
