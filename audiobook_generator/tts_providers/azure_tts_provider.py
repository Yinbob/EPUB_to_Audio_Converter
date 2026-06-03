import logging
import os
import requests
from audiobook_generator.config.general_config import GeneralConfig
from audiobook_generator.tts_providers.base_tts_provider import BaseTTSProvider

logger = logging.getLogger(__name__)


class AzureTTSProvider(BaseTTSProvider):
    def __init__(self, config: GeneralConfig):
        super().__init__(config)
        # 默认使用你提供的 Qwen API 地址，也可以通过环境变量 QWEN_TTS_URL 进行覆盖
        self.url = os.getenv("QWEN_TTS_URL", "http://10.5.96.159:8000/generate")

        # 将原 Azure 的 voice_name 映射为 Qwen 的 speaker
        # 这样你在 UI 或配置中输入的音色名称（如 Aiden）会直接传给大模型
        self.speaker = self.config.voice_name if self.config.voice_name else "Aiden"

        # 获取配置中的语言设置，若无则默认 "English"
        self.language = getattr(self.config, "language", "English")

    def text_to_speech(self, text: str, output_file_path: str):
        """
        调用 Qwen TTS API 并将返回的音频数据保存到指定路径
        """
        # 封装请求数据
        data = {
            "text": text,
            "language": self.language,
            "speaker": self.speaker,
            "instruct": "gentle tone"  # 默认语气，可根据需要在此处修改
        }

        logger.info(f"正在调用 Qwen TTS 接口 | 音色: {self.speaker} | 语言: {self.language} | 文本长度: {len(text)}")

        try:
            # 大模型生成音频可能需要一定时间，在此处设置合理的超时时间（如 5 分钟）
            response = requests.post(self.url, json=data, timeout=300)

            if response.status_code == 200:
                # 将大模型返回的二进制音频流直接写入目标文件
                with open(output_file_path, "wb") as f:
                    f.write(response.content)
                logger.info(f"音频成功生成并保存至: {output_file_path}")
            else:
                raise RuntimeError(f"Qwen TTS 接口返回错误: {response.status_code} - {response.text}")

        except requests.exceptions.RequestException as e:
            logger.error(f"请求 Qwen TTS 接口时发生网络异常: {e}")
            raise e
        except Exception as e:
            logger.error(f"处理音频文件时发生异常: {e}")
            raise e

    def estimate_cost(self, text: str) -> float:
        """
        由于使用的是私有化或本地部署的 Qwen 大模型，单次生成的计费成本视为 0
        """
        return 0.0