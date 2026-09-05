import io
import logging
import os
import tempfile
from pathlib import Path

import torch
from pydub import AudioSegment

from audiobook_generator.config.general_config import GeneralConfig
from audiobook_generator.core.audio_tags import AudioTags
from audiobook_generator.tts_providers.base_tts_provider import BaseTTSProvider
from audiobook_generator.utils.utils import split_text, set_audio_tags, merge_audio_segments

logger = logging.getLogger(__name__)

# 全局模型缓存，避免重复加载
_chatterbox_model = None
_chatterbox_device = None
_chatterbox_model_name = None

# Chatterbox 支持的模型列表
CHATTERBOX_MODELS = {
    "chatterbox-multilingual-v3": {
        "hf_repo": "resemble-ai/chatterbox",
        "description": "多语言 V3 版本，支持中文、英文等多种语言",
        "supports_chinese": True
    },
    "chatterbox-v0.5": {
        "hf_repo": "resemble-ai/chatterbox",
        "description": "原始版本，主要支持英文",
        "supports_chinese": False
    }
}

# 默认使用多语言版本
DEFAULT_CHATTERBOX_MODEL = "chatterbox-multilingual-v3"


def get_chatterbox_supported_models():
    """返回支持的模型列表"""
    return list(CHATTERBOX_MODELS.keys())


