import unittest
import io
import tempfile
import wave
from unittest.mock import patch

from audiobook_generator.tts_providers.base_tts_provider import get_tts_provider
from audiobook_generator.tts_providers.openai_tts_provider import OpenAITTSProvider
from audiobook_generator.role_script.models import VoiceProfile
from tests.test_utils import get_openai_config


def _wav_bytes(sample_rate=24000, channels=1, duration_ms=40):
    frame_count = max(1, sample_rate * duration_ms // 1000)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(b"\x00\x00" * frame_count * channels)
    return buffer.getvalue()


class TestOpenAiTtsProvider(unittest.TestCase):

    @patch('audiobook_generator.tts_providers.openai_tts_provider.get_mimo_credentials')
    def test_missing_credentials_is_reported(self, credentials):
        credentials.side_effect = RuntimeError('missing MiMo credentials')
        with self.assertRaises(RuntimeError):
            get_tts_provider(get_openai_config())

    @patch('audiobook_generator.tts_providers.openai_tts_provider.get_mimo_credentials',
           return_value=('fake_key', 'https://example.invalid/v1'))
    def test_estimate_cost(self, _credentials):
        tts_provider = get_tts_provider(get_openai_config())
        self.assertIsInstance(tts_provider, OpenAITTSProvider)
        self.assertEqual(tts_provider.estimate_cost(1000000), 0)

    @patch('audiobook_generator.tts_providers.openai_tts_provider.get_mimo_credentials',
           return_value=('fake_key', 'https://example.invalid/v1'))
    def test_mimo_defaults(self, _credentials):
        config = get_openai_config()
        config.model_name = None
        config.voice_name = None
        config.output_format = None
        tts_provider = get_tts_provider(config)
        self.assertEqual(tts_provider.config.model_name, 'mimo-v2.5-tts')
        self.assertEqual(tts_provider.config.voice_name, 'mimo_default')
        self.assertEqual(tts_provider.config.output_format, 'wav')

    @patch('audiobook_generator.tts_providers.openai_tts_provider.get_mimo_credentials',
           return_value=('fake_key', 'https://example.invalid/v1'))
    def test_custom_model_and_voice_reach_mimo_route(self, _credentials):
        config = get_openai_config()
        config.model_name = 'my-mimo-model'
        config.voice_name = 'my-account-voice'
        config.allow_custom_tts = True
        provider = get_tts_provider(config)
        route = provider.resolve_voice()
        self.assertEqual(route['model'], 'my-mimo-model')
        self.assertEqual(route['voice'], 'my-account-voice')

    @patch('audiobook_generator.tts_providers.openai_tts_provider.get_mimo_credentials',
           return_value=('fake_key', 'https://example.invalid/v1'))
    def test_segment_uses_profile_voice_instructions_and_tone(self, _credentials):
        provider = get_tts_provider(get_openai_config())
        profile = VoiceProfile(
            role_id="hero",
            display_name="主角",
            provider_params={"voice": "茉莉", "instructions": "平静", "speed": 1.2},
            tone="压低声音",
        )
        with tempfile.TemporaryDirectory() as work_dir:
            with patch.object(
                provider, "_request_mimo_chunk", return_value=_wav_bytes()
            ) as request:
                artifact = provider.synthesize_segment("你好", profile, work_dir)
        self.assertEqual(request.call_args.kwargs["voice"], "茉莉")
        self.assertIn("平静", request.call_args.kwargs["instructions"])
        self.assertIn("压低声音", request.call_args.kwargs["instructions"])
        self.assertEqual(artifact.format, "wav")

    @patch('audiobook_generator.tts_providers.openai_tts_provider.get_mimo_credentials',
           return_value=('fake_key', 'https://example.invalid/v1'))
    def test_segment_retries_and_cache_hits(self, _credentials):
        provider = get_tts_provider(get_openai_config())
        profile = VoiceProfile("narrator", "旁白", {"voice": "冰糖", "speed": 1.0})
        with tempfile.TemporaryDirectory() as work_dir:
            with patch.object(
                provider,
                "_request_mimo_chunk",
                side_effect=[RuntimeError("temporary"), _wav_bytes()],
            ) as request:
                provider.synthesize_segment("重试文本", profile, work_dir)
                self.assertEqual(request.call_count, 2)
                provider.synthesize_segment("重试文本", profile, work_dir)
                self.assertEqual(request.call_count, 2)

    @patch('audiobook_generator.tts_providers.openai_tts_provider.get_mimo_credentials',
           return_value=('fake_key', 'https://example.invalid/v1'))
    def test_segment_chunks_do_not_cross_role_boundary(self, _credentials):
        config = get_openai_config()
        config.output_format = "wav"
        provider = get_tts_provider(config)
        first = VoiceProfile("a", "甲", {"voice": "冰糖", "speed": 1.0})
        second = VoiceProfile("b", "乙", {"voice": "苏打", "speed": 1.0})
        with tempfile.TemporaryDirectory() as work_dir:
            with patch.object(
                provider, "_request_mimo_chunk", return_value=_wav_bytes()
            ) as request, patch(
                'audiobook_generator.tts_providers.openai_tts_provider.split_text',
                return_value=["一", "二"],
            ):
                provider.synthesize_segment("甲乙", first, work_dir)
                provider.synthesize_segment("甲乙", second, work_dir)
        self.assertEqual(request.call_count, 4)
        self.assertEqual(
            [call.kwargs["voice"] for call in request.call_args_list],
            ["冰糖", "冰糖", "苏打", "苏打"],
        )


    @patch('audiobook_generator.tts_providers.openai_tts_provider.get_mimo_credentials',
           return_value=('fake_key', 'https://example.invalid/v1'))
    def test_cache_reuses_audio_for_speed_but_invalidates_inherited_instructions(self, _credentials):
        provider = get_tts_provider(get_openai_config())
        slow = VoiceProfile("hero", "主角", {"voice": "茉莉", "speed": 0.9})
        fast = VoiceProfile("hero", "主角", {"voice": "茉莉", "speed": 1.2})
        with tempfile.TemporaryDirectory() as root, patch.object(
            provider, "_request_mimo_chunk", return_value=_wav_bytes()
        ) as request:
            provider.synthesize_segment("同文试听", slow, root)
            provider.synthesize_segment("同文试听", fast, root)
            self.assertEqual(request.call_count, 1)
            self.assertIn("稳定", request.call_args.kwargs["instructions"])
            provider.config.instructions = "轻声朗读"
            provider.synthesize_segment("同文试听", slow, root)
            self.assertEqual(request.call_count, 2)
            self.assertIn("轻声朗读", request.call_args.kwargs["instructions"])

    @patch('audiobook_generator.tts_providers.openai_tts_provider.get_mimo_credentials',
           return_value=('fake_key', 'https://example.invalid/v1'))
    def test_segment_uses_english_tone_instruction_for_english_book(self, _credentials):
        config = get_openai_config()
        config.language = "en-US"
        provider = get_tts_provider(config)
        profile = VoiceProfile(
            role_id="little_prince",
            display_name="The Little Prince",
            provider_params={
                "voice": "Dean",
                "instructions": "Speak naturally in English at a steady pace.",
                "speed": 1.0,
            },
            tone="Speak softly and warmly.",
        )
        with tempfile.TemporaryDirectory() as work_dir:
            with patch.object(
                provider, "_request_mimo_chunk", return_value=_wav_bytes()
            ) as request:
                provider.synthesize_segment("Hello, I am the little prince.", profile, work_dir)
        instructions = request.call_args.kwargs["instructions"]
        self.assertIn("Tone requirement: Speak softly and warmly.", instructions)
        self.assertNotIn("语气要求", instructions)


if __name__ == '__main__':
    unittest.main()
