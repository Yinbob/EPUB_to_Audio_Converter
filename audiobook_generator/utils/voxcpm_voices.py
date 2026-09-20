"""VoxCPM 内置音色库：描述预设 + 参考音频缓存。

VoxCPM2 模型本身**没有内置音色表**（config.json 不含 speaker embedding）：
不开参考音频时，每次调用都会生成一个新的随机音色，跨分块/跨章节会变声。
因此本项目约定「固定描述 + 固定 seed + 固定试听文本」生成一段 5~10 秒的
参考音频，缓存到音色库目录（默认仓库根目录下 `voices/`）复用，保证整本书
和多次运行音色一致。

本模块只负责音色目录、预设、指纹校验、文件锁这类纯 IO 逻辑；真正调用
VoxCPM 模型生成音频的是 `voxcpm_tts_provider`（避免循环依赖）。
生成文件默认不进 git（见 .gitignore），目录里保留 README 占位说明。
"""

import json
import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# 内置预设（6 个中文音色）
# description   → design 模式的固定声音描述（每块都会前置叠加）
# seed          → 固定生成 seed，保证同一预设的音色可复现
# audition_text → 首次使用时生成参考音频的固定试听文本（同时作为 Hi-Fi
#                 模式下的预设转写文本）
# ═══════════════════════════════════════════════════════════════
VOXCPM_VOICE_PRESETS = {
    "沉稳男声": {
        "description": "成熟沉稳的男声，中低音，语速适中，语调平缓，字字清晰，适合长篇朗读",
        "seed": 101,
        "audition_text": "你好，欢迎使用有声书工坊。愿你享受聆听的每一刻。",
    },
    "温柔女声": {
        "description": "温柔亲切的女声，音色柔美，语速舒缓，口齿清楚，适合睡前故事",
        "seed": 202,
        "audition_text": "你好，欢迎使用有声书工坊。愿你享受聆听的每一刻。",
    },
    "青年男声": {
        "description": "清亮有朝气的青年男声，略带磁性，语速轻快，富有活力",
        "seed": 303,
        "audition_text": "你好，欢迎使用有声书工坊。愿你享受聆听的每一刻。",
    },
    "知性女声": {
        "description": "知性大方的中年女声，发音标准，语气自信从容，适合知识类内容",
        "seed": 404,
        "audition_text": "你好，欢迎使用有声书工坊。愿你享受聆听的每一刻。",
    },
    "新闻播报": {
        "description": "标准新闻播音腔，字正腔圆，语速均匀，庄重清晰，富有权威感",
        "seed": 505,
        "audition_text": "这里是新闻播报，欢迎收听今日的有声书内容。",
    },
    "亲切老者": {
        "description": "亲切慈祥的老年男声，声音温暖沙哑，语速偏慢，像讲故事的长辈",
        "seed": 606,
        "audition_text": "孩子，坐好了，我慢慢给你讲这个故事。",
    },
}

# 预设值前缀（WebUI 下拉 value 与 CLI 参数通用）
VOXCPM_PRESET_PREFIX = "preset:"
VOXCPM_FILE_PREFIX = "file:"

# 默认音色：沉稳男声
VOXCPM_DEFAULT_VOICE_KEY = "沉稳男声"
VOXCPM_DEFAULT_VOICE_VALUE = f"{VOXCPM_PRESET_PREFIX}{VOXCPM_DEFAULT_VOICE_KEY}"

# 音色库目录名（仓库根目录下）
VOXCPM_VOICES_DIRNAME = "voices"

# 指纹字段：任一变化 → 缓存失效重生成
VOXCPM_FINGERPRINT_FIELDS = (
    "model_id",
    "description",
    "seed",
    "audition_text",
    "cfg_value",
    "inference_timesteps",
)


def get_default_voxcpm_voice_dir() -> str:
    """返回默认音色库目录（仓库根目录/voices）。"""
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    return os.path.join(repo_root, VOXCPM_VOICES_DIRNAME)


