"""Webhook → process_connector_event with submit + ML dispatch stubbed."""

from unittest.mock import patch

from django.test import Client, TestCase, override_settings

from apps.accounts.models import User
from apps.bits.models import TokenLedgerEntry
from apps.bits.services import credit_wallet, get_wallet_for_user
from apps.connectors.adapters import echo  # noqa: F401 — register side effect
from apps.connectors.adapters.echo.adapter import ECHO_EXTERNAL_ID
from apps.connectors.models import ConnectorEvent, ConnectorInstall, ConnectorType
from apps.connectors.tasks import process_connector_event
from apps.verifications.models import Verification


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=True,
    CELERY_TASK_EAGER_PROPAGATES=True,
)
@patch('apps.verifications.tasks.process_verification.delay')
@patch('apps.connectors.tasks.submit_b2c_verification')
class EchoWebhookFlowTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=False)
        self.user = User.objects.create_user(
            email='echo-flow@test.dev',
            password='secret',
        )
        wallet = get_wallet_for_user(self.user)
        credit_wallet(
            wallet.id,
            50,
            TokenLedgerEntry.EntryType.ADJUSTMENT,
            note='test funding',
        )
        self.ct = ConnectorType.objects.get(slug='echo')
        self.install = ConnectorInstall.objects.create(
            type=self.ct,
            user=self.user,
            organization=None,
            external_account_id=ECHO_EXTERNAL_ID,
            external_account_label='Echo',
            is_active=True,
        )

    def test_webhook_duplicate_is_idempotent(self, mock_submit, _mock_process_delay):
        v = Verification.objects.create(
            user=self.user,
            modality=Verification.Modality.TEXT,
            text_input='stub',
            status=Verification.Status.QUEUED,
        )
        mock_submit.return_value = v

        body = b'{"id": "evt-dup-1", "text": "hello"}'
        url = '/api/connectors/webhook/echo/'
        r1 = self.client.post(
            url,
            data=body,
            content_type='application/json',
        )
        self.assertEqual(r1.status_code, 200)
        r2 = self.client.post(
            url,
            data=body,
            content_type='application/json',
        )
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(ConnectorEvent.objects.count(), 1)

    def test_process_links_verification_and_completes_event(
        self,
        mock_submit,
        _mock_process_delay,
    ):
        v = Verification.objects.create(
            user=self.user,
            modality=Verification.Modality.TEXT,
            text_input='placeholder',
            status=Verification.Status.QUEUED,
        )
        mock_submit.return_value = v

        ev = ConnectorEvent.objects.create(
            install=self.install,
            external_event_id='evt-flow-1',
            event_type='text_submitted',
            raw_payload={'text': 'verify me'},
            status=ConnectorEvent.Status.RECEIVED,
        )

        process_connector_event.apply(args=[str(ev.id)])

        v.refresh_from_db()
        self.assertEqual(v.source, 'connector')
        self.assertEqual(v.source_install_id, self.install.id)
        self.assertEqual(v.source_event_id, ev.id)

        ev.refresh_from_db()
        self.assertEqual(ev.status, ConnectorEvent.Status.PROCESSED)
        self.assertTrue(ev.verifications.filter(pk=v.id).exists())
        mock_submit.assert_called_once()
