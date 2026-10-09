from typing import List, Optional

from audiobook_generator.config.general_config import GeneralConfig

TTS_QWEN = "qwen"
TTS_OPENAI = "openai"
TTS_EDGE = "edge"
TTS_PIPER = "piper"
TTS_MINIMAX = "minimax"
TTS_CHATTERBOX = "chatterbox"
TTS_VOXCPM = "voxcpm"


class BaseTTSProvider:  # Base interface for TTS providers
    # Base provider interface
    provider_id = None

    def __init__(self, config: GeneralConfig):
        self.config = config
        self.validate_config()

    def __str__(self) -> str:
        return f"{self.config}"

    def validate_config(self):
        raise NotImplementedError

    def text_to_speech(self, *args, **kwargs):
        raise NotImplementedError

    def synthesize_segment(self, text, profile, work_dir, progress):
        """角色模式接口：合成单个 segment，返回实际格式的 AudioArtifact。"""
        raise NotImplementedError

    def text_to_speech_segments(self, units, output_file, tags):
        """兼容门面：逐段合成后交由角色音频管线合并。"""
        from audiobook_generator.role_script.audio_pipeline import assemble_chapter_audio
        from audiobook_generator.role_script.models import ChapterSynthesisPlan

        units = tuple(units)
        if not units:
            raise ValueError("角色模式没有可合成的 segment")
        plan = ChapterSynthesisPlan(
            chapter_index=units[0].chapter_index,
            title=units[0].chapter_title,
            units=units,
            output_format=self.get_output_file_extension(),
            provider=self.provider_id or self.__class__.__name__.lower(),
        )
        artifacts = []
        for unit in units:
            artifacts.append(
                self.synthesize_segment(
                    unit.text,
                    unit.profile,
                    output_file + ".segments",
                    None,
                )
            )
        return assemble_chapter_audio(
            plan,
            artifacts,
            output_file,
            tags,
            output_file + ".segments",
        )

    def estimate_cost(self, total_chars):
        raise NotImplementedError

    def get_break_string(self):
        raise NotImplementedError

    def get_output_file_extension(self):
        raise NotImplementedError


# Common support methods for all TTS providers
def get_supported_tts_providers() -> List[str]:
    return [TTS_QWEN, TTS_OPENAI, TTS_EDGE, TTS_PIPER, TTS_MINIMAX, TTS_CHATTERBOX, TTS_VOXCPM]


def get_tts_provider(config) -> BaseTTSProvider:
    if config.tts == TTS_QWEN:
        from audiobook_generator.tts_providers.qwen_tts_provider import (
            QwenTTSProvider,
        )

        return QwenTTSProvider(config)
    elif config.tts == TTS_OPENAI:
        from audiobook_generator.tts_providers.openai_tts_provider import (
            OpenAITTSProvider,
        )

        return OpenAITTSProvider(config)
    elif config.tts == TTS_EDGE:
        from audiobook_generator.tts_providers.edge_tts_provider import EdgeTTSProvider

        return EdgeTTSProvider(config)
    elif config.tts == TTS_PIPER:
        from audiobook_generator.tts_providers.piper_tts_provider import PiperTTSProvider

        return PiperTTSProvider(config)
    elif config.tts == TTS_MINIMAX:
        from audiobook_generator.tts_providers.minimax_tts_provider import MiniMaxTTSProvider

        return MiniMaxTTSProvider(config)
    elif config.tts == TTS_CHATTERBOX:
        from audiobook_generator.tts_providers.chatterbox_tts_provider import ChatterboxTTSProvider

        return ChatterboxTTSProvider(config)
    elif config.tts == TTS_VOXCPM:
        from audiobook_generator.tts_providers.voxcpm_tts_provider import VoxCPMTTSProvider

        return VoxCPMTTSProvider(config)
    else:
        raise ValueError(f"Invalid TTS provider: {config.tts}")
