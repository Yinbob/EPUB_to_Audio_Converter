"""VoxCPM2 本地 TTS 引擎提供商。

特性：
- 三种合成模式：design（描述生成音色）/ clone（参考音频克隆）/ hifi（极致克隆：参考音频 + 逐字转写）；
- 内置音色库：固定描述 + 固定 seed 生成的参考音频缓存在 `voices/`，保证长篇章节
  分块合成与多次运行音色一致（VoxCPM 本身没有内置音色表）；
- 长文本按句分块（默认 400 字/块）→ 逐块合成 → pydub 合并，避开官方警告的
  语速漂移 / 爆音 / OOM / 不停止问题；
- GPU 隔离友好：设备解析与 torch.cuda 探测全部延后到模型加载（worker 进程内）
  进行，WebUI 主进程 / CLI 父进程不会提前占用显存；默认 `worker_count=1`，
  torch.compile 产生的 CUDA Graphs 不做多线程并发。

安装前提（Ubuntu + RTX 4090）：
  ./venv_chatterbox/bin/pip install voxcpm
  ./venv_chatterbox/bin/pip install --force-reinstall --no-deps gradio==5.50.0 gradio_client==1.14.0
"""

import io
import logging
import os
import re
import shutil
import subprocess
from typing import Optional

try:
    import torch
except ImportError:  # 未安装 torch 时仍允许项目启动（使用非 VoxCPM 引擎）
    torch = None

from pydub import AudioSegment

from audiobook_generator.config.general_config import GeneralConfig
from audiobook_generator.core.audio_tags import AudioTags
from audiobook_generator.tts_providers.base_tts_provider import BaseTTSProvider
from audiobook_generator.tts_providers.chatterbox_tts_provider import (
    FFMPEG_PATH,
    should_use_pydub_merge,
)
from audiobook_generator.utils.utils import split_text, set_audio_tags, merge_audio_segments
from audiobook_generator.utils.voxcpm_asr import transcribe_audio
from audiobook_generator.utils.voxcpm_voices import (
    VOXCPM_DEFAULT_VOICE_VALUE,
    VOXCPM_VOICE_PRESETS,
    ensure_preset_audio,
    fingerprint_matches,
    get_default_voxcpm_voice_dir,
    preset_audio_stem,
    resolve_voxcpm_voice,
)

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# 常量与默认值
# ═══════════════════════════════════════════════════════════════
DEFAULT_VOXCPM_MODEL = "openbmb/VoxCPM2"
DEFAULT_VOXCPM_OUTPUT_FORMAT = "mp3"
VOXCPM_OUTPUT_FORMATS = ["wav", "mp3", "aac", "flac"]

# 合成模式
VOXCPM_MODE_DESIGN = "design"
VOXCPM_MODE_CLONE = "clone"
VOXCPM_MODE_HIFI = "hifi"
VOXCPM_MODES = {
    VOXCPM_MODE_DESIGN: "描述生成音色（无需参考音频，可叠加声音描述）",
    VOXCPM_MODE_CLONE: "声音克隆（参考音频提供音色，可叠加风格描述）",
    VOXCPM_MODE_HIFI: "极致克隆（参考音频 + 逐字转写，相似度最高，忽略描述）",
}
VOXCPM_MODE_OPTIONS = [
    ("描述生成（Voice Design）", VOXCPM_MODE_DESIGN),
    ("声音克隆（Clone）", VOXCPM_MODE_CLONE),
    ("极致克隆（Hi-Fi）", VOXCPM_MODE_HIFI),
]
DEFAULT_VOXCPM_MODE = VOXCPM_MODE_DESIGN

# 生成参数
DEFAULT_VOXCPM_CFG_VALUE = 2.0
MIN_VOXCPM_CFG_VALUE = 0.5
MAX_VOXCPM_CFG_VALUE = 8.0
DEFAULT_VOXCPM_INFERENCE_TIMESTEPS = 10
MIN_VOXCPM_INFERENCE_TIMESTEPS = 1
MAX_VOXCPM_INFERENCE_TIMESTEPS = 50
DEFAULT_VOXCPM_RETRY_BADCASE = True

