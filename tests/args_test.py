import unittest
from unittest.mock import patch
from main import handle_args


class TestHandleArgs(unittest.TestCase):
    @patch('sys.argv',['program','input_file.epub','output_folder','--tts','openai','--audio_core_tail_repeat_mode','auto'])
    def test_tail_repeat_mode(self):
        self.assertEqual(handle_args().audio_core_tail_repeat_mode,'auto')

    @patch('sys.argv', ['program', 'input_file.epub', 'output_folder', '--tts', 'openai', '--audio_core_transition_boundaries', 'a|b', '--audio_core_transition_source_group', 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'])
    def test_audio_core_reviewed_transition_boundaries(self):
        config = handle_args()
        self.assertEqual(config.audio_core_transition_boundaries, ['a|b'])
        self.assertEqual(config.audio_core_transition_source_group, 'a' * 64)

    @patch('sys.argv', ['program', 'input_file.epub', 'output_folder', '--tts', 'openai', '--audio_core_max_repair_characters', '0'])
    def test_audio_core_repair_character_limit(self):
        self.assertEqual(handle_args().audio_core_max_repair_characters, 0)

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
