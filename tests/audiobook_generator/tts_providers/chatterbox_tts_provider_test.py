import unittest
from unittest.mock import patch

from audiobook_generator.tts_providers.chatterbox_tts_provider import (
    FFMPEG_PATH,
    FFPROBE_PATH,
)
from audiobook_generator.config.general_config import GeneralConfig
from audiobook_generator.tts_providers.chatterbox_tts_provider import (
    CHATTERBOX_SPEED_SCALE,
    DEFAULT_CHATTERBOX_OUTPUT_FORMAT,
    DEFAULT_CHATTERBOX_SPEED,
    MAX_CHATTERBOX_SPEED,
    MIN_CHATTERBOX_SPEED,
    ChatterboxTTSProvider,
    _ffmpeg_available,
    display_speed_to_internal_speed,
    get_chatterbox_speed_range,
    normalize_display_speed,
    should_use_pydub_merge,
)


def get_chatterbox_config(**overrides):
    """构造一份 Chatterbox 配置（WebUI 的 GeneralConfig(None) + 逐字段赋值写法）"""
    config = GeneralConfig(None)
    config.input_file = "examples/The_Life_and_Adventures_of_Robinson_Crusoe.epub"
    config.output_folder = "output"
    config.preview = False
    config.output_text = False
    config.log = "INFO"
    config.worker_count = 1
    config.chapter_start = 1
    config.chapter_end = -1
    config.language = "zh-CN"
    config.tts = "chatterbox"
    config.model_name = None
    config.output_format = None
    config.chatterbox_device = "cpu"
    config.chatterbox_reference_audio = None
    config.chatterbox_exaggeration = None
    config.chatterbox_cfg_weight = None
    config.chatterbox_speed = None
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


class TestSpeedMapping(unittest.TestCase):
    """语速换算：对外显示 1.0 == 旧版的 0.7 实际倍率"""

    def test_display_1_equals_legacy_0_7(self):
        self.assertAlmostEqual(display_speed_to_internal_speed(DEFAULT_CHATTERBOX_SPEED), 0.7)
        self.assertAlmostEqual(CHATTERBOX_SPEED_SCALE, 0.7)

    def test_range_endpoints_map_to_expected_multiplier(self):
        low, high = get_chatterbox_speed_range()
        self.assertAlmostEqual(low, 0.2)
        self.assertAlmostEqual(high, 2.0)
        self.assertAlmostEqual(display_speed_to_internal_speed(low), 0.14)
        self.assertAlmostEqual(display_speed_to_internal_speed(high), 1.4)

    def test_normalize_clamps_and_falls_back(self):
        self.assertEqual(normalize_display_speed(None), DEFAULT_CHATTERBOX_SPEED)
        self.assertEqual(normalize_display_speed(5), MAX_CHATTERBOX_SPEED)
        self.assertEqual(normalize_display_speed(0.01), MIN_CHATTERBOX_SPEED)
        self.assertEqual(normalize_display_speed("0.9"), 0.9)
        self.assertEqual(normalize_display_speed("不是数字"), DEFAULT_CHATTERBOX_SPEED)


class TestProviderDefaults(unittest.TestCase):
    def test_default_output_format_is_mp3_and_speed_is_1(self):
        provider = ChatterboxTTSProvider(get_chatterbox_config())
        self.assertEqual(provider.config.output_format, DEFAULT_CHATTERBOX_OUTPUT_FORMAT)
        self.assertEqual(provider.config.output_format, "mp3")
        self.assertEqual(provider.display_speed, 1.0)
        self.assertAlmostEqual(provider.speed, 0.7)

    def test_explicit_output_format_is_preserved(self):
        provider = ChatterboxTTSProvider(get_chatterbox_config(output_format="wav"))
        self.assertEqual(provider.config.output_format, "wav")

    def test_display_speed_is_clamped_and_converted(self):
        provider = ChatterboxTTSProvider(get_chatterbox_config(chatterbox_speed=10))
        self.assertEqual(provider.display_speed, MAX_CHATTERBOX_SPEED)
        self.assertAlmostEqual(provider.speed, 1.4)

        provider = ChatterboxTTSProvider(get_chatterbox_config(chatterbox_speed=0.5))
        self.assertEqual(provider.display_speed, 0.5)
        self.assertAlmostEqual(provider.speed, 0.35)

    def test_non_wav_format_requires_ffmpeg(self):
        with patch(
            "audiobook_generator.tts_providers.chatterbox_tts_provider._ffmpeg_available",
            return_value=False,
        ):
            with self.assertRaises(ValueError) as ctx:
                ChatterboxTTSProvider(get_chatterbox_config())
            self.assertIn("ffmpeg", str(ctx.exception))

            # wav 格式不依赖 ffmpeg，仍可正常初始化
            provider = ChatterboxTTSProvider(get_chatterbox_config(output_format="wav"))
            self.assertEqual(provider.config.output_format, "wav")