def _ensure_dir(path: str) -> str:
    Path(path).mkdir(parents=True, exist_ok=True)
    return path


def get_preset_keys() -> list:
    """返回预设音色名（按定义顺序）。"""
    return list(VOXCPM_VOICE_PRESETS.keys())


def get_voxcpm_voice_choices(voice_dir: str = None) -> list:
    """返回 WebUI 下拉音色选项：预设 + 音色库目录里的用户 wav。

    选项 value 统一用可解析的约定值：
    - preset:<预设名>
    - file:<文件名>
    """
    voice_dir = voice_dir or get_default_voxcpm_voice_dir()
    choices = [
        (f"{name}（预设）", f"{VOXCPM_PRESET_PREFIX}{name}")
        for name in get_preset_keys()
    ]
    for wav_name in list_user_voice_files(voice_dir):
        choices.append((f"{wav_name}（自定义）", f"{VOXCPM_FILE_PREFIX}{wav_name}"))
    return choices


def list_user_voice_files(voice_dir: str = None) -> list:
    """列出音色库目录里的用户参考音频（.wav/.mp3/.flac/.m4a/.aac）。"""
    voice_dir = voice_dir or get_default_voxcpm_voice_dir()
    if not os.path.isdir(voice_dir):
        return []
    supported = (".wav", ".mp3", ".flac", ".m4a", ".aac")
    files = []
    for name in sorted(os.listdir(voice_dir)):
        low = name.lower()
        if low.endswith(supported) and not name.startswith("."):
            files.append(name)
    return files


def is_preset_value(value: str) -> bool:
    return isinstance(value, str) and value.startswith(VOXCPM_PRESET_PREFIX)


def pop_preset(value: str) -> str:
    """值为预设时（preset:xxx）剥离前缀返回预设名，否则原样返回。"""
    if is_preset_value(value):
        return value[len(VOXCPM_PRESET_PREFIX):]
    return value


def resolve_voxcpm_voice(value, voice_dir: str = None) -> dict:
    """把 WebUI/CLI 的音色值解析成内部描述。

    value 取值约定（同时兼容 CLI 与 WebUI）：
    - "preset:<预设名>" 或直接写预设名（如 "沉稳男声"）→ 内置预设；
    - "file:<文件名>" → voice_dir 下的 wav / mp3 等；
    - 其他值按文件路径处理（绝对或相对路径）。

    返回 dict，字段：
    kind          preset / file / none
    key           预设名（preset 时）
    label         展示名
    description   预设声音描述（preset 时）
    seed          预设固定 seed（preset 时，int）
    audition_text 预设试听文本（preset 时，兼作 Hi-Fi 转写）
    wav_path      参考音频路径（preset 且已缓存 / file 时）
    display       展示名
    """
    voice_dir = voice_dir or get_default_voxcpm_voice_dir()
    if not value:
        return {"kind": "none", "display": ""}

    value = str(value).strip()
    preset_name = pop_preset(value)
    if preset_name in VOXCPM_VOICE_PRESETS:
        preset = VOXCPM_VOICE_PRESETS[preset_name]
        cached = cached_preset_audio_path(preset_name, voice_dir)
        return {
            "kind": "preset",
            "key": preset_name,
            "label": f"{preset_name}（预设）",
            "display": preset_name,
            "description": preset["description"],
            "seed": preset["seed"],
            "audition_text": preset["audition_text"],
            "wav_path": cached if cached and os.path.exists(cached) else None,
        }

    if value.startswith(VOXCPM_FILE_PREFIX):
        file_name = value[len(VOXCPM_FILE_PREFIX):]
        path = os.path.join(voice_dir, file_name)
        if not os.path.exists(path):
            raise ValueError(
                f"音色文件不存在：{path}（音色库目录 {voice_dir} 下找不到 {file_name}）"
            )
        return {"kind": "file", "label": file_name, "display": file_name, "wav_path": path}

    # 直接传文件路径（CLI 常用）
    if os.path.exists(value):
        return {
            "kind": "file",
            "label": os.path.basename(value),
            "display": os.path.basename(value),
            "wav_path": value,
        }
    raise ValueError(
        f"无法解析音色 {value!r}：既不是内置预设（可选：{', '.join(get_preset_keys())}），"
        f"也不是音色库中的文件（目录：{voice_dir}），更不是存在的文件路径。"
    )


