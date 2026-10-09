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
from audiobook_generator.tts_providers.voice_catalog import list_provider_voices
from audiobook_generator.tts_providers.segment_synthesis import (
    atomic_export_audio,
    atomic_write_bytes,
    emit_role_progress,
    segment_cache_key,
)
from audiobook_generator.utils.mimo_config import get_mimo_credentials

logger = logging.getLogger(__name__)


def get_openai_supported_output_formats():
    return ["mp3", "aac", "flac", "opus", "wav"]


def get_openai_supported_voices():
    """返回内置 MiMo 音色，并合并用户人工上传官网文档得到的音色。"""
    builtin = ["mimo_default", "冰糖", "茉莉", "苏打", "白桦", "Mia", "Chloe", "Milo", "Dean"]
    try:
        imported = [entry.voice_id for entry in list_provider_voices("openai")]
    except Exception as exc:
        logger.warning("读取人工 MiMo 音色目录失败：%s", exc)
        imported = []
    return list(dict.fromkeys(imported + [voice for voice in builtin if voice not in imported]))


def get_openai_supported_models():
    return ["mimo-v2.5-tts"]


def get_openai_instructions_example():
    return """Voice Affect: Calm, composed, and reassuring. Competent and in control, instilling trust."""


def get_price(model):
    return 0.0


class OpenAITTSProvider(BaseTTSProvider):
    provider_id = "openai"

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
            api_key=api_key,
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

    def _request_mimo_chunk(
        self,
        chunk: str,
        *,
        voice: str,
        instructions: str | None,
    ) -> bytes:
        messages = []
        messages.append({
            "role": "user",
            "content": instructions or "Read the text in a natural and clear audiobook voice.",
        })
        messages.append({"role": "assistant", "content": chunk})

        if self.config.stream:
            completion = self.client.chat.completions.create(
                model=self.config.model_name,
                messages=messages,
                audio={"format": "pcm16", "voice": voice},
                stream=True,
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
                raise RuntimeError("MiMo 流式响应没有音频数据")
            wav_buffer = io.BytesIO()
            sf.write(wav_buffer, collected_pcm, samplerate=24000, format="WAV")
            return wav_buffer.getvalue()

        completion = self.client.chat.completions.create(
            model=self.config.model_name,
            messages=messages,
            audio={
                "format": self.config.output_format,
                "voice": voice,
            },
        )
        message = completion.choices[0].message
        audio_data = getattr(getattr(message, "audio", None), "data", None)
        if not audio_data:
            raise RuntimeError("MiMo 响应没有音频数据")
        return base64.b64decode(audio_data)

    def synthesize_segment(self, text, profile, work_dir, progress=None):
        """在单个 segment 内分块、重试并缓存，speed 由章节音频管线统一后处理。"""
        from audiobook_generator.role_script.audio_pipeline import build_audio_artifact

        params = dict(profile.provider_params)
        voice = str(params.get("voice") or self.config.voice_name or "mimo_default")
        instructions = params.get("instructions", self.config.instructions)
        tone = getattr(profile, "tone", None) or profile.provider_params.get("_tone")
        effective_instructions = instructions
        if tone:
            tone_instruction = (
                f"Tone requirement: {tone}"
                if str(getattr(self.config, "language", "") or "").lower().startswith("en")
                else f"语气要求：{tone}"
            )
            effective_instructions = (
                f"{instructions}\n{tone_instruction}" if instructions else tone_instruction
            )

        # 音色与情绪不应隐式决定快慢；明确的用户快慢要求仍保留。
        pace_instruction = (
            "Unless an explicit pace is requested above, use a steady, moderate audiobook "
            "pace. Keep the pace consistent across voices and emotions; avoid drawn-out "
            "syllables and excessive pauses. Read only the supplied text."
            if str(self.config.language or "").lower().startswith("en")
            else "除非上文明确要求快慢，否则使用稳定、适中的有声书语速。"
            "不同音色和情绪保持一致的朗读节奏，不拖长字音或添加过长停顿，只朗读所给正文。"
        )
        effective_instructions = "\n".join(filter(None, [effective_instructions, pace_instruction]))

        actual_extension = "wav" if self.config.stream else self.config.output_format
        cache_key = segment_cache_key(
            provider="openai",
            model=self.config.model_name,
            # speed 在后处理阶段生效，调倍率可以复用原音频；缓存必须包含实际请求指令。
            provider_params={"voice": voice, "instructions": effective_instructions},
            tone=tone,
            text=text,
            request_options={
                "stream": bool(self.config.stream),
                "output_format": self.config.output_format,
            },
        )
        cache_dir = os.path.join(work_dir, "segment_cache")
        os.makedirs(cache_dir, exist_ok=True)
        cache_file = os.path.join(cache_dir, f"{cache_key}.{actual_extension}")
        logger.info(
            "MiMo 角色 segment 调用：voice=%s, speed=%s, instructions=%s",
            voice,
            params.get("speed", 1.0),
            (effective_instructions or "")[:160],
        )
        if os.path.isfile(cache_file):
            logger.info("角色 segment 缓存命中：%s", cache_file)
            return build_audio_artifact(cache_file, cache_key=cache_key)

        chunks = split_text(text, 1800, self.config.language) or [text]
        last_error = None
        for attempt in range(1, 3):
            try:
                generated = []
                for index, chunk in enumerate(chunks, 1):
                    emit_role_progress(
                        progress,
                        f"role_segment_chunk_{index}_of_{len(chunks)}",
                    )
                    generated.append(
                        self._request_mimo_chunk(
                            chunk,
                            voice=voice,
                            instructions=effective_instructions,
                        )
                    )
                if len(generated) == 1:
                    atomic_write_bytes(cache_file, generated[0])
                else:
                    combined = AudioSegment.empty()
                    for audio_bytes in generated:
                        combined += AudioSegment.from_file(
                            io.BytesIO(audio_bytes), format=actual_extension
                        )
                    atomic_export_audio(
                        combined, cache_file, format=actual_extension
                    )
                return build_audio_artifact(cache_file, cache_key=cache_key)
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "MiMo 角色 segment 合成失败（第 %d/2 次）：%s", attempt, exc
                )
        raise RuntimeError(f"MiMo 角色 segment 合成失败：{last_error}")

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
