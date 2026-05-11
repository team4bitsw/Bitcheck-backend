from django.core.cache import cache
from django.test import TestCase, override_settings

from apps.connectors.rate_limit import allow_event, check_install_limit, check_type_limit


@override_settings(
    CONNECTORS_DEFAULT_RATE_LIMIT_PER_TYPE=2,
    CONNECTORS_DEFAULT_RATE_LIMIT_PER_INSTALL=3,
)
class RateLimitTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_allow_event_window(self):
        self.assertTrue(allow_event('unit-test-key', limit=2, window_seconds=60))
        self.assertTrue(allow_event('unit-test-key', limit=2, window_seconds=60))
        self.assertFalse(allow_event('unit-test-key', limit=2, window_seconds=60))

    def test_check_helpers_use_settings(self):
        cache.clear()
        self.assertTrue(check_type_limit('slack'))
        self.assertTrue(check_type_limit('slack'))
        self.assertFalse(check_type_limit('slack'))

        cache.clear()
        iid = '11111111-1111-1111-1111-111111111111'
        self.assertTrue(check_install_limit(iid))
        self.assertTrue(check_install_limit(iid))
        self.assertTrue(check_install_limit(iid))
        self.assertFalse(check_install_limit(iid))
