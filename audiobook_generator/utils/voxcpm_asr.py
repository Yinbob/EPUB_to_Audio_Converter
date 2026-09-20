"""VoxCPM Hi-Fi（极致克隆）模式的可选自动转写（iic/SenseVoiceSmall）。

VoxCPM 官方 Demo 用 SenseVoice 自动识别参考音频的文本，配合
``prompt_wav_path + prompt_text + reference_wav_path`` 实现逐字对齐的
极致克隆。本模块做成懒加载：只有在 Hi-Fi 模式且未手填转写文本时才
下载/加载模型，并固定跑在 CPU 上（不给 GPU 添负担、避免与合成抢显存）。
"""

import logging
import os

logger = logging.getLogger(__name__)

DEFAULT_ASR_MODEL = "iic/SenseVoiceSmall"

_asr_model = None
_asr_device = None


def _get_or_load_asr_model(model_id: str = DEFAULT_ASR_MODEL, device: str = "cpu"):
    """懒加载 SenseVoice（进程内只加载一次）。"""
    global _asr_model, _asr_device
    if _asr_model is not None and _asr_device == device:
        return _asr_model
    try:
        from funasr import AutoModel
    except ImportError as e:
        raise ImportError(
            "自动转写需要 funasr（SenseVoice）。请安装：\n"
            "  ./venv_chatterbox/bin/pip install funasr\n"
            "或直接手填参考音频转写文本以使用 Hi-Fi 模式。"
        ) from e

    logger.info(f"正在加载 SenseVoice 转写模型：{model_id}（设备：{device}）")
    _asr_model = AutoModel(
        model=model_id,
        disable_update=True,
        log_level="INFO",
        device=device,
    )
    _asr_device = device
    logger.info("SenseVoice 转写模型加载完成")
    return _asr_model


def transcribe_audio(audio_path: str, model_id: str = DEFAULT_ASR_MODEL,
                     device: str = "cpu") -> str:
    """识别参考音频内容，返回纯文本转写（去掉 SenseVoice 的 tag/标点标记）。

    SenseVoice 输出形如 "<|zh|><|NEUTRAL|><|Speech|><|woitn|>你好世界"，
    官方 Demo 取 ``split("|>")[-1]`` 得到实际文本。
    """
    if not audio_path or not os.path.exists(audio_path):
        raise FileNotFoundError(f"参考音频不存在，无法自动转写：{audio_path}")

    model = _get_or_load_asr_model(model_id=model_id, device=device)
    logger.info(f"自动转写参考音频：{audio_path}")
    result = model.generate(
        input=audio_path,
        language="auto",
        use_itn=True,
    )
    try:
        text = str(result[0]["text"]).split("|>")[-1].strip()
    except (IndexError, KeyError, TypeError) as e:
        raise RuntimeError(f"SenseVoice 转写结果格式异常：{result!r}") from e
    if not text:
        raise RuntimeError("SenseVoice 未能识别出参考音频的文字内容，请手填转写文本。")
    logger.info(f"自动转写完成：{text}")
    return text
