"""VoxCPM TTS 提供商单元测试（mock 模型，不依赖真实权重/GPU）。"""

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from audiobook_generator.config.general_config import GeneralConfig
from audiobook_generator.tts_providers.base_tts_provider import TTS_VOXCPM
from audiobook_generator.tts_providers.voxcpm_tts_provider import (
    DEFAULT_VOXCPM_CFG_VALUE,
    DEFAULT_VOXCPM_CHUNK_CHARS,
    DEFAULT_VOXCPM_INFERENCE_TIMESTEPS,
    DEFAULT_VOXCPM_MODE,
    DEFAULT_VOXCPM_MODEL,
    DEFAULT_VOXCPM_OUTPUT_FORMAT,
    DEFAULT_VOXCPM_SPEED,
    MAX_VOXCPM_SPEED,
    MIN_VOXCPM_SPEED,
    VOXCPM_MODE_CLONE,
    VOXCPM_MODE_DESIGN,
    VOXCPM_MODE_HIFI,
    VoxCPMTTSProvider,
    get_voxcpm_speed_range,
    normalize_voxcpm_speed,
)
from audiobook_generator.core.audio_tags import AudioTags


def get_voxcpm_config(**overrides):
    """构造一份 VoxCPM 配置（按 WebUI 的 GeneralConfig(None) + 逐字段赋值写法）。"""
    config = GeneralConfig(None)
    config.input_file = "examples/sample.epub"
    config.output_folder = "output"
    config.preview = False
    config.output_text = False
    config.log = "INFO"
    config.worker_count = 1
    config.chapter_start = 1
    config.chapter_end = -1
    config.language = "zh-CN"
    config.tts = TTS_VOXCPM
    config.model_name = None
    config.output_format = None
    config.voxcpm_device = None
    config.voxcpm_mode = None
    config.voxcpm_voice = None
    config.voxcpm_voice_description = None
    config.voxcpm_voice_dir = None
    config.voxcpm_regenerate_voice = None
    config.voxcpm_reference_audio = None
    config.voxcpm_reference_text = None
    config.voxcpm_auto_transcribe = None
    config.voxcpm_denoise = None
    config.voxcpm_normalize = None
    config.voxcpm_cfg_value = None
    config.voxcpm_inference_timesteps = None
    config.voxcpm_speed = None
    config.voxcpm_chunk_chars = None
    config.voxcpm_optimize = None
    config.voxcpm_seed = None
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


class _FakeVoxCPMModel:
    """模拟 VoxCPM 模型：返回 4 秒 48kHz 静音并记录调用参数。"""

    def __init__(self):
        self.tts_model = MagicMock()
        self.tts_model.sample_rate = 48000
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return np.zeros(48000 * 4, dtype="float32")


