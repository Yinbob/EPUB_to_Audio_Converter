"""VoxCPM 部署冒烟/基准自检脚本（请在 Ubuntu + RTX 4090 目标机上运行）。

用途（对应部署验收门）：
1. 环境检查：Python 3.10~3.12、torch CUDA 可用、gradio 5.50.0、voxcpm 已安装、ffmpeg 可用；
2. 端到端：走真实 provider（含预设音色参考音频生成 + 分块 + 合并），产出有效音频文件；
3. 性能门：RTF（合成秒/音频秒）≤ 0.5、推理显存峰值 ≤ 12GB（默认 timesteps=10）；
4. 三模式验证：分别用 --mode design / clone / hifi 各跑一次（README「GPU 多项目共存注意事项」）。

用法（在仓库根目录，conda 3.11 环境）：
  ./venv_chatterbox/bin/python3 voxcpm_smoke_test.py --device cuda
  ./venv_chatterbox/bin/python3 voxcpm_smoke_test.py --device cuda --mode hifi \
      --reference /path/to/voice.wav --reference_text "参考音频说的话"

返回码 0 = 通过；1 = 环境/生成失败；2 = 性能门未达标。
"""

import argparse
import logging
import os
import platform
import sys
import tempfile
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("voxcpm_smoke")

# 国内网络默认关闭 HuggingFace Xet/CAS 加速：它会绕过镜像直连官方后端（401）
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

# 验收门（RTX 4090 + timesteps=10 + torch.compile 官方基准 RTF≈0.3 / 显存≈8GB）
RTF_GATE = 0.5
VRAM_GATE_GB = 12.0


def _require(cond, msg):
    if not cond:
        logger.error(f"✗ {msg}")
        sys.exit(1)


def check_environment(device):
    logger.info("=== 1/3 环境检查 ===")
    py = platform.python_version()
    logger.info(f"Python {py}")
    _require(
        (3, 10) <= tuple(int(x) for x in py.split(".")[:2]) <= (3, 12),
        f"Python 必须为 3.10~3.12（当前 {py}），否则 voxcpm 无法安装/运行",
    )

    try:
        import torch
    except ImportError:
        torch = None
    _require(torch is not None, "torch 未安装，请按 README「VoxCPM TTS」安装")
    logger.info(f"torch {torch.__version__}")
    if device != "cpu":
        _require(torch.cuda.is_available(), "CUDA 不可用（nvidia-smi 是否正常？是否设置了 CUDA_VISIBLE_DEVICES？）")
        logger.info(f"CUDA {torch.version.cuda} | 设备 {torch.cuda.get_device_name(0)}")

    try:
        import gradio
    except ImportError:
        gradio = None
    _require(gradio is not None and gradio.__version__.startswith("5."),
             f"gradio 必须为 5.x（当前 {getattr(gradio, '__version__', '未安装')}），"
             "voxcpm 会装 gradio 6，需固定回 5.50.0")
    logger.info(f"gradio {gradio.__version__}")

    try:
        from voxcpm import VoxCPM  # noqa: F401
        logger.info("voxcpm 已安装")
    except ImportError as e:
        _require(False, f"voxcpm 未安装：{e}")

    import shutil
    _require(shutil.which("ffmpeg") is not None, "ffmpeg 未安装（sudo apt install -y ffmpeg）")
    logger.info(f"ffmpeg {shutil.which('ffmpeg')}")
    hf_endpoint = os.environ.get("HF_ENDPOINT") or "（未设置，走官方 huggingface.co）"
    logger.info(f"HF_ENDPOINT={hf_endpoint}（国内网络请使用 https://hf-mirror.com）")
    logger.info(f"HF_HUB_DISABLE_XET={os.environ.get('HF_HUB_DISABLE_XET', '0')}")


def build_provider(args):
    from audiobook_generator.config.general_config import GeneralConfig
    from audiobook_generator.tts_providers.voxcpm_tts_provider import VoxCPMTTSProvider

    cfg = GeneralConfig(None)
    cfg.model_name = args.model
    cfg.output_format = args.output_format
    cfg.language = "zh-CN"
    cfg.voxcpm_device = args.device
    cfg.voxcpm_mode = args.mode
    cfg.voxcpm_voice = args.voice
    cfg.voxcpm_voice_description = args.voice_description
    cfg.voxcpm_regenerate_voice = args.regenerate_voice
    cfg.voxcpm_reference_audio = args.reference
    cfg.voxcpm_reference_text = args.reference_text
    cfg.voxcpm_auto_transcribe = args.auto_transcribe
    cfg.voxcpm_denoise = False
    cfg.voxcpm_normalize = True
    cfg.voxcpm_cfg_value = args.cfg_value
    cfg.voxcpm_inference_timesteps = args.timesteps
    cfg.voxcpm_speed = args.speed
    cfg.voxcpm_chunk_chars = args.chunk_chars
    cfg.voxcpm_optimize = args.optimize
    return VoxCPMTTSProvider(cfg)


