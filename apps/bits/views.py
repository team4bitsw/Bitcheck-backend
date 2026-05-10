"""
Bits views — B2B virtual account provisioning, wallet balance, and top-up history.

Endpoints:
  POST /api/bits/virtual-account/provision/  — create a Squad VA for an org
  GET  /api/bits/virtual-account/            — get VA details for the user's org
  GET  /api/bits/wallet/                     — wallet balance + top-up history
"""

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.accounts.models import Membership
from .models import TopUp, VirtualAccount
from .services import get_wallet_for_organization
from .va_services import provision_virtual_account, get_virtual_account_info


def _get_user_organization(user):
    """
    Get the organization the user belongs to.
    Returns (organization, error_response) — error_response is None on success.
    """
    membership = Membership.objects.select_related('organization').filter(
        user=user,
    ).first()

    if not membership:
        return None, Response(
            {'detail': 'You are not a member of any organization.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    return membership.organization, None


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def provision_virtual_account_view(request):
    """
    Provision a Squad B2B virtual account for the user's organization.

    Creates a permanent bank account number that the organization can
    use to top up their bit wallet via standard bank transfers.

    Request body:
        bvn*:        str — BVN of the org representative
        mobile_num*: str — Phone number (e.g., '08012345678')

    Returns:
        Virtual account details (account_number, bank_name, etc.)
    """
    org, error = _get_user_organization(request.user)
    if error:
        return error

    # Check admin role
    membership = Membership.objects.get(user=request.user, organization=org)
    if membership.role != Membership.Role.ADMIN:
        return Response(
            {'detail': 'Only organization admins can provision virtual accounts.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    bvn = request.data.get('bvn', '').strip()
    mobile_num = request.data.get('mobile_num', '').strip()

    if not bvn or not mobile_num:
        return Response(
            {'detail': 'Both bvn and mobile_num are required.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if len(bvn) != 11 or not bvn.isdigit():
        return Response(
            {'detail': 'BVN must be exactly 11 digits.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if len(mobile_num) > 11 or not mobile_num.isdigit():
        return Response(
            {'detail': 'Phone number must be at most 11 digits.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        result = provision_virtual_account(org, bvn=bvn, mobile_num=mobile_num)
    except ValueError as e:
        return Response(
            {'detail': str(e)},
            status=status.HTTP_400_BAD_REQUEST,
        )

    return Response(result, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def virtual_account_detail_view(request):
    """
    Get the virtual account details for the user's organization.
    Returns the bank account number and details for top-up transfers.
    """
    org, error = _get_user_organization(request.user)
    if error:
        return error

    info = get_virtual_account_info(org)
    if not info:
        return Response(
            {'detail': 'No virtual account provisioned for this organization.'},
            status=status.HTTP_404_NOT_FOUND,
        )

    return Response(info)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def wallet_detail_view(request):
    """
    Get the organization's wallet balance and recent top-up history.

    Returns:
        wallet: {id, balance_bits}
        topups: [{amount_naira, bits_credited, rate, status, created_at}, ...]
        virtual_account: {account_number, bank_name} or null
    """
    org, error = _get_user_organization(request.user)
    if error:
        return error

    wallet = get_wallet_for_organization(org)

    topups = TopUp.objects.filter(
        organization=org,
    ).order_by('-created_at')[:25]

    topup_list = [
        {
            'id': str(t.id),
            'amount_naira': t.amount_naira,
            'bits_credited': t.bits_credited,
            'rate_naira_per_bit': t.rate_naira_per_bit,
            'status': t.status,
            'squad_transaction_reference': t.squad_transaction_reference,
            'credited_at': t.credited_at.isoformat() if t.credited_at else None,
            'created_at': t.created_at.isoformat(),
        }
        for t in topups
    ]

    va_info = get_virtual_account_info(org)

    return Response({
        'wallet': {
            'id': str(wallet.id),
            'balance_bits': wallet.balance_bits,
        },
        'topups': topup_list,
        'virtual_account': va_info,
    })