class TestSpeedAdjustment(unittest.TestCase):
    """用真实 ffmpeg 验证语速确实生效（无 ffmpeg 时跳过）"""

    @unittest.skipUnless(_ffmpeg_available(), "需要 ffmpeg 才能验证语速调整")
    def test_internal_speed_lengthens_audio(self):
        import numpy as np

        sample_rate = 24000
        seconds = 1.0
        t = np.linspace(0, seconds, int(sample_rate * seconds), endpoint=False)
        wav = (0.2 * np.sin(2 * np.pi * 440 * t)).astype("float32")

        provider = ChatterboxTTSProvider(get_chatterbox_config(output_format="wav"))

        # 默认显示语速 1.0 → 实际 0.7，音频应放慢到约 1/0.7 倍长度
        adjusted = provider._adjust_speed_with_ffmpeg(wav, sample_rate, provider.speed)
        self.assertAlmostEqual(len(adjusted) / len(wav), 1 / 0.7, delta=0.2)

        # 最低档（显示 0.2 → 实际 0.14）触发 atempo 链式叠加，同样应生效
        slowest = display_speed_to_internal_speed(MIN_CHATTERBOX_SPEED)
        adjusted_slow = provider._adjust_speed_with_ffmpeg(wav, sample_rate, slowest)
        self.assertAlmostEqual(len(adjusted_slow) / len(wav), 1 / slowest, delta=1.0)


class TestDefaultMp3Pipeline(unittest.TestCase):
    """默认输出 mp3：wav → mp3 → pydub 合并，产物应能被 ffmpeg 干净解码（无 ffmpeg 时跳过）"""

    @unittest.skipUnless(_ffmpeg_available(), "需要 ffmpeg 才能验证 mp3 导出/合并")
    def test_wav_to_mp3_export_and_pydub_merge(self):
        import io
        import os
        import subprocess
        import tempfile

        import numpy as np
        import soundfile as sf
        from pydub import AudioSegment

        from audiobook_generator.utils.utils import merge_audio_segments

        sample_rate = 24000
        seconds = 0.5
        t = np.linspace(0, seconds, int(sample_rate * seconds), endpoint=False)
        wav = (0.2 * np.sin(2 * np.pi * 440 * t)).astype("float32")

        wav_buffer = io.BytesIO()
        sf.write(wav_buffer, wav, samplerate=sample_rate, format="WAV")
        wav_buffer.seek(0)

        # provider 里对非 wav 格式的处理：pydub 导出
        mp3_buffer = io.BytesIO()
        AudioSegment.from_wav(wav_buffer).export(mp3_buffer, format="mp3")
        mp3_chunk = mp3_buffer.getvalue()
        self.assertGreater(len(mp3_chunk), 1000, "mp3 导出为空")

        # 默认路径：多分片自动走 pydub 合并（见 should_use_pydub_merge）
        self.assertTrue(should_use_pydub_merge(2, "mp3"))
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_file = os.path.join(tmp_dir, "merged.mp3")
            merge_audio_segments(
                [io.BytesIO(mp3_chunk), io.BytesIO(mp3_chunk)],
                output_file,
                "mp3",
                ["chunk_1", "chunk_2"],
                True,
            )
            self.assertTrue(os.path.exists(output_file))

            # ffprobe 校验时长 ≈ 2 × 0.5s（pydub 合并成单条音轨，不含分片边界补偿）
            probe = subprocess.run(
                [FFPROBE_PATH, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", output_file],
                capture_output=True, text=True,
            )
            self.assertEqual(probe.returncode, 0, probe.stderr)
            self.assertAlmostEqual(float(probe.stdout.strip()), 1.0, delta=0.05)

            # ffmpeg 解码整文件，不应有任何错误输出
            decode = subprocess.run(
                [FFMPEG_PATH, "-v", "error", "-i", output_file, "-f", "null", "-"],
                capture_output=True, text=True,
            )
            self.assertEqual(decode.returncode, 0, decode.stderr)
            self.assertEqual(decode.stderr.strip(), "", f"mp3 解码有错误：{decode.stderr}")

    def test_merge_strategy_rules(self):
        # 单分片 wav：直接写最快，安全
        self.assertFalse(should_use_pydub_merge(1, "wav"))
        # 多分片 wav：直接拼接后播放器只认第一块，必须 pydub
        self.assertTrue(should_use_pydub_merge(2, "wav"))
        # 压缩格式：直接拼接会在边界丢帧
        self.assertTrue(should_use_pydub_merge(1, "mp3"))
        self.assertTrue(should_use_pydub_merge(1, "flac"))
        # 用户显式要求 pydub 合并
        self.assertTrue(should_use_pydub_merge(1, "wav", requested=True))


if __name__ == "__main__":
    unittest.main()
