import unittest

from audiobook_generator.tts_providers.base_tts_provider import get_supported_tts_providers


class TestRemovedAzureProvider(unittest.TestCase):
    def test_azure_is_not_registered(self):
        self.assertNotIn('azure', get_supported_tts_providers())


if __name__ == '__main__':
    unittest.main()
