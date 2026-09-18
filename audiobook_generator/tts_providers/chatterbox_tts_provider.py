import io
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

try:
    import torch
except ImportError:  # 未安装 torch 时仍允许项目启动（使用非 Chatterbox 引擎）
    torch = None

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
        "hf_repo": "ResembleAI/chatterbox",
        "description": "多语言 V3 版本，支持中文、英文等多种语言",
        "supports_chinese": True
    },
    "chatterbox-v0.5": {
        "hf_repo": "ResembleAI/chatterbox",
        "description": "原始版本，主要支持英文",
        "supports_chinese": False
    }
}

# 默认使用多语言版本
DEFAULT_CHATTERBOX_MODEL = "chatterbox-multilingual-v3"

# 默认输出格式：mp3 体积小、播放器兼容性好
DEFAULT_CHATTERBOX_OUTPUT_FORMAT = "mp3"

# ═══════════════════════════════════════════════════════════════
# 语速换算
# 对外（WebUI 滑块 / CLI 参数）统一暴露 0.2~2.0 的「显示语速」，1.0 为标准语速；
# 实际交给 ffmpeg atempo 的倍率 = 显示语速 × CHATTERBOX_SPEED_SCALE。
# 之所以要换算：显示 1.0 时的听感对齐旧版本习惯的 0.7 倍速（更慢、更自然），
# 于是显示范围 0.2~2.0 对应实际倍率 0.14~1.4。
# ═══════════════════════════════════════════════════════════════
DEFAULT_CHATTERBOX_SPEED = 1.0
CHATTERBOX_SPEED_SCALE = 0.7
MIN_CHATTERBOX_SPEED = 0.2
MAX_CHATTERBOX_SPEED = 2.0


def get_chatterbox_speed_range():
    """返回对外暴露的语速范围（显示值）"""
    return MIN_CHATTERBOX_SPEED, MAX_CHATTERBOX_SPEED


def normalize_display_speed(display_speed):
    """把任意输入夹紧到允许的显示语速范围，非法输入回落到默认值"""
    if display_speed is None:
        return DEFAULT_CHATTERBOX_SPEED
    try:
        value = float(display_speed)
    except (TypeError, ValueError):
        logger.warning(f"语速 {display_speed!r} 不是数字，已回落到默认值 {DEFAULT_CHATTERBOX_SPEED}")
        return DEFAULT_CHATTERBOX_SPEED
    return min(max(value, MIN_CHATTERBOX_SPEED), MAX_CHATTERBOX_SPEED)


def display_speed_to_internal_speed(display_speed):
    """把显示语速换算成实际 atempo 倍率（显示 1.0 → 实际 0.7）"""
    return round(float(display_speed) * CHATTERBOX_SPEED_SCALE, 4)


def _ffmpeg_available():
    """ffmpeg 是否可用（未找到时 FFMPEG_PATH 会退回裸命令名，再查一次 PATH）"""
    if os.path.sep in FFMPEG_PATH:
        return os.path.exists(FFMPEG_PATH)
    return shutil.which(FFMPEG_PATH) is not None


def should_use_pydub_merge(segment_count, output_format, requested=None):
    """判断是否必须用 pydub 合并音频分片。

    直接写入（把字节流首尾相接）只在「单分片 + wav」时安全：
    - wav 每个分片都带自己的 RIFF 头，直接拼接后播放器只认第一块（实测容器时长只有第一块的长度）；
    - mp3 虽然是帧流，但拼接处会丢帧并让解码器报 Header missing。
    多分片或压缩格式交给 pydub 解码后重新导出，得到一条完整、干净的音轨。
    """
    if requested:
        return True
    if segment_count <= 1 and output_format == "wav":
        return False
    return True


def _resolve_ffmpeg_binary(name):
    """按 环境变量 -> PATH -> 常见安装路径 的顺序解析 ffmpeg/ffprobe 可执行文件。"""
    env_value = os.environ.get(f"{name.upper()}_PATH")
    if env_value:
        return env_value
    found = shutil.which(name)
    if found:
        return found
    for path in (f"/usr/bin/{name}", f"/usr/local/bin/{name}", f"/opt/homebrew/bin/{name}"):
        if os.path.exists(path):
            return path
    return name  # 交由 PATH 解析，找不到时由调用方报错


