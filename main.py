import sys
import os
import shutil

from audiobook_generator.utils.project_runtime import bootstrap_project_python

if __name__ == '__main__':
    bootstrap_project_python(os.path.dirname(os.path.abspath(__file__)), 'cli')

import argparse
from pathlib import Path

from audiobook_generator.config.general_config import GeneralConfig
from audiobook_generator.core.audiobook_generator import AudiobookGenerator
from audiobook_generator.tts_providers.base_tts_provider import (
    get_supported_tts_providers,
)
from audiobook_generator.utils.log_handler import setup_logging, generate_unique_log_path
from audiobook_generator.tts_providers.chatterbox_tts_provider import (
    DEFAULT_CHATTERBOX_SPEED,
    MAX_CHATTERBOX_SPEED,
    MIN_CHATTERBOX_SPEED,
    get_chatterbox_supported_devices,
)
from audiobook_generator.tts_providers.voxcpm_tts_provider import (
    DEFAULT_VOXCPM_CFG_VALUE,
    DEFAULT_VOXCPM_CHUNK_CHARS,
    DEFAULT_VOXCPM_INFERENCE_TIMESTEPS,
    DEFAULT_VOXCPM_MODE,
    DEFAULT_VOXCPM_SPEED,
    MAX_VOXCPM_SPEED,
    MIN_VOXCPM_SPEED,
    VOXCPM_MODES,
)
from audiobook_generator.utils.voxcpm_voices import (
    VOXCPM_DEFAULT_VOICE_VALUE,
    get_preset_keys,
)
from pydub import AudioSegment


def _resolve_ffmpeg_binary(name):
    """按 环境变量 -> PATH -> 常见安装路径 的顺序解析 ffmpeg/ffprobe。

    - 环境变量 FFMPEG_PATH / FFPROBE_PATH 优先级最高
    - 其次使用 PATH 中的可执行文件（macOS/Linux 通用）
    - 最后回退到常见安装路径，找不到时返回 None，交由 pydub 自行解析
    """
    env_value = os.environ.get(f"{name.upper()}_PATH")
    if env_value:
        return env_value
    found = shutil.which(name)
    if found:
        return found
    for path in (f"/usr/bin/{name}", f"/usr/local/bin/{name}", f"/opt/homebrew/bin/{name}"):
        if os.path.exists(path):
            return path
    return None


# 自动探测 ffmpeg/ffprobe（不再硬编码 macOS 路径，兼容 Linux 服务器）
_ffmpeg_path = _resolve_ffmpeg_binary("ffmpeg")
_ffprobe_path = _resolve_ffmpeg_binary("ffprobe")
if _ffmpeg_path:
    AudioSegment.converter = _ffmpeg_path
if _ffprobe_path:
    AudioSegment.ffprobe = _ffprobe_path