# 长文本分块
DEFAULT_VOXCPM_CHUNK_CHARS = 400
MIN_VOXCPM_CHUNK_CHARS = 50
MAX_VOXCPM_CHUNK_CHARS = 1200
VOXCPM_TAIL_MERGE_MIN_CHARS = 80

# 语速（实际 atempo 倍率，1.0 = 原生语速）
DEFAULT_VOXCPM_SPEED = 1.0
MIN_VOXCPM_SPEED = 0.5
MAX_VOXCPM_SPEED = 2.0

VOXCPM_SAMPLE_RATE = 48000

# 输出时长合理性校验：中文朗读约 4.5 字/秒；偏差超过 0.2~3.0 倍告警
CJK_CHARS_PER_SECOND = 4.5
DURATION_RATIO_WARN_LOW = 0.2
DURATION_RATIO_WARN_HIGH = 3.0

# 全局模型缓存（worker 进程内复用，避免每章重复加载）
_voxcpm_model = None
_voxcpm_model_key = None


# ═══════════════════════════════════════════════════════════════
# 设备与参数工具函数（UI / CLI 共用）
# ═══════════════════════════════════════════════════════════════
def get_voxcpm_supported_devices():
    """返回设备列表。仅做探测，不在 UI 进程初始化 CUDA 上下文。"""
    devices = ["auto", "cpu"]
    if torch is not None:
        try:
            if torch.cuda.is_available():
                devices.append("cuda")
        except Exception:
            pass
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            devices.append("mps")
    return devices


def get_voxcpm_supported_output_formats():
    return list(VOXCPM_OUTPUT_FORMATS)


def get_voxcpm_speed_range():
    return MIN_VOXCPM_SPEED, MAX_VOXCPM_SPEED


def get_voxcpm_mode_options():
    return [mode for mode, _ in VOXCPM_MODE_OPTIONS]


def normalize_voxcpm_speed(speed):
    """语速钳制到 0.5~2.0，非法输入回落到默认 1.0。"""
    if speed is None:
        return DEFAULT_VOXCPM_SPEED
    try:
        value = float(speed)
    except (TypeError, ValueError):
        logger.warning(f"语速 {speed!r} 不是数字，已回落到默认值 {DEFAULT_VOXCPM_SPEED}")
        return DEFAULT_VOXCPM_SPEED
    return min(max(value, MIN_VOXCPM_SPEED), MAX_VOXCPM_SPEED)


def _validate_device_syntax(device) -> str | None:
    """校验设备字符串，返回规范化值；非法返回 None（调用方报错）。"""
    if not device:
        return "auto"
    device = str(device).strip()
    if device in ("auto", "cpu", "cuda", "mps"):
        return device
    if re.fullmatch(r"cuda:\d+", device):
        return device
    return None


def _normalize_device(device):
    """把配置里的设备字符串转成 VoxCPM 接受的 device 参数。

    "auto" / 空 → None（VoxCPM 自动选择）；cuda / cuda:N / cpu / mps 原样透传。
    """
    valid = _validate_device_syntax(device)
    if valid is None:
        raise ValueError(
            f"VoxCPM: 设备 {device!r} 格式不合法（可选：auto、cpu、cuda、cuda:N、mps）"
        )
    return None if valid == "auto" else valid


def _ffmpeg_available():
    if os.path.sep in FFMPEG_PATH:
        return os.path.exists(FFMPEG_PATH)
    return shutil.which(FFMPEG_PATH) is not None


def _import_voxcpm():
    try:
        from voxcpm import VoxCPM
        return VoxCPM
    except ImportError as e:
        raise ImportError(
            "VoxCPM 需要安装 voxcpm 包。请在服务器上执行：\n"
            "  ./venv_chatterbox/bin/pip install voxcpm\n"
            "（注意它会把 gradio 升到 6.x，必须随后固定回 5.50.0：\n"
            "  ./venv_chatterbox/bin/pip install --force-reinstall --no-deps "
            "gradio==5.50.0 gradio_client==1.14.0）"
        ) from e