# ffmpeg 路径（不再硬编码 macOS 路径，兼容 Linux 服务器）
FFMPEG_PATH = _resolve_ffmpeg_binary("ffmpeg")
FFPROBE_PATH = _resolve_ffmpeg_binary("ffprobe")


def get_chatterbox_supported_models():
    """返回支持的模型列表"""
    return list(CHATTERBOX_MODELS.keys())


def get_chatterbox_supported_devices():
    """返回支持的设备列表（torch 未安装时仅返回 CPU 选项）"""
    devices = ["auto", "cpu"]
    if torch is not None:
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
    if torch is None:
        # torch 未安装时只能回退到 CPU；真正使用 Chatterbox 时会在加载模型处给出明确报错
        if device_config and device_config not in ("auto", "cpu"):
            logger.warning(f"torch 未安装，无法使用设备 {device_config}，回退到 CPU")
        return "cpu"

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

    if torch is None:
        raise ImportError(
            "Chatterbox 需要 PyTorch，但当前环境未安装 torch。\n"
            "请创建独立虚拟环境并安装（详见 README「Linux 服务器部署（Miniconda）」章节）：\n"
            "  python -m venv venv_chatterbox --system-site-packages\n"
            "  ./venv_chatterbox/bin/pip install torch torchaudio\n"
            "  ./venv_chatterbox/bin/pip install chatterbox-tts"
        )

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
        config.output_format = config.output_format or DEFAULT_CHATTERBOX_OUTPUT_FORMAT
        config.model_name = config.model_name or DEFAULT_CHATTERBOX_MODEL
        self.model_name = config.model_name
        self.reference_audio = getattr(config, 'chatterbox_reference_audio', None)
        
        super().__init__(config)
        
        self.device = _get_device(getattr(config, 'chatterbox_device', None))
        self.exaggeration = getattr(config, 'chatterbox_exaggeration', 0.5) or 0.5
        self.cfg_weight = getattr(config, 'chatterbox_cfg_weight', 0.5) or 0.5

        # 语速：config 里存的是显示语速，真正生效的是折算后的倍率
        raw_speed = getattr(config, 'chatterbox_speed', None)
        self.display_speed = normalize_display_speed(raw_speed)
        if raw_speed is not None:
            try:
                if abs(float(raw_speed) - self.display_speed) > 1e-9:
                    logger.warning(
                        f"语速 {raw_speed} 超出范围 {MIN_CHATTERBOX_SPEED}~{MAX_CHATTERBOX_SPEED}，"
                        f"已按 {self.display_speed} 处理"
                    )
            except (TypeError, ValueError):
                pass
        self.speed = display_speed_to_internal_speed(self.display_speed)
        
        model_info = get_chatterbox_model_info(self.model_name)
        
        logger.info(f"ChatterboxTTSProvider 初始化")
        logger.info(f"  - 模型: {self.model_name}")
        logger.info(f"  - 设备: {self.device}")
        logger.info(f"  - 输出格式: {self.config.output_format}")
        logger.info(f"  - 语速: 显示 {self.display_speed}x → 实际 {self.speed}x")
        logger.info(f"  - 支持中文: {model_info['supports_chinese']}")
        if self.reference_audio:
            logger.info(f"  - 参考音频: {self.reference_audio}")

    def __str__(self) -> str:
        return f"ChatterboxTTSProvider(model={self.model_name}, device={self.device})"

    def validate_config(self):
        if self.config.output_format not in get_chatterbox_supported_output_formats():
            raise ValueError(f"Chatterbox: 不支持的输出格式: {self.config.output_format}")

        # 非 wav 输出需要 ffmpeg 转码；提前给出可操作的中文提示，避免 pydub 抛出晦涩异常
        if (self.config.output_format != "wav"
                and not getattr(self.config, "preview", False)
                and not _ffmpeg_available()):
            raise ValueError(
                f"Chatterbox: 输出格式 {self.config.output_format} 需要 ffmpeg，但当前环境未检测到。"
                "请先安装 ffmpeg（Ubuntu: sudo apt install -y ffmpeg；macOS: brew install ffmpeg），"
                "或把输出格式改为 wav。"
            )
        
        if self.model_name not in CHATTERBOX_MODELS:
            raise ValueError(f"Chatterbox: 不支持的模型: {self.model_name}. 可用模型: {get_chatterbox_supported_models()}")
        
        if self.reference_audio and not os.path.exists(self.reference_audio):
            raise ValueError(f"Chatterbox: 参考音频文件不存在: {self.reference_audio}")
        
        # 检查中文支持
        model_info = get_chatterbox_model_info(self.model_name)
        if self.config.language and "zh" in self.config.language.lower() and not model_info["supports_chinese"]:
            logger.warning(f"模型 {self.model_name} 不支持中文，建议使用 chatterbox-multilingual-v3")

    def _adjust_speed_with_ffmpeg(self, wav, sample_rate, speed):
        """使用 ffmpeg atempo 滤波器调整语速，保持音调不变"""
        import soundfile as sf
        import io

        # atempo 单个滤波器范围 0.5~2.0，超出需要链式叠加
        if speed < 0.5:
            filters = []
            remaining = speed
            while remaining < 0.5:
                filters.append("atempo=0.5")
                remaining /= 0.5
            filters.append(f"atempo={remaining:.6f}")
            filter_str = ",".join(filters)
        elif speed > 2.0:
            filters = []
            remaining = speed
            while remaining > 2.0:
                filters.append("atempo=2.0")
                remaining /= 2.0
            filters.append(f"atempo={remaining:.6f}")
            filter_str = ",".join(filters)
        else:
            filter_str = f"atempo={speed:.6f}"

        # 内存中通过 pipe 处理，不写临时文件
        wav_buffer = io.BytesIO()
        sf.write(wav_buffer, wav, samplerate=sample_rate, format="wav")
        wav_buffer.seek(0)

        try:
            proc = subprocess.Popen(
                [FFMPEG_PATH, '-y', '-i', 'pipe:0',
                 '-filter:a', filter_str,
                 '-f', 'wav', 'pipe:1'],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            out, err = proc.communicate(input=wav_buffer.read(), timeout=30)
            if proc.returncode != 0:
                logger.error(f"ffmpeg atempo 失败: {err.decode(errors='replace')}")
                return wav  # fallback
            wav_adjusted, _ = sf.read(io.BytesIO(out))
            return wav_adjusted
        except FileNotFoundError:
            logger.warning(
                "未找到 ffmpeg，已跳过语速调整（按原始语速输出）。"
                "安装后即可生效：Ubuntu `sudo apt install -y ffmpeg` / macOS `brew install ffmpeg`"
            )
            return wav  # fallback
        except Exception as e:
            logger.error(f"语速调整异常: {e}")
            return wav  # fallback

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

                # 语速调整（使用 ffmpeg atempo 滤波器，保持音调不变）
                if self.speed and self.speed != 1.0:
                    wav = self._adjust_speed_with_ffmpeg(wav, model.sr, self.speed)
                    logger.debug(f"语速调整为 {self.speed}x，新长度 = {len(wav)} 采样")
                
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
        
        # 合并音频片段：直接拼接在多分片/压缩格式下会丢音频，这里自动改用 pydub 合并
        use_pydub_merge = should_use_pydub_merge(
            len(audio_segments), self.config.output_format, self.config.use_pydub_merge
        )
        if use_pydub_merge and not self.config.use_pydub_merge:
            if _ffmpeg_available():
                logger.info(
                    f"共 {len(audio_segments)} 个音频分片（输出格式 {self.config.output_format}），"
                    "自动使用 pydub 合并以保证音频完整"
                )
            else:
                logger.warning(
                    "未检测到 ffmpeg，无法使用 pydub 合并；直接拼接多分片可能丢失部分音频，"
                    "建议安装 ffmpeg（Ubuntu: sudo apt install -y ffmpeg）"
                )
                use_pydub_merge = False

        merge_audio_segments(audio_segments, output_file, self.config.output_format, chunk_ids,
                             use_pydub_merge)
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
