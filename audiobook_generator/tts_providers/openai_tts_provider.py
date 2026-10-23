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
    return ["mimo-v2.5-tts", "mimo-v2.5-tts-voicedesign"]


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
        if not config.voice_name or (not getattr(config, 'allow_custom_tts', False) and config.voice_name not in get_openai_supported_voices()):
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

            route = self.resolve_voice()
            audio_content = self._request_mimo_chunk(chunk, voice=route['voice'],
                instructions=route['instructions'], request=route)
            logger.debug(f"Remote server response: size={len(audio_content)} bytes")
            audio_segments.append(io.BytesIO(audio_content))
            chunk_ids.append(chunk_id)

        if self.resolve_voice()['mode'] in {'design', 'clone'}:
            combined = AudioSegment.empty()
            for segment in audio_segments:
                combined += AudioSegment.from_file(segment, format='wav')
            atomic_export_audio(combined, output_file, format=self.config.output_format)
        else:
            merge_audio_segments(audio_segments, output_file, self.config.output_format, chunk_ids,
                                 self.config.use_pydub_merge)
        set_audio_tags(output_file, audio_tags)

    def resolve_voice(self, params=None, *, tone=None):
        from .mimo_voice import resolve_voice
        return resolve_voice(self.config, params, tone=tone)

    def _request_mimo_chunk(
        self,
        chunk: str,
        *,
        voice: str,
        instructions: str | None,
        client=None,
        request=None,
    ) -> bytes:
        client = self.client if client is None else client
        route = request or self.resolve_voice({'voice': voice, 'instructions': instructions})
        audio_options = {'format': 'pcm16' if route['stream'] else route['format']}
        if route['mode'] == 'preset':
            audio_options['voice'] = voice
        elif route['mode'] == 'clone':
            from .mimo_reference import clone_reference_data_uri
            audio_options['voice'] = clone_reference_data_uri(route)
        else:
            audio_options['optimize_text_preview'] = False
        messages = []
        messages.append({
            "role": "user",
            "content": instructions or "Read the text in a natural and clear audiobook voice.",
        })
        messages.append({"role": "assistant", "content": chunk})

        if route['stream']:
            completion = client.chat.completions.create(
                model=route['model'],
                messages=messages,
                audio=audio_options,
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

        completion = client.chat.completions.create(
            model=route['model'],
            messages=messages,
            audio=audio_options,
        )
        message = completion.choices[0].message
        audio_data = getattr(getattr(message, "audio", None), "data", None)
        if not audio_data:
            raise RuntimeError("MiMo 响应没有音频数据")
        return base64.b64decode(audio_data)

    def synthesize_observed_chunk(self, text, profile, store, run_id, *, resample=False, repair=False):
        """统一核心的一次可观测请求；无隐藏分块、重试、合并或本地变速。"""
        from audiobook_generator.audio_core.store import fingerprint

        if not text.strip() or len(text) > 1800:
            raise ValueError("MiMo 可观测块必须非空且不超过 1800 字符")
        route = self.resolve_voice(profile.provider_params, tone=getattr(profile, 'tone', None))
        voice, instructions, extension = route['voice'], route['instructions'], route['format']
        key = fingerprint({'adapter': 'mimo-observed-v2', 'request': route,
                           'endpoint': str(self.client.base_url), 'text': text})
        cached = None if resample else store.cached(key)
        if cached:
            return cached
        request_id = store.reserve(run_id, key, len(text), repair=repair)
        try:
            # 单次传输即单次账本事件，避免 SDK 自动重试掩盖请求次数。
            client = self.client.with_options(max_retries=0, timeout=max(0.1, min(120.0, store.remaining_seconds(run_id))))
            data = self._request_mimo_chunk(text, voice=voice, instructions=instructions, client=client, request=route)
            decoded = AudioSegment.from_file(io.BytesIO(data), format=extension)
            if not len(decoded):
                raise RuntimeError("MiMo 返回空音频")
            path = store.save_sample(key, data, extension)
            store.write_json(f'requests/{request_id}.json', {'request_id': request_id, 'run_id': run_id,
                'text': text, 'request': route, 'audio_path': path, 'resample': resample})
            store.settle(request_id, artifact=path)
            return path
        except Exception as exc:
            store.settle(request_id, error=exc)
            raise

    def synthesize_segment(self, text, profile, work_dir, progress=None):
        """在单个 segment 内分块、重试并缓存，speed 由章节音频管线统一后处理。"""
        from audiobook_generator.role_script.audio_pipeline import build_audio_artifact

        params = dict(profile.provider_params)
        tone = getattr(profile, 'tone', None) or params.get('_tone')
        route = self.resolve_voice(params, tone=tone)
        voice, effective_instructions, actual_extension = route['voice'], route['instructions'], route['format']
        cache_key = segment_cache_key(provider='openai', model=route['model'],
            provider_params=route, tone=tone, text=text,
            request_options={'endpoint': str(self.client.base_url)})
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
                            request=route,
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
        if self.config.model_name not in get_openai_supported_models() and not getattr(self.config, 'allow_custom_tts', False):
            raise ValueError('不支持的 MiMo 模型')
        self.resolve_voice()
        if self.config.output_format not in get_openai_supported_output_formats():
            raise ValueError(f"OpenAI: Unsupported output format: {self.config.output_format}")
        if self.config.speed < 0.25 or self.config.speed > 4.0:
            raise ValueError(f"OpenAI: Unsupported speed: {self.config.speed}")
        if self.config.voice_name not in get_openai_supported_voices() and not getattr(self.config, 'allow_custom_tts', False):
            raise ValueError(
                f"OpenAI: Unsupported voice: {self.config.voice_name}. Available: {get_openai_supported_voices()}")

    def estimate_cost(self, total_chars):
        return math.ceil(total_chars / 1000) * self.price