def preset_audio_stem(preset_key: str) -> str:
    """预设参考音频文件名（不含扩展名）。"""
    return f"preset_{preset_key}"


def cached_preset_audio_path(preset_key: str, voice_dir: str = None) -> str | None:
    """返回已缓存且 wav/json 均存在的预设参考音频路径；缺失返回 None。"""
    voice_dir = voice_dir or get_default_voxcpm_voice_dir()
    if preset_key not in VOXCPM_VOICE_PRESETS:
        return None
    base = os.path.join(voice_dir, preset_audio_stem(preset_key))
    wav_path = f"{base}.wav"
    json_path = f"{base}.json"
    if not (os.path.exists(wav_path) and os.path.exists(json_path)):
        return None
    return wav_path


def build_preset_fingerprint(preset_key: str, model_id: str,
                             cfg_value, inference_timesteps) -> dict:
    """构造预设缓存指纹（模型/描述/seed/试听文本/生成参数任一变化即失效）。"""
    preset = VOXCPM_VOICE_PRESETS[preset_key]
    return {
        "model_id": model_id,
        "description": preset["description"],
        "seed": preset["seed"],
        "audition_text": preset["audition_text"],
        "cfg_value": float(cfg_value),
        "inference_timesteps": int(inference_timesteps),
    }


def read_preset_fingerprint(preset_key: str, voice_dir: str = None) -> dict | None:
    voice_dir = voice_dir or get_default_voxcpm_voice_dir()
    base = os.path.join(voice_dir, preset_audio_stem(preset_key))
    json_path = f"{base}.json"
    if not os.path.exists(json_path):
        return None
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {k: data.get(k) for k in VOXCPM_FINGERPRINT_FIELDS}
    except Exception as e:
        logger.warning(f"读取音色指纹失败（将重新生成）：{json_path} — {e}")
        return None


def fingerprint_matches(preset_key: str, model_id: str,
                        cfg_value, inference_timesteps, voice_dir: str = None) -> bool:
    expected = build_preset_fingerprint(preset_key, model_id, cfg_value, inference_timesteps)
    actual = read_preset_fingerprint(preset_key, voice_dir)
    return actual == expected


# ═══════════════════════════════════════════════════════════════
# 文件锁 + 原子写入（允许多 worker 并发首次生成同一预设）
# ═══════════════════════════════════════════════════════════════
_fallback_lock = threading.Lock()


class _PresetFileLock:
    """POSIX flock 文件锁；非 POSIX（Windows）回退到进程内线程锁。"""

    def __init__(self, lock_path: str):
        self.lock_path = lock_path
        self._file = None

    def __enter__(self):
        _ensure_dir(os.path.dirname(self.lock_path))
        try:
            import fcntl
            self._file = open(self.lock_path, "a+")
            fcntl.flock(self._file.fileno(), fcntl.LOCK_EX)
        except (ImportError, OSError):
            _fallback_lock.acquire()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._file is not None:
            try:
                import fcntl
                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            except (ImportError, OSError):
                pass
            self._file.close()
            self._file = None
        else:
            _fallback_lock.release()