def _voxcpm_accepts_seed(model) -> bool:
    """探测当前 voxcpm 版本是否支持 seed 参数。

    PyPI 发布的 voxcpm 与 GitHub 最新版存在差异：旧版 `_generate()` 不接受
    `seed`（`generate()` 会把 kwargs 原样透传给它，传了会直接 TypeError）。
    因此调用前探测 `_generate`；不支持时降级（预设音色的一致性由缓存参考音频保证，
    自定义描述的 design 模式改用固定描述保证音色，代价是无法精确复现随机音色）。
    """
    try:
        import inspect
        target = getattr(model, "_generate", None) or model.generate
        return "seed" in inspect.signature(target).parameters
    except Exception:
        return False


def _load_voxcpm_model(model_name=None, device="auto", optimize=True, cache=True):
    """加载 VoxCPM 模型。

    cache=True 时进程内复用（转换 worker）；cache=False 供 WebUI 试听等临时
    用途，用完即释放，避免长期占用显存。
    """
    global _voxcpm_model, _voxcpm_model_key

    model_name = model_name or DEFAULT_VOXCPM_MODEL
    normalized_device = _normalize_device(device)
    key = (model_name, normalized_device, bool(optimize))

    if cache and _voxcpm_model is not None and _voxcpm_model_key == key:
        return _voxcpm_model

    VoxCPM = _import_voxcpm()
    logger.info(f"正在加载 VoxCPM 模型：{model_name}")
    logger.info(f"  - 设备：{normalized_device or 'auto'}")
    logger.info(f"  - torch.compile：{optimize}")
    logger.info(
        "  - GPU 提示：若与其他项目共享显卡导致显存不足，请先设置环境变量 "
        "CUDA_VISIBLE_DEVICES 固定本应用使用的 GPU。"
    )

    model = VoxCPM.from_pretrained(
        model_name,
        load_denoiser=False,  # denoise=True 时才需要 ZipEnhancer，默认不加载省显存
        optimize=optimize,
        device=normalized_device,
    )

    if cache:
        _voxcpm_model = model
        _voxcpm_model_key = key
    logger.info(f"VoxCPM 模型加载完成：{model_name}")
    return model


def _release_voxcpm_model(model):
    """释放临时模型并清空 CUDA 缓存（试听后调用，避免与正式转换抢显存）。"""
    if model is None:
        return
    try:
        del model
        if torch is not None and torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception as e:
        logger.warning(f"释放 VoxCPM 临时模型时出错：{e}")


