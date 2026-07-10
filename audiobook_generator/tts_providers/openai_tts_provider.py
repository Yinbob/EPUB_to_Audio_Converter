import io
import logging
import math
import tempfile
import os
import base64
from pydub import AudioSegment

import numpy as np
import soundfile as sf
from openai import OpenAI

from audiobook_generator.core.audio_tags import AudioTags
from audiobook_generator.config.general_config import GeneralConfig
from audiobook_generator.utils.utils import split_text, set_audio_tags, merge_audio_segments
from audiobook_generator.tts_providers.base_tts_provider import BaseTTSProvider
from audiobook_generator.utils.mimo_config import get_mimo_credentials

logger = logging.getLogger(__name__)


def get_openai_supported_output_formats():
    return ["mp3", "aac", "flac", "opus", "wav"]


def get_openai_supported_voices():
    # 彻底替换为小米 MiMo 支持的合法音色列表
    return ["mimo_default", "冰糖", "茉莉", "苏打", "白桦", "Mia", "Chloe", "Milo", "Dean"]


def get_openai_supported_models():
    return ["mimo-v2.5-tts"]


def get_openai_instructions_example():
    return """Voice Affect: Calm, composed, and reassuring. Competent and in control, instilling trust."""


def get_price(model):
    return 0.0


class OpenAITTSProvider(BaseTTSProvider):
    def __init__(self, config: GeneralConfig):
        # 1. 强制设定或纠正默认参数，防止其回退到官方的 alloy
        config.model_name = config.model_name or "mimo-v2.5-tts"

        # 如果音色为空，或者传入了不属于 MiMo 的音色（例如系统默认带入的 alloy），强制纠正为 mimo_default
        if not config.voice_name or config.voice_name not in get_openai_supported_voices():
            logger.warning(f"Voice '{config.voice_name}' is not supported by MiMo. Falling back to 'mimo_default'.")
            config.voice_name = "mimo_default"

        config.speed = config.speed or 1.0
        config.instructions = config.instructions or None
        config.output_format = config.output_format or "wav"

        self.price = get_price(config.model_name)
        super().__init__(config)

        # 2. 从本地配置文件 / 环境变量 / 交互式输入获取凭证
        api_key, base_url = get_mimo_credentials()

        # 安全处理：自动去除 API Key 中可能误带的非 ASCII 字符（如弯引号）
        cleaned_key = api_key.encode("ascii", "ignore").decode("ascii").strip()
        if cleaned_key != api_key:
            logger.warning("OPENAI_API_KEY contains non-ASCII characters (e.g. smart quotes). Automatically cleaned.")
            api_key = cleaned_key
            os.environ["OPENAI_API_KEY"] = cleaned_key

        self.client = OpenAI(
            base_url=base_url,
            max_retries=4
        )

    def __str__(self) -> str:
        return super().__str__()

    def text_to_speech(self, text: str, output_file: str, audio_tags: AudioTags):
        max_chars = 1800
        text_chunks = split_text(text, max_chars, self.config.language)

        audio_segments = []
        chunk_ids = []

        for i, chunk in enumerate(text_chunks, 1):
            chunk_id = f"chapter-{audio_tags.idx}_{audio_tags.title}_chunk_{i}_of_{len(text_chunks)}"
            logger.info(f"Processing {chunk_id}, length={len(chunk)}")

            if self.config.model_name == "mimo-v2.5-tts":
                messages = []
                if self.config.instructions:
                    messages.append({
                        "role": "user",
                        "content": self.config.instructions
                    })
                else:
                    messages.append({
                        "role": "user",
                        "content": "Read the text in a natural and clear audiobook voice."
                    })

                messages.append({
                    "role": "assistant",
                    "content": chunk
                })

                if self.config.stream:
                    # ── 流式调用：收集 PCM16 分片后合成 WAV ──
                    logger.info(f"Streaming mode enabled for chunk {chunk_id}")
                    completion = self.client.chat.completions.create(
                        model=self.config.model_name,
                        messages=messages,
                        audio={
                            "format": "pcm16",
                            "voice": self.config.voice_name
                        },
                        stream=True
                    )

                    collected_pcm = np.array([], dtype=np.float32)
                    for stream_chunk in completion:
                        if not stream_chunk.choices:
                            continue
                        delta = stream_chunk.choices[0].delta
                        audio = getattr(delta, "audio", None)
                        if audio is not None and isinstance(audio, dict) and "data" in audio:
                            pcm_bytes = base64.b64decode(audio["data"])
                            np_pcm = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
                            collected_pcm = np.concatenate((collected_pcm, np_pcm))

                    if len(collected_pcm) == 0:
                        logger.warning(f"No audio data received for {chunk_id}")
                        continue

                    # 将 PCM float32 写入 WAV 格式的 BytesIO
                    wav_buffer = io.BytesIO()
                    sf.write(wav_buffer, collected_pcm, samplerate=24000, format="WAV")
                    wav_buffer.seek(0)
                    audio_content = wav_buffer.read()
                    logger.info(f"Stream collected {len(collected_pcm)} samples ({len(audio_content)} bytes WAV)")
                else:
                    # ── 非流式调用（原有逻辑） ──
                    completion = self.client.chat.completions.create(
                        model=self.config.model_name,
                        messages=messages,
                        audio={
                            "format": self.config.output_format,
                            "voice": self.config.voice_name
                        }
                    )

                    message = completion.choices[0].message
                    audio_content = base64.b64decode(message.audio.data)

            else:
                response = self.client.audio.speech.create(
                    model=self.config.model_name,
                    voice=self.config.voice_name,
                    speed=self.config.speed,
                    input=chunk,
                    response_format=self.config.output_format,
                )
                audio_content = response.content

            logger.debug(f"Remote server response: size={len(audio_content)} bytes")
            audio_segments.append(io.BytesIO(audio_content))
            chunk_ids.append(chunk_id)

        merge_audio_segments(audio_segments, output_file, self.config.output_format, chunk_ids,
                             self.config.use_pydub_merge)
        set_audio_tags(output_file, audio_tags)

    def get_break_string(self):
        return "   "

    def get_output_file_extension(self):
        return self.config.output_format

    def validate_config(self):
        if self.config.output_format not in get_openai_supported_output_formats():
            raise ValueError(f"OpenAI: Unsupported output format: {self.config.output_format}")
        if self.config.speed < 0.25 or self.config.speed > 4.0:
            raise ValueError(f"OpenAI: Unsupported speed: {self.config.speed}")
        if self.config.voice_name not in get_openai_supported_voices():
            raise ValueError(
                f"OpenAI: Unsupported voice: {self.config.voice_name}. Available: {get_openai_supported_voices()}")

    def estimate_cost(self, total_chars):
        return math.ceil(total_chars / 1000) * self.price