"""
B2B Virtual Account provisioning and top-up services.

Calls Squad's Virtual Account API to create dedicated bank accounts
for organizations, and provides helper functions for the top-up flow.

Architectural decisions (per user requirements):
  - Uses the B2B (Business) model endpoint: POST /virtual-account/business
  - customer_identifier = organization.slug (unique, URL-safe)
  - NO beneficiary_account → funds pool into our Squad wallet (T+1 settlement)
  - bank_name is derived from Squad's response bank_code (GTBank = 058)

Ref: docs/Squad_API_Docs/VIRTUAL_ACCOUNT/api-specifications.mdx
"""

import logging
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

# Squad bank codes → human-readable names
SQUAD_BANK_CODES = {
    '058': 'GTBank',
    '737': 'GTBank (Digits)',
}


def _squad_headers():
    """Common headers for Squad API calls."""
    return {
        'Authorization': f'Bearer {settings.SQUAD_SECRET_KEY}',
        'Content-Type': 'application/json',
    }


def provision_virtual_account(organization, bvn, mobile_num):
    """
    Create a Squad B2B virtual account for an organization.

    Uses the Business model endpoint which requires:
      - customer_identifier: our org.slug (unique per org)
      - business_name: the org's name
      - bvn: BVN of the org owner/representative
      - mobile_num: phone number (max 11 digits)

    We intentionally omit beneficiary_account so funds pool into
    our main Squad wallet.

    Args:
        organization: Organization model instance
        bvn: str — Bank Verification Number of the representative
        mobile_num: str — Phone number (e.g., '08012345678')

    Returns:
        dict with 'account_number', 'bank_code', 'bank_name',
        'customer_identifier'

    Raises:
        ValueError: if Squad API rejects the request
    """
    from apps.bits.models import VirtualAccount

    # Prevent double-provisioning
    if VirtualAccount.objects.filter(organization=organization).exists():
        raise ValueError('This organization already has a virtual account.')

    payload = {
        'customer_identifier': organization.slug,
        'business_name': organization.name,
        'mobile_num': mobile_num,
        'bvn': bvn,
        # NO beneficiary_account — funds go to our Squad wallet
    }

    url = f'{settings.SQUAD_BASE_URL}/virtual-account/business'

    try:
        resp = requests.post(url, json=payload, headers=_squad_headers(), timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        logger.error(f'Squad virtual account creation failed for org {organization.slug}: {e}')
        raise ValueError(f'Payment gateway error: {e}')

    if not data.get('success', False):
        msg = data.get('message', 'Unknown error')
        logger.error(f'Squad virtual account rejected: {msg}')
        raise ValueError(f'Payment gateway rejected: {msg}')

    account_data = data.get('data', {})
    account_number = account_data.get('virtual_account_number', '')
    bank_code = account_data.get('bank_code', '')

    if not account_number:
        raise ValueError('No virtual_account_number returned from Squad.')

    bank_name = SQUAD_BANK_CODES.get(bank_code, f'Bank ({bank_code})')

    # Create our local VirtualAccount record
    va = VirtualAccount.objects.create(
        organization=organization,
        bank_name=bank_name,
        account_number=account_number,
        account_name=organization.name,
        squad_account_reference=organization.slug,  # = customer_identifier
    )

    logger.info(
        f'Virtual account provisioned: org={organization.slug}, '
        f'account={account_number}, bank={bank_name}'
    )

    return {
        'id': str(va.id),
        'account_number': account_number,
        'bank_code': bank_code,
        'bank_name': bank_name,
        'account_name': organization.name,
        'customer_identifier': organization.slug,
    }


def get_virtual_account_info(organization):
    """
    Retrieve the virtual account details for an organization.

    Returns:
        dict with account details, or None if not provisioned
    """
    from apps.bits.models import VirtualAccount

    try:
        va = VirtualAccount.objects.get(organization=organization)
    except VirtualAccount.DoesNotExist:
        return None

    return {
        'id': str(va.id),
        'account_number': va.account_number,
        'bank_name': va.bank_name,
        'account_name': va.account_name,
        'customer_identifier': va.squad_account_reference,
        'created_at': va.created_at.isoformat(),
    }
