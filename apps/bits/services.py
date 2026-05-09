"""
Bit token ledger services — safe credit/debit operations.

These are the ONLY functions that should ever modify token_wallets.balance_bits.
Every call writes both the wallet balance and a ledger entry in the same
atomic transaction with a row lock (select_for_update) to prevent races.

Ref: database design doc § 6 — Money & token handling rules.

    "The rules a bug here would burn the company.
     Worth reading once and tattooing."
"""

import logging
from django.db import transaction
from .models import TokenWallet, TokenLedgerEntry

logger = logging.getLogger(__name__)


class InsufficientBits(Exception):
    """Raised when a wallet doesn't have enough bits for a debit."""

    def __init__(self, wallet_id, requested, available):
        self.wallet_id = wallet_id
        self.requested = requested
        self.available = available
        super().__init__(
            f'Insufficient bits in wallet {wallet_id}: '
            f'requested {requested}, available {available}'
        )


def credit_wallet(
    wallet_id,
    amount,
    entry_type,
    reference_type=None,
    reference_id=None,
    note=None,
    created_by=None,
):
    """
    Credit (add) bit tokens to a wallet.

    This is an atomic operation: the wallet balance and ledger entry
    are written in the same transaction with a row lock.

    Args:
        wallet_id:      UUID of the TokenWallet to credit.
        amount:         Positive integer — number of bits to add.
        entry_type:     One of TokenLedgerEntry.EntryType values.
        reference_type: Optional string identifying the source entity type
                        (e.g. 'subscription', 'top_up').
        reference_id:   Optional string/UUID identifying the source row.
        note:           Optional human-readable context.
        created_by:     Optional User instance (for manual adjustments).

    Returns:
        The created TokenLedgerEntry.

    Raises:
        ValueError: If amount is not positive.
        TokenWallet.DoesNotExist: If wallet_id is invalid.
    """
    if amount <= 0:
        raise ValueError(f'Credit amount must be positive, got {amount}')

    with transaction.atomic():
        wallet = TokenWallet.objects.select_for_update().get(pk=wallet_id)
        new_balance = wallet.balance_bits + amount

        wallet.balance_bits = new_balance
        wallet.save(update_fields=['balance_bits', 'updated_at'])

        entry = TokenLedgerEntry.objects.create(
            wallet=wallet,
            delta_bits=amount,
            balance_after_bits=new_balance,
            entry_type=entry_type,
            reference_type=reference_type,
            reference_id=str(reference_id) if reference_id else None,
            note=note,
            created_by=created_by,
        )

        logger.info(
            f'Credited {amount} bits to wallet {wallet_id} '
            f'(type={entry_type}, new_balance={new_balance})'
        )

    return entry


def debit_wallet(
    wallet_id,
    amount,
    entry_type,
    reference_type=None,
    reference_id=None,
    note=None,
    created_by=None,
):
    """
    Debit (subtract) bit tokens from a wallet.

    This is an atomic operation: the wallet balance and ledger entry
    are written in the same transaction with a row lock.

    Args:
        wallet_id:      UUID of the TokenWallet to debit.
        amount:         Positive integer — number of bits to subtract.
        entry_type:     One of TokenLedgerEntry.EntryType values.
        reference_type: Optional string identifying the source entity type.
        reference_id:   Optional string/UUID identifying the source row.
        note:           Optional human-readable context.
        created_by:     Optional User instance (for manual adjustments).

    Returns:
        The created TokenLedgerEntry.

    Raises:
        ValueError: If amount is not positive.
        InsufficientBits: If wallet doesn't have enough bits.
        TokenWallet.DoesNotExist: If wallet_id is invalid.
    """
    if amount <= 0:
        raise ValueError(f'Debit amount must be positive, got {amount}')

    with transaction.atomic():
        wallet = TokenWallet.objects.select_for_update().get(pk=wallet_id)
        new_balance = wallet.balance_bits - amount

        if new_balance < 0:
            raise InsufficientBits(
                wallet_id=wallet_id,
                requested=amount,
                available=wallet.balance_bits,
            )

        wallet.balance_bits = new_balance
        wallet.save(update_fields=['balance_bits', 'updated_at'])

        entry = TokenLedgerEntry.objects.create(
            wallet=wallet,
            delta_bits=-amount,  # negative for debits
            balance_after_bits=new_balance,
            entry_type=entry_type,
            reference_type=reference_type,
            reference_id=str(reference_id) if reference_id else None,
            note=note,
            created_by=created_by,
        )

        logger.info(
            f'Debited {amount} bits from wallet {wallet_id} '
            f'(type={entry_type}, new_balance={new_balance})'
        )

    return entry