def handle_args():
    parser = argparse.ArgumentParser(description="Convert text book to audiobook")
    parser.add_argument("input_file", help="Path to the book file (supports EPUB, DOC, DOCX)")
    parser.add_argument("output_folder", help="Path to the output folder")
    parser.add_argument(
        "--tts",
        choices=get_supported_tts_providers(),
        default=get_supported_tts_providers()[0],
        help="Choose TTS provider (default: qwen). qwen: Qwen TTS API, openai: MiMo TTS API, edge: Edge TTS, minimax: MiniMax TTS API, piper: Piper TTS, chatterbox: Chatterbox TTS, voxcpm: VoxCPM2 本地模型.",
    )
    parser.add_argument(
        "--log",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="Log level (default: INFO), can be DEBUG, INFO, WARNING, ERROR, CRITICAL",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Enable preview mode. In preview mode, the script will not convert the text to speech. Instead, it will print the chapter index, titles, and character counts.",
    )
    parser.add_argument(
        "--no_prompt",
        action="store_true",
        help="Don't ask the user if they wish to continue after estimating the cloud cost for TTS. Useful for scripting.",
    )
    parser.add_argument(
        "--language",
        default="en-US",
        help="Language for the text-to-speech service (default: en-US). For Qwen TTS (--tts=qwen), supported languages include Auto, English, Chinese, Japanese, Korean, etc. For OpenAI TTS (--tts=openai), their API detects the language automatically. But setting this will also help on splitting the text into chunks with different strategies in this tool, especially for Chinese characters. For Chinese books, use zh-CN, zh-TW, or zh-HK.",
    )
    parser.add_argument(
        "--newline_mode",
        choices=["single", "double", "none"],
        default="double",
        help="Choose the mode of detecting new paragraphs: 'single', 'double', or 'none'. 'single' means a single newline character, while 'double' means two consecutive newline characters. 'none' means all newline characters will be replace with blank so paragraphs will not be detected. (default: double, works for most ebooks but will detect less paragraphs for some ebooks)",
    )
    parser.add_argument(
        "--title_mode",
        choices=["auto", "tag_text", "first_few"],
        default="auto",
        help="Choose the parse mode for chapter title, 'tag_text' search 'title','h1','h2','h3' tag for title, 'first_few' set first 60 characters as title, 'auto' auto apply the best mode for current chapter.",
    )
    parser.add_argument(
        "--chapter_start",
        default=1,
        type=int,
        help="Chapter start index (default: 1, starting from 1)",
    )
    parser.add_argument(
        "--chapter_end",
        default=-1,
        type=int,
        help="Chapter end index (default: -1, meaning to the last chapter)",
    )
    parser.add_argument(
        "--output_text",
        action="store_true",
        help="Enable Output Text. This will export a plain text file for each chapter specified and write the files to the output folder specified.",
    )
    parser.add_argument(
        "--remove_endnotes",
        action="store_true",
        help="This will remove endnote numbers from the end or middle of sentences. This is useful for academic books.",
    )

    parser.add_argument(
        "--remove_reference_numbers",
        action="store_true",
        help="This will remove reference numbers from the end or middle of sentences (e.g [3] or [12.1]). Also useful for academic books."
    )

    parser.add_argument(
        "--search_and_replace_file",
        default="",
        help="""Path to a file that contains 1 regex replace per line, to help with fixing pronunciations, etc. The format is:
        <search>==<replace>
        Note that you may have to specify word boundaries, to avoid replacing parts of words.
        """,
    )

    parser.add_argument(
        "--worker_count",
        type=int,
        default=1,
        help="Specifies the number of parallel workers to use for audiobook generation. "
        "Increasing this value can significantly speed up the process by processing multiple chapters simultaneously. "
        "Note: Chapters may not be processed in sequential order, but this will not affect the final audiobook.",
    )

    parser.add_argument(
        "--use_pydub_merge",
        action="store_true",
        help="Use pydub to merge audio segments of one chapter into single file instead of direct write. "
        "Currently only supported for OpenAI and Qwen TTS. "
        "Direct write is faster but might skip audio segments if formats differ. "
        "Pydub merge is slower but more reliable for different audio formats. It requires ffmpeg to be installed first. "
        "You can use this option to avoid the issue of skipping audio segments in some cases. "
        "However, it's recommended to use direct write for most cases as it's faster. "
        "Only use this option if you encounter issues with direct write.",
    )

    parser.add_argument(
        "--role_script",
        default=None,
        help="Path to a RoleScriptV1/V2 JSON file. Enables multi-role segmented TTS for MiMo/MiniMax.",
    )
    parser.add_argument('--voice_profile', default=None,
                        help='已试听确认的可迁移声音卡 ZIP；按当前提供商、模型和服务地址匹配绑定。')
    parser.add_argument(
        "--allow_role_text_override",
        action="store_true",
        help="Role mode: skip chapter text coverage checks (use only after manual proofing).",
    )
    parser.add_argument(
        "--allow_role_title_mismatch",
        action="store_true",
        help="Role mode: allow script chapter titles to differ from parser titles.",
    )
    parser.add_argument(
        "--allow_role_fallback",
        action="store_true",
        help="Role mode: fallback missing roles to narrator, then global defaults.",
    )
    parser.add_argument(
        "--role_quality_enabled", action="store_true",
        help="角色模式逐段评估语速、清晰度和音频完整性；MiMo 失败段最多自动重试一次。",
    )
    parser.add_argument(
        "--role_quality_max_rate", type=float, default=4.3,
        help="角色音频中文语速上限（汉字/秒，默认 4.3）。",
    )
    parser.add_argument("--audio_core_enabled", action="store_true", help="启用 MiMo 统一分块、拼接和质量报告（普通／角色模式）")
    parser.add_argument("--audio_core_repair", action="store_true", help="统一核心：启用受限局部修复")
    parser.add_argument("--audio_core_max_english_wpm", type=float, default=300.0, help="英文语速筛查上限（词/分钟；未标定的保守规则）")
    parser.add_argument("--audio_core_chunk_chars", type=int, default=300, help="统一核心分块目标，20～1500 字符")
    parser.add_argument("--audio_core_max_requests", type=int, default=1000, help="本次运行最多实际合成请求次数")
    parser.add_argument("--audio_core_max_repairs", type=int, default=24, help="本次运行最多追加修复请求次数")
    parser.add_argument("--audio_core_max_repair_characters", type=int, default=None, help="本次运行最多追加修复正文字符数（默认不设上限，0 禁用重合成）")
    parser.add_argument("--audio_core_max_seconds", type=float, default=3600, help="统一核心运行时限（秒）")
    parser.add_argument("--audio_core_no_asr", action="store_true", help="关闭内容转写检查，报告标记未完整评测")
    parser.add_argument("--audio_core_no_speaker", action="store_true", help="关闭声纹检查，报告标记未完整评测")
    parser.add_argument("--audio_core_vad", action="store_true", help="使用本地 Silero VAD 辅助语速分析")
    parser.add_argument("--audio_core_asr_model", help="本地 SenseVoice 模型目录，不自动下载")
    parser.add_argument("--audio_core_speaker_model", help="本地 ECAPA 模型目录，不自动下载")
    parser.add_argument("--audio_core_boundary_model", help="已训练的边界特征分类器 JSON")
    parser.add_argument("--audio_core_role_references", help="人工核验且绑定声音版本的固定跨章参考文件")
    parser.add_argument('--audio_core_tail_repeat_mode', choices=['off','review','auto'], default='review',
                        help='尾部重复：off关闭，review导出候选，auto在启用修复时尝试严格匹配的安全裁切')
    parser.add_argument("--audio_core_casting", help="已审查的 MiMo 角色选角 JSON")
    parser.add_argument("--audio_core_reading_dictionary", help="显式朗读词典 JSON：原文→实际读法，不支持 SSML")
    parser.add_argument("--audio_core_transition_boundaries", nargs="+", default=[],
                        help="指定接缝编号（左块|右块），使用人工确认的 50%→100%／100 毫秒起读处理")
    parser.add_argument("--audio_core_transition_source_group",
                        help="起读处理对应报告的 source_group_id；正文不符时在合成前报错")

    parser.add_argument(
        "--voice_name",
        help="Various TTS providers has different voice names, look up for your provider settings.",
    )

    parser.add_argument(
        "--output_format",
        help="Output format for the text-to-speech service. Supported format depends on selected TTS provider",
    )

    parser.add_argument(
        "--model_name",
        help="Various TTS providers has different neural model names",
    )

    openai_tts_group = parser.add_argument_group(title="openai specific")
    openai_tts_group.add_argument(
        "--speed",
        default=1.0,
        type=float,
        help="The speed of the generated audio. Select a value from 0.25 to 4.0. 1.0 is the default.",
    )

    openai_tts_group.add_argument(
        "--instructions",
        help="Instructions for the TTS model. Only supported for 'gpt-4o-mini-tts' model.",
    )

    openai_tts_group.add_argument(
        "--stream",
        action="store_true",
        help="Enable streaming mode for MiMo TTS. Uses PCM16 stream for real-time audio chunk collection.",
    )

    edge_tts_group = parser.add_argument_group(title="edge specific")
    edge_tts_group.add_argument(
        "--voice_rate",
        help="""
            Speaking rate of the text. Valid relative values range from -50%%(--xxx='-50%%') to +100%%. 
            For negative value use format --arg=value,
        """,
    )

    edge_tts_group.add_argument(
        "--voice_volume",
        help="""
            Volume level of the speaking voice. Valid relative values floor to -100%%.
            For negative value use format --arg=value,
        """,
    )

    edge_tts_group.add_argument(
        "--voice_pitch",
        help="""
            Baseline pitch for the text.Valid relative values like -80Hz,+50Hz, pitch changes should be within 0.5 to 1.5 times the original audio.
            For negative value use format --arg=value,
        """,
    )

    edge_tts_group.add_argument(
        "--proxy",
        help="Proxy server for the TTS provider. Format: http://[username:password@]proxy.server:port",
    )

    qwen_edge_tts_group = parser.add_argument_group(title="qwen/edge specific")
    qwen_edge_tts_group.add_argument(
        "--break_duration",
        default="1250",
        help="Break duration in milliseconds for the different paragraphs or sections (default: 1250, means 1.25 s). Valid values range from 0 to 5000 milliseconds for Qwen TTS.",
    )

    piper_tts_group = parser.add_argument_group(title="piper specific")
    piper_tts_group.add_argument(
        "--piper_path",
        default="piper",
        help="Path to the Piper TTS executable",
    )
    piper_tts_group.add_argument(
        "--piper_docker_image",
        default="lscr.io/linuxserver/piper:latest",
        help="Piper Docker image name (if using Docker)",
    )
    piper_tts_group.add_argument(
        "--piper_speaker",
        default=0,
        help="Piper speaker id, used for multi-speaker models",
    )
    piper_tts_group.add_argument(
        "--piper_sentence_silence",
        default=0.2,
        help="Seconds of silence after each sentence",
    )
    piper_tts_group.add_argument(
        "--piper_length_scale",
        default=1.0,
        help="Phoneme length, a.k.a. speaking rate",
    )

    chatterbox_tts_group = parser.add_argument_group(title="chatterbox specific")
    chatterbox_tts_group.add_argument(
        "--chatterbox_device",
        default="auto",
        choices=get_chatterbox_supported_devices(),
        help="设备选择：auto（自动选择）、cpu、cuda（需NVIDIA GPU）、mps（需Apple Silicon）",
    )
    chatterbox_tts_group.add_argument(
        "--chatterbox_reference_audio",
        default=None,
        help="参考音频路径，用于语音克隆（可选）",
    )
    chatterbox_tts_group.add_argument(
        "--chatterbox_exaggeration",
        type=float,
        default=0.5,
        help="语气夸张程度（0.0-1.0），值越大情感越丰富",
    )
    chatterbox_tts_group.add_argument(
        "--chatterbox_cfg_weight",
        type=float,
        default=0.5,
        help="CFG 引导权重（0.0-1.0），值越大发音越清晰",
    )
    chatterbox_tts_group.add_argument(
        "--chatterbox_speed",
        type=float,
        default=DEFAULT_CHATTERBOX_SPEED,
        help=f"语速（{MIN_CHATTERBOX_SPEED}-{MAX_CHATTERBOX_SPEED}），1.0 为标准语速"
             "（内部按 0.7 倍处理），<1.0 更慢，>1.0 更快",
    )

    voxcpm_tts_group = parser.add_argument_group(title="voxcpm specific")
    voxcpm_tts_group.add_argument(
        "--voxcpm_device",
        default="auto",
        help="设备选择：auto（自动）、cpu、cuda、cuda:N（指定 GPU 序号）。"
             "多卡/与其它项目共用 GPU 时，推荐再用环境变量 CUDA_VISIBLE_DEVICES 隔离",
    )
    voxcpm_tts_group.add_argument(
        "--voxcpm_mode",
        choices=list(VOXCPM_MODES.keys()),
        default=DEFAULT_VOXCPM_MODE,
        help="合成模式：design 描述生成音色（默认）、clone 声音克隆、hifi 极致克隆（参考音频+转写文本）",
    )
    voxcpm_tts_group.add_argument(
        "--voxcpm_voice",
        default=VOXCPM_DEFAULT_VOICE_VALUE,
        help=f"音色：内置预设（preset:沉稳男声 或直接写 {get_preset_keys()}）、"
             "音色库文件（file:xxx.wav）、或 wav/mp3 文件路径",
    )
    voxcpm_tts_group.add_argument(
        "--voxcpm_voice_description",
        default=None,
        help="声音描述（design 模式，自定义时覆盖预设描述，例如：成熟稳重的男声，中低音）",
    )
    voxcpm_tts_group.add_argument(
        "--voxcpm_voice_dir",
        default=None,
        help="音色库目录（默认 <仓库根目录>/voices，预设参考音频与自定义音频都在这里）",
    )
    voxcpm_tts_group.add_argument(
        "--voxcpm_regenerate_voice",
        action="store_true",
        help="重新生成预设音色的参考音频（忽略已有缓存）",
    )
    voxcpm_tts_group.add_argument(
        "--voxcpm_reference_audio",
        default=None,
        help="参考音频路径（clone / hifi 模式；不填时使用音色下拉里的预设/音色库文件）",
    )
    voxcpm_tts_group.add_argument(
        "--voxcpm_reference_text",
        default=None,
        help="参考音频的转写文本（hifi 模式，手填优先；预设音色会自动带上试听文本）",
    )
    voxcpm_tts_group.add_argument(
        "--voxcpm_auto_transcribe",
        action="store_true",
        help="hifi 模式未手填转写时，用 SenseVoice 自动识别参考音频",
    )
    voxcpm_tts_group.add_argument(
        "--voxcpm_denoise",
        action="store_true",
        help="对参考音频降噪（需额外下载 ZipEnhancer，会改变音色，默认关闭）",
    )
    voxcpm_tts_group.add_argument(
        "--voxcpm_normalize",
        default=True,
        action=argparse.BooleanOptionalAction,
        help="文本规范化：展开数字/日期等（默认开启）",
    )
    voxcpm_tts_group.add_argument(
        "--voxcpm_cfg_value",
        type=float,
        default=DEFAULT_VOXCPM_CFG_VALUE,
        help=f"CFG 引导权重（默认 {DEFAULT_VOXCPM_CFG_VALUE}），越高越贴合描述/参考音色",
    )
    voxcpm_tts_group.add_argument(
        "--voxcpm_inference_timesteps",
        type=int,
        default=DEFAULT_VOXCPM_INFERENCE_TIMESTEPS,
        help=f"推理步数（默认 {DEFAULT_VOXCPM_INFERENCE_TIMESTEPS}，越大越精细但越慢）",
    )
    voxcpm_tts_group.add_argument(
        "--voxcpm_speed",
        type=float,
        default=DEFAULT_VOXCPM_SPEED,
        help=f"语速（{MIN_VOXCPM_SPEED}-{MAX_VOXCPM_SPEED}），1.0 为原生语速",
    )
    voxcpm_tts_group.add_argument(
        "--voxcpm_chunk_chars",
        type=int,
        default=DEFAULT_VOXCPM_CHUNK_CHARS,
        help=f"长文本按句分块字数（默认 {DEFAULT_VOXCPM_CHUNK_CHARS}，VoxCPM 长文本会语速漂移/OOM）",
    )
    voxcpm_tts_group.add_argument(
        "--voxcpm_optimize",
        default=True,
        action=argparse.BooleanOptionalAction,
        help="启用 torch.compile（CUDA Graphs）。多线程并发推理会冲突时改为 --no-voxcpm_optimize",
    )
    voxcpm_tts_group.add_argument(
        "--voxcpm_seed",
        type=int,
        default=None,
        help="固定 seed（design 模式未指定时使用预设固定 seed，保证音色可复现）",
    )

    args = parser.parse_args()
    return GeneralConfig(args)


def main(config=None, log_file=None):
    if not config: # config passed from UI, or uses args if CLI
        config = handle_args()

    if log_file:
        # If log_file is provided (e.g., from UI), use it directly as a Path object.
        # The UI passes an absolute path string.
        effective_log_file = Path(log_file)
    else:
        # Otherwise (e.g., CLI usage without a specific log file from UI),
        # generate a unique log file name.
        effective_log_file = generate_unique_log_path("EtA")
    
    # Ensure config.log_file is updated, as it's used by AudiobookGenerator for worker processes.
    config.log_file = effective_log_file

    setup_logging(config.log, str(effective_log_file))

    return AudiobookGenerator(config).run()


if __name__ == "__main__":
    main()