class TestProviderDefaults(unittest.TestCase):
    def test_defaults_are_sane(self):
        provider = VoxCPMTTSProvider(get_voxcpm_config())
        self.assertEqual(provider.model_name, DEFAULT_VOXCPM_MODEL)
        self.assertEqual(provider.config.output_format, DEFAULT_VOXCPM_OUTPUT_FORMAT)
        self.assertEqual(provider.mode, DEFAULT_VOXCPM_MODE)
        self.assertEqual(provider.cfg_value, DEFAULT_VOXCPM_CFG_VALUE)
        self.assertEqual(provider.inference_timesteps, DEFAULT_VOXCPM_INFERENCE_TIMESTEPS)
        self.assertEqual(provider.chunk_chars, DEFAULT_VOXCPM_CHUNK_CHARS)
        self.assertEqual(provider.speed, DEFAULT_VOXCPM_SPEED)
        self.assertTrue(provider.normalize)
        self.assertTrue(provider.optimize)
        self.assertEqual(provider.voice_ctx["kind"], "preset")
        self.assertEqual(provider.voice_ctx["key"], "沉稳男声")

    def test_explicit_values_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            ref = os.path.join(tmp, "ref.wav")
            with open(ref, "wb") as f:
                f.write(b"RIFF-dummy")
            provider = VoxCPMTTSProvider(
                get_voxcpm_config(
                    output_format="wav",
                    voxcpm_mode=VOXCPM_MODE_CLONE,
                    voxcpm_reference_audio=ref,
                    voxcpm_cfg_value=3.5,
                    voxcpm_inference_timesteps=20,
                    voxcpm_chunk_chars=600,
                    voxcpm_speed=1.5,
                    voxcpm_optimize=False,
                    voxcpm_normalize=False,
                )
            )
            self.assertEqual(provider.config.output_format, "wav")
            self.assertEqual(provider.mode, VOXCPM_MODE_CLONE)
            self.assertEqual(provider.cfg_value, 3.5)
            self.assertEqual(provider.inference_timesteps, 20)
            self.assertEqual(provider.chunk_chars, 600)
            self.assertEqual(provider.speed, 1.5)
            self.assertFalse(provider.optimize)
            self.assertFalse(provider.normalize)

    def test_speed_normalize(self):
        self.assertEqual(normalize_voxcpm_speed(None), DEFAULT_VOXCPM_SPEED)
        self.assertEqual(normalize_voxcpm_speed(10), MAX_VOXCPM_SPEED)
        self.assertEqual(normalize_voxcpm_speed(0.1), MIN_VOXCPM_SPEED)
        self.assertEqual(normalize_voxcpm_speed("不是数字"), DEFAULT_VOXCPM_SPEED)
        low, high = get_voxcpm_speed_range()
        self.assertEqual((low, high), (0.5, 2.0))


class TestValidateConfig(unittest.TestCase):
    def test_invalid_output_format(self):
        with self.assertRaises(ValueError):
            VoxCPMTTSProvider(get_voxcpm_config(output_format="ogg"))

    def test_invalid_mode(self):
        with self.assertRaises(ValueError):
            VoxCPMTTSProvider(get_voxcpm_config(voxcpm_mode="unknown"))

    def test_invalid_device(self):
        with self.assertRaises(ValueError):
            VoxCPMTTSProvider(get_voxcpm_config(voxcpm_device="gpu:0"))

    def test_cuda_index_device_accepted(self):
        provider = VoxCPMTTSProvider(get_voxcpm_config(voxcpm_device="cuda:1"))
        self.assertEqual(provider.device_raw, "cuda:1")

    def test_clone_mode_falls_back_to_default_preset(self):
        # 音色留空 → 默认预设（作为参考音频来源），clone 模式可正常初始化
        provider = VoxCPMTTSProvider(get_voxcpm_config(voxcpm_mode=VOXCPM_MODE_CLONE))
        self.assertEqual(provider.voice_ctx["kind"], "preset")

    def test_clone_mode_unknown_voice_raises(self):
        with self.assertRaises(ValueError) as ctx:
            VoxCPMTTSProvider(
                get_voxcpm_config(voxcpm_mode=VOXCPM_MODE_CLONE, voxcpm_voice="preset:不存在")
            )
        self.assertIn("无法解析音色", str(ctx.exception))

    def test_clone_mode_missing_reference_file_raises(self):
        with self.assertRaises(ValueError) as ctx:
            VoxCPMTTSProvider(
                get_voxcpm_config(
                    voxcpm_mode=VOXCPM_MODE_CLONE,
                    voxcpm_reference_audio="no_such_file.wav",
                )
            )
        self.assertIn("参考音频", str(ctx.exception))

    def test_hifi_mode_requires_transcript(self):
        with self.assertRaises(ValueError) as ctx:
            VoxCPMTTSProvider(
                get_voxcpm_config(
                    voxcpm_mode=VOXCPM_MODE_HIFI,
                    voxcpm_reference_audio="does_not_exist.wav",
                )
            )
        self.assertIn("参考音频", str(ctx.exception))

    def test_hifi_preset_provides_transcript(self):
        provider = VoxCPMTTSProvider(
            get_voxcpm_config(voxcpm_mode=VOXCPM_MODE_HIFI)
        )
        self.assertEqual(provider.mode, VOXCPM_MODE_HIFI)

    def test_hifi_user_audio_without_transcript_fails_even_with_preset_selected(self):
        with tempfile.TemporaryDirectory() as tmp:
            ref = os.path.join(tmp, "ref.wav")
            with open(ref, "wb") as f:
                f.write(b"RIFF-dummy")
            with self.assertRaises(ValueError) as ctx:
                VoxCPMTTSProvider(
                    get_voxcpm_config(
                        voxcpm_mode=VOXCPM_MODE_HIFI,
                        voxcpm_reference_audio=ref,
                    )
                )
            self.assertIn("转写", str(ctx.exception))


