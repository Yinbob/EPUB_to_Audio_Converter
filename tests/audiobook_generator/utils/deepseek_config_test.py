import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from audiobook_generator.utils import deepseek_config


class DeepSeekConfigTest(unittest.TestCase):
    def test_current_official_models_explicitly_disable_thinking(self):
        for model in (None, '', '  ', 'deepseek-flash', 'deepseek-v4-pro'):
            with self.subTest(model=model):
                options = deepseek_config.deepseek_completion_options(model)
                self.assertEqual(options['model'], (model or '').strip() or 'deepseek-flash')
                self.assertEqual(options['extra_body'], {'thinking': {'type': 'disabled'}})
        self.assertEqual(deepseek_config.deepseek_completion_options(' custom-model '), {'model': 'custom-model'})

    def test_connection_probe_uses_current_model_without_thinking(self):
        with patch('openai.OpenAI') as client:
            ok, _ = deepseek_config.test_deepseek_connection('dummy', '', '')
        self.assertTrue(ok)
        self.assertEqual(client.call_args.kwargs['base_url'], 'https://api.deepseek.com')
        self.assertEqual(client.call_args.kwargs['timeout'], 20.0)
        params = client.return_value.chat.completions.create.call_args.kwargs
        self.assertEqual(params['model'], 'deepseek-flash')
        self.assertEqual(params['extra_body'], {'thinking': {'type': 'disabled'}})

    def test_all_script_requests_use_current_model_options(self):
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        from audiobook_generator.role_script import deepseek_splitter, narration, v2_generation
        client = MagicMock()
        create = client.chat.completions.create
        for run, content in (
            (lambda: deepseek_splitter._request_chunk(client, '', 1, 'chapter', 'text', 'openai'), '{}'),
            (lambda: narration.request_narration_context(client, '', 1, 'chapter', 'text', []), '{"perspective":"unknown","narrators":[]}'),
            (lambda: v2_generation._request_character_chunk(client, '', 1, 'text', {}), '{"characters":[]}'),
        ):
            create.return_value = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
            run()
            self.assertEqual(create.call_args.kwargs['model'], 'deepseek-flash')
            self.assertEqual(create.call_args.kwargs['extra_body'], {'thinking': {'type': 'disabled'}})

    def test_save_and_load_round_trip(self):
        with tempfile.TemporaryDirectory() as root:
            config_path = Path(root) / "deepseek_config.json"
            with patch.object(deepseek_config, "CONFIG_FILE", config_path):
                deepseek_config.save_deepseek_config(
                    "  sk-test  ", " https://example.test/v1 ", " deepseek-chat "
                )
                self.assertEqual(
                    json.loads(config_path.read_text(encoding="utf-8")),
                    {
                        "api_key": "sk-test",
                        "base_url": "https://example.test/v1",
                        "model": "deepseek-chat",
                    },
                )
                self.assertEqual(
                    deepseek_config.get_deepseek_credentials(),
                    ("sk-test", "https://example.test/v1", "deepseek-chat"),
                )

    def test_file_values_take_precedence_over_environment(self):
        with tempfile.TemporaryDirectory() as root:
            config_path = Path(root) / "deepseek_config.json"
            config_path.write_text(
                json.dumps(
                    {
                        "api_key": "file-key",
                        "base_url": "https://file.example/v1",
                        "model": "file-model",
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(deepseek_config, "CONFIG_FILE", config_path), patch.dict(
                os.environ,
                {
                    "DEEPSEEK_API_KEY": "env-key",
                    "DEEPSEEK_BASE_URL": "https://env.example/v1",
                    "DEEPSEEK_MODEL": "env-model",
                },
                clear=False,
            ):
                self.assertEqual(
                    deepseek_config.get_deepseek_credentials(),
                    ("file-key", "https://file.example/v1", "file-model"),
                )

    def test_environment_and_defaults_are_used_when_file_is_missing(self):
        with tempfile.TemporaryDirectory() as root:
            config_path = Path(root) / "missing.json"
            with patch.object(deepseek_config, "CONFIG_FILE", config_path), patch.dict(
                os.environ,
                {"DEEPSEEK_API_KEY": "env-key"},
                clear=True,
            ):
                self.assertEqual(
                    deepseek_config.get_deepseek_credentials(),
                    ("env-key", deepseek_config.DEFAULT_BASE_URL, deepseek_config.DEFAULT_MODEL),
                )

    def test_mask_api_key_keeps_only_tail(self):
        self.assertEqual(deepseek_config.mask_api_key("sk-123456"), "•••••3456")
        self.assertEqual(deepseek_config.mask_api_key("abc"), "••••••••")


if __name__ == "__main__":
    unittest.main()
