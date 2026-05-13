"""
Bits admin — Token wallets, ledger, virtual accounts, top-ups.
"""

from django.contrib import admin
from .models import TokenWallet, TokenLedgerEntry, VirtualAccount, TopUp


@admin.register(TokenWallet)
class TokenWalletAdmin(admin.ModelAdmin):
    list_display = ('id', 'owner_type', 'owner_display', 'balance_bits', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('owner_user__email', 'owner_organization__name')
    readonly_fields = ('id', 'balance_bits', 'created_at', 'updated_at')

    def owner_type(self, obj):
        return obj.owner_type

    def owner_display(self, obj):
        return str(obj.owner)
    owner_display.short_description = 'Owner'


@admin.register(TokenLedgerEntry)
class TokenLedgerEntryAdmin(admin.ModelAdmin):
    list_display = ('id', 'wallet', 'entry_type', 'delta_bits', 'balance_after_bits', 'created_at')
    list_filter = ('entry_type', 'created_at')
    search_fields = ('wallet__owner_user__email', 'wallet__owner_organization__name', 'reference_id')
    readonly_fields = (
        'id', 'wallet', 'delta_bits', 'balance_after_bits',
        'entry_type', 'reference_type', 'reference_id',
        'note', 'created_at', 'created_by',
    )
    ordering = ('-created_at',)

    def has_add_permission(self, request):
        return False  # Ledger entries are created only via services

    def has_change_permission(self, request, obj=None):
        return False  # Append-only

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(VirtualAccount)
class VirtualAccountAdmin(admin.ModelAdmin):
    list_display = ('account_name', 'account_number', 'bank_name', 'organization', 'created_at')
    search_fields = ('account_name', 'account_number', 'organization__name')
    readonly_fields = ('id', 'created_at', 'updated_at')


@admin.register(TopUp)
class TopUpAdmin(admin.ModelAdmin):
    list_display = ('id', 'organization', 'amount_naira', 'bits_credited', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('organization__name', 'squad_transaction_reference')
    readonly_fields = ('id', 'created_at', 'updated_at', 'credited_at')
    ordering = ('-created_at',)
