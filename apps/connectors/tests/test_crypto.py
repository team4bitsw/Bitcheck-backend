from django.test import SimpleTestCase, override_settings

from apps.connectors.crypto import decrypt_dict, encrypt_dict


@override_settings(
    CONNECTOR_CREDENTIALS_KEY='YLuDPrZbz0GWCzAYnnTZaf6Vu0TG3uRbmtdQhTnSzMk=',
)
class CryptoTests(SimpleTestCase):
    def test_encrypt_decrypt_roundtrip(self):
        data = {'token': 'abc', 'nested': {'x': 1}}
        blob = encrypt_dict(data)
        self.assertIsInstance(blob, bytes)
        out = decrypt_dict(blob)
        self.assertEqual(out, data)

    def test_decrypt_empty_bytes(self):
        self.assertEqual(decrypt_dict(b''), {})
        self.assertEqual(decrypt_dict(None), {})