class TestChunkHelpers(unittest.TestCase):
    def test_merge_tail_chunk(self):
        provider = VoxCPMTTSProvider(get_voxcpm_config())
        merged = provider._merge_tail_chunk(["很长" * 50, "很短"])
        self.assertEqual(len(merged), 1)

    def test_merge_tail_keeps_large_chunks(self):
        provider = VoxCPMTTSProvider(get_voxcpm_config())
        chunks = ["很长" * 50, "文本" * 60]
        merged = provider._merge_tail_chunk(chunks)
        self.assertEqual(len(merged), 2)

    def test_duration_check_does_not_raise(self):
        provider = VoxCPMTTSProvider(get_voxcpm_config())
        wav = np.zeros(48000, dtype="float32")
        provider._check_chunk_duration("测试文本" * 20, wav, 48000)  # 只告警不报错


class TestTextToSpeechFlow(unittest.TestCase):
    def _run(self, provider, text="这是第一章的内容。" * 40):
        fake_model = _FakeVoxCPMModel()
        out = os.path.join(tempfile.mkdtemp(), "chapter_1.mp3")
        with patch(
            "audiobook_generator.tts_providers.voxcpm_tts_provider._load_voxcpm_model",
            return_value=fake_model,
        ), patch(
            "audiobook_generator.tts_providers.voxcpm_tts_provider.merge_audio_segments",
        ) as mock_merge, patch(
            "audiobook_generator.tts_providers.voxcpm_tts_provider.set_audio_tags",
        ) as mock_tags, patch(
            "audiobook_generator.tts_providers.voxcpm_tts_provider.transcribe_audio",
            return_value="自动转写文本",
        ) as mock_asr:
            provider.text_to_speech(
                text, out,
                AudioTags(title="第一章", author="作者", book_title="测试书", idx=1),
            )
        return fake_model, mock_merge, mock_tags, mock_asr

    def test_design_mode_builds_description_prompt_and_reference(self):
        provider = VoxCPMTTSProvider(get_voxcpm_config())
        with patch(
            "audiobook_generator.tts_providers.voxcpm_tts_provider.ensure_preset_audio",
            return_value="/tmp/preset_沉稳男声.wav",
        ):
            fake, merge, tags, _ = self._run(provider)
        self.assertTrue(fake.calls)
        first = fake.calls[0]
        self.assertTrue(first["text"].startswith("(成熟沉稳的男声"))
        self.assertEqual(first["reference_wav_path"], "/tmp/preset_沉稳男声.wav")
        self.assertNotIn("prompt_wav_path", first)
        self.assertEqual(fake.calls[0]["cfg_value"], DEFAULT_VOXCPM_CFG_VALUE)
        self.assertEqual(fake.calls[0]["inference_timesteps"], DEFAULT_VOXCPM_INFERENCE_TIMESTEPS)
        merge.assert_called_once()
        tags.assert_called_once()

    def test_design_mode_custom_description_overrides_preset(self):
        provider = VoxCPMTTSProvider(
            get_voxcpm_config(voxcpm_voice_description="清脆的少年音")
        )
        with patch(
            "audiobook_generator.tts_providers.voxcpm_tts_provider.ensure_preset_audio",
            return_value="/tmp/preset_沉稳男声.wav",
        ):
            fake, _, _, _ = self._run(provider)
        self.assertTrue(fake.calls[0]["text"].startswith("(清脆的少年音)"))
        self.assertEqual(fake.calls[0]["reference_wav_path"], "/tmp/preset_沉稳男声.wav")

    def test_design_mode_fixed_seed(self):
        provider = VoxCPMTTSProvider(get_voxcpm_config())
        with patch(
            "audiobook_generator.tts_providers.voxcpm_tts_provider.ensure_preset_audio",
            return_value="/tmp/preset_沉稳男声.wav",
        ):
            fake, _, _, _ = self._run(provider)
        seeds = {call["seed"] for call in fake.calls}
        self.assertEqual(seeds, {101})  # 预设固定 seed

    def test_clone_mode_uses_user_reference_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            ref = os.path.join(tmp, "user.wav")
            with open(ref, "wb") as f:
                f.write(b"RIFF-dummy")
            provider = VoxCPMTTSProvider(
                get_voxcpm_config(
                    voxcpm_mode=VOXCPM_MODE_CLONE,
                    voxcpm_reference_audio=ref,
                    voxcpm_voice_description="语速稍快",
                )
            )
            fake, _, _, _ = self._run(provider)
        first = fake.calls[0]
        self.assertEqual(first["reference_wav_path"], ref)
        self.assertTrue(first["text"].startswith("(语速稍快)"))
        self.assertIsNone(first["seed"])

    def test_hifi_mode_uses_prompt_text_and_ignores_description(self):
        with tempfile.TemporaryDirectory() as tmp:
            ref = os.path.join(tmp, "user.wav")
            with open(ref, "wb") as f:
                f.write(b"RIFF-dummy")
            provider = VoxCPMTTSProvider(
                get_voxcpm_config(
                    voxcpm_mode=VOXCPM_MODE_HIFI,
                    voxcpm_reference_audio=ref,
                    voxcpm_reference_text="这是参考音频的转写",
                    voxcpm_voice_description="应该被忽略的描述",
                )
            )
            fake, _, _, _ = self._run(provider)
        first = fake.calls[0]
        self.assertEqual(first["reference_wav_path"], ref)
        self.assertEqual(first["prompt_wav_path"], ref)
        self.assertEqual(first["prompt_text"], "这是参考音频的转写")
        self.assertFalse(first["text"].startswith("(应该被忽略"))
        self.assertEqual(first["seed"], None)

    def test_hifi_preset_auto_transcribe_when_no_manual_text(self):
        provider = VoxCPMTTSProvider(
            get_voxcpm_config(voxcpm_mode=VOXCPM_MODE_HIFI, voxcpm_auto_transcribe=True)
        )
        with patch(
            "audiobook_generator.tts_providers.voxcpm_tts_provider.ensure_preset_audio",
            return_value="/tmp/preset_温柔女声.wav",
        ):
            fake, _, _, mock_asr = self._run(provider)
        first = fake.calls[0]
        # 预设自带试听文本 → 不需要 SenseVoice
        self.assertEqual(first["prompt_text"], "你好，欢迎使用有声书工坊。愿你享受聆听的每一刻。")
        mock_asr.assert_not_called()
        self.assertEqual(first["reference_wav_path"], "/tmp/preset_温柔女声.wav")

    def test_provider_registered_in_base(self):
        from audiobook_generator.tts_providers.base_tts_provider import (
            get_supported_tts_providers,
            get_tts_provider,
        )
        self.assertIn(TTS_VOXCPM, get_supported_tts_providers())
        provider = get_tts_provider(get_voxcpm_config())
        self.assertIsInstance(provider, VoxCPMTTSProvider)


if __name__ == "__main__":
    unittest.main()