def reset_and_grant(wallet_id, grant_amount, subscription_id):
    """
    Subscription period rollover: reset the wallet to zero, then
    credit the new period's grant. Both operations happen in a single
    atomic transaction.

    This implements the "use-it-or-lose-it" rule for B2C subscriptions:
    unused bits don't roll over.

    Ref: database design doc § 4.3 — period rollover logic.

    Args:
        wallet_id:       UUID of the user's TokenWallet.
        grant_amount:    Positive integer — bits to grant for the new period.
        subscription_id: UUID of the Subscription driving this rollover.

    Returns:
        Tuple of (reset_entry, grant_entry) — the two ledger entries created.
    """
    if grant_amount <= 0:
        raise ValueError(f'Grant amount must be positive, got {grant_amount}')

    with transaction.atomic():
        wallet = TokenWallet.objects.select_for_update().get(pk=wallet_id)
        current_balance = wallet.balance_bits

        entries = []

        # Step 1: Reset to zero (only if balance > 0)
        if current_balance > 0:
            wallet.balance_bits = 0
            wallet.save(update_fields=['balance_bits', 'updated_at'])

            reset_entry = TokenLedgerEntry.objects.create(
                wallet=wallet,
                delta_bits=-current_balance,
                balance_after_bits=0,
                entry_type=TokenLedgerEntry.EntryType.PERIOD_RESET,
                reference_type='subscription',
                reference_id=str(subscription_id),
                note=f'Period reset: forfeited {current_balance} unused bits',
            )
            entries.append(reset_entry)

            logger.info(
                f'Period reset: zeroed {current_balance} bits from wallet {wallet_id}'
            )
        else:
            entries.append(None)

        # Step 2: Credit the new grant
        new_balance = grant_amount  # always starts from 0 after reset
        wallet.balance_bits = new_balance
        wallet.save(update_fields=['balance_bits', 'updated_at'])

        grant_entry = TokenLedgerEntry.objects.create(
            wallet=wallet,
            delta_bits=grant_amount,
            balance_after_bits=new_balance,
            entry_type=TokenLedgerEntry.EntryType.SUBSCRIPTION_GRANT,
            reference_type='subscription',
            reference_id=str(subscription_id),
            note=f'Monthly grant: {grant_amount} bits',
        )
        entries.append(grant_entry)

        logger.info(
            f'Subscription grant: {grant_amount} bits to wallet {wallet_id}'
        )

    return tuple(entries)


def check_balance(wallet_id, required_bits):
    """
    Check if a wallet has enough bits for an operation.
    Does NOT lock the row — use this for pre-flight checks only.
    The actual debit_wallet() call will re-check with a lock.

    Args:
        wallet_id:     UUID of the TokenWallet.
        required_bits: Minimum balance needed.

    Returns:
        True if balance >= required_bits, False otherwise.

    Raises:
        TokenWallet.DoesNotExist: If wallet_id is invalid.
    """
    wallet = TokenWallet.objects.get(pk=wallet_id)
    return wallet.balance_bits >= required_bits


def get_wallet_for_user(user):
    """
    Get or create the TokenWallet for a B2C user.

    Per the design doc, a wallet should be created on user signup.
    This function is a safe fallback that creates one if missing.

    Returns:
        The user's TokenWallet.
    """
    wallet, created = TokenWallet.objects.get_or_create(
        owner_user=user,
        defaults={'balance_bits': 0},
    )
    if created:
        logger.info(f'Created wallet for user {user.id}')
    return wallet


def get_wallet_for_organization(organization):
    """
    Get or create the TokenWallet for a B2B organization.

    Per the design doc, a wallet should be created on org creation.
    This function is a safe fallback that creates one if missing.

    Returns:
        The organization's TokenWallet.
    """
    wallet, created = TokenWallet.objects.get_or_create(
        owner_organization=organization,
        defaults={'balance_bits': 0},
    )
    if created:
        logger.info(f'Created wallet for organization {organization.id}')
    return wallet