# ═══════════════════════════════════════════════════════════════
# WebUI 试听：生成/返回预设音色参考音频（用完即释放模型）
# ═══════════════════════════════════════════════════════════════
def preview_voxcpm_preset_audio(voice_value=None, voice_dir=None, model_name=None,
                                device="auto", cfg_value=None, inference_timesteps=None,
                                regenerate=False, optimize=True) -> str:
    """生成或返回预设音色的试听参考音频路径。

    仅支持内置预设（自定义参考音频可直接上传试听，不经过这里）。
    缓存命中（指纹匹配）时不加载模型；否则临时加载 → 生成 → 立即释放。
    """
    voice_value = voice_value or VOXCPM_DEFAULT_VOICE_VALUE
    voice_dir = voice_dir or get_default_voxcpm_voice_dir()
    ctx = resolve_voxcpm_voice(voice_value, voice_dir)
    if ctx.get("kind") != "preset" or not ctx.get("key"):
        raise ValueError("试听仅支持内置预设音色，请从下拉框选择预设。")

    model_name = model_name or DEFAULT_VOXCPM_MODEL
    cfg_value = cfg_value if cfg_value is not None else DEFAULT_VOXCPM_CFG_VALUE
    inference_timesteps = (
        inference_timesteps if inference_timesteps is not None
        else DEFAULT_VOXCPM_INFERENCE_TIMESTEPS
    )
    preset_key = ctx["key"]

    if not regenerate and fingerprint_matches(
        preset_key, model_name, cfg_value, inference_timesteps, voice_dir
    ):
        cached = os.path.join(voice_dir, f"{preset_audio_stem(preset_key)}.wav")
        if os.path.exists(cached):
            logger.info(f"命中预设音色缓存：{cached}")
            return cached

    def _gen(text, seed):
        tmp_model = _load_voxcpm_model(model_name, device, optimize, cache=False)
        try:
            description = VOXCPM_VOICE_PRESETS[preset_key]["description"]
            gen_kwargs = dict(
                text=f"({description}){text}",
                cfg_value=float(cfg_value),
                inference_timesteps=int(inference_timesteps),
                normalize=True,
                retry_badcase=True,
            )
            if _voxcpm_accepts_seed(tmp_model):
                gen_kwargs["seed"] = seed
            wav = tmp_model.generate(**gen_kwargs)
            sample_rate = getattr(tmp_model.tts_model, "sample_rate", VOXCPM_SAMPLE_RATE)
            return wav, sample_rate
        finally:
            _release_voxcpm_model(tmp_model)

    ensure_preset_audio(
        preset_key, voice_dir, model_name, cfg_value, inference_timesteps,
        _gen, regenerate=regenerate,
    )
    return os.path.join(voice_dir, f"{preset_audio_stem(preset_key)}.wav")