def ensure_voice_dir(voice_dir: str = None) -> str:
    """确保音色库目录存在，并写入占位 README（不覆盖已有内容）。"""
    voice_dir = voice_dir or get_default_voxcpm_voice_dir()
    _ensure_dir(voice_dir)
    readme = os.path.join(voice_dir, "README.md")
    if not os.path.exists(readme):
        try:
            with open(readme, "w", encoding="utf-8") as f:
                f.write(
                    "# 音色库\n\n"
                    "此目录保存 VoxCPM 预设音色首次使用/试听时生成的参考音频（wav + 指纹 json），"
                    "以及手动放入的自定义参考音频（wav/mp3/flac/m4a/aac，文件名会自动出现在 WebUI 音色下拉中）。\n\n"
                    "生成文件默认被 .gitignore 忽略，不会进入版本库。\n"
                )
        except OSError as e:
            logger.warning(f"无法写入音色目录 README：{e}")
    return voice_dir


def fingerprint_path(preset_key: str, voice_dir: str = None) -> str:
    voice_dir = voice_dir or get_default_voxcpm_voice_dir()
    return os.path.join(voice_dir, f"{preset_audio_stem(preset_key)}.json")


def write_preset_audio(preset_key: str, voice_dir: str, wav: "object",
                       sample_rate: int, fingerprint: dict) -> str:
    """原子写入预设参考音频（wav + 指纹 json）。

    wav 为 1D float32 numpy 数组。写完 wav 再写指纹 json；读取时两者缺一即失效。
    """
    import numpy as np
    import soundfile as sf

    voice_dir = ensure_voice_dir(voice_dir)
    base = os.path.join(voice_dir, preset_audio_stem(preset_key))
    wav_path = f"{base}.wav"
    json_path = f"{base}.json"
    tmp_wav = f"{base}.wav.tmp.{os.getpid()}"
    tmp_json = f"{base}.json.tmp.{os.getpid()}"

    try:
        sf.write(
            tmp_wav,
            np.asarray(wav, dtype="float32"),
            samplerate=int(sample_rate),
            format="WAV",  # tmp 文件名带 .tmp.<pid> 后缀，必须显式指定格式
        )
        os.replace(tmp_wav, wav_path)
        with open(tmp_json, "w", encoding="utf-8") as f:
            json.dump(fingerprint, f, ensure_ascii=False, indent=2)
        os.replace(tmp_json, json_path)
    except Exception:
        for tmp in (tmp_wav, tmp_json):
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        raise
    logger.info(f"预设音色已缓存：{wav_path}（指纹：{fingerprint}）")
    return wav_path


def ensure_preset_audio(preset_key: str, voice_dir: str, model_id: str,
                        cfg_value, inference_timesteps, generator, regenerate: bool = False) -> str:
    """确保预设参考音频存在且指纹匹配，否则调用 generator 生成并缓存。

    generator(text, seed) -> (wav: np.ndarray 1D float32, sample_rate: int)
    带文件锁，多 worker 并发首次生成时只会生成一次。
    """
    if preset_key not in VOXCPM_VOICE_PRESETS:
        raise ValueError(f"未知预设音色：{preset_key}")

    voice_dir = voice_dir or get_default_voxcpm_voice_dir()
    voice_dir = ensure_voice_dir(voice_dir)
    lock = _PresetFileLock(os.path.join(voice_dir, f"{preset_audio_stem(preset_key)}.lock"))
    with lock:
        if not regenerate and cached_preset_audio_path(preset_key, voice_dir) is not None \
                and fingerprint_matches(preset_key, model_id, cfg_value, inference_timesteps, voice_dir):
            return cached_preset_audio_path(preset_key, voice_dir)

        preset = VOXCPM_VOICE_PRESETS[preset_key]
        logger.info(
            f"生成预设音色参考音频：{preset_key}（seed={preset['seed']}，"
            f"描述={preset['description']}）"
        )
        wav, sample_rate = generator(preset["audition_text"], preset["seed"])
        fingerprint = build_preset_fingerprint(preset_key, model_id, cfg_value, inference_timesteps)
        return write_preset_audio(preset_key, voice_dir, wav, sample_rate, fingerprint)
