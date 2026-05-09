"""
Accounts admin — User, Organization, Membership.
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, Organization, Membership


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Admin for the custom User model (email-based, no username)."""

    list_display = ('email', 'full_name', 'account_type', 'is_active', 'is_staff', 'created_at')
    list_filter = ('account_type', 'is_active', 'is_staff', 'is_superuser')
    search_fields = ('email', 'full_name')
    ordering = ('-created_at',)

    # Override fieldsets since we don't use username
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal Info', {'fields': ('full_name', 'account_type')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Timestamps', {'fields': ('email_verified_at', 'last_login_at')}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'password1', 'password2', 'full_name', 'account_type'),
        }),
    )


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'created_by', 'created_at')
    search_fields = ('name', 'slug')
    readonly_fields = ('id', 'slug', 'created_at', 'updated_at')
    ordering = ('-created_at',)


@admin.register(Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ('user', 'organization', 'role', 'created_at')
    list_filter = ('role',)
    search_fields = ('user__email', 'organization__name')
    ordering = ('-created_at',)