def run_smoke(args):
    from audiobook_generator.core.audio_tags import AudioTags
    from pydub import AudioSegment
    import torch

    text = args.text
    logger.info(f"=== 2/3 生成（{args.mode} 模式，文本 {len(text)} 字）===")
    provider = build_provider(args)
    out_dir = args.output_dir or tempfile.mkdtemp(prefix="voxcpm_smoke_")
    os.makedirs(out_dir, exist_ok=True)
    output = os.path.join(out_dir, f"smoke_{args.mode}.{args.output_format or 'mp3'}")

    # 预热（model 加载含 torch.compile/warm-up，不计入 RTF）
    def _chapter(suffix, text):
        provider.text_to_speech(
            text,
            os.path.join(out_dir, f"warmup_{suffix}.{args.output_format or 'mp3'}"),
            AudioTags(title="预热", author="smoke", book_title="smoke", idx=1),
        )
    warmup_text = "预热。这是一段用于统计带宽的短文本。"
    if args.mode == "hifi":
        if args.reference and (args.reference_text or args.auto_transcribe):
            _chapter("a", warmup_text)
        else:
            logger.info(
                "hifi 模式未提供参考音频/转写，跳过预热；首次 RTF 将包含 torch.compile 编译开销"
            )
    else:
        _chapter("a", warmup_text)
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
        torch.cuda.synchronize()

    start = time.perf_counter()
    provider.text_to_speech(
        text,
        output,
        AudioTags(title="冒烟测试", author="smoke", book_title="smoke", idx=1),
    )
    if torch.cuda.is_available():
        torch.cuda.synchronize()
    elapsed = time.perf_counter() - start

    segment = AudioSegment.from_file(output)
    audio_seconds = segment.duration_seconds
    rtf = elapsed / max(audio_seconds, 1e-6)
    peak_gb = (torch.cuda.max_memory_allocated() / 1024 ** 3) if torch.cuda.is_available() else 0.0

    logger.info(f"=== 3/3 结果 ===")
    logger.info(f"输出文件：{output}（音频时长 {audio_seconds:.1f}s / {len(segment)} ms）")
    logger.info(f"合成耗时：{elapsed:.1f}s | RTF={rtf:.3f}（门限 ≤{RTF_GATE}）")
    logger.info(f"推理显存峰值：{peak_gb:.2f}GB（门限 ≤{VRAM_GATE_GB}GB）")

    _require(os.path.exists(output) and os.path.getsize(output) > 0, "输出文件缺失或为空")
    if audio_seconds < 1.0:
        logger.warning("音频过短，请检查文本是否为空/生成是否异常")

    ok = rtf <= RTF_GATE and peak_gb <= VRAM_GATE_GB
    if not ok:
        logger.error(
            "性能门未达标：可尝试 ① --chunk_chars 200~300；② --timesteps 8；"
            "③ 确认机上有其他项目占用显存（用 CUDA_VISIBLE_DEVICES 隔离）；"
            "④ --no-optimize（稳定但更慢）"
        )
        sys.exit(2)
    logger.info("✅ 冒烟测试通过")


def main():
    parser = argparse.ArgumentParser(description="VoxCPM 部署冒烟/基准自检")
    parser.add_argument("--model", default="openbmb/VoxCPM2")
    parser.add_argument("--device", default="auto", help="auto / cpu / cuda / cuda:N")
    parser.add_argument("--mode", choices=["design", "clone", "hifi"], default="design")
    parser.add_argument("--voice", default=None, help="语音预设或音色库文件（默认沉稳男声）")
    parser.add_argument("--voice_description", default=None)
    parser.add_argument("--reference", default=None, help="clone/hifi 参考音频")
    parser.add_argument("--reference_text", default=None, help="hifi 转写文本")
    parser.add_argument("--auto_transcribe", action="store_true")
    parser.add_argument("--timesteps", type=int, default=10)
    parser.add_argument("--cfg_value", type=float, default=2.0)
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--chunk_chars", type=int, default=400)
    parser.add_argument("--output_format", default="mp3")
    parser.add_argument("--output_dir", default=None)
    parser.add_argument("--regenerate_voice", action="store_true")
    parser.add_argument("--no-optimize", dest="optimize", action="store_false")
    parser.set_defaults(optimize=True)
    parser.add_argument(
        "--text",
        default=("第五章的第五章。这是一段用于验收的中文有声书文本，" * 25
                 + "我们用它测量端到端合成速度与显存占用，请留意日志中的分块标记。"),
        help="验收文本（默认约 600 字中文）",
    )
    args = parser.parse_args()

    check_environment(args.device)
    run_smoke(args)


if __name__ == "__main__":
    main()
