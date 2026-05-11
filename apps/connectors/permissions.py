"""DRF permissions for connector installs."""

from rest_framework.permissions import BasePermission

from apps.accounts.models import Membership


class IsConnectorInstallOwner(BasePermission):
    """B2C: install.user == request.user. B2B: request.user is member of install.organization."""

    message = 'You do not have access to this connector install.'

    def has_object_permission(self, request, view, obj):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if obj.user_id and obj.user_id == user.id:
            return True
        if obj.organization_id:
            return Membership.objects.filter(
                user=user,
                organization_id=obj.organization_id,
            ).exists()
        return False
