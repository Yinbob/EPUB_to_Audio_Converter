import unittest
from unittest.mock import patch
from main import handle_args


class TestHandleArgs(unittest.TestCase):

    @patch('sys.argv', ['program', 'input_file.epub', 'output_folder', '--tts', 'openai'])
    def test_openai_args(self):
        config = handle_args()
        self.assertEqual(config.tts, 'openai')

    @patch('sys.argv', ['program', 'input_file.epub', 'output_folder', '--tts', 'minimax'])
    def test_minimax_args(self):
        config = handle_args()
        self.assertEqual(config.tts, 'minimax')

    @patch('sys.argv', ['program', 'input_file.epub', 'output_folder', '--tts', 'azure'])
    def test_removed_azure_provider_is_rejected(self):
        with self.assertRaises(SystemExit):
            handle_args()

    @patch('sys.argv', ['program', 'input_file.epub', 'output_folder', '--tts', 'unsupported_tts'])
    def test_unsupported_tts(self):
        with self.assertRaises(SystemExit):
            handle_args()

    @patch('sys.argv', ['program', 'output_folder', '--tts', 'openai'])
    def test_missing_input_file(self):
        with self.assertRaises(SystemExit):
            handle_args()

    @patch('sys.argv', ['program', 'input_file.epub', 'output_folder', '--log', 'INVALID_LOG_LEVEL'])
    def test_invalid_log_level(self):
        with self.assertRaises(SystemExit):
            handle_args()


if __name__ == '__main__':
    unittest.main()
