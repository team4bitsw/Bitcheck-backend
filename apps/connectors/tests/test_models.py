from django.db import IntegrityError
from django.test import TestCase

from apps.accounts.models import Organization, User
from apps.connectors.models import ConnectorInstall, ConnectorType


class ConnectorModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='conn@test.dev',
            password='x',
        )
        self.org = Organization.objects.create(
            name='Conn Org',
            slug='conn-org',
            created_by=self.user,
        )
        self.ct = ConnectorType.objects.create(
            slug='model-test-ct',
            name='Model test',
            auth_type='api_key',
            supports_b2c=True,
            supports_b2b=True,
        )

    def test_xor_owner_rejects_both_user_and_org(self):
        with self.assertRaises(IntegrityError):
            ConnectorInstall.objects.create(
                type=self.ct,
                user=self.user,
                organization=self.org,
                external_account_id='acc1',
            )

    def test_xor_owner_rejects_neither_user_nor_org(self):
        with self.assertRaises(IntegrityError):
            ConnectorInstall.objects.create(
                type=self.ct,
                user=None,
                organization=None,
                external_account_id='acc2',
            )

    def test_unique_external_per_type(self):
        ConnectorInstall.objects.create(
            type=self.ct,
            user=self.user,
            organization=None,
            external_account_id='same-ext',
        )
        with self.assertRaises(IntegrityError):
            ConnectorInstall.objects.create(
                type=self.ct,
                user=self.user,
                organization=None,
                external_account_id='same-ext',
            )