def get_chatterbox_supported_devices():
    """返回支持的设备列表"""
    devices = ["auto", "cpu"]
    if torch.cuda.is_available():
        devices.append("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        devices.append("mps")
    return devices


def get_chatterbox_supported_output_formats():
    """返回支持的输出格式"""
    return ["wav", "mp3", "aac", "flac"]


def get_chatterbox_model_info(model_name):
    """获取模型信息"""
    return CHATTERBOX_MODELS.get(model_name, CHATTERBOX_MODELS[DEFAULT_CHATTERBOX_MODEL])


def _get_device(device_config):
    """根据配置和硬件情况确定设备"""
    if device_config and device_config != "auto":
        if device_config == "cuda" and not torch.cuda.is_available():
            logger.warning("CUDA 不可用，回退到 CPU")
            return "cpu"
        if device_config == "mps" and not (hasattr(torch.backends, "mps") and torch.backends.mps.is_available()):
            logger.warning("MPS 不可用，回退到 CPU")
            return "cpu"
        return device_config
    
    # 自动选择最佳设备
    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _load_chatterbox_model(device, model_name=None):
    """加载 Chatterbox 模型（带缓存）"""
    global _chatterbox_model, _chatterbox_device, _chatterbox_model_name
    
    if model_name is None:
        model_name = DEFAULT_CHATTERBOX_MODEL
    
    # 如果模型已加载且设备和模型名称匹配，直接返回
    if (_chatterbox_model is not None and 
        _chatterbox_device == device and 
        _chatterbox_model_name == model_name):
        return _chatterbox_model
    
    try:
        from chatterbox.tts import ChatterboxTTS
    except ImportError:
        raise ImportError(
            "请先安装 chatterbox-tts: pip install chatterbox-tts\n"
            "注意：这会安装 PyTorch 等较大依赖\n"
            "如需中文支持，请确保安装的是多语言版本"
        )
    
    model_info = get_chatterbox_model_info(model_name)
    hf_repo = model_info["hf_repo"]
    
    logger.info(f"正在加载 Chatterbox TTS 模型: {model_name}")
    logger.info(f"  - HuggingFace 仓库: {hf_repo}")
    logger.info(f"  - 运行设备: {device}")
    logger.info(f"  - 支持中文: {model_info['supports_chinese']}")
    
    try:
        # 尝试从 HuggingFace 加载指定模型
        _chatterbox_model = ChatterboxTTS.from_pretrained(
            repo_id=hf_repo,
            device=device
        )
        _chatterbox_device = device
        _chatterbox_model_name = model_name
        logger.info(f"Chatterbox TTS 模型加载完成: {model_name}")
    except Exception as e:
        logger.error(f"加载 Chatterbox 模型失败: {e}")
        raise
    
    return _chatterbox_model


class ChatterboxTTSProvider(BaseTTSProvider):
    def __init__(self, config: GeneralConfig):
        # 设置默认值
        config.output_format = config.output_format or "wav"
        config.model_name = config.model_name or DEFAULT_CHATTERBOX_MODEL
        
        super().__init__(config)
        
        self.device = _get_device(getattr(config, 'chatterbox_device', None))
        self.reference_audio = getattr(config, 'chatterbox_reference_audio', None)
        self.exaggeration = getattr(config, 'chatterbox_exaggeration', 0.5) or 0.5
        self.cfg_weight = getattr(config, 'chatterbox_cfg_weight', 0.5) or 0.5
        self.model_name = config.model_name
        
        model_info = get_chatterbox_model_info(self.model_name)
        
        logger.info(f"ChatterboxTTSProvider 初始化")
        logger.info(f"  - 模型: {self.model_name}")
        logger.info(f"  - 设备: {self.device}")
        logger.info(f"  - 支持中文: {model_info['supports_chinese']}")
        if self.reference_audio:
            logger.info(f"  - 参考音频: {self.reference_audio}")

    def __str__(self) -> str:
        return f"ChatterboxTTSProvider(model={self.model_name}, device={self.device})"

    def validate_config(self):
        if self.config.output_format not in get_chatterbox_supported_output_formats():
            raise ValueError(f"Chatterbox: 不支持的输出格式: {self.config.output_format}")
        
        if self.model_name not in CHATTERBOX_MODELS:
            raise ValueError(f"Chatterbox: 不支持的模型: {self.model_name}. 可用模型: {get_chatterbox_supported_models()}")
        
        if self.reference_audio and not os.path.exists(self.reference_audio):
            raise ValueError(f"Chatterbox: 参考音频文件不存在: {self.reference_audio}")
        
        # 检查中文支持
        model_info = get_chatterbox_model_info(self.model_name)
        if self.config.language and "zh" in self.config.language.lower() and not model_info["supports_chinese"]:
            logger.warning(f"模型 {self.model_name} 不支持中文，建议使用 chatterbox-multilingual-v3")

    def text_to_speech(self, text: str, output_file: str, audio_tags: AudioTags):
        """将文本转换为语音并保存到文件"""
        logger.info(f"Chatterbox TTS 开始处理 | 模型: {self.model_name} | 文本长度: {len(text)}")
        
        # 加载模型
        model = _load_chatterbox_model(self.device, self.model_name)
        
        # 分块处理长文本（Chatterbox 对长文本可能有限制）
        max_chars = 500  # Chatterbox 推荐的文本长度
        text_chunks = split_text(text, max_chars, self.config.language)
        
        audio_segments = []
        chunk_ids = []
        
        for i, chunk in enumerate(text_chunks, 1):
            chunk_id = f"chapter-{audio_tags.idx}_{audio_tags.title}_chunk_{i}_of_{len(text_chunks)}"
            logger.info(f"处理 {chunk_id}, 长度={len(chunk)}")
            
            try:
                # 生成音频
                if self.reference_audio:
                    # 使用参考音频进行语音克隆
                    wav = model.generate(
                        chunk,
                        audio_prompt_path=self.reference_audio,
                        exaggeration=self.exaggeration,
                        cfg_weight=self.cfg_weight
                    )
                else:
                    # 使用默认声音
                    wav = model.generate(
                        chunk,
                        exaggeration=self.exaggeration,
                        cfg_weight=self.cfg_weight
                    )
                
                # wav 是 torch.Tensor，形状为 (1, samples)
                if isinstance(wav, torch.Tensor):
                    wav = wav.squeeze(0).cpu().numpy()
                
                # 将 numpy 数组转换为 WAV 字节
                import soundfile as sf
                import io
                
                wav_buffer = io.BytesIO()
                sf.write(wav_buffer, wav, samplerate=model.sr, format="WAV")
                wav_buffer.seek(0)
                audio_content = wav_buffer.read()
                
                # 如果需要其他格式，用 pydub 转换
                if self.config.output_format != "wav":
                    audio_segment = AudioSegment.from_wav(io.BytesIO(audio_content))
                    converted_buffer = io.BytesIO()
                    audio_segment.export(converted_buffer, format=self.config.output_format)
                    audio_content = converted_buffer.getvalue()
                
                logger.debug(f"生成音频大小: {len(audio_content)} 字节")
                audio_segments.append(io.BytesIO(audio_content))
                chunk_ids.append(chunk_id)
                
            except Exception as e:
                logger.error(f"处理 {chunk_id} 时出错: {e}")
                raise
        
        # 合并音频片段
        merge_audio_segments(audio_segments, output_file, self.config.output_format, chunk_ids,
                             self.config.use_pydub_merge)
        set_audio_tags(output_file, audio_tags)
        
        logger.info(f"Chatterbox TTS 完成 | 输出文件: {output_file}")

    def get_break_string(self):
        """返回用于分隔文本的字符串"""
        return "   "

    def get_output_file_extension(self):
        """返回输出文件扩展名"""
        return self.config.output_format

    def estimate_cost(self, total_chars):
        """估算成本（本地推理免费）"""
        return 0.0


def get_chatterbox_reference_audio_info(audio_path):
    """获取参考音频文件信息"""
    if not audio_path or not os.path.exists(audio_path):
        return None
    
    try:
        audio = AudioSegment.from_file(audio_path)
        return {
            "duration": len(audio) / 1000.0,  # 秒
            "channels": audio.channels,
            "sample_rate": audio.frame_rate,
            "format": Path(audio_path).suffix
        }
    except Exception as e:
        logger.warning(f"无法读取参考音频信息: {e}")
        return None
