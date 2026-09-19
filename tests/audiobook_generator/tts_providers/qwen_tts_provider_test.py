import unittest
from unittest.mock import patch

import requests

from audiobook_generator.config.general_config import GeneralConfig
from audiobook_generator.tts_providers.qwen_tts_provider import (
    DEFAULT_QWEN_MAX_CHARS,
    QwenTTSProvider,
    _should_use_pydub_merge,
)


def get_qwen_config(**overrides):
    """构造一份 Qwen 配置（WebUI 的 GeneralConfig(None) + 逐字段赋值写法）"""
    config = GeneralConfig(None)
    config.input_file = "examples/The_Life_and_Adventures_of_Robinson_Crusoe.epub"
    config.output_folder = "output"
    config.preview = False
    config.output_text = False
    config.log = "INFO"
    config.worker_count = 1
    config.chapter_start = 1
    config.chapter_end = -1
    config.language = "Auto"
    config.tts = "qwen"
    config.voice_name = "Vivian"
    config.model_name = None
    config.output_format = None
    config.use_pydub_merge = None
    config.no_prompt = True
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


class FakeResponse:
    def __init__(self, status_code=200, content=b"mp3data", text=""):
        self.status_code = status_code
        self.content = content
        self.text = text

    def iter_content(self, chunk_size=8192):
        yield self.content


class TestQwenTTSProvider(unittest.TestCase):
    def _make_provider(self, **overrides):
        with patch("audiobook_generator.utils.qwen_config.get_qwen_credentials") as creds:
            creds.return_value = ("test-key", "https://gpu.ncut.edu.cn/v1", "qwen3-tts-12hz-1.7b-voicedesign")
            return QwenTTSProvider(get_qwen_config(**overrides))

    def test_long_text_is_chunked_into_multiple_requests(self):
        provider = self._make_provider()
        text = "你好。" * 2000  # 8000 字符，按 1500 拆成多个分片

        with (
            patch.object(provider, "_request_audio", return_value=b"mp3data") as mock_req,
            patch("audiobook_generator.tts_providers.qwen_tts_provider.merge_audio_segments") as merge,
            patch("audiobook_generator.tts_providers.qwen_tts_provider.set_audio_tags"),
        ):
            provider.text_to_speech(text, "out.mp3", audio_tags=None)

            self.assertGreater(mock_req.call_count, 1)
            # 每个分片都不能超过单次请求上限
            for call in mock_req.call_args_list:
                self.assertLessEqual(len(call.args[0]), DEFAULT_QWEN_MAX_CHARS)
            # 多分片必须走 pydub 合并
            self.assertTrue(merge.call_args.args[4])

    def test_short_text_single_request_direct_write(self):
        provider = self._make_provider()
        text = "你好，这是测试。"

        with (
            patch.object(provider, "_request_audio", return_value=b"mp3data") as mock_req,
            patch("audiobook_generator.tts_providers.qwen_tts_provider.merge_audio_segments") as merge,
            patch("audiobook_generator.tts_providers.qwen_tts_provider.set_audio_tags"),
        ):
            provider.text_to_speech(text, "out.mp3", audio_tags=None)

            self.assertEqual(mock_req.call_count, 1)
            self.assertFalse(merge.call_args.args[4])

    def test_read_timeout_retries_then_succeeds(self):
        provider = self._make_provider()
        responses = [requests.exceptions.ReadTimeout("Read timed out."), FakeResponse()]

        with patch("audiobook_generator.tts_providers.qwen_tts_provider.requests.post", side_effect=responses) as post:
            audio = provider._request_audio("你好")

        self.assertEqual(audio, b"mp3data")
        self.assertEqual(post.call_count, 2)

    def test_http_401_does_not_retry(self):
        provider = self._make_provider()

        with patch(
            "audiobook_generator.tts_providers.qwen_tts_provider.requests.post",
            return_value=FakeResponse(status_code=401, text="Unauthorized"),
        ) as post:
            with self.assertRaises(RuntimeError):
                provider._request_audio("你好")

        self.assertEqual(post.call_count, 1)

    def test_pydub_merge_selection(self):
        # 单分片直接写，多分片用 pydub（mp3 直接拼接会丢帧）
        self.assertFalse(_should_use_pydub_merge(1, None))
        self.assertTrue(_should_use_pydub_merge(2, None))
        self.assertTrue(_should_use_pydub_merge(1, True))


if __name__ == "__main__":
    unittest.main()
