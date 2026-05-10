"""
Accounts models — Identity & Access layer.

Models:
  - User:         AUTH_USER_MODEL. Email-based, UUID PK.
  - Organization: B2B entity. Has a slug, created by a user.
  - Membership:   Many-to-many link between User and Organization with a role.

Ref: database design doc § 4.1
"""

import uuid
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils.text import slugify


# ============================================================
# User
# ============================================================

class UserManager(BaseUserManager):
    """Custom manager for email-based authentication (no username)."""

    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('Users must have an email address')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('account_type', 'individual')

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """
    Custom user model — email-based, no username.

    Extends AbstractBaseUser + PermissionsMixin as specified in the
    database design doc (§ 4.1). UUID primary key for cross-system
    compatibility.

    `account_type` is a UX hint (drives default landing surface),
    NOT a security boundary. Authorization checks use Memberships.
    """

    class AccountType(models.TextChoices):
        INDIVIDUAL = 'individual', 'Individual'
        BUSINESS = 'business', 'Business'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True, max_length=255)
    full_name = models.CharField(max_length=255, blank=True, default='')
    account_type = models.CharField(
        max_length=20,
        choices=AccountType.choices,
        default=AccountType.INDIVIDUAL,
    )

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    email_verified_at = models.DateTimeField(null=True, blank=True)
    last_login_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []  # email is already required by USERNAME_FIELD

    class Meta:
        db_table = 'users'
        verbose_name = 'user'
        verbose_name_plural = 'users'

    def __str__(self):
        return self.email


# ============================================================
# Organization
# ============================================================

class Organization(models.Model):
    """
    A B2B entity. One user creates it; access is managed via Memberships.

    `slug` is auto-generated from `name` on creation and must be unique.
    Ref: database design doc § 4.1 — organizations table.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    slug = models.SlugField(max_length=255, unique=True)
    created_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.RESTRICT,
        related_name='created_organizations',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'organizations'
        verbose_name = 'organization'
        verbose_name_plural = 'organizations'

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        """Auto-generate slug from name if not set."""
        if not self.slug:
            base_slug = slugify(self.name)
            slug = base_slug
            counter = 1
            while Organization.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f'{base_slug}-{counter}'
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)


# ============================================================
# Membership
# ============================================================

class Membership(models.Model):
    """
    Links a User to an Organization with a role.

    Even in the hackathon 1:1 case (one user per org), we use this
    join table so multi-member support is free later.

    Ref: database design doc § 4.1 — memberships table.
    """

    class Role(models.TextChoices):
        OWNER = 'owner', 'Owner'
        ADMIN = 'admin', 'Admin'
        MEMBER = 'member', 'Member'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        'accounts.User',
        on_delete=models.CASCADE,
        related_name='memberships',
    )
    organization = models.ForeignKey(
        'accounts.Organization',
        on_delete=models.CASCADE,
        related_name='memberships',
    )
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.OWNER,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'memberships'
        verbose_name = 'membership'
        verbose_name_plural = 'memberships'
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'organization'],
                name='unique_user_organization',
            ),
        ]

    def __str__(self):
        return f'{self.user.email} → {self.organization.name} ({self.role})'
