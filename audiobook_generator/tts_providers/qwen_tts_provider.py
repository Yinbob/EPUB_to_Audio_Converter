import logging
import os
import requests
from audiobook_generator.config.general_config import GeneralConfig
from audiobook_generator.tts_providers.base_tts_provider import BaseTTSProvider
from audiobook_generator.utils.qwen_config import get_qwen_credentials

logger = logging.getLogger(__name__)


class QwenTTSProvider(BaseTTSProvider):
    def __init__(self, config: GeneralConfig):
        super().__init__(config)
        
        # Qwen TTS API 配置 - 优先从配置文件读取，覆盖环境变量
        self.api_key, self.base_url, self.model = get_qwen_credentials()
        
        # 设置 speaker (voice)
        self.speaker = self.config.voice_name if self.config.voice_name else "Vivian"
        
        # 获取配置中的语言设置，若无则默认 "Auto"
        self.language = getattr(self.config, "language", "Auto")

    def text_to_speech(self, text: str, output_file_path: str, audio_tags=None):
        """
        调用 Qwen TTS API 并将返回的音频数据保存到指定路径
        """
        logger.info(f"正在调用 Qwen TTS 接口 | 音色: {self.speaker} | 语言: {self.language} | 文本长度: {len(text)}")
        logger.info(f"API 配置 | base_url: {self.base_url} | model: {self.model}")

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

        try:
            logger.info("正在发送请求到 API...")
            response = requests.post(url, headers=headers, json=data, timeout=300, stream=True)
            logger.info(f"收到 API 响应 | 状态码: {response.status_code}")
            
            if response.status_code == 200:
                with open(output_file_path, "wb") as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                logger.info(f"音频成功生成并保存至: {output_file_path}")
            else:
                raise RuntimeError(f"Qwen TTS 接口返回错误: {response.status_code} - {response.text}")

        except Exception as e:
            logger.error(f"调用 Qwen TTS 接口时发生异常: {e}")
            import traceback
            logger.error(traceback.format_exc())
            raise e

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
