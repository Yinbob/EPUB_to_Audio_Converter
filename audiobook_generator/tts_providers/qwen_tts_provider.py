import io
import logging
import os
import shutil
import time

import requests
from pydub import AudioSegment

from audiobook_generator.config.general_config import GeneralConfig
from audiobook_generator.core.audio_tags import AudioTags
from audiobook_generator.tts_providers.base_tts_provider import BaseTTSProvider
from audiobook_generator.utils.qwen_config import get_qwen_credentials
from audiobook_generator.utils.utils import split_text, merge_audio_segments, set_audio_tags

logger = logging.getLogger(__name__)

# 单次请求的最大文本长度：Qwen3-TTS VoiceDesign 模型对输入长度有限制，
# 整章一次性发送容易触发服务端排队/超时（实测故障：Read timed out (read timeout=300)）。
DEFAULT_QWEN_MAX_CHARS = 1500
# 每次请求的超时时间（秒），可用环境变量 QWEN_TTS_TIMEOUT 覆盖
DEFAULT_QWEN_TIMEOUT = 300
# 单分片失败重试次数（指数退避），网络抖动/服务端繁忙时自动重试
DEFAULT_QWEN_MAX_RETRIES = 3


class _NoRetryError(RuntimeError):
    """参数/鉴权类错误（4xx），重试无意义，直接抛出。"""


def _ffmpeg_available():
    """ffmpeg 是否可用（pydub 合并多分片 mp3 需要）"""
    converter = getattr(AudioSegment, "converter", None) or "ffmpeg"
    if os.path.sep in converter:
        return os.path.exists(converter)
    return shutil.which(converter) is not None


def _should_use_pydub_merge(segment_count, requested=None):
    """多分片直接拼接 mp3 会在拼接处丢帧，必须用 pydub 合并；单分片直接写入即可。"""
    if requested:
        return True
    return segment_count > 1


class QwenTTSProvider(BaseTTSProvider):
    def __init__(self, config: GeneralConfig):
        super().__init__(config)

        # Qwen TTS API 配置 - 优先从配置文件读取，覆盖环境变量
        self.api_key, self.base_url, self.model = get_qwen_credentials()

        # 设置 speaker (voice)
        self.speaker = self.config.voice_name if self.config.voice_name else "Vivian"

        # 获取配置中的语言设置，若无则默认 "Auto"
        self.language = getattr(self.config, "language", "Auto")

        # 每次请求的超时时间，可通过环境变量 QWEN_TTS_TIMEOUT 调大/调小
        try:
            self.timeout = int(os.environ.get("QWEN_TTS_TIMEOUT", DEFAULT_QWEN_TIMEOUT))
        except ValueError:
            self.timeout = DEFAULT_QWEN_TIMEOUT

    def _request_audio(self, text: str) -> bytes:
        """
        请求单个分片的音频，失败自动重试（指数退避）。
        返回 mp3 字节内容。
        """
        url = f"{self.base_url}/audio/speech"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        data = {
            "model": self.model,
            "voice": self.speaker,
            "response_format": "mp3",
            "task_type": "VoiceDesign",
            "language": self.language,
            "instructions": "gentle tone",
            "input": text,
        }

        last_exc: Exception | None = None
        for attempt in range(1, DEFAULT_QWEN_MAX_RETRIES + 1):
            try:
                logger.info(
                    f"正在发送请求到 API | 分片长度: {len(text)} | 尝试 {attempt}/{DEFAULT_QWEN_MAX_RETRIES}"
                )
                response = requests.post(
                    url, headers=headers, json=data, timeout=self.timeout, stream=True
                )
                logger.info(f"收到 API 响应 | 状态码: {response.status_code}")

                if response.status_code != 200:
                    msg = f"Qwen TTS 接口返回错误: {response.status_code} - {response.text}"
                    logger.error(msg)
                    if 400 <= response.status_code < 500:
                        raise _NoRetryError(msg)
                    raise RuntimeError(msg)

                buf = io.BytesIO()
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        buf.write(chunk)
                audio = buf.getvalue()
                if not audio:
                    raise RuntimeError("Qwen TTS 接口返回了空音频")
                return audio

            except _NoRetryError:
                raise
            except Exception as e:  # noqa: BLE001 - 网络/服务端错误需要重试
                last_exc = e
                logger.error(f"调用 Qwen TTS 接口时发生异常: {e}")
                if attempt < DEFAULT_QWEN_MAX_RETRIES:
                    sleep_time = 2 ** (attempt - 1)
                    logger.warning(f"{sleep_time} 秒后自动重试...")
                    time.sleep(sleep_time)

        raise last_exc  # type: ignore[misc]

    def text_to_speech(self, text: str, output_file_path: str, audio_tags: AudioTags = None):
        """
        调用 Qwen TTS API 并将返回的音频数据保存到指定路径。

        长文本会先按 DEFAULT_QWEN_MAX_CHARS 分片，逐片请求，避免单次请求
        文本过长导致服务端超时；多分片时用 pydub 合并，保证音频完整。
        """
        text_chunks = split_text(text, DEFAULT_QWEN_MAX_CHARS, self.language) or [text]

        audio_segments = []
        chunk_ids = []
        for i, chunk in enumerate(text_chunks, 1):
            if audio_tags is not None:
                chunk_id = f"chapter-{audio_tags.idx}_{audio_tags.title}_chunk_{i}_of_{len(text_chunks)}"
            else:
                chunk_id = f"chunk_{i}_of_{len(text_chunks)}"
            logger.info(
                f"正在调用 Qwen TTS 接口 | 音色: {self.speaker} | 语言: {self.language} | "
                f"分片 {chunk_id} 长度: {len(chunk)}"
            )
            audio = self._request_audio(chunk)
            audio_segments.append(io.BytesIO(audio))
            chunk_ids.append(chunk_id)

        use_pydub_merge = _should_use_pydub_merge(len(audio_segments), self.config.use_pydub_merge)
        if use_pydub_merge and not self.config.use_pydub_merge and not _ffmpeg_available():
            logger.warning(
                "未检测到 ffmpeg，无法使用 pydub 合并；直接拼接多分片可能丢失部分音频，"
                "建议安装 ffmpeg（Ubuntu: sudo apt install -y ffmpeg）"
            )
            use_pydub_merge = False

        merge_audio_segments(
            audio_segments, output_file_path, "mp3", chunk_ids, use_pydub_merge
        )

        if audio_tags is not None:
            set_audio_tags(output_file_path, audio_tags)

        logger.info(f"音频成功生成并保存至: {output_file_path}")

    def get_break_string(self):
        return " @BRK#"

    def get_output_file_extension(self):
        return "mp3"

    def validate_config(self):
        """验证配置参数"""
        if self.config.voice_name and self.config.voice_name not in get_qwen_supported_voices():
            raise ValueError(f"QwenTTS: Unsupported voice name: {self.config.voice_name}")

    def estimate_cost(self, text: str) -> float:
        """
        由于使用的是私有化或本地部署的 Qwen 大模型，单次生成的计费成本视为 0
        """
        return 0.0


def get_qwen_supported_output_formats():
    """返回支持的输出格式"""
    return ["mp3"]


def get_qwen_supported_languages():
    """返回支持的语言"""
    return ["Auto", "English", "Chinese", "Japanese", "Korean", "French", "German", "Spanish", "Portuguese", "Russian"]


def get_qwen_supported_voices():
    """返回支持的音色"""
    return ["Vivian", "Aiden", "Alloy", "Echo", "Fable", "Onyx", "Nova", "Shimmer"]
