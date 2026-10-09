import io
import tempfile
import unittest
import wave
from unittest.mock import AsyncMock, patch

from audiobook_generator.role_script.models import VoiceProfile
from audiobook_generator.tts_providers.base_tts_provider import get_tts_provider
from audiobook_generator.tts_providers.minimax_tts_provider import MiniMaxTTSProvider
from tests.test_utils import get_minimax_config


def _wav_bytes(sample_rate=32000, channels=1, duration_ms=40):
    frame_count = max(1, sample_rate * duration_ms // 1000)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\x00\x00" * frame_count * channels)
    return buffer.getvalue()


class TestMiniMaxTtsProvider(unittest.TestCase):
    @patch(
        "audiobook_generator.tts_providers.minimax_tts_provider.get_minimax_credentials",
        return_value="fake-key",
    )
    def test_registered_provider(self, _credentials):
        config = get_minimax_config()
        config.output_format = "mp3"
        self.assertIsInstance(get_tts_provider(config), MiniMaxTTSProvider)

    @patch(
        "audiobook_generator.tts_providers.minimax_tts_provider.get_minimax_credentials",
        return_value="fake-key",
    )
    def test_segment_maps_role_params_and_ignores_tone(self, _credentials):
        config = get_minimax_config()
        config.output_format = "wav"
        provider = get_tts_provider(config)
        profile = VoiceProfile(
            role_id="hero",
            display_name="主角",
            provider_params={
                "voice_id": "female-shaonv",
                "speed": 1.25,
                "pitch": 3,
                "volume": 4.5,
            },
            tone="激动",
        )
        generate = AsyncMock(return_value=_wav_bytes())
        with tempfile.TemporaryDirectory() as work_dir:
            with patch.object(provider, "_generate_audio", generate):
                artifact = provider.synthesize_segment("你好", profile, work_dir)

        setting = generate.call_args.kwargs["voice_setting"]
        self.assertEqual(setting["voice_id"], "female-shaonv")
        self.assertEqual(setting["speed"], 1.25)
        self.assertEqual(setting["pitch"], 3)
        self.assertEqual(setting["vol"], 4.5)
        self.assertNotIn("tone", setting)
        self.assertNotIn("激动", repr(generate.call_args))
        self.assertEqual(artifact.format, "wav")

    @patch(
        "audiobook_generator.tts_providers.minimax_tts_provider.get_minimax_credentials",
        return_value="fake-key",
    )
    def test_segment_chunks_stay_inside_one_segment_and_cache(self, _credentials):
        config = get_minimax_config()
        config.output_format = "wav"
        provider = get_tts_provider(config)
        profile = VoiceProfile(
            "narrator", "旁白", {"voice_id": "male-qn-qingse", "speed": 1.0}
        )
        generate = AsyncMock(side_effect=[_wav_bytes(), _wav_bytes()])
        with tempfile.TemporaryDirectory() as work_dir:
            with patch.object(provider, "_generate_audio", generate), patch(
                "audiobook_generator.tts_providers.minimax_tts_provider.split_text",
                return_value=["第一段", "第二段"],
            ):
                provider.synthesize_segment("第一段第二段", profile, work_dir)
                self.assertEqual(generate.await_count, 2)
                provider.synthesize_segment("第一段第二段", profile, work_dir)
                self.assertEqual(generate.await_count, 2)

    @patch(
        "audiobook_generator.tts_providers.minimax_tts_provider.get_minimax_credentials",
        return_value="fake-key",
    )
    def test_segment_retries_once(self, _credentials):
        config = get_minimax_config()
        config.output_format = "wav"
        provider = get_tts_provider(config)
        profile = VoiceProfile(
            "narrator", "旁白", {"voice_id": "male-qn-qingse", "speed": 1.0}
        )
        generate = AsyncMock(side_effect=[RuntimeError("temporary"), _wav_bytes()])
        with tempfile.TemporaryDirectory() as work_dir:
            with patch.object(provider, "_generate_audio", generate):
                artifact = provider.synthesize_segment("重试", profile, work_dir)
        self.assertEqual(generate.await_count, 2)
        self.assertEqual(artifact.format, "wav")

    @patch(
        "audiobook_generator.tts_providers.minimax_tts_provider.get_minimax_credentials",
        return_value="fake-key",
    )
    def test_segment_raises_after_two_failures(self, _credentials):
        config = get_minimax_config()
        config.output_format = "wav"
        provider = get_tts_provider(config)
        profile = VoiceProfile(
            "narrator", "旁白", {"voice_id": "male-qn-qingse", "speed": 1.0}
        )
        generate = AsyncMock(side_effect=RuntimeError("down"))
        with tempfile.TemporaryDirectory() as work_dir:
            with patch.object(provider, "_generate_audio", generate):
                with self.assertRaisesRegex(RuntimeError, "合成失败"):
                    provider.synthesize_segment("失败", profile, work_dir)
        self.assertEqual(generate.await_count, 2)


if __name__ == "__main__":
    unittest.main()
