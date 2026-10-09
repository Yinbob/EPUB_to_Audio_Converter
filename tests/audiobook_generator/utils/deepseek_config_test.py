import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from audiobook_generator.utils import deepseek_config


class DeepSeekConfigTest(unittest.TestCase):
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
