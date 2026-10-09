import unittest
from unittest.mock import patch

from audiobook_generator.tts_providers.base_tts_provider import get_tts_provider
from audiobook_generator.tts_providers.openai_tts_provider import OpenAITTSProvider
from tests.test_utils import get_openai_config


class TestBaseTtsProvider(unittest.TestCase):

    @patch('audiobook_generator.tts_providers.openai_tts_provider.get_mimo_credentials',
           return_value=('fake_key', 'https://example.invalid/v1'))
    def test_get_tts_provider_openai(self, _credentials):
        tts_provider = get_tts_provider(get_openai_config())
        self.assertIsInstance(tts_provider, OpenAITTSProvider)

    def test_get_tts_provider_invalid(self):
        config = get_openai_config()
        config.tts = 'invalid_tts_provider'
        with self.assertRaises(ValueError):
            get_tts_provider(config)


if __name__ == '__main__':
    unittest.main()
