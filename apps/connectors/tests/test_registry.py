from django.test import TestCase

from apps.connectors.exceptions import ConnectorError
from apps.connectors.registry import get, registered_slugs


class RegistryTests(TestCase):

    def test_echo_registered(self):
        from apps.connectors.adapters import echo  # noqa: F401 — registers side effect

        self.assertIn('echo', registered_slugs())
        adapter = get('echo')
        self.assertEqual(adapter.slug, 'echo')

    def test_unknown_slug_raises(self):
        from apps.connectors.adapters import echo  # noqa: F401

        with self.assertRaises(ConnectorError):
            get('not-a-real-slug')