# ═══════════════════════════════════════════════════════════════
# Provider
# ═══════════════════════════════════════════════════════════════
class VoxCPMTTSProvider(BaseTTSProvider):
    def __init__(self, config: GeneralConfig):
        # 默认值（WebUI 的 GeneralConfig(None) 字段都是 None，需在此补齐）
        config.output_format = config.output_format or DEFAULT_VOXCPM_OUTPUT_FORMAT
        self.model_name = config.model_name or DEFAULT_VOXCPM_MODEL

        self.device_raw = getattr(config, "voxcpm_device", None) or "auto"
        self.mode = getattr(config, "voxcpm_mode", None) or DEFAULT_VOXCPM_MODE
        self.voice_value = (
            getattr(config, "voxcpm_voice", None) or VOXCPM_DEFAULT_VOICE_VALUE
        )
        self.voice_dir = (
            getattr(config, "voxcpm_voice_dir", None) or get_default_voxcpm_voice_dir()
        )
        self.voice_description = (
            (getattr(config, "voxcpm_voice_description", None) or "").strip() or None
        )
        self.regenerate_voice = bool(getattr(config, "voxcpm_regenerate_voice", False))
        self.reference_audio = getattr(config, "voxcpm_reference_audio", None) or None
        self.reference_text = (
            (getattr(config, "voxcpm_reference_text", None) or "").strip() or None
        )
        self.auto_transcribe = bool(getattr(config, "voxcpm_auto_transcribe", False))
        self.denoise = bool(getattr(config, "voxcpm_denoise", False))
        self.normalize = True if getattr(config, "voxcpm_normalize", None) is None \
            else bool(config.voxcpm_normalize)
        self.cfg_value = float(
            getattr(config, "voxcpm_cfg_value", None) or DEFAULT_VOXCPM_CFG_VALUE
        )
        self.inference_timesteps = int(
            getattr(config, "voxcpm_inference_timesteps", None)
            or DEFAULT_VOXCPM_INFERENCE_TIMESTEPS
        )
        self.speed = normalize_voxcpm_speed(getattr(config, "voxcpm_speed", None))
        self.chunk_chars = int(
            getattr(config, "voxcpm_chunk_chars", None) or DEFAULT_VOXCPM_CHUNK_CHARS
        )
        optimize = getattr(config, "voxcpm_optimize", None)
        self.optimize = True if optimize is None else bool(optimize)
        seed = getattr(config, "voxcpm_seed", None)
        self.seed = int(seed) if seed is not None else None

        self.voice_ctx = {"kind": "none", "display": ""}
        super().__init__(config)

        logger.info("VoxCPMTTSProvider 初始化")
        logger.info(f"  - 模型: {self.model_name}")
        logger.info(f"  - 模式: {self.mode}（{VOXCPM_MODES.get(self.mode, '')}）")
        logger.info(f"  - 设备: {self.device_raw}")
        logger.info(f"  - 音色: {self.voice_value}（目录: {self.voice_dir}）")
        logger.info(f"  - 输出格式: {self.config.output_format}")
        logger.info(f"  - 分块字数: {self.chunk_chars}，语速: {self.speed}x")
        logger.info(
            f"  - CFG: {self.cfg_value}，步数: {self.inference_timesteps}，"
            f"normalize: {self.normalize}，denoise: {self.denoise}，"
            f"torch.compile: {self.optimize}"
        )
        if self.reference_audio:
            logger.info(f"  - 参考音频: {self.reference_audio}")
        if self.reference_text:
            logger.info("  - 参考转写: 手填")
        elif self.auto_transcribe:
            logger.info("  - 参考转写: 自动（SenseVoice）")

    def __str__(self) -> str:
        return (
            f"VoxCPMTTSProvider(model={self.model_name}, "
            f"device={self.device_raw}, mode={self.mode})"
        )

    # ───────────────────────── 校验 ─────────────────────────
    def validate_config(self):
        if self.config.output_format not in VOXCPM_OUTPUT_FORMATS:
            raise ValueError(
                f"VoxCPM: 不支持的输出格式 {self.config.output_format}，"
                f"可用：{VOXCPM_OUTPUT_FORMATS}"
            )

        if (self.config.output_format != "wav"
                and not getattr(self.config, "preview", False)
                and not _ffmpeg_available()):
            raise ValueError(
                f"VoxCPM: 输出格式 {self.config.output_format} 需要 ffmpeg，"
                "但当前环境未检测到。请安装（Ubuntu: sudo apt install -y ffmpeg）"
                "或把输出格式改为 wav。"
            )

        if self.mode not in VOXCPM_MODES:
            raise ValueError(
                f"VoxCPM: 不支持的合成模式 {self.mode}，可用：{list(VOXCPM_MODES.keys())}"
            )

        if _validate_device_syntax(self.device_raw) is None:
            raise ValueError(
                f"VoxCPM: 设备 {self.device_raw!r} 格式不合法"
                "（可选：auto、cpu、cuda、cuda:N、mps）"
            )

        try:
            self.voice_ctx = resolve_voxcpm_voice(self.voice_value, self.voice_dir)
        except ValueError as e:
            self.voice_ctx = {"kind": "none", "display": ""}
            raise ValueError(f"VoxCPM: {e}") from e

        if self.cfg_value < MIN_VOXCPM_CFG_VALUE or self.cfg_value > MAX_VOXCPM_CFG_VALUE:
            raise ValueError(
                f"VoxCPM: CFG 值需在 {MIN_VOXCPM_CFG_VALUE}~{MAX_VOXCPM_CFG_VALUE} 之间"
            )
        if (self.inference_timesteps < MIN_VOXCPM_INFERENCE_TIMESTEPS
                or self.inference_timesteps > MAX_VOXCPM_INFERENCE_TIMESTEPS):
            raise ValueError(
                f"VoxCPM: 推理步数需在 {MIN_VOXCPM_INFERENCE_TIMESTEPS}~"
                f"{MAX_VOXCPM_INFERENCE_TIMESTEPS} 之间"
            )
        if self.chunk_chars < MIN_VOXCPM_CHUNK_CHARS or self.chunk_chars > MAX_VOXCPM_CHUNK_CHARS:
            raise ValueError(
                f"VoxCPM: 分块字数需在 {MIN_VOXCPM_CHUNK_CHARS}~{MAX_VOXCPM_CHUNK_CHARS} 之间"
            )
        if self.speed < MIN_VOXCPM_SPEED or self.speed > MAX_VOXCPM_SPEED:
            logger.warning(
                f"语速 {self.speed} 超出范围 {MIN_VOXCPM_SPEED}~{MAX_VOXCPM_SPEED}，已按边界处理"
            )

        # 参考音频来源（用户上传 > 预设缓存 > 音色库文件）
        audio_src = self.reference_audio or self.voice_ctx.get("wav_path")
        if self.mode in (VOXCPM_MODE_CLONE, VOXCPM_MODE_HIFI):
            if self.reference_audio and not os.path.exists(self.reference_audio):
                raise ValueError(f"VoxCPM: 参考音频文件不存在：{self.reference_audio}")
            # 预设音色允许尚未生成缓存（首次使用时在 worker 内生成并缓存）
            has_preset_source = self.voice_ctx.get("kind") == "preset"
            if not self.reference_audio and not audio_src and not has_preset_source:
                raise ValueError(
                    "VoxCPM: clone / hifi 模式需要参考音频："
                    "请上传参考音频文件，或从音色下拉选择预设/音色库中的音频。"
                )
        if self.mode == VOXCPM_MODE_HIFI:
            has_transcript = (
                bool(self.reference_text)
                or self.auto_transcribe
                or (
                    not self.reference_audio
                    and self.voice_ctx.get("kind") == "preset"
                    and bool(self.voice_ctx.get("audition_text"))
                )
            )
            if not has_transcript:
                raise ValueError(
                    "VoxCPM Hi-Fi（极致克隆）模式需要参考音频的转写文本："
                    "请手填「参考音频转写文本」，或勾选「自动转写参考音频」，"
                    "或改用声音克隆（Clone）模式。"
                )

        if self.regenerate_voice and self.voice_ctx.get("kind") != "preset":
            logger.warning("「重新生成音色」仅对内置预设生效，已忽略。")

    # ───────────────────────── 辅助 ─────────────────────────
    def _resolve_text_prompt(self, chunk):
        """按模式组合最终文本：
        - design：声音描述（自定义优先，其次预设描述）前置；
        - clone：可选风格描述前置；
        - hifi：控制指令会被模型忽略，直接输出正文。
        """
        if self.mode == VOXCPM_MODE_HIFI:
            return chunk
        if self.mode == VOXCPM_MODE_DESIGN:
            desc = self.voice_description or self.voice_ctx.get("description") or ""
            desc = re.sub(r"[()（）]", "", desc).strip()
            return f"({desc}){chunk}" if desc else chunk
        # clone
        desc = re.sub(r"[()（）]", "", (self.voice_description or "")).strip()
        return f"({desc}){chunk}" if desc else chunk

    def _resolve_seed(self):
        """确定每块使用的 seed：
        - 用户显式指定 → 用之；
        - design 模式：预设固定 seed（无预设时用 42），保证分块间音色一致；
        - clone/hifi：参考音频已锁定音色，seed=None（交给模型）。
        """
        if self.seed is not None:
            return self.seed
        if self.mode == VOXCPM_MODE_DESIGN:
            return self.voice_ctx.get("seed") or 42
        return None

    def _ensure_reference_audio(self, model):
        """返回 (reference_wav_path, prompt_text_for_hifi)。按需生成预设缓存音色。"""
        audio_path = self.reference_audio
        if not audio_path and self.voice_ctx.get("kind") == "preset":
            preset_key = self.voice_ctx["key"]

            def _gen(text, seed):
                description = self.voice_ctx["description"]
                gen_kwargs = dict(
                    text=f"({description}){text}",
                    cfg_value=self.cfg_value,
                    inference_timesteps=self.inference_timesteps,
                    normalize=True,
                    retry_badcase=DEFAULT_VOXCPM_RETRY_BADCASE,
                )
                if _voxcpm_accepts_seed(model):
                    gen_kwargs["seed"] = seed
                wav = model.generate(**gen_kwargs)
                sample_rate = getattr(model.tts_model, "sample_rate", VOXCPM_SAMPLE_RATE)
                return wav, sample_rate

            audio_path = ensure_preset_audio(
                preset_key, self.voice_dir, self.model_name,
                self.cfg_value, self.inference_timesteps,
                _gen, regenerate=self.regenerate_voice,
            )
        elif not audio_path and self.voice_ctx.get("kind") == "file":
            audio_path = self.voice_ctx["wav_path"]

        prompt_text = None
        if self.mode == VOXCPM_MODE_HIFI and audio_path:
            prompt_text = self.reference_text
            if not prompt_text and not self.reference_audio \
                    and self.voice_ctx.get("kind") == "preset":
                prompt_text = self.voice_ctx.get("audition_text")
            if not prompt_text and self.auto_transcribe:
                prompt_text = transcribe_audio(audio_path)
        return audio_path, prompt_text

    def _adjust_speed_with_ffmpeg(self, wav, sample_rate, speed):
        """ffmpeg atempo 变速（0.5~2.0 单段即可覆盖本引擎范围），保持音调。"""
        import soundfile as sf

        if speed < 0.5 or speed > 2.0:
            logger.warning(f"atempo 超出单段范围，按边界处理：{speed}")
            speed = min(max(speed, 0.5), 2.0)
        filter_str = f"atempo={speed:.6f}"

        wav_buffer = io.BytesIO()
        sf.write(wav_buffer, wav, samplerate=sample_rate, format="wav")
        wav_buffer.seek(0)
        try:
            proc = subprocess.Popen(
                [FFMPEG_PATH, "-y", "-i", "pipe:0",
                 "-filter:a", filter_str,
                 "-f", "wav", "pipe:1"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            out, err = proc.communicate(input=wav_buffer.read(), timeout=60)
            if proc.returncode != 0:
                logger.error(f"ffmpeg atempo 失败: {err.decode(errors='replace')}")
                return wav
            adjusted, _ = sf.read(io.BytesIO(out))
            return adjusted
        except FileNotFoundError:
            logger.warning("未找到 ffmpeg，跳过语速调整（按原始语速输出）")
            return wav
        except Exception as e:
            logger.error(f"语速调整异常: {e}")
            return wav

    def _check_chunk_duration(self, chunk, wav, sample_rate):
        """输出时长合理性校验（约 4.5 字/秒），异常仅告警不中断。"""
        try:
            duration = len(wav) / float(sample_rate)
            expected = len(chunk) / CJK_CHARS_PER_SECOND
            ratio = duration / max(expected, 1e-6)
            if ratio < DURATION_RATIO_WARN_LOW or ratio > DURATION_RATIO_WARN_HIGH:
                logger.warning(
                    f"分块时长异常：文本 {len(chunk)} 字，期望 ≈{expected:.1f}s，"
                    f"实际 {duration:.1f}s（比率 {ratio:.2f}）。可能生成失败或语速漂移。"
                )
        except Exception as e:
            logger.warning(f"时长校验失败（忽略）：{e}")

    @staticmethod
    def _merge_tail_chunk(chunks, min_keep=VOXCPM_TAIL_MERGE_MIN_CHARS):
        """把尾部过短的小块并入前一块，避免生成"气声"般的超短音频。"""
        while len(chunks) > 1 and len(chunks[-1]) < min_keep:
            tail = chunks.pop()
            chunks[-1] = chunks[-1] + tail
        return chunks

    # ───────────────────────── 主流程 ─────────────────────────
    def text_to_speech(self, text: str, output_file: str, audio_tags: AudioTags):
        logger.info(
            f"VoxCPM TTS 开始处理 | 模型: {self.model_name} | 模式: {self.mode} | "
            f"文本长度: {len(text)}"
        )
        model = _load_voxcpm_model(self.model_name, self.device_raw, self.optimize, cache=True)
        sample_rate = getattr(model.tts_model, "sample_rate", VOXCPM_SAMPLE_RATE)

        reference_audio, prompt_text = self._ensure_reference_audio(model)
        if reference_audio:
            logger.info(f"参考音频：{reference_audio}")
        if prompt_text:
            logger.info(f"Hi-Fi 转写文本：{prompt_text}")

        text_chunks = split_text(text, self.chunk_chars, self.config.language or "zh-CN")
        if not text_chunks:
            logger.warning("空文本，跳过合成")
            return
        text_chunks = self._merge_tail_chunk(text_chunks)
        seed = self._resolve_seed()
        logger.info(
            f"分块数量：{len(text_chunks)}（每块最多 {self.chunk_chars} 字，seed={seed}）"
        )

        audio_segments = []
        chunk_ids = []
        for i, chunk in enumerate(text_chunks, 1):
            chunk_id = f"chapter-{audio_tags.idx}_{audio_tags.title}_chunk_{i}_of_{len(text_chunks)}"
            logger.info(f"处理 {chunk_id}, 长度={len(chunk)}")
            try:
                final_text = self._resolve_text_prompt(chunk)
                gen_kwargs = dict(
                    text=final_text,
                    cfg_value=self.cfg_value,
                    inference_timesteps=self.inference_timesteps,
                    normalize=self.normalize,
                    denoise=self.denoise,
                    retry_badcase=DEFAULT_VOXCPM_RETRY_BADCASE,
                )
                if _voxcpm_accepts_seed(model):
                    gen_kwargs["seed"] = seed
                if reference_audio:
                    gen_kwargs["reference_wav_path"] = reference_audio
                if self.mode == VOXCPM_MODE_HIFI:
                    if not reference_audio or not prompt_text:
                        raise ValueError(
                            "Hi-Fi 模式缺少参考音频或转写文本（前置校验应已兜住）"
                        )
                    gen_kwargs["prompt_wav_path"] = reference_audio
                    gen_kwargs["prompt_text"] = prompt_text
                wav = model.generate(**gen_kwargs)

                # VoxCPM.generate 返回 CPU float32 numpy；防御性兼容 torch.Tensor
                if hasattr(wav, "cpu") and hasattr(wav, "squeeze"):
                    wav = wav.squeeze(0).cpu().numpy()

                # 时长合理性校验（在变速前检查，反映模型原生输出质量）
                self._check_chunk_duration(chunk, wav, sample_rate)

                if self.speed and self.speed != 1.0:
                    wav = self._adjust_speed_with_ffmpeg(wav, sample_rate, self.speed)
                    logger.debug(f"语速调整为 {self.speed}x，新长度 = {len(wav)} 采样")

                import soundfile as sf
                wav_buffer = io.BytesIO()
                sf.write(wav_buffer, wav, samplerate=sample_rate, format="WAV")
                wav_buffer.seek(0)
                audio_content = wav_buffer.read()
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

        # 多分片/压缩格式必须用 pydub 合并，否则直接拼接会丢音频
        use_pydub_merge = should_use_pydub_merge(
            len(audio_segments), self.config.output_format, self.config.use_pydub_merge
        )
        if use_pydub_merge and not self.config.use_pydub_merge and not _ffmpeg_available():
            logger.warning(
                "未检测到 ffmpeg，无法用 pydub 合并；直接拼接多分片可能丢失音频，"
                "建议安装 ffmpeg（Ubuntu: sudo apt install -y ffmpeg）"
            )
            use_pydub_merge = False

        merge_audio_segments(
            audio_segments, output_file, self.config.output_format,
            chunk_ids, use_pydub_merge,
        )
        set_audio_tags(output_file, audio_tags)
        logger.info(f"VoxCPM TTS 完成 | 输出文件: {output_file}")

    def get_break_string(self):
        return "   "

    def get_output_file_extension(self):
        return self.config.output_format

    def estimate_cost(self, total_chars):
        return 0.0
