import unittest
from scripts.manage_n8n import configure_http_retry


class RetryConfigurationTests(unittest.TestCase):
    def test_moves_legacy_retry_without_losing_http_options(self):
        node = {"parameters": {"options": {
            "timeout": 30000, "retryOnFail": True,
            "maxTries": 3, "waitBetweenTries": 2000,
        }}}
        configure_http_retry(node)
        self.assertEqual(node["parameters"]["options"], {"timeout": 30000})
        self.assertTrue(node["retryOnFail"])
        self.assertEqual(node["maxTries"], 3)
        self.assertEqual(node["waitBetweenTries"], 2000)

    def test_configuration_is_idempotent_without_options(self):
        node = {"parameters": {"url": "https://example.invalid"}}
        configure_http_retry(node)
        expected = dict(node)
        configure_http_retry(node)
        self.assertEqual(node, expected)
        self.assertEqual(node["parameters"], {"url": "https://example.invalid"})
