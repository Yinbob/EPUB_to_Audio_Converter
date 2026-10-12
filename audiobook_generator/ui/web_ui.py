"""
Apple 风格 WebUI —— 全新设计的有声书生成工作台。

设计理念：
- 完全摒弃旧版单页堆叠式表单，改用「二级页面 + 弹窗」结构。
- 顶部胶囊导航在「转换 / 资源库 / 日志」三个主页面间切换。
- TTS 引擎配置以卡片选择 + 浮层弹窗（Modal）形式呈现。
- 苹果风视觉：留白、毛玻璃、SF 字体、克制动效、渐变高亮。

功能与旧版单页式 UI 完全等价，当前为项目唯一的 WebUI。
入口：main_ui.py
"""

from multiprocessing import Process, get_context
from typing import Optional
from pathlib import Path
from dataclasses import asdict, replace
import hashlib
import os
import json
import logging
import math
import signal
import tempfile
import time
import zipfile
import shutil
from datetime import datetime

import gradio as gr
from gradio_log import Log

from audiobook_generator.config.general_config import GeneralConfig
from audiobook_generator.tts_providers.edge_tts_provider import (
    get_edge_tts_supported_voices,
    get_edge_tts_supported_language,
    get_edge_tts_supported_output_formats,
)
from audiobook_generator.tts_providers.openai_tts_provider import (
    get_openai_supported_models,
    get_openai_supported_voices,
    get_openai_instructions_example,
    get_openai_supported_output_formats,
)
from audiobook_generator.tts_providers.qwen_tts_provider import (
    get_qwen_supported_languages,
    get_qwen_supported_voices,
    get_qwen_supported_output_formats,
)
from audiobook_generator.tts_providers.voice_catalog import (
    clear_user_voice_entries,
    import_voice_catalog_document,
    list_catalog_entries,
    save_user_voice_entries,
)
from audiobook_generator.tts_providers.minimax_tts_provider import (
    get_minimax_supported_models,
    get_minimax_supported_output_formats,
    get_minimax_voice_choices,
    get_minimax_voice_id_from_choice,
)
from audiobook_generator.tts_providers.chatterbox_tts_provider import (
    DEFAULT_CHATTERBOX_OUTPUT_FORMAT,
    DEFAULT_CHATTERBOX_SPEED,
    get_chatterbox_supported_models,
    get_chatterbox_supported_devices,
    get_chatterbox_supported_output_formats,
    get_chatterbox_speed_range,
)
from audiobook_generator.tts_providers.voxcpm_tts_provider import (
    DEFAULT_VOXCPM_CFG_VALUE,
    DEFAULT_VOXCPM_CHUNK_CHARS,
    DEFAULT_VOXCPM_INFERENCE_TIMESTEPS,
    DEFAULT_VOXCPM_MODEL,
    DEFAULT_VOXCPM_OUTPUT_FORMAT,
    DEFAULT_VOXCPM_SPEED,
    VOXCPM_MODES,
    get_voxcpm_speed_range,
    get_voxcpm_supported_devices,
    get_voxcpm_supported_output_formats,
    preview_voxcpm_preset_audio,
)
from audiobook_generator.utils.voxcpm_voices import (
    VOXCPM_DEFAULT_VOICE_VALUE,
    get_default_voxcpm_voice_dir,
    get_voxcpm_voice_choices,
    resolve_voxcpm_voice,
)
from audiobook_generator.utils.log_handler import generate_unique_log_path
from audiobook_generator.ui.ambient_background import AMBIENT_CSS, AMBIENT_LAYER_HTML
from audiobook_generator.ui.progress_parser import decide_progress_state, parse_progress
from audiobook_generator.ui.theme import THEME_CSS, THEME_HEAD_HTML, THEME_TOKENS_CSS
from audiobook_generator.utils.mimo_config import (
    load_mimo_config, save_mimo_config, mask_api_key as mimo_mask_api_key, test_mimo_connection
)
from audiobook_generator.utils.minimax_config import (
    load_minimax_config, save_minimax_config, mask_api_key as minimax_mask_api_key, test_minimax_connection
)
from audiobook_generator.utils.qwen_config import (
    load_qwen_config, save_qwen_config, mask_api_key as qwen_mask_api_key, test_qwen_connection
)
from audiobook_generator.utils.deepseek_config import (
    DEFAULT_BASE_URL as DEEPSEEK_DEFAULT_BASE_URL,
    DEFAULT_MODEL as DEEPSEEK_DEFAULT_MODEL,
    load_deepseek_config,
    save_deepseek_config,
    mask_api_key as deepseek_mask_api_key,
    test_deepseek_connection,
)
from audiobook_generator.book_parsers.base_book_parser import get_book_parser
from audiobook_generator.core.audiobook_generator import ROLE_BREAK_STRINGS
from audiobook_generator.role_script.deepseek_splitter import (
    DeepSeekSplitError,
    detect_role_script_language,
    differentiate_role_voices,
    split_chapters_with_deepseek,
    write_role_script,
)
from audiobook_generator.role_script.loader import load_role_script
from audiobook_generator.role_script.project_store import (
    load_project, parser_fingerprint, project_path, save_project,
)
from audiobook_generator.role_script.review import (
    confirm_segment_speaker, lock_entity_voice, merge_entities, pending_segments,
)
from audiobook_generator.role_script.v2_generation import generate_v2_for_book
from audiobook_generator.role_script.models import (
    RoleDefinition,
    RoleScriptV1,
    RoleScriptV2,
    VoiceProfile,
)
from audiobook_generator.role_script.validator import validate_role_script
from audiobook_generator.role_script.errors import ValidationReport
from audiobook_generator.tts_providers.base_tts_provider import get_tts_provider
from main import main


logger = logging.getLogger(__name__)

# ── 设置持久化（与旧版共用 .webui_settings.json） ─────────────────
_SETTINGS_PATH = os.path.join(
    os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")),
    ".webui_settings.json",
)
_DEFAULT_SETTINGS = {
    "output_text": False,
    "preview": False,
    "remove_endnotes": False,
    "remove_reference_numbers": False,
    "show_voice_instructions": False,
}


def _load_settings() -> dict:
    merged = dict(_DEFAULT_SETTINGS)
    if os.path.exists(_SETTINGS_PATH):
        try:
            with open(_SETTINGS_PATH, "r", encoding="utf-8") as f:
                merged.update(json.load(f))
        except Exception:
            pass
    return merged


def _save_checkbox(key: str, value: bool):
    settings = _load_settings()
    settings[key] = value
    try:
        with open(_SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def _save_setting(key: str, value):
    """保存任意类型的设置（字符串、数字等）"""
    settings = _load_settings()
    settings[key] = value
    try:
        with open(_SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


# ── 管理员密码验证 ─────────────────────────────────────────────────
def _hash_password(password: str) -> str:
    """对密码进行 SHA256 哈希"""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def _get_admin_password_hash() -> str:
    """获取存储的管理员密码哈希，若未设置则返回默认密码 'admin' 的哈希"""
    settings = _load_settings()
    return settings.get("admin_password_hash", _hash_password("admin"))


def _verify_admin_password(password: str) -> bool:
    """验证管理员密码"""
    return _hash_password(password) == _get_admin_password_hash()


def _change_admin_password(old_password: str, new_password: str) -> tuple[bool, str]:
    """修改管理员密码，返回 (success, message)"""
    if not _verify_admin_password(old_password):
        return False, "原密码错误"
    if len(new_password) < 4:
        return False, "新密码长度不能少于4位"
    _save_setting("admin_password_hash", _hash_password(new_password))
    return True, "密码修改成功"


# ── API 配置管理 ─────────────────────────────────────────────────
def _load_api_configs() -> dict:
    """加载所有 API 配置"""
    configs = {}
    
    # MiMo 配置
    mimo_config = load_mimo_config()
    mimo_api_key = mimo_config.get("api_key", "")
    configs["mimo_api_key"] = mimo_api_key
    configs["mimo_api_key_masked"] = mimo_mask_api_key(mimo_api_key) if mimo_api_key else ""
    configs["mimo_base_url"] = mimo_config.get("base_url", "https://token-plan-cn.xiaomimimo.com/v1")
    
    # MiniMax 配置
    minimax_config = load_minimax_config()
    minimax_api_key = minimax_config.get("api_key", "")
    configs["minimax_api_key"] = minimax_api_key
    configs["minimax_api_key_masked"] = minimax_mask_api_key(minimax_api_key) if minimax_api_key else ""
    
    # Qwen 配置
    qwen_config = load_qwen_config()
    qwen_api_key = qwen_config.get("api_key", "")
    configs["qwen_api_key"] = qwen_api_key
    configs["qwen_api_key_masked"] = qwen_mask_api_key(qwen_api_key) if qwen_api_key else ""
    configs["qwen_base_url"] = qwen_config.get("base_url", "https://gpu.ncut.edu.cn/v1")
    configs["qwen_model"] = qwen_config.get("model", "qwen3-tts-12hz-1.7b-voicedesign")

    # DeepSeek 只用于多角色脚本拆分，与 TTS Provider 凭证独立。
    deepseek_config = load_deepseek_config()
    deepseek_api_key = str(deepseek_config.get("api_key") or "")
    configs["deepseek_api_key"] = deepseek_api_key
    configs["deepseek_api_key_masked"] = (
        deepseek_mask_api_key(deepseek_api_key) if deepseek_api_key else ""
    )
    configs["deepseek_base_url"] = str(
        deepseek_config.get("base_url") or DEEPSEEK_DEFAULT_BASE_URL
    )
    configs["deepseek_model"] = str(
        deepseek_config.get("model") or DEEPSEEK_DEFAULT_MODEL
    )

    return configs


def _save_mimo_api_config(api_key: str, base_url: str) -> str:
    """保存 MiMo API 配置，返回保存结果消息"""
    if not api_key.strip():
        return "❌ API Key 不能为空"
    save_mimo_config(api_key.strip(), base_url.strip())
    return "✅ MiMo 配置已保存"


def _save_minimax_api_config(api_key: str) -> str:
    """保存 MiniMax API 配置，返回保存结果消息"""
    if not api_key.strip():
        return "❌ API Key 不能为空"
    save_minimax_config(api_key.strip())
    return "✅ MiniMax 配置已保存"


def _save_qwen_api_config(api_key: str, base_url: str, model: str) -> str:
    """保存 Qwen API 配置，返回保存结果消息"""
    if not api_key.strip():
        return "❌ API Key 不能为空"
    save_qwen_config(api_key.strip(), base_url.strip(), model.strip())
    return "✅ Qwen 配置已保存"


def _test_mimo_api(api_key: str, base_url: str) -> str:
    """测试 MiMo API 连接，返回测试结果消息"""
    if not api_key.strip():
        return "❌ 请先输入 API Key"
    success, msg = test_mimo_connection(api_key.strip(), base_url.strip())
    return "✅ " + msg if success else "❌ " + msg


def _test_minimax_api(api_key: str) -> str:
    """测试 MiniMax API 连接，返回测试结果消息"""
    if not api_key.strip():
        return "❌ 请先输入 API Key"
    success, msg = test_minimax_connection(api_key.strip())
    return "✅ " + msg if success else "❌ " + msg


def _test_qwen_api(api_key: str, base_url: str, model: str) -> str:
    """测试 Qwen API 连接，返回测试结果消息"""
    if not api_key.strip():
        return "❌ 请先输入 API Key"
    success, msg = test_qwen_connection(api_key.strip(), base_url.strip(), model.strip())
    return "✅ " + msg if success else "❌ " + msg


def _save_deepseek_api_config(api_key: str, base_url: str, model: str) -> str:
    """保存 DeepSeek 脚本拆分配置。"""
    if not api_key.strip():
        return "❌ API Key 不能为空"
    save_deepseek_config(api_key.strip(), base_url.strip(), model.strip())
    return "✅ DeepSeek 配置已保存"


def _test_deepseek_api(api_key: str, base_url: str, model: str) -> str:
    """测试 DeepSeek API 连接，返回测试结果消息。"""
    if not api_key.strip():
        return "❌ 请先输入 API Key"
    success, msg = test_deepseek_connection(api_key.strip(), base_url.strip(), model.strip())
    return "✅ " + msg if success else "❌ " + msg


# ── 运行态 ────────────────────────────────────────────────────────
running_process: Optional[Process] = None
# 是否由用户点了「停止转换」而结束（用于把状态显示成"已停止"而不是"异常中断"）
manual_stopped = False
webui_log_file = None
# VoxCPM 试听任务互斥（模型加载+生成耗时长，且临时占用约 8GB 显存）
_voxcpm_preview_busy = False

_PROVIDER_LABEL = {
    "Mimo": "MiMo",
    "MiniMax": "MiniMax",
    "Edge": "Edge",
    "Qwen": "Qwen TTS",
    "Chatterbox": "Chatterbox",
    "VoxCPM": "VoxCPM",
}


def _badge_html(provider: str) -> str:
    label = _PROVIDER_LABEL.get(provider, provider)
    return f'''
    <div class="engine-badge">
        <span class="engine-badge-dot"></span>
        <span class="engine-badge-label">当前语音引擎</span>
        <span class="engine-badge-name">{label}</span>
    </div>'''


# ── 输出目录 / 文件管理 ───────────────────────────────────────────
def get_output_dir():
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
    out_dir = os.path.join(project_root, "audiobook_output")
    os.makedirs(out_dir, exist_ok=True)
    return out_dir


def get_folders_list():
    target_dir = get_output_dir()
    folders = []
    for item in os.listdir(target_dir):
        item_path = os.path.join(target_dir, item)
        if os.path.isdir(item_path) and not item.startswith('.'):
            mtime = os.path.getmtime(item_path)
            folders.append((item, mtime))
    folders.sort(key=lambda x: x[1], reverse=True)
    return [f[0] for f in folders]


def get_files_in_folder(folder_name):
    if not folder_name:
        return []
    target_dir = os.path.join(get_output_dir(), folder_name)
    if not os.path.exists(target_dir):
        return []
    files = []
    for f in os.listdir(target_dir):
        if os.path.isfile(os.path.join(target_dir, f)) and not f.startswith('.'):
            files.append(f)
    files.sort()
    return files


def update_output_dir_from_file(file_objs):
    if not file_objs:
        return gr.update()
    if not isinstance(file_objs, list):
        file_objs = [file_objs]
    if len(file_objs) == 0:
        return gr.update()
    first = file_objs[0]
    file_path = first.name if hasattr(first, "name") else first
    if not file_path:
        return gr.update()
    book_name = Path(file_path).stem
    safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in book_name)
    if len(file_objs) > 1:
        safe_name += f" 等{len(file_objs)}本书"
    output_path = os.path.join("audiobook_output", safe_name)
    return gr.update(value=output_path)


# ── TTS 联动下拉 ──────────────────────────────────────────────────
def get_edge_voices_by_language(language):
    voices_list = [v for v in get_edge_tts_supported_voices() if v.startswith(language)]
    return gr.Dropdown(voices_list, value=voices_list[0] if voices_list else None,
                       label="音色 Voice", interactive=True)


def get_qwen_voices_gui():
    voices_list = get_qwen_supported_voices()
    return gr.Dropdown(voices_list, value=voices_list[0] if voices_list else None,
                       label="音色 Voice", interactive=True)


def get_qwen_languages_gui():
    languages_list = get_qwen_supported_languages()
    return gr.Dropdown(languages_list, value="Auto", label="语言 Language", interactive=True)


# ── VoxCPM 试听 ─────────────────────────────────────────────────
def voxcpm_preview_voice(voice, model_name, device, voice_dir, cfg_value, inference_timesteps,
                         regenerate):
    """生成/返回预设音色试听音频。缓存命中时不加载模型；否则临时加载并立即释放。

    释放模型是为了避免 WebUI 主进程长期占用显存，与转换 worker 抢资源
    （多项目共用一张 GPU 时的基本防护）。
    """
    global _voxcpm_preview_busy
    if _voxcpm_preview_busy:
        gr.Warning("已有试听任务正在生成，请稍候…")
        return gr.update()
    if running_process and running_process.is_alive():
        gr.Warning(
            "当前有转换任务正在运行：试听会临时再占约 8GB 显存，"
            "如需稳定转换请等转换结束再试听，或用 CUDA_VISIBLE_DEVICES 隔离显卡。"
        )
    _voxcpm_preview_busy = True
    try:
        resolved = resolve_voxcpm_voice(voice, voice_dir)
        if resolved.get("kind") != "preset":
            gr.Warning("试听仅支持内置预设音色；自定义参考音频可直接上传参考音频后试听。")
            return gr.update()
        path = preview_voxcpm_preset_audio(
            voice_value=voice,
            voice_dir=voice_dir,
            model_name=model_name,
            device=device,
            cfg_value=cfg_value,
            inference_timesteps=inference_timesteps,
            regenerate=bool(regenerate),
        )
    except Exception as e:
        gr.Warning(f"生成试听音频失败：{e}")
        logger.warning(f"VoxCPM 试听失败: {e}", exc_info=True)
        return gr.update()
    finally:
        _voxcpm_preview_busy = False
    gr.Info("试听音频已就绪")
    return gr.update(value=path)


# ── 多角色剧本 ───────────────────────────────────────────────────
ROLE_TABLE_HEADERS = [
    "role_id", "display_name", "voice", "voice_id", "speed",
    "instructions", "pitch", "volume",
]
_ROLE_PROVIDER_TTS = {"Mimo": "openai", "MiniMax": "minimax"}
_ROLE_FINAL_FORMATS = {"mp3", "wav", "flac"}
_VOICE_CATALOG_PROVIDERS = ("自动识别", "MiMo", "MiniMax")
_VOICE_CATALOG_LANGUAGES = ("自动识别", "英语", "中文", "粤语")
_VOICE_CATALOG_FILE_TYPES = [".json", ".csv", ".tsv", ".txt", ".md", ".html", ".htm", ".docx", ".pdf"]


def _uploaded_file_path(file_obj):
    """兼容 Gradio 字符串、FileData、dict 和列表形式。"""
    if isinstance(file_obj, (list, tuple)):
        return _uploaded_file_path(file_obj[0]) if file_obj else None
    if isinstance(file_obj, (str, os.PathLike)):
        return os.fspath(file_obj)
    if isinstance(file_obj, dict):
        value = file_obj.get("path") or file_obj.get("name")
        return os.fspath(value) if value else None
    value = getattr(file_obj, "path", None) or getattr(file_obj, "name", None)
    return os.fspath(value) if value else None


def _role_provider_id(provider: str):
    return _ROLE_PROVIDER_TTS.get(provider)


def _selected_role_output_format(provider: str, openai_output_format, minimax_output_format):
    if provider == "Mimo":
        return openai_output_format
    if provider == "MiniMax":
        return minimax_output_format
    return None


def _format_role_validation_report(report, heading: str = "剧本校验") -> str:
    if report is None:
        return f"**{heading}**：尚未校验"
    if report.ok and not report.warnings:
        return f"**✅ {heading}通过**"
    lines = []
    if report.ok:
        lines.append(f"**✅ {heading}通过**")
    else:
        lines.append(f"**❌ {heading}失败（{len(report.errors)} 个错误）**")
    for item in report.errors:
        lines.append(f"- `{item.code}` `{item.path}`：{item.message}")
    for item in report.warnings:
        lines.append(f"- ⚠️ `{item.code}` `{item.path}`：{item.message}")
    return "\n".join(lines)


def _voice_catalog_provider_choice(choice: str):
    return {"MiMo": "openai", "MiniMax": "minimax"}.get(str(choice or "").strip())


def _voice_catalog_language_choice(choice: str) -> str:
    return {"英语": "en", "中文": "zh", "粤语": "yue"}.get(str(choice or "").strip(), "")


def _voice_catalog_overview_markdown() -> str:
    """展示用户目录摘要；用户目录为空时明确说明仍可用内置音色。"""
    try:
        uploaded = list_catalog_entries(include_builtin=False)
    except Exception as exc:
        return f"**音色目录读取失败**：{exc}"
    if not uploaded:
        return "**当前音色目录**：未导入官网文档，正在使用内置音色池。"

    language_names = {"en": "英文", "zh": "中文", "yue": "粤语", "ja": "日语", "ko": "韩语", "unknown": "语言未识别"}
    counts = {}
    for entry in uploaded:
        counts[entry.language or "unknown"] = counts.get(entry.language or "unknown", 0) + 1
    count_text = "、".join(
        f"{language_names.get(language, language)} {count}"
        for language, count in sorted(counts.items())
    )
    english = [entry.voice_id for entry in uploaded if entry.language == "en"]
    preview = "、".join(f"`{voice_id}`" for voice_id in english[:12]) or "无"
    if len(english) > 12:
        preview += f" 等 {len(english)} 个"
    return (
        f"**当前音色目录**：已导入 {len(uploaded)} 个用户音色（{count_text}）。\n\n"
        f"- 用户英文音色：{preview}\n"
        "- 重新拆分剧本后，DeepSeek 会优先从这些音色中分配角色。"
    )


def _voice_catalog_result_markdown(result, saved_entries) -> str:
    lines = [
        "**✅ 官网音色说明解析并保存成功**",
        f"- 来源：`{result.source_name or '粘贴内容'}`",
        f"- 解析有效音色：{len(result.entries)} 个；当前用户目录共 {len(saved_entries)} 个",
    ]
    language_names = {"en": "英文", "zh": "中文", "yue": "粤语", "ja": "日语", "ko": "韩语", "unknown": "语言未识别"}
    counts = {}
    for entry in result.entries:
        counts[entry.language or "unknown"] = counts.get(entry.language or "unknown", 0) + 1
    lines.append("- 本次语言分布：" + "、".join(
        f"{language_names.get(language, language)} {count}"
        for language, count in sorted(counts.items())
    ))
    unknown = [entry.voice_id for entry in result.entries if entry.language in ("", "unknown")]
    if unknown:
        lines.append(f"- ⚠️ 语言未识别：{'、'.join(f'`{voice}`' for voice in unknown[:10])}")
    if result.warnings:
        lines.append("- ⚠️ 解析提醒：")
        lines.extend(f"  - {warning}" for warning in result.warnings[:8])
    lines.append("\n" + _voice_catalog_overview_markdown())
    lines.append("\n> 如已生成剧本，请点击「重新生成」让新音色参与角色分配。")
    return "\n".join(lines)


def import_voice_catalog_document_ui(file_obj, pasted_text, provider_choice, language_choice):
    """手动上传或粘贴官网音色说明，解析后保存到用户音色目录。"""
    file_path = _uploaded_file_path(file_obj)
    pasted = str(pasted_text or "").strip()
    if not file_path and not pasted:
        message = "请上传官网音色说明文档，或粘贴音色说明内容。"
        gr.Warning(message)
        return f"**❌ {message}**", gr.update(), gr.update()

    # 文件优先，避免上一次粘贴内容覆盖新上传的文档。
    text = "" if file_path else pasted
    provider = _voice_catalog_provider_choice(provider_choice)
    default_language = _voice_catalog_language_choice(language_choice)
    result = import_voice_catalog_document(
        file_path,
        text=text,
        provider=provider,
        default_language=default_language,
    )
    if result.errors:
        message = "；".join(result.errors)
        gr.Warning(message)
        return f"**❌ 音色说明解析失败**\n\n{message}", gr.update(), gr.update()
    try:
        saved_entries = save_user_voice_entries(result.entries)
    except Exception as exc:
        logger.exception("保存人工音色目录失败")
        gr.Warning(f"音色目录保存失败：{exc}")
        return f"**❌ 音色目录保存失败**\n\n{exc}", gr.update(), gr.update()

    gr.Info(f"已保存 {len(result.entries)} 个音色，请重新生成剧本以应用。")
    return (
        _voice_catalog_result_markdown(result, saved_entries),
        gr.update(choices=get_openai_supported_voices()),
        gr.update(choices=get_minimax_voice_choices()),
    )


def clear_voice_catalog_ui():
    """清空用户导入项，保留内置音色池。"""
    clear_user_voice_entries()
    gr.Info("已清空用户导入的音色目录，恢复使用内置音色。")
    return (
        _voice_catalog_overview_markdown(),
        gr.update(choices=get_openai_supported_voices()),
        gr.update(choices=get_minimax_voice_choices()),
    )


def _role_confirmation_signature(script: RoleScriptV1) -> str:
    """生成确认内容指纹，用于区分程序化 change 和用户真实编辑。"""
    payload = json.dumps(
        asdict(script),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# 服务端人工确认记录：{剧本绝对路径: 已确认内容指纹}。
# Gradio 的 gr.State 在部分事件链（自动拆分写回文件、表格 change 竞态）里会
# 被旧快照覆盖，表现为“明明点过确认使用，开始生成却仍提示等待 DeepSeek”。
# 这里在服务端再记一份，只要剧本文件没被重新生成、内容指纹一致就视为已确认。
_ROLE_CONFIRMED_SCRIPTS = {}


def _remember_role_confirmation(file_obj, signature: str) -> None:
    """把人工确认结果落到服务端缓存，避免前端 State 被竞态覆盖。"""
    path = _uploaded_file_path(file_obj)
    if not path or not signature:
        return
    try:
        key = os.path.abspath(path)
    except (TypeError, ValueError):
        return
    _ROLE_CONFIRMED_SCRIPTS[key] = str(signature)


def _forget_role_confirmation(file_obj) -> None:
    """剧本被重新生成时清掉旧的确认记录（同一路径、内容已变）。"""
    path = _uploaded_file_path(file_obj)
    if not path:
        return
    try:
        key = os.path.abspath(path)
    except (TypeError, ValueError):
        return
    _ROLE_CONFIRMED_SCRIPTS.pop(key, None)


def _recall_role_confirmation(file_obj) -> str:
    """读取服务端人工确认记录；文件或内容变化时由调用方做指纹比对兜底。"""
    path = _uploaded_file_path(file_obj)
    if not path:
        return ""
    try:
        key = os.path.abspath(path)
    except (TypeError, ValueError):
        return ""
    return str(_ROLE_CONFIRMED_SCRIPTS.get(key, ""))


def _role_confirmation_probe(confirmed: bool, signature: str = "", gate: bool = False) -> str:
    """给前端“完成/开始生成”按钮提供可读的人工确认状态，不承载任何剧本内容。

    gate 表示“当前存在一份尚未人工确认、但已经生成好的自动拆分剧本”，
    前端据此在点击“完成”时提示先确认，而不是放行到一个随后必然失败的状态。
    """
    confirmed_value = "1" if confirmed else "0"
    gate_value = "1" if (gate and not confirmed) else "0"
    return (
        f'<span id="role_confirmation_probe" data-confirmed="{confirmed_value}" '
        f'data-signature="{signature}" data-gate="{gate_value}"></span>'
    )


def _ensure_role_voice_diversity(script: RoleScriptV1, report: ValidationReport) -> RoleScriptV1:
    """兼容旧剧本：非旁白角色全部同音色时，自动分配性别适配的差异化音色。"""
    upgraded, changed = differentiate_role_voices(script)
    if not changed:
        return script
    report.warn(
        "role_voice_differentiated",
        "$.roles",
        "检测到多个角色共用同一音色，已按角色性别/名称自动分配差异化音色；可在角色表中继续手动调整。",
    )
    return upgraded


def _load_uploaded_role_script(file_obj):
    path = _uploaded_file_path(file_obj)
    if not path:
        report = ValidationReport()
        report.error("read_error", "$", "请先上传 RoleScript JSON 文件")
        return None, report
    return load_role_script(path)


def _role_table_rows(script: RoleScriptV1):
    rows = []
    for role_id, role in script.roles.items():
        params = role.provider_params
        rows.append([
            role_id,
            role.display_name,
            params.get("voice", ""),
            params.get("voice_id", ""),
            params.get("speed", ""),
            params.get("instructions", ""),
            params.get("pitch", ""),
            params.get("volume", ""),
        ])
    return rows


def _is_blank_cell(value) -> bool:
    if value is None:
        return True
    if isinstance(value, float):
        return math.isnan(value) or math.isinf(value)
    if isinstance(value, str):
        return not value.strip() or value.strip().lower() in {"nan", "none", "null"}
    return False


def _role_table_raw_rows(value):
    if value is None:
        return []
    if hasattr(value, "values") and not isinstance(value, dict):
        try:
            return value.values.tolist()
        except Exception:
            pass
    if hasattr(value, "to_dict") and not isinstance(value, dict):
        try:
            return value.to_dict(orient="records")
        except Exception:
            pass
    if isinstance(value, dict):
        data = value.get("data", value.get("value", []))
        if hasattr(data, "values") and not isinstance(data, dict):
            return data.values.tolist()
        return data if isinstance(data, (list, tuple)) else []
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


def _role_cell(row, index: int, header: str):
    if isinstance(row, dict):
        return row.get(header)
    if isinstance(row, (list, tuple)) and index < len(row):
        return row[index]
    return None


def _role_text(value, *, strip: bool = True):
    if _is_blank_cell(value):
        return None
    text = str(value)
    return text.strip() if strip else text


def _role_number(value, field_name: str, row_number: int):
    if _is_blank_cell(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"角色表第 {row_number} 行 {field_name} 不是有效数字：{value!r}") from exc


def _apply_role_table(script: RoleScriptV1, table_value) -> RoleScriptV1:
    """把 WebUI 角色表回写成新的不可变 RoleScriptV1。空表保留原角色定义。"""
    raw_rows = _role_table_raw_rows(table_value)
    if not raw_rows:
        return script

    # 表格通常由上传脚本生成；从原定义开始合并，避免局部编辑/分页数据误删未列出的角色。
    roles = dict(script.roles)
    seen_role_ids = set()
    for row_number, row in enumerate(raw_rows, 1):
        values = [_role_cell(row, index, header) for index, header in enumerate(ROLE_TABLE_HEADERS)]
        if all(_is_blank_cell(value) for value in values):
            continue

        role_id = _role_text(values[0])
        if not role_id:
            raise ValueError(f"角色表第 {row_number} 行缺少 role_id")
        if role_id in seen_role_ids:
            raise ValueError(f"角色表第 {row_number} 行 role_id 重复：{role_id}")
        seen_role_ids.add(role_id)

        display_name = _role_text(values[1]) or role_id
        params = {}
        if script.provider == "openai":
            voice = _role_text(values[2])
            instructions = _role_text(values[5], strip=False)
            speed = _role_number(values[4], "speed", row_number)
            if voice is not None:
                params["voice"] = voice
            if instructions is not None:
                params["instructions"] = instructions
            if speed is not None:
                params["speed"] = speed
        elif script.provider == "minimax":
            voice_id = _role_text(values[3])
            speed = _role_number(values[4], "speed", row_number)
            pitch = _role_number(values[6], "pitch", row_number)
            volume = _role_number(values[7], "volume", row_number)
            if voice_id is not None:
                params["voice_id"] = voice_id
            if speed is not None:
                params["speed"] = speed
            if pitch is not None:
                params["pitch"] = pitch
            if volume is not None:
                params["volume"] = volume
        else:
            raise ValueError(f"角色表不支持 provider：{script.provider}")

        original_role = script.roles.get(role_id)
        roles[role_id] = RoleDefinition(
            display_name=display_name,
            provider_params=params,
            gender=getattr(original_role, "gender", None),
        )

    if not roles:
        raise ValueError("角色表没有有效角色行")
    return replace(script, roles=roles)


def _validate_uploaded_role_script(script, provider: str, output_format: str):
    """上传阶段只做结构、参数和 Provider 校验；书指纹/标题/覆盖率由转换前统一校验。"""
    report = ValidationReport(schema_version=script.schema_version if script else None)
    provider_id = _role_provider_id(provider)
    if provider_id is None:
        report.error(
            "provider_mismatch",
            "$.provider",
            "角色模式首版只支持 MiMo（openai）和 MiniMax",
            tts_provider=provider,
        )
    elif script is not None and script.provider != provider_id:
        report.error(
            "provider_mismatch",
            "$.provider",
            f"剧本 provider={script.provider!r}，当前选择={provider_id!r}",
            script_provider=script.provider,
            tts_provider=provider_id,
        )
    if output_format not in _ROLE_FINAL_FORMATS:
        report.error(
            "unsupported_role_output_format",
            "$.output_format",
            "角色模式最终格式只支持 mp3/wav/flac",
            actual=output_format,
        )

    normalized = script
    if script is not None:
        validation = validate_role_script(script)
        report.errors.extend(validation.report.errors)
        report.warnings.extend(validation.report.warnings)
        normalized = validation.script
    return normalized if report.ok else None, report


def role_script_upload_changed(file_obj, provider, openai_output_format, minimax_output_format):
    """上传 JSON 后刷新参数表和校验摘要，不触发 Provider。"""
    output_format = _selected_role_output_format(
        provider, openai_output_format, minimax_output_format
    )
    script, load_report = _load_uploaded_role_script(file_obj)
    if not load_report.ok or script is None:
        return [], _format_role_validation_report(load_report), gr.update(choices=[], value=None)

    script = _ensure_role_voice_diversity(script, load_report)
    rows = _role_table_rows(script)
    _, report = _validate_uploaded_role_script(script, provider, output_format)
    report.warnings = list(load_report.warnings) + list(report.warnings)
    choices = [f"{role_id} — {role.display_name}" for role_id, role in script.roles.items()]
    return rows, _format_role_validation_report(report), gr.update(
        choices=choices, value=choices[0] if choices else None
    )


def role_table_changed(
    file_obj,
    provider,
    openai_output_format,
    minimax_output_format,
    role_split_confirmed,
    role_confirmed_signature,
    table_value,
):
    """角色表编辑后刷新校验摘要；内容未变时保留人工确认。"""
    output_format = _selected_role_output_format(
        provider, openai_output_format, minimax_output_format
    )
    script, load_report = _load_uploaded_role_script(file_obj)
    if not load_report.ok or script is None:
        return (
            _format_role_validation_report(load_report),
            gr.update(choices=[], value=None),
            False,
            "",
            gr.update(value=_role_confirmation_probe(False)),
        )
    try:
        edited = _apply_role_table(script, table_value)
    except ValueError as exc:
        report = ValidationReport(schema_version=script.schema_version)
        report.error("invalid_role_table", "$.roles", str(exc))
        return (
            _format_role_validation_report(report),
            gr.update(choices=[], value=None),
            False,
            "",
            gr.update(value=_role_confirmation_probe(False)),
        )

    diversity_report = ValidationReport(schema_version=script.schema_version)
    edited = _ensure_role_voice_diversity(edited, diversity_report)
    normalized, report = _validate_uploaded_role_script(edited, provider, output_format)
    report.warnings = list(diversity_report.warnings) + list(report.warnings)
    effective_script = normalized or edited
    new_signature = _role_confirmation_signature(effective_script)
    confirmed_signature = str(role_confirmed_signature or "")
    # 程序化 / 无内容变化的 change 事件也带 role_split_confirmed=False 的旧快照；
    # 只要内容指纹仍与已确认指纹一致，就不能把人工确认打回未确认状态。
    still_confirmed = bool(confirmed_signature) and new_signature == confirmed_signature
    choices = [
        f"{role_id} — {role.display_name}"
        for role_id, role in effective_script.roles.items()
    ]
    return (
        _format_role_validation_report(report),
        gr.update(choices=choices, value=choices[0] if choices else None),
        still_confirmed,
        new_signature if still_confirmed else "",
        gr.update(
            value=_role_confirmation_probe(
                still_confirmed, new_signature if still_confirmed else "", gate=True
            )
        ),
    )


def preview_role_segment(provider, role_script_file, role_table, role_choice, preview_text,
                         openai_model, mimo_voice, mimo_speed, mimo_instructions,
                         mimo_stream, openai_output_format, minimax_model,
                         minimax_voice, minimax_output_format):
    """单角色试听；失败只告警，不进入转换批次。"""
    if running_process and running_process.is_alive():
        gr.Warning("当前有转换任务正在运行，请先停止或等待完成后再试听。")
        return gr.update()
    if not preview_text or not preview_text.strip():
        gr.Warning("请输入试听文本")
        return gr.update()

    output_format = _selected_role_output_format(
        provider, openai_output_format, minimax_output_format
    )
    script, load_report = _load_uploaded_role_script(role_script_file)
    if not load_report.ok or script is None:
        gr.Warning(_format_role_validation_report(load_report, "试听前校验").replace("**", ""))
        return gr.update()
    try:
        script = _apply_role_table(script, role_table)
    except ValueError as exc:
        gr.Warning(f"角色表无效：{exc}")
        return gr.update()

    diversity_report = ValidationReport(schema_version=script.schema_version)
    script = _ensure_role_voice_diversity(script, diversity_report)
    normalized, report = _validate_uploaded_role_script(script, provider, output_format)
    report.warnings = list(diversity_report.warnings) + list(report.warnings)
    if normalized is None:
        gr.Warning(_format_role_validation_report(report, "试听前校验").replace("**", ""))
        return gr.update()

    role_id = str(role_choice or "").split(" — ", 1)[0].strip()
    role = normalized.roles.get(role_id)
    if role is None:
        gr.Warning("请选择有效的试听角色")
        return gr.update()

    config = GeneralConfig(None)
    config.language = (
        "en-US" if detect_role_script_language(normalized) == "en" else "zh-CN"
    )
    if provider == "Mimo":
        config.tts = "openai"
        config.model_name = openai_model
        config.voice_name = mimo_voice
        config.instructions = mimo_instructions
        config.speed = mimo_speed
        config.stream = bool(mimo_stream)
        config.output_format = openai_output_format
    elif provider == "MiniMax":
        config.tts = "minimax"
        config.model_name = minimax_model
        config.voice_name = get_minimax_voice_id_from_choice(minimax_voice)
        config.output_format = minimax_output_format
    else:
        gr.Warning("角色试听只支持 MiMo 和 MiniMax")
        return gr.update()

    preview_root = os.path.join(get_output_dir(), ".role_preview")
    os.makedirs(preview_root, exist_ok=True)
    work_dir = tempfile.mkdtemp(prefix="role-preview-", dir=preview_root)
    try:
        tts_provider = get_tts_provider(config)
        profile = VoiceProfile(
            role_id=role_id,
            display_name=role.display_name,
            provider_params=dict(role.provider_params),
        )
        artifact = tts_provider.synthesize_segment(preview_text.strip(), profile, work_dir, None)
        from audiobook_generator.role_script.audio_pipeline import render_role_preview
        artifact = render_role_preview(
            artifact, profile, config.tts, os.path.join(work_dir, "preview_processed.wav")
        )
        safe_role_id = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in role_id)
        suffix = (artifact.format or output_format or "wav").lower()
        digest = artifact.sha256 or hashlib.sha256(preview_text.encode("utf-8")).hexdigest()
        destination = os.path.join(preview_root, f"{safe_role_id}-{digest[:12]}.{suffix}")
        shutil.copy2(artifact.path, destination)
    except Exception as exc:
        logger.warning("角色试听失败：%s", exc, exc_info=True)
        gr.Warning(f"角色试听失败：{exc}")
        return gr.update()
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    gr.Info("试听音频已就绪")
    return gr.update(value=destination)



# ── DeepSeek 自动角色拆分 ─────────────────────────────────────────
def _sha256_file_ui(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _auto_split_chapters(provider, input_file, chapter_start, chapter_end,
                         title_mode, new_line_mode, remove_endnotes,
                         remove_reference_numbers, search_and_replace_file):
    """按转换链路相同的 parser 配置读取书稿，供 DeepSeek 和最终转换共用。"""
    file_path = _uploaded_file_path(input_file)
    if not file_path:
        raise ValueError("请先上传书籍文件")
    provider_id = _role_provider_id(provider)
    if provider_id not in ROLE_BREAK_STRINGS:
        raise ValueError("自动角色拆分只支持 MiMo（openai）和 MiniMax")

    config = GeneralConfig(None)
    config.input_file = file_path
    config.title_mode = title_mode or "auto"
    config.newline_mode = new_line_mode or "single"
    config.remove_endnotes = bool(remove_endnotes)
    config.remove_reference_numbers = bool(remove_reference_numbers)
    config.search_and_replace_file = _uploaded_file_path(search_and_replace_file)
    book_parser = get_book_parser(config)
    chapters = [
        (title, text)
        for title, text in book_parser.get_chapters(ROLE_BREAK_STRINGS[provider_id])
        if text.strip()
    ]
    if not chapters:
        raise ValueError("书籍解析后没有可转换章节")

    start = int(chapter_start or 1)
    end = len(chapters) if chapter_end in (None, -1) else int(chapter_end)
    if start < 1 or end < 1 or start > end or end > len(chapters):
        raise ValueError(
            f"章节范围无效：{start}..{end}，书籍共 {len(chapters)} 章"
        )
    return chapters, start, end, _sha256_file_ui(file_path), book_parser


def _role_script_summary(script: RoleScriptV1, heading: str = "自动拆分结果") -> str:
    lines = [
        f"**{heading}**",
        f"- 角色数：{len(script.roles)}；章节数：{len(script.chapters)}",
        "- 角色：" + "、".join(
            f"`{role_id}`（{role.display_name}）"
            for role_id, role in script.roles.items()
        ),
    ]
    for chapter in script.chapters:
        role_sequence = " → ".join(
            f"{segment.role_id}" for segment in chapter.segments
        )
        lines.append(
            f"- 第 {chapter.chapter_index} 章《{chapter.title}》："
            f"{len(chapter.segments)} 段（{role_sequence}）"
        )
    if isinstance(script, RoleScriptV2):
        pending = sum(
            1 for chapter in script.chapters for segment in chapter.segments
            if segment.speaker and segment.speaker.status in {"needs_review", "unknown", "proposed"}
        )
        lines.append(f"- 全书人物表：{len(script.entities)} 个实体；待逐段核对：{pending} 段")
        lines.append("- 自动归属分数尚未用标注集校准，请结合原文证据复核。")
    return "\n".join(lines)


def load_role_review(file_obj):
    """仅检查当前 V2 项目；不修改生成音频。"""
    script, report = _load_uploaded_role_script(file_obj)
    if not report.ok or not isinstance(script, RoleScriptV2):
        return (gr.update(choices=[], value=None), gr.update(choices=[], value=None),
                gr.update(choices=[], value=None), gr.update(choices=[], value=None),
                "请先生成 RoleScriptV2 项目。")
    pending = pending_segments(script)
    segment_choices = [(f"第 {chapter} 章 · {excerpt}", segment_id)
                       for segment_id, chapter, excerpt in pending]
    entity_choices = [(f"{item.canonical_name} ({entity_id})", entity_id)
                      for entity_id, item in script.entities.items() if entity_id in script.roles]
    return (
        gr.update(choices=segment_choices, value=segment_choices[0][1] if segment_choices else None),
        gr.update(choices=entity_choices, value=None),
        gr.update(choices=entity_choices, value=None),
        gr.update(choices=entity_choices, value=None),
        f"待复核 {len(pending)} 段。选择段落查看原文证据；确认归属后需重新点击「确认剧本与角色参数」。",
    )


def role_review_details(file_obj, segment_id):
    script, report = _load_uploaded_role_script(file_obj)
    if not report.ok or not isinstance(script, RoleScriptV2) or not segment_id:
        return "请选择 V2 项目中的待复核段落。"
    for chapter in script.chapters:
        for segment in chapter.segments:
            if segment.segment_id != segment_id:
                continue
            speaker = segment.speaker
            evidence = "；".join(f"{item.kind}: {item.quote}" for item in speaker.evidence) if speaker else ""
            return (f"第 {chapter.chapter_index} 章 · `{segment_id}`\n\n"
                    f"原文：{segment.text}\n\n"
                    f"当前人物：`{speaker.entity_id if speaker else 'unknown'}`；"
                    f"状态：`{speaker.status if speaker else 'unknown'}`；"
                    f"未校准分数：{speaker.confidence if speaker else '无'}\n\n"
                    f"原文证据：{evidence or '无；请根据上下文人工判断'}")
    return "找不到指定段落。"


def apply_role_review(file_obj, operation, segment_id, entity_id, source_id, target_id):
    path = _uploaded_file_path(file_obj)
    project_root = os.path.abspath(os.path.join(get_output_dir(), ".role_projects"))
    if not path or not os.path.abspath(path).startswith(project_root + os.sep):
        return (gr.update(), gr.update(), "只能在自动生成的 V2 项目中保存人工复核。",
                False, "", gr.update(value=_role_confirmation_probe(False, "", gate=True)))
    script, report = _load_uploaded_role_script(path)
    if not report.ok or not isinstance(script, RoleScriptV2):
        return (gr.update(), gr.update(), "V2 项目读取失败。", False, "",
                gr.update(value=_role_confirmation_probe(False, "", gate=True)))
    try:
        if operation == "confirm":
            updated = confirm_segment_speaker(script, segment_id, entity_id)
        elif operation == "merge":
            updated = merge_entities(script, source_id, target_id)
        elif operation == "lock":
            updated = lock_entity_voice(script, entity_id)
        else:
            raise ValueError("未知复核操作")
        result = validate_role_script(updated)
        if not result.ok:
            raise ValueError(_format_role_validation_report(result.report, "复核后校验"))
        _forget_role_confirmation(path)
        save_project(result.script, path)
        queue = pending_segments(result.script)
        choices = [(f"第 {chapter} 章 · {excerpt}", sid) for sid, chapter, excerpt in queue]
        return (
            gr.update(choices=choices, value=choices[0][1] if choices else None),
            gr.update(value=_role_table_rows(result.script)),
            f"✅ 已保存复核；剩余 {len(queue)} 段待复核。请重新确认剧本后生成。",
            False, "", gr.update(value=_role_confirmation_probe(False, "", gate=True)),
        )
    except (ValueError, OSError) as exc:
        signature = _recall_role_confirmation(path)
        return (gr.update(), gr.update(), f"复核未保存：{exc}", bool(signature), signature,
                gr.update(value=_role_confirmation_probe(bool(signature), signature,
                                                         gate=not bool(signature))))


def calibrate_role_pace(provider, role_script_file, role_table, preview_text,
                        openai_model, mimo_voice, mimo_speed, mimo_instructions, mimo_stream):
    """同文试听、以旁白为基准测量倍率；全部成功后才回填，失败保留原表。"""
    from audiobook_generator.role_script.pace_calibration import calibrated_speeds

    unchanged = gr.update()
    if provider != "Mimo":
        return unchanged, "语速校准仅适用于 MiMo；MiniMax 可直接在角色表中调整 speed。"
    if running_process and running_process.is_alive():
        return unchanged, "请等待当前转换结束或停止后，再校准语速。"
    text = str(preview_text or "").strip()
    if len(text) < 20 or len(text) > 400:
        return unchanged, "请在试听文本中输入 20～400 字的完整句子；过短的文本难以测准语速。"
    work_dir = None
    try:
        script, report = _load_uploaded_role_script(role_script_file)
        if script is None or not report.ok:
            raise ValueError("请先生成或上传有效剧本")
        script = _apply_role_table(script, role_table)
        script, report = _validate_uploaded_role_script(script, provider, "wav")
        if script is None:
            raise ValueError(_format_role_validation_report(report).replace("**", ""))
        baseline = "narrator" if "narrator" in script.roles else next(iter(script.roles))
        config = GeneralConfig(None)
        config.tts, config.model_name = "openai", openai_model
        config.voice_name, config.speed = mimo_voice, mimo_speed
        config.instructions, config.stream = mimo_instructions, bool(mimo_stream)
        config.output_format = "wav"
        config.language = "en-US" if detect_role_script_language(script) == "en" else "zh-CN"
        provider_instance = get_tts_provider(config)
        root = os.path.join(get_output_dir(), ".role_preview")
        os.makedirs(root, exist_ok=True)
        work_dir = tempfile.mkdtemp(prefix="pace-calibration-", dir=root)
        durations = {}
        for role_id, role in script.roles.items():
            profile = VoiceProfile(role_id, role.display_name, dict(role.provider_params))
            artifact = provider_instance.synthesize_segment(text, profile, work_dir, None)
            durations[role_id] = artifact.duration_ms
        baseline_speed = float(script.roles[baseline].provider_params.get("speed", 1.0))
        speeds, limited = calibrated_speeds(durations, baseline, baseline_speed)
        rows = _role_table_rows(script)
        for row in rows:
            row[4] = speeds[row[0]]
        lines = [
            f"**已按{script.roles[baseline].display_name}的节奏校准。下一步：试听各角色，再确认剧本。**",
            "",
            "| 角色 | 原始试听时长 | 建议倍率 |", "| --- | --- | --- |",
        ]
        for role_id, role in script.roles.items():
            name = role.display_name.replace("|", "／").replace("\n", " ")
            lines.append(f"| {name} | {durations[role_id] / 1000:.2f} 秒 | {speeds[role_id]:.3f} |")
        lines.extend(["", "校准是同文时长估算，情绪和停顿仍可能影响正式对白；可继续手动微调 speed。"])
        if limited:
            lines.append("部分倍率已限制在 0.25～4.0，请重点试听：" + "、".join(limited))
        return gr.update(value=rows), "\n".join(lines)
    except Exception as exc:
        logger.warning("角色语速校准失败：%s", exc, exc_info=True)
        return unchanged, f"语速校准失败：{exc}。原有参数已保留，可调整后重试。"
    finally:
        if work_dir:
            shutil.rmtree(work_dir, ignore_errors=True)


def split_role_script_now(*args):
    """显式拆分按钮不受“上传后自动拆分”开关限制。"""
    values = list(args)
    values[2] = True
    return auto_split_role_script(*values)


def auto_split_role_script(
    input_file,
    role_mode,
    auto_role_split,
    provider,
    chapter_start,
    chapter_end,
    title_mode,
    new_line_mode,
    remove_endnotes,
    remove_reference_numbers,
    search_and_replace_file,
    deepseek_api_key,
    deepseek_base_url,
    deepseek_model,
    fullbook_index_ack=False,
):
    """上传书籍后调用 DeepSeek 生成待人工确认的剧本。

    函数只生成文件和校验摘要，不会启动 TTS。返回值中的确认状态始终为未确认，
    必须由用户点击「确认剧本与角色参数」后才能进入转换。
    """
    empty = (
        gr.update(),
        gr.update(value=[]),
        gr.update(value="**尚未自动拆分**"),
        gr.update(choices=[], value=None),
        gr.update(value=""),
        gr.update(visible=False),
        False,
        False,
        "",
        gr.update(value=_role_confirmation_probe(False)),
    )
    if not role_mode or not auto_role_split:
        return empty
    try:
        if not fullbook_index_ack:
            raise ValueError("请先确认：建立全书人物表会把未选择章节也提交给当前 DeepSeek 服务，并增加调用量")
        chapters, start, end, book_sha256, _book_parser = _auto_split_chapters(
            provider,
            input_file,
            chapter_start,
            chapter_end,
            title_mode,
            new_line_mode,
            remove_endnotes,
            remove_reference_numbers,
            search_and_replace_file,
        )
        report = ValidationReport(schema_version=2)
        fingerprint = parser_fingerprint({
            "title_mode": title_mode or "auto",
            "new_line_mode": new_line_mode or "single",
            "remove_endnotes": bool(remove_endnotes),
            "remove_reference_numbers": bool(remove_reference_numbers),
            "search_and_replace_sha256": (
                _sha256_file_ui(_uploaded_file_path(search_and_replace_file))
                if _uploaded_file_path(search_and_replace_file) else None
            ),
            "provider": _role_provider_id(provider),
        })
        script_path = project_path(get_output_dir(), book_sha256)
        previous = load_project(script_path, book_sha256=book_sha256)
        result = generate_v2_for_book(
            chapters,
            start,
            end,
            _role_provider_id(provider),
            book_sha256,
            deepseek_api_key,
            deepseek_base_url,
            deepseek_model,
            parser_fingerprint=fingerprint,
            previous=previous,
            progress=lambda message: logger.info("%s", message),
        )
        result = _ensure_role_voice_diversity(result, report)
        script_path = save_project(result, script_path)
        # 同一路径重新生成后，旧的“已确认”记录必须作废。
        _forget_role_confirmation(script_path)
        rows = _role_table_rows(result)
        choices = [
            f"{role_id} — {role.display_name}"
            for role_id, role in result.roles.items()
        ]
        validation_text = _format_role_validation_report(report, "DeepSeek 剧本校验")
        summary = _role_script_summary(result)
        summary += (
            "\n\n**请人工核对角色划分和逐章段数，确认前不会开始生成。**"
            f"\n\n{validation_text}"
        )
        return (
            gr.update(value=str(script_path)),
            gr.update(value=rows),
            gr.update(value=validation_text),
            gr.update(choices=choices, value=choices[0] if choices else None),
            gr.update(value=summary),
            gr.update(visible=True),
            False,
            True,
            "",
            gr.update(value=_role_confirmation_probe(False, "", gate=True)),
        )
    except Exception as exc:
        logger.warning("DeepSeek 自动拆分失败：%s", exc, exc_info=True)
        message = (
            "**❌ DeepSeek 自动拆分失败**\n\n"
            f"{exc}\n\n可以关闭自动拆分后手动上传 RoleScript JSON，或修正配置后重试。"
        )
        return (
            gr.update(),
            gr.update(value=[]),
            gr.update(value=message),
            gr.update(choices=[], value=None),
            gr.update(value=message),
            gr.update(visible=True),
            False,
            False,
            "",
            gr.update(value=_role_confirmation_probe(False)),
        )


def confirm_auto_role_script(
    role_script_file,
    role_table,
    provider,
    openai_output_format,
    minimax_output_format,
):
    """人工确认自动拆分结果；校验失败时保持未确认状态。"""
    script, load_report = _load_uploaded_role_script(role_script_file)
    if not load_report.ok or script is None:
        return (
            False,
            _format_role_validation_report(load_report, "确认前校验"),
            gr.update(),
            "",
            gr.update(value=_role_confirmation_probe(False, "", gate=True)),
        )
    try:
        script = _apply_role_table(script, role_table)
    except ValueError as exc:
        report = ValidationReport(schema_version=script.schema_version)
        report.error("invalid_role_table", "$.roles", str(exc))
        return (
            False,
            _format_role_validation_report(report, "确认前校验"),
            gr.update(),
            "",
            gr.update(value=_role_confirmation_probe(False, "", gate=True)),
        )
    diversity_report = ValidationReport(schema_version=script.schema_version)
    script = _ensure_role_voice_diversity(script, diversity_report)
    normalized, report = _validate_uploaded_role_script(
        script,
        provider,
        _selected_role_output_format(provider, openai_output_format, minimax_output_format),
    )
    report.warnings = list(diversity_report.warnings) + list(report.warnings)
    if normalized is None:
        return (
            False,
            _format_role_validation_report(report, "确认前校验"),
            gr.update(),
            "",
            gr.update(value=_role_confirmation_probe(False, "", gate=True)),
        )
    summary = _role_script_summary(normalized, "已确认使用的剧本")
    summary += "\n\n✅ 已确认。下一步：点击「返回生成页」，再点击「开始生成」。"
    summary += "\n\n" + _format_role_validation_report(report, "剧本校验")
    signature = _role_confirmation_signature(normalized)
    # 服务端记一份确认结果：后续 start 事件即便拿到被竞态覆盖的旧 State，
    # 也能凭“路径 + 内容指纹”识别为已确认。
    _remember_role_confirmation(role_script_file, signature)
    return (
        True,
        gr.update(value=summary),
        gr.update(value="✅ 已确认当前角色参数。"),
        signature,
        gr.update(value=_role_confirmation_probe(True, signature)),
    )


def manual_role_script_uploaded(
    role_script_file,
    provider,
    openai_output_format,
    minimax_output_format,
    role_split_confirmed=False,
    role_split_generated=False,
    role_confirmed_signature="",
):
    """手动上传剧本等同于人工确认，自动拆分面板显示摘要。"""
    # 自动拆分会把生成文件写回同一个 gr.File。这里的 change 事件也会随
    # 程序化更新触发，但自动拆分不是人工确认，必须保持确认按钮流程。
    uploaded_path = _uploaded_file_path(role_script_file)
    if not uploaded_path:
        return (
            gr.update(value=[]), "先生成剧本，或上传已有剧本。",
            gr.update(choices=[], value=None), gr.update(value=""),
            gr.update(visible=False), False, False, "",
            gr.update(value=_role_confirmation_probe(False)),
        )
    generated_roots = [
        os.path.abspath(os.path.join(get_output_dir(), name))
        for name in (".role_generated", ".role_projects")
    ]
    if uploaded_path and any(
        os.path.abspath(uploaded_path).startswith(root + os.sep) for root in generated_roots
    ):
        # 自动拆分写回文件时保持当前确认 State 不变。
        # gr.State 只接受原始值：这里必须把原值回传，不能返回 gr.update()，
        # 否则会把刚写入的 role_split_generated / role_confirmed_signature 冲掉。
        # 部分事件链会带着被旧快照覆盖的空 State 触发（表现为“已确认却又未确认”），
        # 这时用服务端确认记录兜底。
        recalled = _recall_role_confirmation(role_script_file)
        resolved_signature = str(role_confirmed_signature or "") or recalled
        resolved_confirmed = bool(role_split_confirmed) or bool(recalled)
        return (
            gr.update(),
            gr.update(),
            gr.update(),
            gr.update(),
            gr.update(),
            resolved_confirmed,
            bool(role_split_generated),
            resolved_signature,
            gr.update(
                value=_role_confirmation_probe(resolved_confirmed, resolved_signature)
            ),
        )

    script, load_report = _load_uploaded_role_script(role_script_file)
    if not load_report.ok or script is None:
        return (
            gr.update(value=[]),
            _format_role_validation_report(load_report, "角色剧本校验"),
            gr.update(choices=[], value=None),
            gr.update(value=_format_role_validation_report(load_report, "角色剧本校验")),
            gr.update(visible=True),
            False,
            False,
            "",
            gr.update(value=_role_confirmation_probe(False)),
        )
    script = _ensure_role_voice_diversity(script, load_report)
    normalized, report = _validate_uploaded_role_script(
        script,
        provider,
        _selected_role_output_format(provider, openai_output_format, minimax_output_format),
    )
    report.warnings = list(load_report.warnings) + list(report.warnings)
    rows = _role_table_rows(normalized or script)
    choices = [f"{role_id} — {role.display_name}" for role_id, role in (normalized or script).roles.items()]
    validation = _format_role_validation_report(report, "角色剧本校验")
    summary = _role_script_summary(normalized or script, "手动上传的剧本")
    summary += "\n\n✅ 已作为人工确认剧本使用。\n\n" + validation
    confirmed = normalized is not None
    signature = _role_confirmation_signature(normalized) if confirmed else ""
    if confirmed:
        _remember_role_confirmation(role_script_file, signature)
    return (
        gr.update(value=rows),
        gr.update(value=validation),
        gr.update(choices=choices, value=choices[0] if choices else None),
        gr.update(value=summary),
        gr.update(visible=True),
        confirmed,
        False,
        signature,
        gr.update(value=_role_confirmation_probe(confirmed, signature)),
    )


# ── 转换核心 ──────────────────────────────────────────────────────
def process_form(provider,
                 input_file, output_dir, worker_count, log_level, output_text, preview,
                 search_and_replace_file, title_mode, new_line_mode, chapter_start, chapter_end,
                 remove_endnotes, remove_reference_numbers,
                 model, voices, speed, openai_output_format, instructions, enable_stream,
                 minimax_model, minimax_voice, minimax_output_format,
                 edge_language, edge_voice, edge_output_format, proxy, edge_voice_rate,
                 edge_volume, edge_pitch, edge_break_duration,
                 qwen_language, qwen_voice,
                 chatterbox_model, chatterbox_device, chatterbox_output_format,
                 chatterbox_reference_audio, chatterbox_exaggeration, chatterbox_cfg_weight, chatterbox_speed,
                 voxcpm_model, voxcpm_mode, voxcpm_voice, voxcpm_voice_dir, voxcpm_voice_description,
                 voxcpm_regenerate_voice, voxcpm_reference_audio, voxcpm_reference_text, voxcpm_auto_transcribe,
                 voxcpm_device, voxcpm_denoise, voxcpm_normalize, voxcpm_cfg_value,
                 voxcpm_inference_timesteps, voxcpm_speed, voxcpm_chunk_chars, voxcpm_optimize,
                 voxcpm_output_format,
                 role_mode, auto_role_split, role_script_file, role_table,
                 role_split_confirmed, role_split_generated, role_confirmed_signature,
                 allow_role_text_override, allow_role_title_mismatch, allow_role_fallback,
                 role_quality_enabled=False, role_quality_max_rate=4.3,
                 role_quality_deepseek_api_key=None, role_quality_deepseek_base_url=None,
                 role_quality_deepseek_model=None):
    if not input_file:
        gr.Warning("请先选择至少一个书籍文件")
        # 保持进度条现状，只关掉轮询
        return gr.update(), gr.Timer(active=False)
    if not isinstance(input_file, list):
        input_file = [input_file]

    role_script = None
    if role_mode:
        if len(input_file) != 1:
            gr.Warning("角色模式首版只支持单本书，请只选择一个书籍文件")
            return gr.update(), gr.Timer(active=False)
        # 人工确认以“内容指纹”为准：确认按钮会写入 role_confirmed_signature，
        # 服务端再记一份（role_split_confirmed 布尔在 Gradio 事件竞态里可能被旧快照覆盖，
        # 只信布尔会出现“已确认却仍提示等待 DeepSeek”的假阴性）。
        confirmed_signature = str(role_confirmed_signature or "") or _recall_role_confirmation(
            role_script_file
        )
        if not role_split_confirmed and not confirmed_signature:
            if auto_role_split and role_split_generated:
                gr.Warning("自动拆分结果尚未人工确认，请先在高级设置中核对并点击「确认剧本与角色参数」")
            elif auto_role_split:
                gr.Warning("请先等待 DeepSeek 自动拆分完成，并在高级设置中人工确认")
            else:
                gr.Warning("请先手动上传剧本并在高级设置中完成人工确认")
            return gr.update(), gr.Timer(active=False)
        selected_output_format = _selected_role_output_format(
            provider, openai_output_format, minimax_output_format
        )
        uploaded_script, load_report = _load_uploaded_role_script(role_script_file)
        if not load_report.ok or uploaded_script is None:
            gr.Warning(_format_role_validation_report(load_report, "角色剧本校验").replace("**", ""))
            return gr.update(), gr.Timer(active=False)
        try:
            uploaded_script = _apply_role_table(uploaded_script, role_table)
        except ValueError as exc:
            gr.Warning(f"角色参数表无效：{exc}")
            return gr.update(), gr.Timer(active=False)
        diversity_report = ValidationReport(schema_version=uploaded_script.schema_version)
        uploaded_script = _ensure_role_voice_diversity(uploaded_script, diversity_report)
        role_script, validation_report = _validate_uploaded_role_script(
            uploaded_script, provider, selected_output_format
        )
        if role_script is None:
            gr.Warning(
                _format_role_validation_report(validation_report, "角色剧本校验").replace("**", "")
            )
            return gr.update(), gr.Timer(active=False)
        validation_report.warnings = list(diversity_report.warnings) + list(
            validation_report.warnings
        )
        current_signature = _role_confirmation_signature(role_script)
        if confirmed_signature and current_signature != confirmed_signature:
            gr.Warning("剧本内容已修改，请回到高级设置重新点击「确认剧本与角色参数」")
            return gr.update(), gr.Timer(active=False)

    # WebUI 里“开始生成”必须执行真实合成。预解析是普通模式的历史持久化开关，
    # 若角色模式仍透传 preview=True，核心层会只校验剧本后直接返回，表现为“立即完成但没有音频”。
    effective_preview = bool(preview) and not bool(role_mode)
    if role_mode and preview:
        gr.Warning("角色模式已忽略“预解析模式”，本次将执行真实语音合成。")
    elif effective_preview:
        gr.Warning("已开启预解析模式：本次只解析章节，不生成音频。需要音频请在高级设置中关闭此选项。")

    gr.Info("📋 预解析已开始，请查看日志。" if effective_preview else "🚀 有声书生成已开始！请在日志页查看实时进度。")

    configs = []
    for single_file in input_file:
        config = GeneralConfig(None)
        file_path = single_file.name if hasattr(single_file, 'name') else single_file
        config.input_file = file_path

        if len(input_file) > 1:
            book_name = Path(file_path).stem
            safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in book_name)
            config.output_folder = os.path.join(output_dir, safe_name)
        else:
            config.output_folder = output_dir

        config.preview = effective_preview
        config.output_text = output_text
        config.log = log_level
        config.worker_count = worker_count
        config.no_prompt = True
        config.title_mode = title_mode
        config.newline_mode = new_line_mode
        config.chapter_start = chapter_start
        config.chapter_end = chapter_end
        config.remove_endnotes = remove_endnotes
        config.remove_reference_numbers = remove_reference_numbers
        config.search_and_replace_file = (search_and_replace_file.name
                                          if hasattr(search_and_replace_file, 'name')
                                          else search_and_replace_file)
        config.role_script = role_script
        config.allow_role_text_override = bool(allow_role_text_override) if role_mode else False
        config.allow_role_title_mismatch = bool(allow_role_title_mismatch) if role_mode else False
        config.allow_role_fallback = bool(allow_role_fallback) if role_mode else False
        config.role_quality_enabled = bool(role_quality_enabled) if role_mode else False
        config.role_quality_max_rate = float(role_quality_max_rate or 4.3)
        config.role_quality_deepseek_api_key = role_quality_deepseek_api_key if role_mode else None
        config.role_quality_deepseek_base_url = role_quality_deepseek_base_url if role_mode else None
        config.role_quality_deepseek_model = role_quality_deepseek_model if role_mode else None
        if role_script is not None:
            config.language = (
                "en-US"
                if detect_role_script_language(role_script) == "en"
                else "zh-CN"
            )

        if provider == "Mimo":
            config.tts = "openai"
            config.output_format = openai_output_format
            config.voice_name = voices
            config.model_name = model
            config.instructions = instructions
            config.speed = speed
            config.stream = enable_stream
        elif provider == "MiniMax":
            config.tts = "minimax"
            config.model_name = minimax_model
            config.voice_name = get_minimax_voice_id_from_choice(minimax_voice)
            config.output_format = minimax_output_format
        elif provider == "Edge":
            config.tts = "edge"
            config.language = edge_language
            config.voice_name = edge_voice
            config.output_format = edge_output_format
            config.proxy = proxy
            config.voice_rate = f"{edge_voice_rate:+}%"
            config.voice_volume = f"{edge_volume:+}%"
            config.voice_pitch = f"{edge_pitch:+}Hz"
            config.break_duration = edge_break_duration
        elif provider == "Qwen":
            config.tts = "qwen"
            config.language = qwen_language
            config.voice_name = qwen_voice
        elif provider == "Chatterbox":
            config.tts = "chatterbox"
            config.model_name = chatterbox_model
            config.output_format = chatterbox_output_format
            config.chatterbox_device = chatterbox_device
            config.chatterbox_reference_audio = (chatterbox_reference_audio.name
                                                 if hasattr(chatterbox_reference_audio, 'name')
                                                 else chatterbox_reference_audio)
            config.chatterbox_exaggeration = chatterbox_exaggeration
            config.chatterbox_cfg_weight = chatterbox_cfg_weight
            config.chatterbox_speed = chatterbox_speed
        elif provider == "VoxCPM":
            config.tts = "voxcpm"
            config.model_name = voxcpm_model
            config.output_format = voxcpm_output_format
            config.voxcpm_device = voxcpm_device
            config.voxcpm_mode = voxcpm_mode
            config.voxcpm_voice = voxcpm_voice
            config.voxcpm_voice_dir = voxcpm_voice_dir
            config.voxcpm_voice_description = voxcpm_voice_description
            config.voxcpm_regenerate_voice = voxcpm_regenerate_voice
            config.voxcpm_reference_audio = (voxcpm_reference_audio.name
                                             if hasattr(voxcpm_reference_audio, 'name')
                                             else voxcpm_reference_audio)
            config.voxcpm_reference_text = voxcpm_reference_text
            config.voxcpm_auto_transcribe = voxcpm_auto_transcribe
            config.voxcpm_denoise = voxcpm_denoise
            config.voxcpm_normalize = voxcpm_normalize
            config.voxcpm_cfg_value = voxcpm_cfg_value
            config.voxcpm_inference_timesteps = voxcpm_inference_timesteps
            config.voxcpm_speed = voxcpm_speed
            config.voxcpm_chunk_chars = voxcpm_chunk_chars
            config.voxcpm_optimize = voxcpm_optimize
        else:
            raise ValueError("Unsupported TTS provider selected")

        configs.append(config)

    launch_batch(configs)
    # 立刻推送一次状态：新批次会把进度条重置为"正在启动 0%"（不用等下一次轮询）
    return get_progress_info()


def _get_batch_logger(log_file_path):
    """批处理子进程专用 logger：同时写日志文件和终端。

    主界面顶部的进度条依赖日志文件里的「开始转换 / 全部处理完毕」标记，
    而这些信息原本只是 print 到终端，所以这里改成 logger 输出。
    """
    batch_logger = logging.getLogger("webui.batch")
    batch_logger.setLevel(logging.INFO)
    batch_logger.propagate = False
    for handler in list(batch_logger.handlers):
        batch_logger.removeHandler(handler)

    formatter = logging.Formatter("%(asctime)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    batch_logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    batch_logger.addHandler(stream_handler)
    return batch_logger


def _batch_worker(config_list, log_file_path):
    """子进程逐个处理每个 EPUB（须在模块顶层以便 spawn pickle）。"""
    # 自成进程组/会话：章节 worker（进程池）会继承这个进程组，
    # 这样点「停止转换」时可以用 killpg 一次性终止批处理进程连同所有 worker
    # （只 terminate 批处理进程的话，正在合成的 worker 会变成孤儿继续跑，表现为"停止无效"）。
    try:
        os.setsid()
    except OSError:
        pass
    batch_logger = _get_batch_logger(log_file_path)
    total = len(config_list)
    failed = 0
    for idx, cfg in enumerate(config_list):
        book_name = Path(cfg.input_file).stem
        batch_logger.info("=" * 60)
        batch_logger.info(f"📚 [{idx + 1}/{total}] 开始转换: {book_name}")
        batch_logger.info("=" * 60)
        try:
            if main(cfg, log_file_path) is not True:
                raise RuntimeError("转换未成功完成，请查看前面的章节错误日志")
            if cfg.preview:
                batch_logger.info(f"📋 [{idx + 1}/{total}] 预解析完成（未生成音频）: {book_name}")
            else:
                batch_logger.info(f"✅ [{idx + 1}/{total}] 完成: {book_name}")
        except Exception as e:
            failed += 1
            batch_logger.error(f"❌ [{idx + 1}/{total}] 失败: {book_name} — {e}")
    if failed:
        batch_logger.error(f"❌ 批次处理失败：{failed}/{total} 本书失败，请查看日志")
    else:
        batch_logger.info(f"🎉 全部处理完毕！共 {total} 本书")


def launch_batch(configs):
    global running_process, manual_stopped
    if running_process and running_process.is_alive():
        print("Audiobook generator already running")
        return
    manual_stopped = False
    # 必须用 spawn 启动：Gradio 主进程在构建 UI（设备下拉框）时会探测 CUDA，
    # fork 出来的子进程继承该状态后无法再用 GPU，详见 audiobook_generator.py 中的说明。
    running_process = get_context("spawn").Process(
        target=_batch_worker, args=(configs, str(webui_log_file.absolute()))
    )
    running_process.start()



def get_progress_info():
    """解析日志文件获取生成进度，返回给前端的结构化状态 + 定时器开关。

    注意：这里只把状态以 JSON 形式塞进一个隐藏的载荷组件，可见的进度条 DOM 由页面里
    的脚本就地更新（见 HEAD_HTML）。早期实现是每 2 秒整块替换进度条 HTML，导致
    shimmer 等 CSS 动画每 2 秒重新播放一次，看起来"一闪一闪"。
    """
    global webui_log_file
    run_alive = running_process is not None and running_process.is_alive()

    state = None
    if webui_log_file and webui_log_file.exists():
        try:
            state = parse_progress(webui_log_file.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            state = None

    payload = decide_progress_state(state, run_alive, batch_started=running_process is not None,
                                    manually_stopped=manual_stopped)
    return json.dumps(payload, ensure_ascii=False), gr.Timer(active=payload["active"])


def _progress_scaffold_html():
    """进度条骨架：只在页面构建时渲染一次，之后全部由前端脚本就地更新。

    结构保持稳定是"动画连续、不闪烁"的前提（每次替换 DOM 都会让 CSS 动画重新开始）。
    """
    return """<div class="progress-container idle" id="progress_container">
        <div class="progress-header">
            <span class="progress-status" id="progress_status">等待开始生成...</span>
            <span class="progress-detail" id="progress_detail"></span>
            <span class="progress-pct" id="progress_pct">0%</span>
        </div>
        <div class="progress-book" id="progress_book" style="display:none"></div>
        <div class="progress-track"><div class="progress-fill" id="progress_fill" style="width:0%"></div></div>
    </div>"""

def _terminate_running_batch(timeout=3.0):
    """终止当前批处理进程**及其所有子孙**（章节进程池 worker），返回是否真的停掉了东西。

    之前只调 running_process.terminate()：那样只会杀掉批处理进程本身，
    真正在合成音频的 worker（spawn 出来的孙进程）会变成孤儿继续跑，
    所以看起来"停止按钮没反应"——尤其是 chatterbox/GPU 这类单章很慢的引擎。
    """
    global running_process, manual_stopped
    proc = running_process
    if proc is None:
        return False

    if not proc.is_alive():
        running_process = None
        return False

    pid = proc.pid
    try:
        pgid = os.getpgid(pid)
    except (ProcessLookupError, PermissionError):
        pgid = None

    # 1) 先整组 SIGTERM，给它机会自己收尾
    try:
        if pgid:
            os.killpg(pgid, signal.SIGTERM)
        else:
            proc.terminate()
    except (ProcessLookupError, PermissionError):
        pass

    deadline = time.time() + timeout
    while time.time() < deadline and proc.is_alive():
        time.sleep(0.1)

    # 2) 还赖着就整组 SIGKILL（GPU 合成卡在 CUDA 调用里时常见）
    if proc.is_alive():
        try:
            if pgid:
                os.killpg(pgid, signal.SIGKILL)
            else:
                proc.kill()
        except (ProcessLookupError, PermissionError):
            pass
        proc.join(timeout=2)

    running_process = None
    manual_stopped = True
    return True


def terminate_generator():
    stopped = _terminate_running_batch()
    if stopped:
        _append_log_line("⏹ 已手动停止当前生成（批次进程与章节 worker 已终止）")
    return get_progress_info()[0], gr.Timer(active=False)


def _append_log_line(message):
    """把一行提示写进当前 WebUI 日志文件（父进程没有配置 logger，直接追加）"""
    try:
        if webui_log_file:
            with open(webui_log_file, "a", encoding="utf-8") as fh:
                fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {message}\n")
    except Exception:
        pass


# ── 资源库管理 ────────────────────────────────────────────────────
def _placeholder_html(msg="请在左侧选择批次并勾选文件<br>支持多选，点击按钮打包下载"):
    return f'''
    <div class="lib-empty">
        <div class="lib-empty-icon">📁</div>
        <div class="lib-empty-text">{msg}</div>
    </div>'''


def delete_entire_folder(folder_name):
    if not folder_name:
        return (gr.update(), gr.update(choices=[], value=[]),
                gr.update(value=_placeholder_html("未选择任何批次")), gr.update(visible=False))
    folder_path = os.path.join(get_output_dir(), folder_name)
    if os.path.exists(folder_path) and os.path.isdir(folder_path):
        try:
            shutil.rmtree(folder_path, ignore_errors=True)
        except Exception as e:
            print(f"删除文件夹失败: {e}")
    new_folders = get_folders_list()
    new_val = new_folders[0] if new_folders else None
    new_files = get_files_in_folder(new_val) if new_val else []
    msg = f"批次 <b style='color:#ff3b30;'>{folder_name}</b> 已被整体删除"
    return (gr.update(choices=new_folders, value=new_val),
            gr.update(choices=new_files, value=new_files),
            gr.update(value=_placeholder_html(msg)), gr.update(value=None, visible=False))


def delete_selected_files(folder_name, selected_files):
    if not folder_name or not selected_files:
        return (gr.update(), gr.update(),
                gr.update(value=_placeholder_html("未选择任何文件，无需删除")), gr.update(visible=False))
    if isinstance(selected_files, str):
        selected_files = [selected_files]
    folder_path = os.path.join(get_output_dir(), folder_name)
    deleted = 0
    for file_name in selected_files:
        abs_path = os.path.join(folder_path, file_name)
        if os.path.isfile(abs_path):
            try:
                os.remove(abs_path)
                deleted += 1
            except Exception:
                pass
    folder_deleted = False
    if os.path.exists(folder_path) and not os.listdir(folder_path):
        try:
            os.rmdir(folder_path)
            folder_deleted = True
        except Exception:
            pass
    if folder_deleted:
        new_folders = get_folders_list()
        new_val = new_folders[0] if new_folders else None
        new_files = get_files_in_folder(new_val) if new_val else []
        return (gr.update(choices=new_folders, value=new_val),
                gr.update(choices=new_files, value=new_files),
                gr.update(value=_placeholder_html("文件已清空，系统已自动回收空文件夹")),
                gr.update(visible=False))
    new_files = get_files_in_folder(folder_name)
    return (gr.update(), gr.update(choices=new_files, value=[]),
            gr.update(value=_placeholder_html(f"已成功删除 {deleted} 个文件")),
            gr.update(visible=False))


def generate_download(folder_name, selected_files, auto_delete):
    if not folder_name or not selected_files:
        return (gr.update(), gr.update(),
                gr.update(value=_placeholder_html("请至少选择一个文件进行打包")), gr.update(visible=False))
    if isinstance(selected_files, str):
        selected_files = [selected_files]
    folder_path = os.path.join(get_output_dir(), folder_name)

    def _prompt(display_name, warning=""):
        return f'''
        <div class="lib-ready">
            <div class="lib-ready-icon">✅</div>
            <h3>资源组装完毕</h3>
            <p>{display_name}<br><b>👇 点击下方文件名即可开始下载</b></p>
            {warning}
        </div>'''

    temp_dir = os.path.join(get_output_dir(), ".temp_downloads")
    os.makedirs(temp_dir, exist_ok=True)
    timestamp = int(datetime.now().timestamp())
    serve_file_path = None
    display_name = ""

    if len(selected_files) == 1:
        file_name = selected_files[0]
        abs_path = os.path.join(folder_path, file_name)
        if os.path.isfile(abs_path):
            temp_file_path = os.path.join(temp_dir, f"{timestamp}_{file_name}")
            shutil.copy2(abs_path, temp_file_path)
            serve_file_path = temp_file_path
            display_name = f"待下载文件：<b>{file_name}</b>"
    else:
        zip_filename = f"{folder_name}_Export_{timestamp}.zip"
        zip_filepath = os.path.join(temp_dir, zip_filename)
        with zipfile.ZipFile(zip_filepath, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for file_name in selected_files:
                abs_path = os.path.join(folder_path, file_name)
                if os.path.isfile(abs_path):
                    zipf.write(abs_path, arcname=file_name)
        serve_file_path = zip_filepath
        display_name = f"已将 <b style='font-size:1.1em;'>{len(selected_files)}</b> 个文件打包为 ZIP"

    warning_html = ""
    folder_update = gr.update()
    checkbox_update = gr.update()

    if auto_delete:
        for file_name in selected_files:
            abs_path = os.path.join(folder_path, file_name)
            if os.path.isfile(abs_path):
                try:
                    os.remove(abs_path)
                except Exception:
                    pass
        folder_deleted = False
        if os.path.exists(folder_path) and not os.listdir(folder_path):
            try:
                os.rmdir(folder_path)
                folder_deleted = True
            except Exception:
                pass
        if folder_deleted:
            new_folders = get_folders_list()
            new_val = new_folders[0] if new_folders else None
            new_files = get_files_in_folder(new_val) if new_val else []
            folder_update = gr.update(choices=new_folders, value=new_val)
            checkbox_update = gr.update(choices=new_files, value=new_files)
            warning_html = '<div class="lib-warn">⚠️ 阅后即焚已触发：源文件及空文件夹已删除，请保存下方副本</div>'
        else:
            new_files = get_files_in_folder(folder_name)
            checkbox_update = gr.update(choices=new_files, value=[])
            warning_html = '<div class="lib-warn">⚠️ 源文件已自动删除，请及时保存下方副本</div>'

    return (folder_update, checkbox_update, gr.update(value=_prompt(display_name, warning_html)),
            gr.update(value=serve_file_path, visible=True))


def refresh_batches():
    return gr.update(choices=get_folders_list(), value=None), gr.update(choices=[], value=[])


def load_files_for_folder(folder_name):
    files = get_files_in_folder(folder_name)
    return gr.update(choices=files, value=files)


# ── 样式 ──────────────────────────────────────────────────────────
# 页面级脚本：
# 0) 氛围背景层（光晕 + 鼠标交互 + 生成态切换）——实现见 ambient_background.py；
# 1) 进度条"就地更新"——服务端只推一个隐藏的状态载荷，可见 DOM 不再每 2 秒被整块替换，
#    这样 shimmer / 宽度过渡等动画可以连续播放，不会出现"一闪一闪"；
# 2) 指针交互：卡片跟随鼠标的高光、按钮点击水波纹；
# 3) 供按钮 js= 调用：点击「开始生成」后平滑滚动到顶部进度条。
HEAD_HTML = AMBIENT_LAYER_HTML + THEME_HEAD_HTML + """
<script>
(function () {
  function $(sel, root) { return (root || document).querySelector(sel); }

  var lastPct = null;
  var lastPayloadKey = null;   // 去重：相同状态不重复应用，否则收起定时器会被反复重置
  // 本次页面会话里是否见过"批次真的在跑"。日志文件在服务进程启动时创建一次、之后一直累积，
  // 批次跑完后 decide_progress_state() 会一直返回 finished/interrupted/failed；如果不加这道闸门，
  // 每次新开浏览器都会把"上一个文件已完成/已中断"的卡片弹出来闪一下（用户反馈过）。
  var sawActive = false;
  // 结束后自动收起：完成态展示 6 秒、异常/停止态展示 12 秒，然后淡出并把高度收到 0，
  // 不再占着页面顶部；下一次点「开始生成」会立刻重新展开。
  var HIDE_DELAY = { finished: 6000, book_done: 6000, interrupted: 12000, failed: 12000 };
  var hideTimer = null;

  function progressBox() { return $('#progress_container'); }

  function revealProgress() {
    var box = progressBox();
    if (!box) return;
    if (hideTimer) { window.clearTimeout(hideTimer); hideTimer = null; }
    box.style.maxHeight = '';
    box.classList.remove('collapsed');
    box.removeAttribute('aria-hidden');
  }

  function scheduleHide(mode) {
    if (hideTimer) { window.clearTimeout(hideTimer); hideTimer = null; }
    var delay = HIDE_DELAY[mode];
    if (!delay) return;
    hideTimer = window.setTimeout(function () {
      var box = progressBox();
      if (!box) return;
      box.style.maxHeight = box.scrollHeight + 'px';   // 先固定当前高度，才能平滑收拢
      window.requestAnimationFrame(function () {
        box.classList.add('collapsed');
        box.setAttribute('aria-hidden', 'true');       // 收起后对读屏软件也隐藏
      });
    }, delay);
  }

  function applyProgress(payload) {
    var box = progressBox();
    if (!box) return;
    var payloadKey = JSON.stringify(payload);
    if (payloadKey === lastPayloadKey) return;   // 状态没变化（含 boot() 的重复绑定）→ 不做任何事
    lastPayloadKey = payloadKey;
    var mode = payload.mode || 'idle';
    // 实时状态（正在启动/生成中/本书完成）→ 记住"这个会话见过它在跑"；
    // 终态（完成/中断/失败）而本次会话没见过它在跑 → 是上一个批次留下的残留，直接忽略：
    // 不改类名、不展开卡片、不排收起定时器，也就不会触发背景的跑马灯。
    if (mode === 'starting' || mode === 'running' || mode === 'book_done') {
      sawActive = true;
    } else if (mode === 'finished' || mode === 'interrupted' || mode === 'failed') {
      if (!sawActive) return;
    }
    box.classList.remove('idle', 'active', 'starting', 'running', 'done', 'warn');
    if (mode === 'idle') box.classList.add('idle');
    else if (mode === 'starting') box.classList.add('active', 'starting');
    else if (mode === 'finished' || mode === 'book_done') box.classList.add('active', 'done');
    else if (mode === 'interrupted' || mode === 'failed') box.classList.add('active', 'warn');
    else box.classList.add('active', 'running');

    var status = $('#progress_status');
    var detail = $('#progress_detail');
    var pctEl = $('#progress_pct');
    var bookEl = $('#progress_book');
    var fill = $('#progress_fill');
    if (status && status.textContent !== (payload.status || '')) status.textContent = payload.status || '';
    if (detail) detail.textContent = payload.detail || '';

    var pct = Math.max(0, Math.min(100, Number(payload.pct) || 0));
    if (pctEl) pctEl.textContent = pct + '%';
    if (bookEl) {
      var showBook = !!payload.book && mode !== 'idle';
      bookEl.style.display = showBook ? 'inline-block' : 'none';
      if (showBook) bookEl.textContent = '📖 ' + payload.book;
    }
    if (fill) fill.style.width = pct + '%';

    if (lastPct !== null && pct !== lastPct) {
      box.classList.remove('bump');
      void box.offsetWidth;               // 触发重排，让 bump 动画可以重复播放
      box.classList.add('bump');
      window.setTimeout(function () { box.classList.remove('bump'); }, 520);
    }
    lastPct = pct;
    revealProgress();
    scheduleHide(mode);
  }

  function readState() {
    var node = $('#progress_state');
    if (!node) return null;
    var raw = (node.textContent || '').trim();
    if (!raw) return null;
    try { return JSON.parse(raw); } catch (err) { return null; }
  }

  var observer = null;
  function bindProgress() {
    var node = $('#progress_state');
    if (!node) return;
    var fresh = observer === null || node.dataset.ataProgressBound !== '1';
    if (fresh) {
      node.dataset.ataProgressBound = '1';
      if (observer) observer.disconnect();
      observer = new MutationObserver(function () {
        var payload = readState();
        if (payload) applyProgress(payload);
      });
      observer.observe(node, { childList: true, subtree: true, characterData: true });
    }
    var payload = readState();
    if (payload) applyProgress(payload);
  }

  var roleVerificationObserver = null;

  function roleVerificationReady(panel) {
    if (!panel) return false;
    // 不能检查 getClientRects()：核验面板位于高级设置弹窗内，自动拆分完成时
    // 弹窗可能仍是 display:none，祖先不可见会让面板的 rects 全部为 0，
    // 结果永远无法触发弹窗。这里只看面板自身的 Gradio 可见性。
    var style = window.getComputedStyle(panel);
    return style.display !== 'none' && style.visibility !== 'hidden';
  }

  function roleVerificationKey(panel) {
    // 同一份结果在自动弹出前后可能呈现不同缩进/换行，必须压缩全部空白，
    // 否则“已关闭指纹”与 observer 重新计算的指纹不一致，会反复自动弹窗。
    return ((panel && panel.innerText) || '')
      .replace(/\\s+/g, ' ')
      .trim()
      .slice(0, 600);
  }

  function revealRoleVerification() {
    syncRoleGate();
    var panel = $('#role_verification_panel');
    if (!panel) return;

    // 面板隐藏时清空标记，下一次自动拆分完成后仍会再次弹出。
    if (!roleVerificationReady(panel)) {
      delete panel.dataset.ataAutoOpenedKey;
      return;
    }

    // 以核验摘要文本作为一次拆分结果的身份，避免用户手动关闭弹窗后，
    // 页面其它 DOM 更新又把它强行弹回来；重新生成后摘要变化则自动再弹出。
    var key = roleVerificationKey(panel);
    if (!key || panel.dataset.ataAutoOpenedKey === key) return;
    // 用户主动关闭同一份核验结果后，页面其它 DOM 更新不应把它再次弹回来；
    // 重新生成会得到新的摘要 key，因此仍能正常自动弹出。
    if (document.body.dataset.ataRoleVerificationDismissed === key) return;
    panel.dataset.ataAutoOpenedKey = key;

    var modal = $('#advanced_modal');
    if (!modal) return;
    // 自动核验弹窗也必须记录底层页面位置，否则用户从弹窗底部点“完成”
    // 时 closeAdvancedModal() 会回退到默认的 0，看起来像页面突然跳到顶部。
    if (!document.body.classList.contains('modal-open')) {
      openAdvancedModal();
    }
    modal.classList.add('show');
    document.body.classList.add('modal-open');

    // 等 Gradio / 浏览器完成一次布局后再在弹窗内部滚动，避免引发布局抖动。
    window.setTimeout(function () {
      var scroller = modal.querySelector('.modal-scroll');
      if (!scroller) return;
      var reviewTarget = roleGateActive() ? $('#role_parameter_table') : panel;
      var panelRect = (reviewTarget || panel).getBoundingClientRect();
      var scrollerRect = scroller.getBoundingClientRect();
      var targetTop = scroller.scrollTop + panelRect.top - scrollerRect.top - 16;
      scroller.scrollTo({ top: Math.max(0, targetTop), behavior: 'smooth' });
    }, 180);
  }

  function bindRoleVerification() {
    if (roleVerificationObserver === null) {
      roleVerificationObserver = new MutationObserver(revealRoleVerification);
      roleVerificationObserver.observe(document.body, {
        subtree: true, childList: true, attributes: true,
        attributeFilter: ['style', 'class']
      });
    }
    revealRoleVerification();
  }

  function currentPageScroll() {
    return window.scrollY || document.documentElement.scrollTop || 0;
  }

  // 经典“固定 body”滚动锁：弹窗打开期间把 body 钉在打开时的偏移上。
  // 这样 Gradio 的任何重排/焦点切换都无法偷偷把底层页面顶回页首，
  // 关闭时再按记录值原样还原（历史实现只靠 overflow:hidden，
  // 布局变化后仍会出现“点完成整页回到顶部”）。
  function lockPageScroll() {
    var y = currentPageScroll();
    document.body.dataset.ataModalScrollY = String(y);
    document.body.dataset.ataUserScrolled = '0';
    document.body.style.position = 'fixed';
    document.body.style.top = (-y) + 'px';
    document.body.style.left = '0';
    document.body.style.right = '0';
    document.body.style.width = '100%';
  }

  function unlockPageScroll() {
    var y = Number(document.body.dataset.ataModalScrollY || '0');
    if (!isFinite(y) || y < 0) y = 0;
    document.body.style.position = '';
    document.body.style.top = '';
    document.body.style.left = '';
    document.body.style.right = '';
    document.body.style.width = '';
    return y;
  }

  function openAdvancedModal(event) {
    if (event) {
      event.preventDefault();
      event.stopPropagation();
    }
    var modal = $('#advanced_modal');
    if (!modal) return;
    // 自动核验可能重复调用这里；弹窗已打开时不能再次覆盖快照，
    // 否则会把记录值覆盖成“锁定后”的偏移（恒为 0），关闭时跳回页首。
    var alreadyLocked = document.body.classList.contains('modal-open');
    if (!alreadyLocked) {
      lockPageScroll();
    }
    modal.classList.add('show');
    modal.style.setProperty('background-color', 'transparent', 'important');
    modal.style.setProperty('--block-background-fill', 'transparent', 'important');
    modal.style.setProperty('--group-background-fill', 'transparent', 'important');
    document.body.classList.add('modal-open');
    syncRoleGate();
  }

  // 只有“存在尚未人工确认、但已生成好的自动拆分剧本”时才拦一下“完成”按钮：
  // 直接放行会掉进一个随后必然失败的状态（点开始生成才提示未确认）。
  // 右上角 ✕ 仍然可以强制关闭，避免剧本校验始终不通过时把用户困在弹窗里。
  function roleGateActive() {
    var probe = document.getElementById('role_confirmation_probe');
    if (!probe) return false;
    if (probe.getAttribute('data-gate') !== '1') return false;
    return probe.getAttribute('data-confirmed') !== '1';
  }

  // 自动拆分结果未确认时直接禁用“完成”按钮：既给出明确的视觉反馈，
  // 也避免点击后仅看到提示却仍停留在原状态（并连带触发布局回弹）。
  function syncRoleGate() {
    var doneBtn = document.querySelector('#advanced_modal .modal-done');
    if (!doneBtn) return;
    if (roleGateActive()) {
      if (!doneBtn.disabled) doneBtn.disabled = true;
      if (doneBtn.getAttribute('aria-disabled') !== 'true') doneBtn.setAttribute('aria-disabled', 'true');
      if (!doneBtn.classList.contains('is-gated')) doneBtn.classList.add('is-gated');
      doneBtn.title = '自动拆分结果尚未人工确认，请先点击「确认剧本与角色参数」';
    } else {
      if (doneBtn.disabled) doneBtn.disabled = false;
      if (doneBtn.hasAttribute('aria-disabled')) doneBtn.removeAttribute('aria-disabled');
      if (doneBtn.classList.contains('is-gated')) doneBtn.classList.remove('is-gated');
      doneBtn.removeAttribute('title');
    }
    var hint = document.getElementById('role_workflow_hint');
    var probe = document.getElementById('role_confirmation_probe');
    var message = roleGateActive()
      ? '下一步：调整音色并试听，再点击「确认剧本与角色参数」。'
      : (probe && probe.getAttribute('data-confirmed') === '1'
        ? '已确认。下一步：返回生成页，点击「开始生成」。'
        : '下一步：先生成剧本，或上传已有剧本。');
    // observer 也监听子节点；仅在内容变化时写 DOM，防止自触发死循环。
    if (hint && hint.textContent !== message) hint.textContent = message;
    var gateHint = document.getElementById('role_gate_hint');
    if (gateHint) {
      var gateMessage = roleGateActive() ? '请先在第 3 步确认剧本与角色参数。' : '';
      if (gateHint.textContent !== gateMessage) gateHint.textContent = gateMessage;
      var display = gateMessage ? 'block' : 'none';
      if (gateHint.style.display !== display) gateHint.style.display = display;
    }
  }

  function showRoleGateHint() {
    var hint = document.getElementById('role_gate_hint');
    if (!hint) return;
    hint.textContent = '自动拆分结果尚未人工确认：请先核对下方角色表并点击「确认剧本与角色参数」，再点“完成”。';
    hint.style.display = 'block';
    var modal = $('#advanced_modal');
    var panel = document.getElementById('role_verification_panel');
    if (modal && panel) {
      var scroller = modal.querySelector('.modal-scroll');
      if (scroller) {
        var panelRect = panel.getBoundingClientRect();
        var scrollerRect = scroller.getBoundingClientRect();
        var targetTop = scroller.scrollTop + panelRect.top - scrollerRect.top - 16;
        scroller.scrollTo({ top: Math.max(0, targetTop), behavior: 'smooth' });
      }
    }
  }

  function closeAdvancedModal(event) {
    var forceClose = !!(event && event.currentTarget &&
      event.currentTarget.classList &&
      event.currentTarget.classList.contains('modal-close-btn'));
    if (!forceClose && roleGateActive()) {
      if (event) {
        event.preventDefault();
        event.stopPropagation();
      }
      showRoleGateHint();
      return;
    }
    if (event) {
      event.preventDefault();
      event.stopPropagation();
    }
    var modal = $('#advanced_modal');
    if (!modal) return;
    var gateHint = document.getElementById('role_gate_hint');
    if (gateHint) gateHint.style.display = 'none';
    var verificationPanel = $('#role_verification_panel');
    if (verificationPanel) {
      var verificationKey = roleVerificationKey(verificationPanel);
      if (verificationKey) {
        document.body.dataset.ataRoleVerificationDismissed = verificationKey;
      }
    }
    modal.classList.remove('show');
    document.body.classList.remove('modal-open');
    var savedScroll = unlockPageScroll();
    var restoreScroll = function () {
      if (document.body.classList.contains('modal-open')) return;
      // 用户已经主动滚动时不再强行拉回，避免和用户操作打架。
      if (document.body.dataset.ataUserScrolled === '1') return;
      var top = Math.max(0, savedScroll);
      if (Math.abs(currentPageScroll() - top) <= 2) return;
      window.scrollTo({ top: top, left: 0, behavior: 'auto' });
      document.documentElement.scrollTop = top;
      document.body.scrollTop = top;
    };
    // Gradio 关闭弹窗后会重建/重排部分组件（表格、Markdown、日志），
    // 单次还原会被后续布局回跳覆盖；在 1s 内多点补几次，且一旦用户开始
    // 滚动就立刻让位。
    window.requestAnimationFrame(restoreScroll);
    [60, 140, 280, 480, 800, 1100].forEach(function (delay) {
      window.setTimeout(restoreScroll, delay);
    });
  }

  window.openAdvancedModal = openAdvancedModal;
  window.closeAdvancedModal = closeAdvancedModal;

  function bindInteractions() {
    if (document.body.dataset.ataInteractions === '1') return;
    document.body.dataset.ataInteractions = '1';

    // 用户在页面（弹窗之外）主动滚动后，关闭弹窗的“还原页面位置”就让位，
    // 避免和用户操作抢滚动。注意：弹窗内部的滚动 / 输入框打字都不算，
    // 否则一次正常的弹窗内操作会导致关闭时页面停在顶部。
    ['wheel', 'touchstart'].forEach(function (evt) {
      window.addEventListener(evt, function (event) {
        if (document.body.classList.contains('modal-open')) return;
        var modal = document.getElementById('advanced_modal');
        if (modal && event.target && modal.contains(event.target)) return;
        document.body.dataset.ataUserScrolled = '1';
      }, { passive: true });
    });

    // 按钮：点击水波纹
    document.addEventListener('pointerdown', function (event) {
      // 多角色模式是核心入口，单独做一次回弹 + 光晕反馈，和普通开关拉开层级。
      var roleSwitch = event.target && event.target.closest && event.target.closest('.advanced-switch');
      if (roleSwitch) {
        roleSwitch.classList.remove('is-switching');
        void roleSwitch.offsetWidth;
        roleSwitch.classList.add('is-switching');
        window.setTimeout(function () { roleSwitch.classList.remove('is-switching'); }, 560);
      }

      var btn = event.target && event.target.closest && event.target.closest(
        '.btn-primary, .btn-ghost, .btn-mini, .btn-danger, .tab-nav button, .engine-tab');
      if (!btn || btn.disabled) return;
      var rect = btn.getBoundingClientRect();
      var ink = document.createElement('span');
      ink.className = 'ata-ripple';
      ink.style.left = (event.clientX - rect.left) + 'px';
      ink.style.top = (event.clientY - rect.top) + 'px';
      btn.appendChild(ink);
      window.setTimeout(function () { if (ink.parentNode) ink.parentNode.removeChild(ink); }, 640);
    }, { passive: true });

    // 「开始生成」按钮：点击后整页平滑滑回最顶端（进度条就在顶部区域）
    // 注意：这里用原生监听实现，而不是 Gradio 事件的 js=（后者会把表单输入变成空值）
    document.addEventListener('click', function (event) {
      var btn = event.target && event.target.closest && event.target.closest('.btn-primary');
      if (!btn || !btn.textContent || btn.textContent.indexOf('开始生成') < 0) return;
      // 只滚动，不强行展开：真正展开由新的状态载荷触发（例如"正在启动"），
      // 这样若表单校验失败（没选文件）也不会把已经收起的进度条留在页面上。
      window.setTimeout(function () {
        window.scrollTo({ top: 0, behavior: 'smooth' });
      }, 120);
    }, true);
  }

  function boot() {
    bindProgress();
    bindRoleVerification();
    bindInteractions();
    syncRoleGate();
  }

  // 供「开始生成」按钮的 js= 调用：平滑滚动到进度条
  window.__ataScrollToProgress = function () {
    revealProgress();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
  // Gradio 是渐进渲染的，组件可能稍后才挂载；轻量重试避免漏绑
  window.setTimeout(boot, 600);
  window.setTimeout(boot, 2000);
  window.setInterval(boot, 3000);
})();
</script>
"""

# 设计令牌（浅色 + 暗色两套）在 audiobook_generator/ui/theme.py 里统一定义，
# 这里只放依赖令牌的组件样式，避免同一批颜色散落在两个文件里。
CUSTOM_CSS = THEME_TOKENS_CSS + """
* { box-sizing: border-box; }
html, body, #root, .gradio-container, .main, footer,
.gradio-container > .main {
  color: var(--apple-text) !important;
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text",
               "Helvetica Neue", "PingFang SC", "Microsoft YaHei", sans-serif !important;
  -webkit-font-smoothing: antialiased; }
html, body {
  /* 环境光渐变兜底：真正的环境光画在固定的 #ata-bg 层上（见 ambient_background.py），
     这里保留同一份渐变，供脚本未挂载 / JS 被禁用时使用。
     ⚠️ 必须用 background-image + background-color 分开写：Gradio 前端的 CSS 压缩
     处理多值 background 简写里带 var() 时会整段丢成空值（实测 background-image 变空，
     渐变和底色都不生效），拆开写才稳定。 */
  background-image:
    radial-gradient(58% 38% at 10% 0%, rgba(0,113,227,0.07), transparent 72%),
    radial-gradient(48% 34% at 92% 4%, rgba(94,92,230,0.07), transparent 72%),
    radial-gradient(46% 32% at 50% 100%, rgba(52,199,89,0.05), transparent 72%) !important;
  background-color: var(--apple-bg) !important;
  background-attachment: fixed !important; }
/* 内容容器保持透明：让 z-index:0 的氛围背景层透上来（内容由 z-index:1 盖在光晕之上） */
#root, .gradio-container, .main, footer, .gradio-container > .main {
  background: transparent !important; }
.gradio-container { margin: 0 auto !important;
  padding: 0 clamp(14px, 4vw, 48px) 64px !important; width: 100% !important; }

/* ── 顶部品牌栏 ── */
.app-header {
  position: sticky; top: 8px; z-index: 100;
  display: flex; align-items: center; justify-content: space-between;
  gap: 12px; padding: 12px 18px; margin: 0 -12px 10px;
  padding-top: max(12px, env(safe-area-inset-top));
  background: rgba(251,251,253,0.72);
  backdrop-filter: saturate(180%) blur(20px);
  -webkit-backdrop-filter: saturate(180%) blur(20px);
  /* 圆角玻璃条：width 用负外边距抵消 gr.HTML 包装层的 12px 内边距，
     让它和下面的卡片同为一条带（原来 680px、比卡片窄 24px，logo 还贴在 4px 处） */
  border: 1px solid var(--apple-border-soft);
  border-radius: var(--radius);
  box-shadow: var(--apple-shadow);
}
.app-brand { display: flex; align-items: center; gap: 12px; }
.app-logo {
  width: 38px; height: 38px; border-radius: 11px;
  background: linear-gradient(135deg, #0a84ff 0%, #5e5ce6 100%);
  display: flex; align-items: center; justify-content: center;
  font-size: 20px; box-shadow: 0 6px 16px rgba(94,92,230,0.35);
}
.app-title { font-size: 1.05rem; font-weight: 600; letter-spacing: -0.01em; color: var(--apple-text); }
.app-sub { font-size: 0.74rem; color: var(--apple-text-3); margin-top: 1px; }
.app-tag { font-size: 0.7rem; color: var(--apple-blue); font-weight: 600;
  background: var(--apple-blue-soft); padding: 3px 10px; border-radius: 980px; }

/* ── 胶囊导航 Tabs ── */
.tabs { gap: 0 !important; border: none !important; background: transparent !important; }
.tab-nav { border: none !important; justify-content: flex-start !important;
  padding: 4px 0 18px !important; overflow-x: auto; -webkit-overflow-scrolling: touch;
  scrollbar-width: none; flex-wrap: nowrap !important; }
.tab-nav::-webkit-scrollbar { display: none; }
.tab-nav button {
  border: none !important; background: transparent !important;
  font-weight: 500 !important; color: var(--apple-text-3) !important;
  font-size: 0.95rem !important; padding: 9px 18px !important;
  border-radius: 980px !important; margin: 0 4px !important;
  transition: all 0.25s cubic-bezier(0.4,0,0.2,1) !important;
}
.tab-nav button:hover { color: var(--apple-text) !important; background: var(--ata-hover) !important; }
.tab-nav button.selected {
  /* 选中态是"浅底深字"的反色胶囊：暗色下底色变浅，文字必须跟着变深 */
  color: var(--apple-bg) !important;
  background: var(--apple-text) !important;
  box-shadow: 0 4px 12px rgba(0,0,0,0.18) !important;
}

/* ── 通用卡片 ── */
.gr-box, .gr-panel, .gr-form { border: none !important; background: transparent !important;
  box-shadow: none !important; }
.app-card {
  background: var(--apple-surface) !important;
  border: 1px solid var(--apple-border-soft) !important;
  border-radius: var(--radius) !important;
  box-shadow: var(--apple-shadow) !important;
  padding: clamp(16px, 3.5vw, 24px) !important;
  margin-bottom: 18px !important;
  animation: fadeUp 0.55s cubic-bezier(0.16,1,0.3,1) both;
  transition: box-shadow 0.35s ease, transform 0.35s cubic-bezier(0.16,1,0.3,1) !important;
}
/* 清除 Gradio group 内部 styler 默认灰色直角底（让卡片白底直接透出） */
.app-card .styler,
.app-card.styler,
.app-card .block.hide-container,
.app-card .gr-group { background: transparent !important; border-radius: 0 !important;
  border: none !important; box-shadow: none !important; }
.app-card:hover { box-shadow: var(--ata-shadow-hover) !important; }

/* ── 毛玻璃 + 指针交互 ── */
/* 顶栏与进度条内部没有 fixed 定位的下拉面板，可以直接用毛玻璃 */
.app-header, .progress-container {
  background: var(--ata-glass-header) !important;
  backdrop-filter: saturate(180%) blur(20px);
  -webkit-backdrop-filter: saturate(180%) blur(20px);
}
/* 卡片里的毛玻璃必须画在伪元素上：
   backdrop-filter（和 transform 一样）会为 position:fixed 的后代建立包含块，
   而 Gradio 的 Dropdown 选项面板正是 fixed 定位并挂在卡片内部——直接加在
   .app-card 上会让面板相对卡片定位、跑到很远的顶部（实测偏移 242px）。
   伪元素没有后代，既能出磨砂效果又不会影响下拉定位。 */
.app-card {
  background: transparent !important;
  backdrop-filter: none !important;
  -webkit-backdrop-filter: none !important;
}
.app-card::before {
  content: ""; position: absolute; inset: 0; border-radius: inherit;
  background: var(--ata-glass);
  backdrop-filter: saturate(180%) blur(20px);
  -webkit-backdrop-filter: saturate(180%) blur(20px);
  z-index: 0; pointer-events: none;
}
/* 注意：这里不能加 overflow: hidden——日志页的 xterm 终端在卡片内，
   被裁剪后会显得"日志显示不全"。圆角由伪元素的 border-radius: inherit 保证。 */
.app-card { position: relative; }
/* gradio_log 内部把终端高度写成 calc(100% - 10px)，没有扣掉上方文件信息行，
   终端会向下溢出，再被组件自己的 overflow:hidden 裁掉最后一行。
   这里不要继续估算信息行高度：外层改成纵向 flex，让终端自动占满剩余空间。

   日志框按视口放大，但内部不能再叠加 64px/18px 两层底部留白：它们会参与
   xterm 的高度测量，结果屏幕比 viewport 高一行，最后几行刚好被裁掉，同时
   终端下方还会留下大片看起来“被挡住”的空带。底部安全距离统一交给卡片
   padding 和 margin，日志框自身只保留 64px 的滚动余量。
   高度再放宽一档：矮屏至少 1600px，随视口按 200vh 生长，高屏封顶 3000px；
   配合卡片底部安全区，长日志滚到底也不会被裁掉最后几行。 */
#run_log {
  display: flex !important;
  flex-direction: column !important;
  height: clamp(1600px, 200vh, 3000px) !important;
  min-height: 1600px !important;
  padding-bottom: 64px !important;
  box-sizing: border-box !important;
  /* 不能让组件根节点裁切 xterm：gradio_log 的内部高度会随字体/版本变化。 */
  overflow: visible !important;
}
.run-log-card {
  padding-bottom: 96px !important;
  margin-bottom: 128px !important;
  overflow: visible !important;
}
#run_log > div:not(.wrap) {
  flex: 1 1 auto !important;
  display: flex !important;
  flex-direction: column !important;
  height: 100% !important;
  min-height: 0 !important;
}
#run_log > div:not(.wrap) > span { flex: 0 0 auto !important; }
#run_log > div:not(.wrap) > div:last-child {
  flex: 1 1 auto !important;
  height: auto !important;
  min-height: 0 !important;
  margin-bottom: 0 !important;
  padding-bottom: 0 !important;
  box-sizing: border-box !important;
  overflow: visible !important;
}
#run_log .xterm,
#run_log .xterm-viewport { height: 100% !important; }
#run_log .xterm-viewport { padding-bottom: 0 !important; scrollbar-gutter: stable; }
/* 卡片内容要盖在玻璃层之上 */
.app-card > * { position: relative; z-index: 1; }
/* Gradio 的 ul.options 虽然用 fixed + 超高 z-index，但仍受所在包装层的堆叠上下文约束。
   后续卡片的内容层同为 z-index:1，DOM 更靠后时会盖住前面卡片展开的选项。
   只提升“当前含展开下拉”的包装层；不要抬高整张卡片，避免越过 sticky 顶栏。 */
.app-card > *:has(ul.options:not([inert])),
#advanced_modal .modal-box > *:has(ul.options:not([inert])) {
  z-index: 2 !important;
}
/* 下拉选项面板同样是「圆角 + 内滚动」：Gradio 给 ul.options 设了 overflow:auto，
   原生滚动条的方块轨道会盖住右侧上下圆角（选项多时最明显）。轨道透明 + 上下内缩。 */
ul.options { scrollbar-width: thin; scrollbar-color: var(--ata-scroll-thumb) transparent; }
ul.options::-webkit-scrollbar { width: 8px; height: 8px; }
ul.options::-webkit-scrollbar-track,
ul.options::-webkit-scrollbar-corner { background: transparent; }
ul.options::-webkit-scrollbar-track { margin-block: var(--container-radius, 4px); }
ul.options::-webkit-scrollbar-thumb { border-radius: 999px; background: var(--ata-scroll-thumb); }
ul.options::-webkit-scrollbar-thumb:hover { background: var(--ata-scroll-thumb-hover); }

/* 点击水波纹（页面脚本插入 .ata-ripple） */
.btn-primary, .btn-ghost, .btn-mini, .btn-danger, .tab-nav button, .engine-tab {
  position: relative; overflow: hidden;
}
.ata-ripple {
  position: absolute; width: 14px; height: 14px; border-radius: 50%;
  background: var(--ata-ripple); pointer-events: none;
  transform: translate(-50%, -50%) scale(0);
  animation: ataRipple 0.62s cubic-bezier(0.22,1,0.36,1) forwards;
}
.btn-primary .ata-ripple, .btn-danger .ata-ripple, .tab-nav button.selected .ata-ripple {
  background: rgba(255, 255, 255, 0.55);
}
@keyframes ataRipple {
  to { transform: translate(-50%, -50%) scale(16); opacity: 0; }
}
/* 注意：fadeUp 不能用 transform（translateY），否则 CSS 规范里 transform 会让
   卡片内 Dropdown 的 portal 选项面板（position:fixed）把卡片当作 containing block
   → 坐标全错 → 选项出现在很远的顶部。改为纯 opacity 淡入动画。 */
@keyframes fadeUp { from { opacity: 0; } to { opacity: 1; } }

.card-title { font-size: 1.05rem; font-weight: 600; color: var(--apple-text);
  margin: 0 0 4px; letter-spacing: -0.012em; display: flex; align-items: center; }
.card-desc { font-size: 0.84rem; color: var(--apple-text-3); margin: 0 0 16px; }
.card-num {
  display: inline-flex; width: 24px; height: 24px; border-radius: 8px;
  background: linear-gradient(135deg, var(--apple-blue) 0%, var(--apple-indigo) 100%);
  color: #fff !important; font-size: 0.76rem;
  font-weight: 700; align-items: center; justify-content: center; margin-right: 10px;
  box-shadow: 0 4px 10px rgba(94,92,230,0.3);
}

/* ── 卡片内分隔与小标题 ── */
.section-divider { height: 1px; background: linear-gradient(90deg, transparent, var(--apple-border-soft) 20%, var(--apple-border-soft) 80%, transparent);
  margin: 18px 0 14px; border: none; }
.card-sub-title { font-size: 0.78rem; font-weight: 600; color: var(--apple-text-2);
  margin: 0 0 12px; letter-spacing: 0.02em; text-transform: uppercase; }

/* ── 英雄区 ── */
.hero { text-align: center; padding: clamp(18px, 4vw, 30px) 8px 24px; animation: fadeUp 0.6s cubic-bezier(0.16,1,0.3,1) both; }
.hero h1 {
  font-size: clamp(1.6rem, 5.5vw, 2.3rem) !important; font-weight: 700 !important; letter-spacing: -0.03em;
  /* ⚠️ 渐变必须走"长写属性 + 纯 var() 引用"（令牌定义在 theme.py）：
     写成 `background: linear-gradient(... var(...) ...)` 简写时，Gradio 处理 CSS 会把这条
     拆成空值长写属性（实测 background-image 变空），而这里又有 -webkit-text-fill-color:
     transparent → 标题整段透明消失（"让文字化作声音"曾经因此看不见）。
     另外保留 color 作为兜底，theme.py 的脚本检测到渐变缺失时会加 .ata-title-solid。 */
  background-image: var(--ata-title-grad);
  -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent; color: var(--apple-text);
  margin: 0 0 10px !important;
}
/* 渐变没生效时的兜底样式（由 theme.py 的 guardTitles() 挂类） */
.hero h1.ata-title-solid {
  background-image: none !important;
  -webkit-text-fill-color: var(--apple-text) !important;
  color: var(--apple-text) !important;
}
.hero p { color: var(--apple-text-2); font-size: clamp(0.92rem, 2.6vw, 1.05rem); margin: 0 auto; max-width: 560px; line-height: 1.5; }
/* 日志页的主动作是读终端：压缩说明区，把节省出的高度让给日志滚动区。 */
.hero.logs-hero { padding: 4px 8px 10px; }
.hero.logs-hero h1 { font-size: clamp(1.65rem, 3vw, 2rem) !important; margin-bottom: 6px !important; }
.hero.logs-hero p { font-size: 0.94rem; line-height: 1.35; }

/* ── 输入控件统一 ── */
input, textarea, select {
  border-radius: var(--radius-sm) !important; background: var(--apple-surface-2) !important;
  border: 1px solid var(--apple-border-soft) !important; color: var(--apple-text) !important;
  font-size: 0.92em !important; transition: border-color 0.2s ease, box-shadow 0.2s ease, background 0.2s ease !important;
}
input:hover, textarea:hover, select:hover { border-color: var(--apple-border) !important; }
input:focus, textarea:focus, select:focus {
  border-color: var(--apple-blue) !important; background: var(--apple-surface) !important;
  box-shadow: 0 0 0 4px rgba(0,113,227,0.14) !important;
}
label { color: var(--apple-text-2) !important; font-weight: 500 !important; font-size: 0.85rem !important; }

/* ── 滑块 ── */
input[type=range] { accent-color: var(--apple-blue) !important; }

/* ── 文件上传拖拽区（替代 Gradio 默认深色方块） ── */
/* 隐藏左上角浮动标签「书籍文件」与 Gradio 默认灰色上传 SVG */
[data-testid="file-upload-button"] label.float,
[data-testid="block-label"].float { display: none !important; }
.book-file-upload button.center.boundedheight.flex > .wrap { display: none !important; }

.book-file-upload button.center.boundedheight.flex,
.book-file-upload div[data-testid="file"] button.center.boundedheight.flex {
  display: flex !important; flex-direction: column !important;
  align-items: center !important; justify-content: center !important; gap: 8px !important;
  width: 100% !important; min-height: 300px !important; padding: 28px !important;
  background: var(--apple-surface-2) !important;
  border: 1.5px dashed var(--apple-border) !important;
  border-radius: var(--radius) !important;
  color: var(--apple-text-3) !important;
  font-size: 0.86rem !important; font-weight: 500 !important;
  cursor: pointer !important;
  transition: border-color 0.25s ease, background 0.25s ease, transform 0.25s cubic-bezier(0.16,1,0.3,1) !important;
  position: relative !important;
}
/* 蓝色上传图标（居中显示，替代被隐藏的灰色 SVG） */
.book-file-upload button.center.boundedheight.flex::before {
  content: "" !important; display: block !important;
  width: 56px !important; height: 56px !important; border-radius: 50% !important;
  background: var(--ata-ready-bg) !important;
  border: 1px solid var(--ata-ready-border) !important;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='26' height='26' viewBox='0 0 24 24' fill='none' stroke='%230071e3' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4'/><polyline points='17 8 12 3 7 8'/><line x1='12' y1='3' x2='12' y2='15'/></svg>") !important;
  background-repeat: no-repeat !important; background-position: center !important;
  transition: transform 0.3s cubic-bezier(0.16,1,0.3,1) !important;
}
/* 提示文案（灰 SVG 隐藏后用伪元素补回） */
.book-file-upload button.center.boundedheight.flex::after {
  content: "拖放文件到此处，或点击选择" !important;
  color: var(--apple-text-3) !important; font-size: 0.84rem !important; font-weight: 500 !important;
}
.book-file-upload button.center.boundedheight.flex:hover {
  border-color: var(--apple-blue) !important; background: var(--apple-blue-soft) !important;
}
.book-file-upload button.center.boundedheight.flex:hover::before { transform: translateY(-3px); }
.book-file-upload button.center.boundedheight.flex:active { transform: scale(0.99) !important; }

/* 书籍文件上传后，隐藏整个上传区域（包括伪元素） */
.book-file-upload:has(.file-preview) button.center.boundedheight.flex,
.book-file-upload:has(.thumbnails) button.center.boundedheight.flex {
  display: none !important;
}

/* 已上传文件列表（gr.File 展示的文件名条）保持简洁圆角 */
div[data-testid="file"] .file-preview,
div[data-testid="file"] .grid-wrap { gap: 6px !important; }
div[data-testid="file"] .file-preview > div {
  border-radius: 12px !important; border: 1px solid var(--apple-border-soft) !important;
  background: var(--apple-surface) !important; padding: 8px 12px !important;
}
/* 上传文件后，通过 JS 隐藏上传按钮（由 page_load_js 执行） */

/* ── 弹窗内规则文件上传：紧凑版拖放区 + 图标 + 说明文字 ── */
#advanced_modal .rules-file-upload button.center.boundedheight.flex {
  min-height: 132px !important; padding: 16px 20px !important;
  margin-top: 2px !important;
}
#advanced_modal .rules-file-upload button.center.boundedheight.flex::before {
  width: 44px !important; height: 44px !important;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='20' height='20' viewBox='0 0 24 24' fill='none' stroke='%230071e3' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4'/><polyline points='17 8 12 3 7 8'/><line x1='12' y1='3' x2='12' y2='15'/></svg>") !important;
}
#advanced_modal .rules-file-upload button.center.boundedheight.flex::after {
  content: "拖放 .txt 规则文件到此处，或点击选择" !important;
  font-size: 0.82rem !important;
}

/* ── 生成进度条 ── */
.progress-container {
  position: relative; overflow: hidden;
  margin: 0 0 16px; padding: 16px 20px;
  border-radius: var(--radius);
  border: 1px solid var(--apple-border-soft);
  /* 只过渡会变的属性，避免整块重绘带来的闪烁感 */
  transition: box-shadow .45s ease, border-color .45s ease, opacity .45s ease, background .45s ease,
              max-height .55s cubic-bezier(0.22,1,0.36,1), margin-bottom .45s ease,
              padding-top .45s ease, padding-bottom .45s ease;
  max-height: 260px;              /* 收起动画需要一个可过渡的高度上限 */
  overflow: hidden;
  scroll-margin-top: 88px;   /* 点「开始生成」后平滑滚动到此处的落点偏移 */
}
/* 生成结束后自动收起：不占页面空间，也不再固定在顶部 */
.progress-container.collapsed {
  max-height: 0 !important; opacity: 0; margin-bottom: 0 !important;
  padding-top: 0 !important; padding-bottom: 0 !important;
  border-color: transparent !important; box-shadow: none !important;
  pointer-events: none;
}
.progress-container.idle { opacity: 0.5; }
.progress-container.idle .progress-header { margin-bottom: 0; }
.progress-container.idle .progress-detail,
.progress-container.idle .progress-pct,
.progress-container.idle .progress-book,
.progress-container.idle .progress-track { display: none !important; }
.progress-container.active {
  background: linear-gradient(135deg, rgba(0,113,227,0.05), rgba(94,92,230,0.05)) !important;
  border-color: rgba(0,113,227,0.18);
  box-shadow: 0 10px 30px rgba(0,113,227,0.10) !important;
}
.progress-container.done { border-color: rgba(52,199,89,0.38); }
.progress-container.warn { border-color: rgba(255,59,48,0.38); }
.progress-header {
  display: flex; align-items: center; gap: 12px;
  margin-bottom: 10px;
}
.progress-status {
  font-weight: 600; font-size: 0.92rem; color: var(--apple-text);
}
.progress-detail {
  color: var(--apple-text-2); font-size: 0.85rem;
}
.progress-pct {
  margin-left: auto; font-weight: 700; font-size: 1.1rem;
  color: var(--apple-blue); font-variant-numeric: tabular-nums;
  transition: color .4s ease;
}
.progress-container.done .progress-pct { color: var(--apple-green); }
.progress-container.warn .progress-pct { color: var(--apple-red); }
.progress-book {
  display: inline-block; margin-bottom: 10px;
  font-size: 0.85rem; color: var(--apple-text-2);
  background: var(--apple-surface-2); padding: 4px 12px;
  border-radius: 8px;
}
.progress-track {
  position: relative; height: 8px; background: var(--ata-track);
  border-radius: 980px; overflow: hidden;
}
.progress-fill {
  position: relative; height: 100%; width: 0; border-radius: 980px;
  background: linear-gradient(90deg, var(--apple-blue), var(--apple-indigo));
  transition: width 0.9s cubic-bezier(0.22,1,0.36,1), background .5s ease;
  will-change: width;
}
.progress-container.done .progress-fill { background: linear-gradient(90deg, #34c759, #30d158); }
.progress-container.warn .progress-fill { background: linear-gradient(90deg, #ff9f0a, #ff3b30); }
/* 光泽只在"正在生成"时流动——DOM 不再被整块替换，动画可以连续播放 */
.progress-fill::after {
  content: ""; position: absolute; inset: 0;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.3), transparent);
  opacity: 0; transition: opacity .4s ease;
}
.progress-container.running .progress-fill::after { opacity: 1; animation: shimmer 2.4s linear infinite; }
@keyframes shimmer {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(100%); }
}
/* 启动中（还没拿到章节标记）：轨道上跑不确定进度条纹 */
.progress-container.starting .progress-fill { width: 34% !important; opacity: .8; }
.progress-container.starting .progress-track::after {
  content: ""; position: absolute; inset: 0;
  background: repeating-linear-gradient(115deg, rgba(0,113,227,.18) 0 12px, transparent 12px 24px);
  animation: ataStripes 1.1s linear infinite;
}
@keyframes ataStripes { to { transform: translateX(24px); } }
/* 百分比变化时轻轻跳一下，给一点"推进感" */
.progress-container.bump .progress-pct { animation: pctPop .5s cubic-bezier(0.22,1,0.36,1); }
@keyframes pctPop { 0% { transform: scale(1); } 35% { transform: scale(1.16); } 100% { transform: scale(1); } }
/* 隐藏的状态载荷组件（前端脚本读取它就地更新进度条） */
.progress-state-hidden { display: none !important; }

/* 隐藏 Gradio Timer 组件本身的可见元素（拖拽横条等）。
   注意：Timer 必须是"有效可见"的顶层组件——不要再用 visible=False 的容器包它，
   否则 Gradio 前端不会应用 active 更新、也不会启动 tick（进度条会永远停在等待态）。 */
.progress-bar-wrap + .gr-timer,
.progress-bar-wrap ~ [data-testid="timer"],
.gradio-timer { display: none !important; height: 0 !important; overflow: hidden !important; }
/* 隐藏所有 Timer 渲染出的分隔/拖拽条 */
div:has(> .progress-bar-wrap) ~ .gr-group:empty,
div:has(> .progress-bar-wrap) ~ .gr-box:empty { display: none !important; }

/* ── 引擎分段选择器（原生 Tabs） ── */
.engine-tabs { gap: 0 !important; }
.engine-tabs > .tab-nav {
  display: grid !important; grid-template-columns: repeat(6, 1fr) !important;
  gap: 4px !important; padding: 4px !important; margin: 0 0 16px !important;
  background: var(--apple-surface-2) !important; border-radius: var(--radius-sm) !important;
  border: 1px solid var(--apple-border-soft) !important;
}
@media (max-width: 560px) {
  .engine-tabs > .tab-nav { grid-template-columns: repeat(3, 1fr) !important; }
}
.engine-tabs > .tab-nav button {
  border: none !important; background: transparent !important;
  font-weight: 600 !important; color: var(--apple-text-2) !important;
  font-size: 0.86rem !important; padding: 10px 6px !important;
  border-radius: 10px !important; margin: 0 !important; text-align: center !important;
  transition: color 0.2s ease, background 0.2s ease, box-shadow 0.25s ease !important; box-shadow: none !important;
}
.engine-tabs > .tab-nav button:hover { color: var(--apple-text) !important; background: var(--ata-hover) !important; }
.engine-tabs > .tab-nav button.selected {
  color: var(--apple-blue) !important; background: var(--apple-surface) !important;
  box-shadow: 0 2px 8px rgba(0,0,0,0.08) !important;
}

/* ── 手风琴（高级设置） ── */
.gr-accordion { border: 1px solid var(--apple-border-soft) !important;
  border-radius: var(--radius-sm) !important; background: var(--apple-surface-2) !important;
  overflow: hidden; transition: box-shadow 0.3s ease !important; }
.gr-accordion:hover { box-shadow: 0 4px 16px rgba(0,0,0,0.05) !important; }
.gr-accordion > .label-wrap { padding: 15px 18px !important; font-weight: 600 !important;
  color: var(--apple-text) !important; font-size: 0.92rem !important; }

/* ── 引擎切换动效 ── */
/* Tab 内容淡入（仅 opacity，不用 transform——tabitem 是 Dropdown 祖先，transform 会破坏 fixed 定位） */
.engine-tabs .tabitem { animation: tabFadeIn 0.3s cubic-bezier(0.16,1,0.3,1) both; }
@keyframes tabFadeIn { from { opacity: 0; } to { opacity: 1; } }

/* 标题行：标题左 + 徽标右 */
.card-title-row { display: flex !important; align-items: center !important; justify-content: space-between !important; gap: 12px; flex-wrap: wrap; }
.card-title-row .card-title { margin: 0 !important; }

.engine-badge {
  display: inline-flex; align-items: center; gap: 8px; padding: 8px 16px;
  background: var(--ata-ready-bg);
  border: 1px solid var(--ata-ready-border); border-radius: 980px; margin-bottom: 0;
  /* 徽标本身无动效，切换时文字直接更新 */
}
/* 防止 gr.HTML 进入 loading 态时把徽标变灰/变透明（服务端 queue 卡住的兜底） */
.block:has(.engine-badge),
.block:has(.engine-badge) .wrap,
.block:has(.engine-badge) .styler,
.block:has(.engine-badge) .html-container {
  filter: none !important; opacity: 1 !important;
  -webkit-filter: none !important; mix-blend-mode: normal !important;
  color-scheme: light !important;
}
.engine-badge-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--apple-green);
  box-shadow: 0 0 0 4px rgba(52,199,89,0.2); animation: pulse 1.8s ease-in-out infinite; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }
.engine-badge-label { font-size: 0.74rem; color: var(--apple-text-3); }
.engine-badge-name { font-size: 0.86rem; font-weight: 600; color: var(--apple-text); }

/* ── 隐藏 Gradio 队列/进度指示器（queue: N/N | Xs 文本 + 半透明遮罩 + spinner） ── */
.wrap.translucent,
.progress-text.meta-text-center,
#progress-bar { display: none !important; }

/* ── 按钮 ── */
.btn-primary {
  background: linear-gradient(135deg, var(--apple-blue) 0%, var(--apple-indigo) 100%) !important;
  color: #fff !important; border: none !important;
  border-radius: 980px !important; font-weight: 600 !important; font-size: 0.95rem !important;
  padding: 13px 28px !important; transition: transform 0.25s cubic-bezier(0.16,1,0.3,1), box-shadow 0.25s ease !important;
  cursor: pointer !important; box-shadow: var(--apple-shadow-blue) !important;
}
.btn-primary:hover { transform: translateY(-2px);
  box-shadow: 0 14px 30px rgba(0,113,227,0.42) !important; }
.btn-primary:active { transform: translateY(0) scale(0.98); }
.btn-primary.pulse { animation: ctaPulse 2.8s ease-in-out infinite; }
@keyframes ctaPulse {
  0%,100% { box-shadow: 0 8px 20px rgba(0,113,227,0.28); }
  50% { box-shadow: 0 8px 32px rgba(0,113,227,0.52); }
}

.btn-ghost {
  background: var(--apple-surface) !important; color: var(--apple-text) !important;
  border: 1px solid var(--apple-border) !important; border-radius: 980px !important;
  font-weight: 500 !important; font-size: 0.92rem !important; padding: 12px 24px !important;
  transition: background 0.2s ease, transform 0.2s ease, border-color 0.2s ease !important; cursor: pointer !important;
}
.btn-ghost:hover { background: var(--apple-surface-2) !important; border-color: var(--apple-border-soft) !important; }
.btn-ghost:active { transform: scale(0.98); }

.btn-danger {
  background: var(--apple-surface) !important; color: var(--apple-red) !important;
  border: 1px solid var(--ata-danger-border) !important; border-radius: 980px !important;
  font-weight: 500 !important; font-size: 0.85rem !important; padding: 9px 18px !important;
  transition: background 0.2s ease, border-color 0.2s ease !important; cursor: pointer !important;
}
.btn-danger:hover { background: var(--ata-danger-bg) !important; border-color: var(--apple-red) !important; }

.btn-mini {
  background: var(--apple-surface-2) !important; color: var(--apple-text-2) !important; border: none !important;
  border-radius: 980px !important; font-size: 0.82rem !important; font-weight: 500 !important;
  padding: 7px 15px !important; transition: all 0.18s ease !important; cursor: pointer !important;
}
.btn-mini:hover { background: var(--ata-hover-strong) !important; color: var(--apple-text) !important; }

/* ── 开关组（苹果风 toggle） ── */
.toggle-grid { display: grid; grid-template-columns: 1fr; gap: 10px; }
@media (min-width: 560px) { .toggle-grid { grid-template-columns: 1fr 1fr; } }
.toggle {
  background: var(--apple-surface) !important; border: 1px solid var(--apple-border-soft) !important;
  border-radius: 14px !important; padding: 12px 16px !important; transition: all 0.25s ease !important;
}
.toggle:hover { border-color: var(--apple-border) !important; }
/* 隐藏 Gradio 原生 checkbox 及任何额外渲染的开关圆点（仅保留伪元素做的苹果风 toggle） */
.toggle .checkbox,
.toggle input[type="checkbox"],
.toggle input,
.toggle .checkbox-wrap,
.toggle .cf-switch,
.toggle .switch { display: none !important; -webkit-appearance: none !important; appearance: none !important; }
.toggle label { position: relative; display: flex !important; align-items: center !important;
  cursor: pointer !important; font-weight: 500 !important; color: var(--apple-text) !important;
  font-size: 0.88rem !important; padding-left: 0 !important; }
.toggle label::before { content: ''; display: block; width: 38px; height: 22px; background: var(--ata-track);
  border-radius: 980px; margin-right: 12px; transition: background 0.3s ease; flex-shrink: 0; }
.toggle label::after { content: ''; position: absolute; left: 3px; top: 50%; transform: translateY(-50%);
  width: 16px; height: 16px; background: var(--apple-surface); border-radius: 50%; box-shadow: 0 1px 3px rgba(0,0,0,0.2);
  transition: transform 0.3s cubic-bezier(0.4,0,0.2,1); }
.toggle label:has(input:checked)::before { background: var(--apple-green); }
.toggle label:has(input:checked)::after { transform: translate(16px, -50%); }

/* ── 文件选择 ── */
.file-checks { border: none !important; background: transparent !important; padding: 0 !important; }
.file-checks label {
  background: var(--apple-surface) !important; border: 1px solid var(--apple-border-soft) !important;
  border-radius: 12px !important; padding: 10px 14px !important; margin-bottom: 6px !important;
  transition: all 0.2s ease !important; cursor: pointer !important;
}
.file-checks label:hover { border-color: var(--apple-blue) !important; background: var(--apple-blue-soft) !important; }
.file-checks label:has(input:checked) {
  background: linear-gradient(135deg, #0071e3 0%, #5e5ce6 100%) !important; color: #fff !important;
  border-color: transparent !important; box-shadow: 0 4px 12px rgba(0,113,227,0.32) !important; }

/* ── 资源库空态 / 就绪 ── */
.lib-empty { padding: 36px 20px; text-align: center; color: var(--apple-text-3);
  background: var(--ata-empty); border-radius: 16px; border: 1px dashed var(--apple-border); min-height: 180px;
  display: flex; flex-direction: column; align-items: center; justify-content: center; }
.lib-empty-icon { font-size: 2.4rem; margin-bottom: 12px; }
.lib-empty-text { font-size: 0.95rem; font-weight: 500; line-height: 1.6; }
.lib-ready { padding: 24px; text-align: center; background: var(--ata-ready-bg);
  border-radius: 16px; border: 1px solid var(--ata-ready-border); margin-top: 12px; }
.lib-ready-icon { font-size: 2.2rem; margin-bottom: 6px; }
.lib-ready h3 { color: var(--ata-ready-title); margin: 0 0 8px; font-size: 1.1rem; font-weight: 700; }
.lib-ready p { color: var(--ata-ready-text); font-size: 0.92rem; word-break: break-all; margin: 0; }
.lib-warn { color: var(--apple-red); font-size: 0.8rem; font-weight: 600; background: var(--ata-danger-bg);
  padding: 7px 12px; border-radius: 10px; display: inline-block; margin-top: 10px; }
.custom-download-zone a { color: var(--apple-blue) !important; font-weight: 600 !important; }

/* ── 资源库：操作区排版 ── */
/* Gradio 卡片内组件默认只有 1px 间隙：开关、主按钮、下载区会贴在一起，这里统一留白 */
.lib-card .styler { gap: 12px !important; }
.lib-card .section-divider { margin: 0; }
/* 分隔线自带的 html 容器上下各 10px 内边距，会和卡片 gap 叠加成大段空白 */
.lib-card .html-container:has(> .prose > .section-divider) { padding-top: 0 !important; padding-bottom: 0 !important; }
/* 行内控件：按钮按内容宽度排布（不再被 Gradio 的 160px 最小宽度撑开）并统一高度 */
.lib-row { gap: 10px !important; align-items: center !important; }
.lib-row > .form { min-width: 0 !important; flex: 1 1 auto !important; }
.lib-row > button { min-width: 0 !important; flex: 0 0 auto !important; }
.lib-row .btn-mini, .lib-row .btn-danger {
  height: 38px !important; padding: 0 16px !important;
  display: inline-flex !important; align-items: center !important; justify-content: center !important;
  font-size: 0.86rem !important; white-space: nowrap !important;
}
.lib-row .lib-push-right { margin-left: auto !important; }
/* 「打包并生成下载通道」与上方开关、下方下载区之间多留一点呼吸空间 */
.lib-generate { margin-top: 4px !important; margin-bottom: 2px !important; }

/* ── 杂项 ── */
h1, h2, h3 { color: var(--apple-text) !important; }
hr { border: none !important; border-top: 1px solid var(--apple-border-soft) !important; margin: 16px 0; }
.gradio-container .form { background: transparent !important; border: none !important; }

/* ═══ 响应式自适应 ═══ */
/* 小屏：隐藏品牌副标签，避免顶栏拥挤 */
@media (max-width: 480px) {
  .app-tag { display: none !important; }
  .app-sub { display: none !important; }
  .tab-nav button { padding: 8px 14px !important; font-size: 0.9rem !important; }
  .hero { padding-top: 12px !important; }
}

/* 小屏：资源库主行（批次列表 / 下载区）纵向堆叠 */
@media (max-width: 720px) {
  .row-stack { flex-direction: column !important; }
  .row-stack > * { width: 100% !important; }
}

/* 小屏：资源库的批次行换行——下拉框独占一行，操作按钮另起一行 */
@media (max-width: 520px) {
  .lib-row > .form { flex: 1 1 100% !important; }
}

/* 小屏：CTA 行按钮等宽撑满 */
@media (max-width: 520px) {
  .row-cta { flex-direction: column !important; gap: 10px !important; }
  .row-cta button { width: 100% !important; }
  .btn-primary, .btn-ghost { padding: 14px 22px !important; font-size: 1rem !important; }
}

/* 触屏：放大可点击区域，避免误触 */
@media (pointer: coarse) {
  .btn-mini { padding: 11px 18px !important; font-size: 0.88rem !important; }
  .btn-danger { padding: 11px 18px !important; }
  .lib-row .btn-mini, .lib-row .btn-danger { height: 44px !important; padding: 0 18px !important; }
  .engine-card { min-height: 72px !important; padding: 18px !important; }
  .file-checks label { padding: 14px 16px !important; margin-bottom: 8px !important; }
  .toggle { padding: 14px 16px !important; }
  input, textarea, select { font-size: 1em !important; }
  .tab-nav button { padding: 11px 18px !important; }
}

/* 触屏：禁用依赖悬停的视觉态，避免 sticky hover */
@media (hover: none) {
  .engine-card:hover, .btn-primary:hover, .btn-ghost:hover, .btn-danger:hover,
  .btn-mini:hover, .toggle:hover, .file-checks label:hover, .modal-close:hover {
    transform: none !important; background: revert !important; color: revert !important;
    box-shadow: revert !important; border-color: revert !important;
  }
  .engine-card:active { transform: scale(0.985); }
}

/* 无障碍：尊重「减少动态」系统偏好 */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.001ms !important; animation-iteration-count: 1 !important;
    transition-duration: 0.001ms !important; scroll-behavior: auto !important;
  }
  .hero h1 { -webkit-text-fill-color: var(--apple-text) !important; }
}

/* ── 高级设置弹窗（居中卡片，背景模糊） ── */
/* 纯客户端控制：默认 display:none，JS 切换 .show → display:flex */
/* ⚠️  不能在 #advanced_modal.show 自身上用 backdrop-filter / transform / filter / contain:layout
   否则 CSS 规范会让所有 position:fixed 的子元素把该元素当作 containing block（不再是 viewport）
   → Gradio Dropdown 的选项面板（portal, fixed）坐标计算全错 → 选项出现在很远的顶部。
   解决方案：把模糊层改成 body::before（弹窗的外部兄弟），由它承担 backdrop-filter，不影响 fixed 定位。 */
body.modal-open { overflow: hidden !important; }
/* .gradio-container 默认 z-index:1，会形成层叠上下文并把 fixed 弹窗困在
   body::before（z-index:999）之下，导致遮罩把弹窗本身也一起模糊。
   弹窗打开时释放容器的层叠上下文，让 #advanced_modal 回到根层叠层。 */
body.modal-open .gradio-container { z-index: auto !important; }
body.modal-open::before {
  content: "" !important;
  position: fixed !important; inset: 0 !important; z-index: 999 !important;
  background: var(--ata-scrim) !important;
  backdrop-filter: blur(8px) !important; -webkit-backdrop-filter: blur(8px) !important;
  pointer-events: none !important;
  display: block !important;
}
/* 遮罩层用 ID 选择器覆盖 Gradio 主题的 .gr-group 背景色 —— 不再有 backdrop-filter */
#advanced_modal { position: fixed !important; top:0; left:0; right:0; bottom:0;
  z-index: 1000; display: none !important; align-items: center !important;
  justify-content: center !important; padding: clamp(12px,3vw,32px);
  background: transparent !important; background-color: transparent !important;
  --block-background-fill: transparent !important;
  --group-background-fill: transparent !important; }
#advanced_modal.show { display: flex !important; }
/* Gradio 内层 wrapper 全部透明，不继承遮罩色；禁止内部滚动条 */
#advanced_modal .styler, #advanced_modal .gr-group,
#advanced_modal .form, #advanced_modal .block, #advanced_modal .group,
#advanced_modal .toggle-grid, #advanced_modal .wrap,
#advanced_modal .component-wrapper, #advanced_modal .contain {
  background: transparent !important; border: none !important; box-shadow: none !important;
}
/* .modal-scroll 是纵向 flex 容器；Gradio 顶层块若允许收缩，会被压成几像素高，
   随后 overflow:hidden 把整块内容裁掉。保留自然高度，让滚动发生在 .modal-scroll。 */
#advanced_modal .modal-scroll > * {
  flex: 0 0 auto !important;
  min-height: auto !important;
  overflow: visible !important;
}
#advanced_modal .styler { display: flex !important; align-items: center !important;
  justify-content: center !important; width: 100% !important; overflow: visible !important;
  max-height: 100% !important; min-height: 0 !important; }
/* modal-box 只负责尺寸、圆角与玻璃壳；滚动交给显式的 .modal-scroll 子层。
   这样滚动内容不会带动 ::before 玻璃背景，弹窗底部不会再露出未模糊的白色区域。 */
#advanced_modal .modal-box {
  position: relative !important; background: transparent !important; border: none !important;
  box-shadow: 0 0 0 1px rgba(0,0,0,0.04), 0 24px 80px rgba(0,0,0,0.28) !important;
  border-radius: 22px !important; padding: 0 !important;
  width: min(760px, 94vw) !important; max-width: 94vw !important;
  max-height: 80vh !important; overflow: hidden !important;
  animation: modalIn 0.3s cubic-bezier(0.16,1,0.3,1);
  display: flex !important; flex-direction: column !important;
}
#advanced_modal .modal-scroll {
  flex: 1 1 auto; width: 100%; min-height: 0; max-height: 80vh;
  box-sizing: border-box; padding: 24px;
  overflow-y: auto !important; overflow-x: hidden !important;
  overscroll-behavior: contain !important; -webkit-overflow-scrolling: touch !important;
  scrollbar-width: thin; scrollbar-color: var(--ata-scroll-thumb) transparent;
}
#advanced_modal .modal-scroll::-webkit-scrollbar { width: 8px; height: 8px; }
#advanced_modal .modal-scroll::-webkit-scrollbar-track,
#advanced_modal .modal-scroll::-webkit-scrollbar-corner { background: transparent; }
#advanced_modal .modal-scroll::-webkit-scrollbar-track { margin-block: 22px; }
#advanced_modal .modal-scroll::-webkit-scrollbar-thumb { border-radius: 999px;
  background: var(--ata-scroll-thumb); }
#advanced_modal .modal-scroll::-webkit-scrollbar-thumb:hover { background: var(--ata-scroll-thumb-hover); }
/* Gradio 的 visible=False 分组第一次切成可见时，内部 Markdown 容器可能仍保留
   初始的 0 高度；核验提示和确认按钮都在这个分组里，必须强制按内容撑开。 */
#advanced_modal #role_verification_panel,
#advanced_modal #role_verification_panel > .styler,
#advanced_modal #role_verification_panel .block.hide-container {
  height: auto !important;
  min-height: 0 !important;
  max-height: none !important;
  overflow: visible !important;
}
#advanced_modal #role_verification_panel {
  display: flex !important;
  flex: 0 0 auto !important;
  flex-direction: column !important;
}
#advanced_modal #role_verification_panel > .styler {
  display: block !important;
  width: 100% !important;
}
/* 只做透明度动画：不能在弹窗或祖先上引入 transform，否则 Gradio 的 fixed
   下拉选项面板会把弹窗当成 containing block，展开位置会跑到页面顶部。 */
@keyframes modalIn { from { opacity:0; } to { opacity:1; } }
#advanced_modal .modal-header { display:flex !important; align-items:center !important; justify-content:space-between !important; margin-bottom:4px; }
#advanced_modal .modal-title { font-size: clamp(1.05rem, 3vw, 1.25rem); font-weight:700; margin:0; color: var(--apple-text); }
#advanced_modal .modal-desc { color: var(--apple-text-2); font-size:0.9rem; margin:0 0 14px; }
#advanced_modal .modal-close-btn { width:34px !important; height:34px !important; min-width:34px !important;
  border-radius:50% !important; padding:0 !important; font-size:1.1rem;
  background: var(--apple-surface-2) !important; border:none !important; color: var(--apple-text) !important; }
/* 完成按钮底部预留安全边距，避免被视口下沿裁切 */
#advanced_modal .modal-done { width: 100%; margin-top: 14px; margin-bottom: 8px; }
/* 自动拆分结果未人工确认时，“完成”按钮置灰禁用，避免误退出后必须回头重做。 */
#advanced_modal .modal-done[disabled],
#advanced_modal .modal-done.is-gated {
  opacity: 0.5 !important;
  cursor: not-allowed !important;
  filter: saturate(0.6);
}
/* 人工确认状态载体：Gradio 的 display:none 会整个组件不渲染，所以用 1px 视觉隐藏。 */
#role_confirmation_probe_host {
  position: absolute !important;
  width: 1px !important;
  height: 1px !important;
  margin: -1px !important;
  padding: 0 !important;
  border: 0 !important;
  overflow: hidden !important;
  clip: rect(0 0 0 0) !important;
  white-space: nowrap !important;
  opacity: 0 !important;
  pointer-events: none !important;
}
#advanced_modal .modal-trigger { width:100%; }

/* ── 高级设置：分区卡片与固定操作栏 ── */
#advanced_modal .modal-header-wrap,
#advanced_modal .modal-footer-wrap { flex: 0 0 auto !important; padding: 0 !important; margin: 0 !important; }
#advanced_modal .modal-header-wrap .html-container,
#advanced_modal .modal-footer-wrap .html-container,
#advanced_modal .advanced-section .html-container { padding: 0 !important; }
#advanced_modal .modal-header {
  display: flex !important; align-items: flex-start !important; justify-content: space-between !important;
  gap: 16px; padding: 20px 24px 16px; margin: 0;
  border-bottom: 1px solid var(--apple-border-soft);
  background: var(--ata-glass-modal);
}
#advanced_modal .modal-title { font-size: clamp(1.05rem, 3vw, 1.25rem); font-weight: 700; margin: 0; color: var(--apple-text); }
#advanced_modal .modal-subtitle { margin: 3px 0 0; color: var(--apple-text-3); font-size: 0.8rem; line-height: 1.45; }
#advanced_modal .modal-close-btn {
  width: 34px !important; height: 34px !important; min-width: 34px !important;
  border-radius: 50% !important; padding: 0 !important; font-size: 1.05rem;
  background: var(--apple-surface-2) !important; border: 1px solid var(--apple-border-soft) !important;
  color: var(--apple-text) !important; cursor: pointer;
}
#advanced_modal .modal-scroll { max-height: none !important; padding: 18px 24px 16px; }
#advanced_modal .advanced-section {
  background: var(--ata-glass-soft) !important;
  border: 1px solid var(--apple-border-soft) !important;
  border-radius: 18px !important;
  padding: 18px !important;
  margin: 0 0 14px !important;
  box-shadow: inset 0 1px 0 var(--ata-glass-edge), 0 8px 28px rgba(0,0,0,0.035) !important;
  overflow: visible !important;
}
#advanced_modal .advanced-section .styler { gap: 12px !important; }
#advanced_modal .advanced-section .styler,
#advanced_modal .advanced-section .gr-group {
  align-items: stretch !important; justify-content: flex-start !important;
  min-width: 0 !important; max-width: 100% !important; width: 100% !important;
  height: auto !important; max-height: none !important;
}
#advanced_modal .advanced-section-head { display: flex; align-items: flex-start; gap: 12px; margin: 0 0 14px; }
#advanced_modal .advanced-section-badge {
  flex: 0 0 auto; display: inline-flex; align-items: center; justify-content: center;
  width: 30px; height: 30px; border-radius: 10px;
  background: linear-gradient(135deg, var(--apple-blue) 0%, var(--apple-indigo) 100%);
  color: #fff; font-size: 0.8rem; font-weight: 700;
  box-shadow: 0 5px 14px rgba(94,92,230,0.25);
}
#advanced_modal .advanced-section-copy { min-width: 0; }
#advanced_modal .advanced-section-copy h3 { margin: 0; font-size: 1rem; line-height: 1.25; }
#advanced_modal .advanced-section-copy p { margin: 4px 0 0; color: var(--apple-text-3); font-size: 0.82rem; line-height: 1.5; }
#advanced_modal .advanced-subsection-head {
  display: flex; align-items: flex-start; justify-content: space-between; gap: 12px;
  margin: 17px 0 10px; padding-top: 15px; border-top: 1px solid var(--apple-border-soft);
}
#advanced_modal .advanced-subsection-head h4 { margin: 0; font-size: 0.9rem; line-height: 1.3; }
#advanced_modal .advanced-subsection-head p { margin: 3px 0 0; color: var(--apple-text-3); font-size: 0.79rem; line-height: 1.45; }
#advanced_modal .advanced-pill {
  flex: 0 0 auto; display: inline-flex; align-items: center; min-height: 24px; padding: 3px 9px;
  border-radius: 999px; background: var(--apple-blue-soft); color: var(--apple-blue);
  font-size: 0.72rem; font-weight: 650; white-space: nowrap;
}
#advanced_modal .advanced-pill-success { background: var(--ata-ready-bg); color: var(--ata-ready-title); }
#advanced_modal .advanced-pill-warn { background: var(--ata-warn-bg); color: var(--apple-amber); }
#advanced_modal .advanced-verification-head {
  margin: 14px 0 10px; padding: 14px 16px; border: 1px solid var(--ata-ready-border);
  border-radius: 14px; background: var(--ata-ready-bg);
}
#advanced_modal .advanced-verification-head h4 { margin: 7px 0 0; color: var(--ata-ready-title); font-size: 0.92rem; }
#advanced_modal .advanced-verification-head p { margin: 3px 0 0; color: var(--ata-ready-text); font-size: 0.79rem; line-height: 1.45; }
/* 字段行统一成两列等宽网格：Gradio Row 的 flex + scale 会让两列宽窄不一、
   有 info 文案的控件比隔壁高半行，label 高低不齐。网格 + 顶部对齐后，左侧 label
   与右侧 label 始终同一水平线，输入框也等宽。 */
#advanced_modal .advanced-field-row {
  display: grid !important;
  grid-template-columns: repeat(2, minmax(0, 1fr)) !important;
  align-items: start !important;
  gap: 12px 14px !important;
  margin-top: 2px !important;
}
#advanced_modal .advanced-field-row > * { min-width: 0 !important; max-width: 100% !important; }
#advanced_modal .advanced-field-row .form,
#advanced_modal .advanced-field-row .block { min-width: 0 !important; max-width: 100% !important; }
#advanced_modal .advanced-field-row input,
#advanced_modal .advanced-field-row textarea,
#advanced_modal .advanced-field-row .wrap { max-width: 100% !important; }
/* 操作按钮做成等宽、右对齐的按钮组：按钮不再一大一小、也不左右乱贴 */
#advanced_modal .advanced-action-row {
  display: flex !important;
  flex-wrap: wrap !important;
  align-items: stretch !important;
  justify-content: flex-end !important;
  gap: 10px !important;
  margin-top: 8px !important;
}
#advanced_modal .advanced-action-row button {
  flex: 0 1 172px !important;
  min-width: 148px !important;
  min-height: 40px !important;
  white-space: nowrap;
}
/* 试听行：下拉占左列，按钮与输入控件底边对齐（不是与整行顶部对齐） */
#advanced_modal .advanced-preview-row { align-items: end !important; }
#advanced_modal .role-step-head { justify-content: flex-start; gap: 10px; margin-top: 24px; }
#advanced_modal .role-step-number {
  flex: 0 0 auto; width: 26px; height: 26px; display: inline-flex;
  align-items: center; justify-content: center; border-radius: 50%;
  background-color: var(--apple-blue-soft); color: var(--apple-blue); font-weight: 600;
}
#advanced_modal .role-workflow-hint {
  color: var(--apple-text); font-size: 0.86rem; line-height: 1.6;
  padding: 10px 0; margin: 0; border-bottom: 1px solid var(--apple-border-soft);
}
#advanced_modal .role-details { background-color: transparent !important; margin: 8px 0 !important; }
#advanced_modal .role-details > .label-wrap { color: var(--apple-text-2); }
#advanced_modal #role_parameter_table { min-width: 0 !important; width: 100% !important; }
#advanced_modal #role_parameter_table .table-wrap { overflow-x: auto !important; }
#advanced_modal #role_parameter_table table { min-width: 1040px; }
#advanced_modal #role_config_panel,
#advanced_modal #role_config_panel > .styler,
#advanced_modal #role_verification_panel {
  min-width: 0 !important; width: 100% !important; max-width: 100% !important;
  align-items: stretch !important;
}
#advanced_modal #role_config_panel > .styler > * {
  min-width: 0 !important; max-width: 100% !important; width: 100%;
}
#advanced_modal #role_split_btn { margin: 4px 0 8px; }
#advanced_modal .role-summary { max-height: 240px; overflow-y: auto !important; }
#advanced_modal .role-details button:focus-visible,
#advanced_modal #role_confirm_btn:focus-visible,
#advanced_modal #role_split_btn:focus-visible {
  outline: 2px solid var(--apple-blue) !important; outline-offset: 3px;
}
#advanced_modal .advanced-preview-row button { align-self: end !important; }
/* 「显示 DeepSeek API Key」只是辅助开关，收成内联小胶囊，不再占一整行 */
#advanced_modal .toggle.advanced-compact-toggle {
  width: fit-content !important;
  max-width: 100% !important;
  padding: 6px 12px !important;
  margin: -6px 0 4px !important;
  border-radius: 999px !important;
  background: var(--ata-glass-soft) !important;
}
#advanced_modal .toggle.advanced-compact-toggle label { font-size: 0.8rem !important; }
#advanced_modal .toggle.advanced-compact-toggle label::before {
  width: 30px !important; height: 18px !important; margin-right: 9px !important;
}
#advanced_modal .toggle.advanced-compact-toggle label::after {
  width: 13px !important; height: 13px !important; left: 2.5px !important;
}
#advanced_modal .toggle.advanced-compact-toggle label:has(input:checked)::after {
  transform: translate(12px, -50%) !important;
}
#advanced_modal .advanced-note { margin: 0 0 2px; }
#advanced_modal .advanced-toggle-grid { margin-top: 2px; }
#advanced_modal .modal-footer {
  display: flex !important; align-items: center !important; justify-content: space-between !important;
  gap: 14px; padding: 14px 24px 18px; margin: 0;
  border-top: 1px solid var(--apple-border-soft); background: var(--ata-glass-modal);
}
#advanced_modal .modal-footer-copy { flex: 1 1 auto; min-width: 0; }
#advanced_modal .modal-footer-hint { margin: 0; color: var(--apple-text-3); font-size: 0.8rem; }
#advanced_modal .modal-footer-gate {
  margin: 6px 0 0; color: var(--apple-amber); font-size: 0.79rem; line-height: 1.45; font-weight: 600;
}
#advanced_modal .modal-footer .modal-done { flex: 0 0 176px; width: 176px; margin: 0 !important; }

/* 多角色模式：独立于普通开关的主功能入口，使用蓝色强调、左侧标线和点击回弹。 */
#advanced_modal .toggle.advanced-switch {
  position: relative !important;
  overflow: hidden !important;
  padding: 16px 18px 16px 20px !important;
  border: 1px solid rgba(0, 113, 227, 0.24) !important;
  border-radius: 16px !important;
  background-color: var(--apple-surface-2) !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.34), 0 7px 20px rgba(0, 113, 227, 0.07) !important;
  text-align: left !important;
  transform-origin: center center;
  transition: transform 0.24s cubic-bezier(0.22, 1, 0.36, 1),
              border-color 0.24s ease, background-color 0.24s ease, box-shadow 0.24s ease !important;
}
#advanced_modal .toggle.advanced-switch::before {
  content: ''; position: absolute; left: 0; top: 14px; bottom: 14px; width: 3px;
  border-radius: 0 8px 8px 0; background-color: var(--apple-blue);
  opacity: 0.48; transition: opacity 0.24s ease, box-shadow 0.24s ease;
}
#advanced_modal .toggle.advanced-switch::after {
  content: ''; position: absolute; right: -34px; top: -50px; width: 132px; height: 132px;
  border-radius: 50%; pointer-events: none; opacity: 0.5;
  background: radial-gradient(circle, rgba(94, 92, 230, 0.2), transparent 68%);
  transition: opacity 0.24s ease, transform 0.24s ease;
}
#advanced_modal .toggle.advanced-switch:hover {
  transform: translateY(-1px);
  border-color: rgba(0, 113, 227, 0.48) !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.38), 0 10px 26px rgba(0, 113, 227, 0.13) !important;
}
#advanced_modal .toggle.advanced-switch label {
  position: relative; z-index: 1; justify-content: flex-start !important;
  width: 100% !important; font-weight: 650 !important; letter-spacing: -0.008em;
}
#advanced_modal .toggle.advanced-switch label::before {
  width: 48px !important; height: 26px !important; margin-right: 13px !important;
  background-color: rgba(120, 120, 128, 0.26) !important;
  box-shadow: inset 0 0 0 1px rgba(0, 0, 0, 0.07) !important;
}
#advanced_modal .toggle.advanced-switch label::after {
  left: 4px !important; width: 20px !important; height: 20px !important;
  background: #fff !important;
  box-shadow: 0 2px 7px rgba(0, 0, 0, 0.22), 0 0 0 1px rgba(0, 0, 0, 0.04) !important;
  transition: transform 0.36s cubic-bezier(0.34, 1.56, 0.64, 1) !important;
}
#advanced_modal .toggle.advanced-switch label:has(input:checked)::before {
  background-color: var(--apple-blue) !important;
  box-shadow: 0 0 0 4px rgba(0, 113, 227, 0.12), inset 0 0 0 1px rgba(255, 255, 255, 0.12) !important;
}
#advanced_modal .toggle.advanced-switch label:has(input:checked)::after {
  transform: translate(22px, -50%) !important;
}
#advanced_modal .toggle.advanced-switch:has(input:checked) {
  border-color: rgba(0, 113, 227, 0.52) !important;
  background-color: var(--apple-blue-soft) !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.4), 0 10px 28px rgba(0, 113, 227, 0.16) !important;
}
#advanced_modal .toggle.advanced-switch:has(input:checked)::before {
  opacity: 1; box-shadow: 0 0 12px rgba(0, 113, 227, 0.55);
}
#advanced_modal .toggle.advanced-switch:has(input:checked)::after { opacity: 0.9; }
#advanced_modal .toggle.advanced-switch.is-switching {
  animation: advancedSwitchPress 0.52s cubic-bezier(0.22, 1, 0.36, 1);
}
#advanced_modal .toggle.advanced-switch.is-switching::after {
  animation: advancedSwitchGlow 0.52s ease-out;
}
@keyframes advancedSwitchPress {
  0% { transform: scale(1); }
  28% { transform: scale(0.975); }
  58% { transform: scale(1.012); }
  100% { transform: scale(1); }
}
@keyframes advancedSwitchGlow {
  0% { opacity: 0.35; transform: scale(0.72); }
  65% { opacity: 0.95; transform: scale(1.08); }
  100% { opacity: 0.7; transform: scale(1); }
}
:root:root .dark #advanced_modal .toggle.advanced-switch,
:root:root.dark #advanced_modal .toggle.advanced-switch {
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.06), 0 8px 24px rgba(0, 0, 0, 0.25) !important;
}
:root:root .dark #advanced_modal .toggle.advanced-switch:has(input:checked),
:root:root.dark #advanced_modal .toggle.advanced-switch:has(input:checked) {
  background-color: rgba(64, 156, 255, 0.23) !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.08), 0 10px 28px rgba(0, 0, 0, 0.32) !important;
}
@media (max-width: 560px) {
  #advanced_modal .modal-header { padding: 16px 16px 13px; }
  #advanced_modal .modal-scroll { padding: 14px 14px 12px; }
  #advanced_modal .advanced-section { padding: 15px !important; border-radius: 16px !important; }
  #advanced_modal .advanced-field-row {
    grid-template-columns: 1fr !important;
    align-items: stretch !important;
  }
  #advanced_modal .advanced-action-row {
    flex-direction: column !important;
    align-items: stretch !important;
  }
  #advanced_modal .advanced-action-row button { flex: 1 1 auto !important; width: 100% !important; }
  #advanced_modal .modal-footer { padding: 12px 14px 14px; }
  #advanced_modal .modal-footer-hint { display: none; }
  #advanced_modal .modal-footer .modal-done { flex: 1 1 auto; width: 100%; }
}

/* 大屏：放宽内容列宽，避免超宽屏拉伸 */
@media (min-width: 1200px) {
  .gradio-container { max-width: 1280px !important; }
}
/* 超宽屏：放宽容器，居中留白 */
@media (min-width: 1440px) {
  .gradio-container { max-width: 1320px !important; }
}
""" + AMBIENT_CSS + THEME_CSS

# ── 主装配 ────────────────────────────────────────────────────────
def host_ui(config):
    default_output_dir = os.path.join("audiobook_output", datetime.now().strftime("%Y-%m-%d_%H-%M-%S"))
    saved = _load_settings()

    theme = gr.themes.Default(primary_hue="blue", secondary_hue="slate", neutral_hue="slate",
                              font=[gr.themes.GoogleFont("Inter"), "system-ui", "sans-serif"]).set(
        body_background_fill="#fbfbfd",
        block_background_fill="#ffffff", block_border_width="0px", block_radius="18px",
        button_large_radius="980px", input_background_fill="#f5f5f7", input_border_color="#e8e8ed",
        # 暗色一套：与 theme.py 的令牌对齐，保证 Gradio 自带组件（下拉/滑块/勾选）同步变暗
        body_background_fill_dark="#0e0e12",
        body_text_color_dark="#f5f5f7",
        block_background_fill_dark="#1c1c22",
        block_label_text_color_dark="#e8e8ed",
        block_title_text_color_dark="#f5f5f7",
        input_background_fill_dark="#232329",
        input_border_color_dark="#3a3a42",
        block_border_color_dark="#2c2c33",
        border_color_primary_dark="#3a3a42",
        panel_background_fill_dark="#1c1c22",
    )

    with gr.Blocks(theme=theme, css=CUSTOM_CSS, analytics_enabled=False,
                   head=HEAD_HTML, title="有声书工坊 · Audiobook Studio") as ui:
        provider_state = gr.State("Mimo")

        # ── 顶部品牌栏 ──
        gr.HTML('''
        <div class="app-header">
            <div class="app-brand">
                <div class="app-logo">🎧</div>
                <div>
                    <div class="app-title">有声书工坊</div>
                    <div class="app-sub">EPUB · DOC · DOCX → 高品质语音</div>
                </div>
            </div>
            <button id="ata-theme-toggle" class="ata-theme-toggle" type="button"
                    aria-label="切换深浅色主题">
                <span class="ata-theme-icon" id="ata-theme-icon">☀️</span>
                <span id="ata-theme-label">跟随系统</span>
            </button>
        </div>''')

        with gr.Tabs(selected="tab_convert") as main_tabs:
            # ════════════ 转换页 ════════════
            with gr.Tab("转换", id="tab_convert"):
                gr.HTML('''
                <div class="hero">
                    <h1>让文字化作声音</h1>
                    <p>上传书籍，选择语音引擎，一键生成有声书。多引擎、多格式、批量处理。</p>
                </div>''')
                # 进度条
                # 注意：Timer 必须放在可见层级，不能包进 visible=False 的容器。
                # Gradio 前端对"有效可见性为 false"的组件不会应用 active 更新，也不会启动
                # tick 定时器（ct() 判定 + Timer 组件在 onMount 里 setInterval），
                # 那样进度条会永远停在初始的「等待开始生成...」。
                #
                # 进度条骨架只渲染一次，之后由 HEAD_HTML 里的脚本就地更新内部元素，
                # 避免每 2 秒整块替换 DOM 导致动画重放（"一闪一闪"）。
                progress_bar = gr.HTML(_progress_scaffold_html(), elem_classes="progress-bar-wrap")
                progress_state = gr.HTML("", elem_id="progress_state", elem_classes="progress-state-hidden")
                progress_timer = gr.Timer(2, active=False)
                # 上传按钮隐藏脚本（运行在浏览器端）
                gr.HTML('''
                <script>
                (function() {
                    function hideUploadWhenFilesExist() {
                        // 遍历所有书籍文件上传组件
                        document.querySelectorAll('.book-file-upload').forEach(function(fileComp) {
                            // 检查是否已有文件（thumbnails 容器有子元素）
                            var thumbs = fileComp.querySelector('[data-testid="container_el"], .thumbnails, .file-preview');
                            if (!thumbs || thumbs.offsetHeight === 0 || thumbs.children.length === 0) return;
                            
                            // 隐藏上传按钮/拖拽区
                            var uploaders = fileComp.querySelectorAll(
                                '.upload-container, [data-testid="file-upload"], .source-selection, button.center'
                            );
                            uploaders.forEach(function(el) {
                                el.style.setProperty('display', 'none', 'important');
                            });
                            
                            // 也隐藏可能的 "添加更多" 按钮
                            var addBtns = fileComp.querySelectorAll('button:not(.delete-button):not(.thumbnail-item)');
                            addBtns.forEach(function(btn) {
                                if (btn.querySelector('svg') || btn.textContent.includes('上传') || btn.textContent.includes('拖放')) {
                                    btn.style.setProperty('display', 'none', 'important');
                                }
                            });
                        });
                    }
                    
                    // MutationObserver 监听 DOM 变化
                    var observer = new MutationObserver(hideUploadWhenFilesExist);
                    observer.observe(document.body, { childList: true, subtree: true, attributes: true });
                    
                    // 定时检查（备用方案）
                    setInterval(hideUploadWhenFilesExist, 1000);
                    
                    // 初始执行
                    hideUploadWhenFilesExist();
                })();
                </script>
                ''', visible=False)

                # —— Step 1 文件 + 章节范围 ——
                with gr.Group(elem_classes="app-card"):
                    gr.HTML('<p class="card-title"><span class="card-num">1</span>上传书籍文件</p>')
                    gr.HTML('<p class="card-desc">支持 EPUB / DOC / DOCX，可多选。输出目录将根据书名自动生成。</p>')
                    input_file = gr.File(label="书籍文件", file_types=[".epub", ".doc", ".docx"],
                                         file_count="multiple", interactive=True, elem_classes="book-file-upload")
                    output_dir = gr.Textbox(label="输出目录", value=default_output_dir, interactive=True,
                                            info="多文件时每本书自动生成以书名为名的子文件夹")
                    input_file.change(fn=update_output_dir_from_file, inputs=input_file, outputs=output_dir, show_progress="hidden")
                    gr.HTML('<div class="section-divider"></div>')
                    gr.HTML('<p class="card-sub-title">章节范围</p>')
                    with gr.Row():
                        chapter_start = gr.Slider(minimum=1, maximum=100, step=1, label="起始章节页码", value=1, interactive=True)
                        chapter_end = gr.Slider(minimum=-1, maximum=100, step=1, label="结束章节页码", value=-1, info="-1 代表处理至最后一章", interactive=True)
                    gr.HTML('<div class="section-divider"></div>')
                    gr.HTML('<button type="button" class="btn-ghost modal-trigger" onclick="openAdvancedModal(event)" style="width:100%;padding:12px;border-radius:14px;font-size:1rem;cursor:pointer;">⚙\u00a0\u00a0高级设置</button>')

                # —— Step 2 引擎 ——
                with gr.Group(elem_classes="app-card"):
                    gr.HTML('''
                    <div class="card-title-row">
                        <p class="card-title"><span class="card-num">2</span>选择语音引擎</p>
                        <div class="engine-badge" id="engine_badge_static">
                            <span class="engine-badge-dot"></span>
                            <span class="engine-badge-label">当前语音引擎</span>
                            <span class="engine-badge-name" id="engine_badge_name">MiMo</span>
                        </div>
                    </div>''')
                    gr.HTML('<p class="card-desc">点击下方标签切换引擎，所选引擎的参数随即显示。</p>')
                    with gr.Tabs(selected="Mimo", elem_classes="engine-tabs") as engine_tabs:
                        # ── MiMo ──
                        with gr.Tab("✨ MiMo", id="Mimo") as mimo_tab:
                            with gr.Row():
                                model = gr.Dropdown(get_openai_supported_models(), value="mimo-v2.5-tts", label="模型", interactive=True, allow_custom_value=True)
                                voices = gr.Dropdown(get_openai_supported_voices(), label="音色风格", interactive=True, allow_custom_value=True)
                            with gr.Row():
                                speed = gr.Slider(minimum=0.25, maximum=4.0, step=0.1, label="生成语速", value=1.0, info="1.0 为自然语速")
                                openai_output_format = gr.Dropdown(get_openai_supported_output_formats(), label="音频输出格式", interactive=True)
                            enable_stream = gr.Checkbox(label="启用流式调用（PCM16 实时合成 WAV）", value=False, elem_classes="toggle")
                            show_voice_instructions = gr.Checkbox(label="展开高级情绪/语气控制", value=saved["show_voice_instructions"], elem_classes="toggle")
                            with gr.Accordion("情绪/语气控制指令", open=saved["show_voice_instructions"]) as voice_instructions_row:
                                instructions = gr.TextArea(label="情绪/语气控制指令", interactive=True, lines=3,
                                                           value=get_openai_instructions_example())
                            show_voice_instructions.change(fn=lambda v: _save_checkbox("show_voice_instructions", v),
                                                           inputs=show_voice_instructions, outputs=None, show_progress="hidden")
                        # ── MiniMax ──
                        with gr.Tab("🎙️ MiniMax", id="MiniMax") as minimax_tab:
                            with gr.Row():
                                minimax_model = gr.Dropdown(get_minimax_supported_models(), value="speech-2.8-hd", label="模型", interactive=True, allow_custom_value=True)
                                minimax_voice = gr.Dropdown(get_minimax_voice_choices(), value=get_minimax_voice_choices()[0], label="音色", interactive=True, allow_custom_value=True)
                            minimax_output_format = gr.Dropdown(get_minimax_supported_output_formats(), value="mp3", label="输出格式", interactive=True)
                            gr.HTML('<p class="card-desc">使用 MiniMax TTS API，请先设置环境变量 MINIMAX_API_KEY</p>')
                        # ── Edge ──
                        with gr.Tab("🌐 Edge", id="Edge") as edge_tab:
                            with gr.Row():
                                edge_language = gr.Dropdown(get_edge_tts_supported_language(), value="en-US", label="语言", interactive=True)
                                edge_voice = get_edge_voices_by_language("en-US")
                                edge_output_format = gr.Dropdown(get_edge_tts_supported_output_formats(), label="输出格式", interactive=True)
                            proxy = gr.Textbox(label="代理 Proxy", value="", interactive=True)
                            with gr.Row():
                                edge_voice_rate = gr.Slider(minimum=-50, maximum=100, step=1, label="语速", value=0)
                                edge_volume = gr.Slider(minimum=-100, maximum=100, step=1, label="音量", value=0)
                            with gr.Row():
                                edge_pitch = gr.Slider(minimum=-100, maximum=100, step=1, label="音调", value=0)
                                edge_break_duration = gr.Slider(minimum=0, maximum=5000, step=1, label="段落停顿 (ms)", value=1250)
                            edge_language.change(fn=get_edge_voices_by_language, inputs=edge_language, outputs=edge_voice, show_progress="hidden")
                        # ── Qwen TTS ──
                        with gr.Tab("🤖 Qwen TTS", id="Qwen") as qwen_tab:
                            gr.HTML('<p class="card-desc">Qwen TTS API（私有化/本地部署），需在「⚙️ 设置」页面配置 API</p>')
                            with gr.Row():
                                qwen_language = gr.Dropdown(get_qwen_supported_languages(), label="语言", value="Auto", interactive=True)
                                qwen_voice = gr.Dropdown(get_qwen_supported_voices(), label="音色", value="Vivian", interactive=True)
                        # ── Chatterbox ──
                        with gr.Tab("🎯 Chatterbox", id="Chatterbox") as chatterbox_tab:
                            gr.HTML('<p class="card-desc">本地 TTS 模型，支持语音克隆，完全离线运行。首次使用需安装 <code>pip install chatterbox-tts</code></p>')
                            with gr.Row():
                                chatterbox_model = gr.Dropdown(
                                    get_chatterbox_supported_models(),
                                    value="chatterbox-multilingual-v3",
                                    label="模型版本",
                                    interactive=True,
                                    info="multilingual-v3 支持中文，v0.5 仅支持英文"
                                )
                                chatterbox_device = gr.Dropdown(
                                    get_chatterbox_supported_devices(),
                                    value="auto",
                                    label="运行设备",
                                    interactive=True,
                                    info="auto 会自动选择最佳设备"
                                )
                            chatterbox_output_format = gr.Dropdown(
                                get_chatterbox_supported_output_formats(),
                                value=DEFAULT_CHATTERBOX_OUTPUT_FORMAT,
                                label="输出格式",
                                interactive=True
                            )
                            chatterbox_reference_audio = gr.File(
                                label="参考音频（可选）",
                                file_count="single",
                                file_types=["audio"]
                            )
                            with gr.Row():
                                chatterbox_speed_min, chatterbox_speed_max = get_chatterbox_speed_range()
                                chatterbox_speed = gr.Slider(
                                    minimum=chatterbox_speed_min, maximum=chatterbox_speed_max, step=0.05,
                                    label="语速",
                                    value=DEFAULT_CHATTERBOX_SPEED,
                                    info="1.0 为标准语速（相当于旧版的 0.7），越小越慢，越大越快"
                                )
                            with gr.Row():
                                chatterbox_exaggeration = gr.Slider(
                                    minimum=0.0, maximum=1.0, step=0.05,
                                    label="表现力",
                                    value=0.5,
                                    info="控制语音的情感表现力"
                                )
                                chatterbox_cfg_weight = gr.Slider(
                                    minimum=0.0, maximum=1.0, step=0.05,
                                    label="稳定性",
                                    value=0.5,
                                    info="控制生成的稳定性"
                                )
                        # ── VoxCPM ──
                        with gr.Tab("🔊 VoxCPM", id="VoxCPM") as voxcpm_tab:
                            gr.HTML('<p class="card-desc">本地多模态 TTS 模型（VoxCPM2，48kHz / 30 语言）。支持「描述生成 / 声音克隆 / 极致克隆」三种模式；首次使用需安装 <code>pip install voxcpm</code> 并固定 gradio 5.50.0（见 README）。</p>')
                            with gr.Row():
                                voxcpm_model = gr.Textbox(
                                    value=DEFAULT_VOXCPM_MODEL,
                                    label="模型",
                                    interactive=True,
                                    info="HuggingFace 模型 ID（openbmb/VoxCPM2）或本地模型目录",
                                )
                                voxcpm_device = gr.Dropdown(
                                    get_voxcpm_supported_devices(),
                                    value="auto",
                                    label="运行设备",
                                    interactive=True,
                                    allow_custom_value=True,
                                    info="多卡可填 cuda:0 / cuda:1；与其他项目共用 GPU 时建议用 CUDA_VISIBLE_DEVICES 隔离",
                                )
                            voxcpm_mode = gr.Dropdown(
                                [(label, key) for key, label in VOXCPM_MODES.items()],
                                value="design",
                                label="合成模式",
                                interactive=True,
                                info="design 描述生成音色；clone 参考音频克隆；hifi 极致克隆（参考音频+转写）",
                            )
                            with gr.Row():
                                voxcpm_voice = gr.Dropdown(
                                    get_voxcpm_voice_choices(),
                                    value=VOXCPM_DEFAULT_VOICE_VALUE,
                                    label="音色",
                                    interactive=True,
                                    allow_custom_value=True,
                                    info="内置预设首次使用会自动生成并缓存；可手动放入 wav 到音色库目录自动并入下拉",
                                )
                                voxcpm_voice_dir = gr.Textbox(
                                    value=get_default_voxcpm_voice_dir(),
                                    label="音色库目录",
                                    interactive=True,
                                )
                            with gr.Row():
                                voxcpm_preview_btn = gr.Button("🎧 试听当前预设音色", elem_classes="btn-ghost", scale=1)
                                voxcpm_preview_audio = gr.Audio(label="试听", type="filepath", interactive=False, scale=2)
                            voxcpm_regenerate_voice = gr.Checkbox(
                                label="重新生成预设音色（忽略已有缓存，需重新生成参考音频）",
                                value=False,
                                elem_classes="toggle",
                            )
                            voxcpm_voice_description = gr.TextArea(
                                label="声音描述（design / clone 模式可选）",
                                lines=2,
                                placeholder="例如：成熟稳重的男声，中低音，语速适中。留空则使用所选预设的描述。",
                                interactive=True,
                            )
                            with gr.Row():
                                voxcpm_reference_audio = gr.File(
                                    label="参考音频（clone / hifi 模式，可选）",
                                    file_count="single",
                                    file_types=["audio"],
                                )
                                voxcpm_reference_text = gr.Textbox(
                                    label="参考音频转写文本（hifi 模式）",
                                    lines=2,
                                    placeholder="手填优先；预设音色会自动带试听文本；留空并开启自动转写时用 SenseVoice 识别",
                                    interactive=True,
                                )
                            voxcpm_auto_transcribe = gr.Checkbox(
                                label="自动转写参考音频（hifi 模式，首次需下载 SenseVoice 模型，固定 CPU 运行）",
                                value=False,
                                elem_classes="toggle",
                            )
                            with gr.Row():
                                voxcpm_output_format = gr.Dropdown(
                                    get_voxcpm_supported_output_formats(),
                                    value=DEFAULT_VOXCPM_OUTPUT_FORMAT,
                                    label="输出格式",
                                    interactive=True,
                                )
                                voxcpm_speed_min, voxcpm_speed_max = get_voxcpm_speed_range()
                                voxcpm_speed = gr.Slider(
                                    minimum=voxcpm_speed_min, maximum=voxcpm_speed_max, step=0.05,
                                    label="语速",
                                    value=DEFAULT_VOXCPM_SPEED,
                                    info="1.0 为模型原生语速，越小越慢，越大越快",
                                )
                            with gr.Row():
                                voxcpm_cfg_value = gr.Slider(
                                    minimum=0.5, maximum=8.0, step=0.1,
                                    label="CFG 引导",
                                    value=DEFAULT_VOXCPM_CFG_VALUE,
                                    info="越高越贴合描述/参考音色，越低越自由（官方推荐 2.0）",
                                )
                                voxcpm_inference_timesteps = gr.Slider(
                                    minimum=1, maximum=50, step=1,
                                    label="推理步数",
                                    value=DEFAULT_VOXCPM_INFERENCE_TIMESTEPS,
                                    info="越高质量越好但越慢；官方基准使用 10 步",
                                )
                            with gr.Row():
                                voxcpm_chunk_chars = gr.Slider(
                                    minimum=50, maximum=1200, step=50,
                                    label="分块字数",
                                    value=DEFAULT_VOXCPM_CHUNK_CHARS,
                                    info="VoxCPM 长文本会语速漂移/爆音/OOM，按句分块逐块合成（默认 400 字）",
                                )
                                voxcpm_denoise = gr.Checkbox(
                                    label="降噪参考音频（需额外下载 ZipEnhancer，可能改变音色）",
                                    value=False,
                                    elem_classes="toggle",
                                )
                            with gr.Row():
                                voxcpm_normalize = gr.Checkbox(
                                    label="文本规范化（展开数字/日期等）",
                                    value=True,
                                    elem_classes="toggle",
                                )
                                voxcpm_optimize = gr.Checkbox(
                                    label="启用 torch.compile 优化（CUDA Graphs 不支持多线程并发，GPU 场景请保持 worker_count=1）",
                                    value=True,
                                    elem_classes="toggle",
                                )

                # —— 高级设置弹窗（纯客户端控制；默认 display:none，JS 切换 .show） ——
                with gr.Group(elem_classes="modal-overlay", elem_id="advanced_modal") as advanced_modal:
                    with gr.Column(elem_classes="modal-box"):
                        gr.HTML('''
<div class="modal-header">
  <div>
    <p class="modal-title">高级设置</p>
    <p class="modal-subtitle">集中配置多角色剧本、生成行为和章节解析。</p>
  </div>
  <button type="button" class="modal-close-btn" aria-label="关闭高级设置" onclick="closeAdvancedModal(event)">✕</button>
</div>''', elem_classes="modal-header-wrap")
                        with gr.Column(elem_classes="modal-scroll"):
                            gr.HTML('<p class="modal-desc">修改会在点击“开始生成”时随表单一并生效。</p>')

                            with gr.Group(elem_classes="advanced-section"):
                                gr.HTML('''
<div class="advanced-section-head">
  <span class="advanced-section-badge">1</span>
  <div class="advanced-section-copy">
    <h3>多角色剧本</h3>
    <p>为旁白和不同人物分配音色。支持 MiMo / MiniMax，每次处理一本书。</p>
  </div>
</div>''')
                                role_mode = gr.Checkbox(
                                    label="启用多角色分段模式（MiMo / MiniMax，单本书）",
                                    value=False,
                                    elem_classes="toggle advanced-switch",
                                    elem_id="role_mode_toggle",
                                )
                                with gr.Group(visible=False, elem_id="role_config_panel") as role_config_panel:
                                    gr.HTML('<p id="role_workflow_hint" class="role-workflow-hint" role="status" aria-live="polite">下一步：先生成剧本，或上传已有剧本。</p>')
                                    gr.HTML('''
<div class="advanced-subsection-head role-step-head">
  <span class="role-step-number">1</span>
  <div><h4>准备剧本</h4><p>先在生成页上传一本书并选择 MiMo 或 MiniMax，再生成剧本。已有剧本可直接上传。</p></div>
</div>''')
                                    with gr.Accordion("DeepSeek 连接配置（首次使用）", open=False, elem_classes="role-details"):
                                        gr.Markdown("自动拆分需要 DeepSeek API Key；已保存配置会自动读取。")
                                        deepseek_api_key = gr.Textbox(
                                            label="DeepSeek API Key",
                                            placeholder="请输入 DeepSeek API Key",
                                            type="password",
                                        )
                                        deepseek_show_key = gr.Checkbox(
                                            label="显示 DeepSeek API Key",
                                            value=False,
                                            elem_classes="toggle advanced-compact-toggle",
                                        )
                                        deepseek_api_key_display = gr.HTML("")
                                        with gr.Row(elem_classes="advanced-field-row"):
                                            deepseek_base_url = gr.Textbox(
                                                label="DeepSeek Base URL",
                                                value=DEEPSEEK_DEFAULT_BASE_URL,
                                                placeholder="https://api.deepseek.com",
                                                scale=1,
                                            )
                                            deepseek_model = gr.Textbox(
                                                label="DeepSeek Model",
                                                value=DEEPSEEK_DEFAULT_MODEL,
                                                placeholder="deepseek-chat",
                                                scale=1,
                                            )
                                        with gr.Row(elem_classes="advanced-action-row"):
                                            deepseek_test_btn = gr.Button(
                                                "🔍 测试 DeepSeek 连接", elem_classes="btn-ghost"
                                            )
                                            deepseek_save_btn = gr.Button(
                                                "💾 保存 DeepSeek 配置", elem_classes="btn-primary"
                                            )
                                        deepseek_msg = gr.HTML("")
                                    auto_role_split = gr.Checkbox(
                                        label="上传书籍后自动调用 DeepSeek 拆分角色",
                                        value=False, elem_classes="toggle",
                                        elem_id="auto_role_split_toggle",
                                    )
                                    fullbook_index_ack = gr.Checkbox(
                                        label="我已知晓：全书人物表会分析未选章节，并将正文发送给当前 DeepSeek 服务（会增加调用量）",
                                        value=False, elem_classes="toggle",
                                    )
                                    role_regenerate_btn = gr.Button(
                                        "生成 / 重新拆分剧本", elem_classes="btn-primary", elem_id="role_split_btn"
                                    )
                                    with gr.Accordion("上传或下载剧本 JSON", open=False, elem_classes="role-details"):
                                        role_script_file = gr.File(
                                            label="RoleScript JSON（支持 V1/V2，自动拆分生成 V2）",
                                            file_types=[".json"], file_count="single", type="filepath", interactive=True,
                                        )
                                    gr.HTML('''
<div class="advanced-subsection-head role-step-head">
  <span class="role-step-number">2</span>
  <div><h4>调整角色并试听</h4><p>MiMo 编辑 voice，MiniMax 编辑 voice_id。speed 是倍率：小于 1 更慢，大于 1 更快；不修改角色 ID。</p></div>
</div>''')
                                    role_validation_summary = gr.Markdown("**请上传或自动生成剧本 JSON 后校验**")
                                    role_table = gr.Dataframe(
                                        headers=ROLE_TABLE_HEADERS,
                                        datatype=["str", "str", "str", "str", "number", "str", "number", "number"],
                                        value=[],
                                        label="角色参数表（可编辑音色、语速、instructions 等）",
                                        interactive=True,
                                        wrap=False,
                                        max_height=300,
                                        column_widths=[120, 100, 100, 170, 90, 280, 80, 80],
                                        elem_id="role_parameter_table",
                                        show_fullscreen_button=True,
                                    )
                                    with gr.Accordion("逐段证据与全书人物复核（V2）", open=False, elem_classes="role-details"):
                                        role_review_load_btn = gr.Button("读取待复核段落", elem_classes="btn-ghost")
                                        role_review_segment = gr.Dropdown(label="待复核段落", choices=[], interactive=True)
                                        role_review_info = gr.Markdown("选择 V2 项目后点击读取。")
                                        role_review_entity = gr.Dropdown(label="确认说话人／锁定此人物音色", choices=[], interactive=True)
                                        with gr.Row(elem_classes="advanced-action-row"):
                                            role_review_confirm_btn = gr.Button("确认此段说话人", elem_classes="btn-primary")
                                            role_review_lock_btn = gr.Button("锁定该人物音色", elem_classes="btn-ghost")
                                        with gr.Row(elem_classes="advanced-field-row"):
                                            role_merge_source = gr.Dropdown(label="别名人物（并入后移除）", choices=[], interactive=True)
                                            role_merge_target = gr.Dropdown(label="目标人物（保留其声音）", choices=[], interactive=True)
                                        role_merge_btn = gr.Button("确认同一人物并合并", elem_classes="btn-ghost")
                                    role_split_confirmed = gr.State(False)
                                    role_split_generated = gr.State(False)
                                    role_confirmed_signature = gr.State("")
                                    # 只作为前端读取的人工确认状态载体（不承载剧本内容），
                                    # 供 closeAdvancedModal 判断能否放行“完成”。
                                    # 不能使用 visible=False：Gradio 前端不会渲染该组件，
                                    # MutationObserver / closeAdvancedModal 都读不到
                                    # #role_confirmation_probe，门禁会恒为“已确认”。
                                    # 这里保持可见，用 CSS 做 1px 视觉隐藏。
                                    role_confirmation_probe_host = gr.HTML(
                                        "", elem_id="role_confirmation_probe_host"
                                    )

                                    with gr.Row(elem_classes="advanced-field-row advanced-preview-row"):
                                        role_preview_role = gr.Dropdown(
                                            choices=[],
                                            label="试听角色",
                                            interactive=True,
                                            allow_custom_value=False,
                                        )
                                        role_preview_btn = gr.Button(
                                            "🎧 试听该角色", elem_classes="btn-ghost"
                                        )
                                    role_preview_text = gr.Textbox(
                                        label="试听文本",
                                        value="傍晚的风轻轻吹过窗边，远处的灯光逐渐亮起。我们停下脚步，认真听完了这个温暖而平静的故事。",
                                        lines=2,
                                        interactive=True,
                                    )
                                    role_preview_audio = gr.Audio(
                                        label="角色试听", type="filepath", interactive=False
                                    )

                                    with gr.Accordion("MiMo 音色间语速校准", open=False, elem_classes="role-details"):
                                        gr.Markdown("先把旁白 speed 调到合适的节奏，再校准。将为每个角色调用一次 MiMo，用上方同一段试听文本（20～400 字）测量时长并回填倍率；没有旁白时以首个角色为基准。校准后再试听确认。")
                                        role_calibrate_btn = gr.Button("以旁白为基准校准语速", elem_classes="btn-ghost")
                                        role_calibration_status = gr.Markdown("尚未校准；可先试听，音色间快慢明显时再使用。")
                                    gr.HTML('''
<div class="advanced-subsection-head role-step-head">
  <span class="role-step-number">3</span>
  <div><h4>确认剧本并返回生成</h4><p>核对角色分配和章节摘要，确认当前参数后，返回生成页点击「开始生成」。修改参数后需要重新确认。</p></div>
</div>''')
                                    with gr.Group(
                                        visible=False, elem_id="role_verification_panel"
                                    ) as role_verification_panel:
                                        gr.HTML('''
<div class="advanced-verification-head">
  <h4>剧本摘要</h4>
  <p>检查下方摘要；音色和语速在上一步调整。</p>
</div>''')
                                        role_verification_summary = gr.Markdown("", elem_classes="role-summary")
                                        with gr.Row(elem_classes="advanced-action-row"):
                                            role_confirm_btn = gr.Button(
                                                "确认剧本与角色参数", elem_classes="btn-primary", elem_id="role_confirm_btn"
                                            )

                                    with gr.Accordion("补充音色目录（可选）", open=False, elem_classes="role-details"):
                                        gr.Markdown("内置音色可直接使用。需要补充官网音色时，在此导入文档，再重新拆分剧本。")
                                        voice_catalog_file = gr.File(
                                            label="上传 TTS 官网音色说明文档",
                                            file_types=_VOICE_CATALOG_FILE_TYPES,
                                            file_count="single",
                                            type="filepath",
                                            interactive=True,
                                        )
                                        voice_catalog_text = gr.TextArea(
                                            label="或直接粘贴官网音色说明",
                                            placeholder="支持 JSON、CSV、Markdown/文本表格，以及 voice_id | 名称 | 语言 | 性别 | 说明；文件优先于粘贴内容。",
                                            lines=5,
                                            interactive=True,
                                        )
                                        with gr.Row(elem_classes="advanced-field-row"):
                                            voice_catalog_provider = gr.Dropdown(
                                                choices=list(_VOICE_CATALOG_PROVIDERS),
                                                value="自动识别",
                                                label="文档对应的 TTS Provider",
                                                interactive=True,
                                            )
                                            voice_catalog_language = gr.Dropdown(
                                                choices=list(_VOICE_CATALOG_LANGUAGES),
                                                value="自动识别",
                                                label="文档默认语言",
                                                interactive=True,
                                            )
                                        with gr.Row(elem_classes="advanced-action-row"):
                                            voice_catalog_clear_btn = gr.Button(
                                                "🧹 清空用户音色目录", elem_classes="btn-ghost"
                                            )
                                            voice_catalog_import_btn = gr.Button(
                                                "📥 解析并保存音色目录", elem_classes="btn-primary"
                                            )
                                        voice_catalog_status = gr.Markdown(
                                            _voice_catalog_overview_markdown(),
                                            elem_id="voice_catalog_status",
                                        )
                                    with gr.Accordion("剧本匹配与容错（可选）", open=False, elem_classes="role-details"):
                                        with gr.Group(elem_classes="toggle-grid advanced-toggle-grid"):
                                            allow_role_text_override = gr.Checkbox(
                                                label="允许剧本文本覆盖书籍正文", value=False, elem_classes="toggle"
                                            )
                                            allow_role_title_mismatch = gr.Checkbox(
                                                label="允许章节标题不匹配", value=False, elem_classes="toggle"
                                            )
                                            allow_role_fallback = gr.Checkbox(
                                                label="允许缺失角色回退到 narrator / 全局配置",
                                                value=False,
                                                elem_classes="toggle",
                                            )
                                    with gr.Accordion("生成音频质量测评（可选）", open=False, elem_classes="role-details"):
                                        role_quality_enabled = gr.Checkbox(
                                            label="逐段检测语速、可辨识度和音频完整性（MiMo 未通过时最多重试一次）",
                                            value=False, elem_classes="toggle",
                                        )
                                        role_quality_max_rate = gr.Slider(
                                            minimum=2.0, maximum=7.0, step=0.1, value=4.3,
                                            label="中文语速上限（汉字/秒）",
                                        )
                                        gr.Markdown(
                                            "测评结果保存到输出目录的 `role_quality_reports/`。可辨识度检测需安装本地 "
                                            "FunASR/SenseVoice；不可用时明确标记为「未完整评测」。失败片段仅 MiMo 会将诊断发给 "
                                            "DeepSeek 并重试一次；仍失败会保留最佳版本并标记人工复核。"
                                        )

                            with gr.Group(elem_classes="advanced-section"):
                                gr.HTML('''
<div class="advanced-section-head">
  <span class="advanced-section-badge">2</span>
  <div class="advanced-section-copy">
    <h3>生成选项</h3>
    <p>控制导出内容、预解析、并行度和日志详细程度。</p>
  </div>
</div>''')
                                with gr.Group(elem_classes="toggle-grid advanced-toggle-grid"):
                                    output_text = gr.Checkbox(label="同步导出章节纯文本", value=saved["output_text"], elem_classes="toggle")
                                    preview = gr.Checkbox(label="仅预解析（不生成音频）", value=saved["preview"], elem_classes="toggle")
                                    remove_endnotes = gr.Checkbox(label="剔除书末尾注", value=saved["remove_endnotes"], elem_classes="toggle")
                                    remove_reference_numbers = gr.Checkbox(label="清理数字文献引用", value=saved["remove_reference_numbers"], elem_classes="toggle")
                                with gr.Row(elem_classes="advanced-field-row"):
                                    worker_count = gr.Slider(minimum=1, maximum=8, step=1, label="并行线程数", value=1, info="多线程加速，依配置微调")
                                    log_level = gr.Dropdown(["INFO", "DEBUG", "WARNING", "ERROR", "CRITICAL"], label="日志级别", value="INFO")

                            with gr.Group(elem_classes="advanced-section"):
                                gr.HTML('''
<div class="advanced-section-head">
  <span class="advanced-section-badge">3</span>
  <div class="advanced-section-copy">
    <h3>解析设置</h3>
    <p>调整章节标题匹配、段落换行检测和文本替换规则。</p>
  </div>
</div>''')
                                with gr.Row(elem_classes="advanced-field-row"):
                                    title_mode = gr.Dropdown(["auto", "tag_text", "first_few"], label="章节标题匹配模式", value="auto", interactive=True)
                                    new_line_mode = gr.Dropdown(["single", "double", "none"], label="段落换行检测模式", value="double", interactive=True)
                                search_and_replace_file = gr.File(label="文本替换规则文件 (.txt，可选)", file_types=[".txt"], file_count="single", interactive=True, elem_classes="rules-file-upload")

                        gr.HTML('''
<div class="modal-footer">
  <div class="modal-footer-copy">
    <p class="modal-footer-hint">返回生成页后，点击「开始生成」应用当前设置。</p>
    <p class="modal-footer-gate" id="role_gate_hint" role="alert" style="display:none;"></p>
  </div>
  <button type="button" class="btn-primary modal-done" onclick="closeAdvancedModal(event)">返回生成页</button>
</div>''', elem_classes="modal-footer-wrap")

                # —— CTA ——
                with gr.Row(elem_classes="row-cta"):
                    stop_btn = gr.Button("停止转换", elem_classes="btn-ghost")
                    start_btn = gr.Button("🚀 开始生成有声书", elem_classes="btn-primary pulse", variant="primary")

            # ════════════ 资源库页 ════════════
            with gr.Tab("资源库", id="tab_library"):
                gr.HTML('<div class="hero"><h1>资源库</h1><p>管理已生成的音频文件：批量下载、打包导出、一键清理。</p></div>')
                with gr.Row(elem_classes="row-stack"):
                    with gr.Column(scale=3):
                        with gr.Group(elem_classes="app-card lib-card"):
                            gr.HTML('<p class="card-title">选择导出批次</p>')
                            with gr.Row(elem_classes="lib-row"):
                                folder_dropdown = gr.Dropdown(choices=get_folders_list(), label="批次", show_label=False,
                                                              interactive=True, scale=1)
                                refresh_btn = gr.Button("🔄 刷新", elem_classes="btn-mini", scale=0, min_width=0)
                                delete_folder_btn = gr.Button("🗑️ 删除批次", elem_classes="btn-danger", scale=0, min_width=0)
                        with gr.Group(elem_classes="app-card lib-card"):
                            gr.HTML('<p class="card-title">选择分卷文件（默认全选）</p>')
                            file_selector = gr.CheckboxGroup(choices=[], label="", show_label=False, interactive=True, elem_classes="file-checks")
                            gr.HTML('<div class="section-divider"></div>')
                            with gr.Row(elem_classes="lib-row"):
                                select_all_btn = gr.Button("全选", elem_classes="btn-mini", scale=0, min_width=0)
                                deselect_all_btn = gr.Button("取消", elem_classes="btn-mini", scale=0, min_width=0)
                                delete_btn = gr.Button("🗑️ 删除选中", elem_classes="btn-danger lib-push-right", scale=0, min_width=0)
                    with gr.Column(scale=2):
                        with gr.Group(elem_classes="app-card lib-card"):
                            gr.HTML('<p class="card-title">下载与清理</p>')
                            gr.HTML('<p class="card-desc">勾选「阅后即焚」将在打包后自动删除源文件。</p>')
                            auto_delete_cb = gr.Checkbox(label="阅后即焚（打包后删除源文件）", value=False, elem_classes="toggle")
                            gr.HTML('<div class="section-divider"></div>')
                            generate_btn = gr.Button("⚡ 打包并生成下载通道", elem_classes="btn-primary lib-generate")
                            download_card = gr.HTML(_placeholder_html())
                            real_download_file = gr.File(label="下载通道", interactive=False, visible=False, elem_classes="custom-download-zone")

            # ════════════ 日志页 ════════════
            with gr.Tab("日志", id="tab_logs"):
                gr.HTML('<div class="hero logs-hero"><h1>运行日志</h1><p>实时查看转换进度与详细信息。</p></div>')
                with gr.Group(elem_classes="app-card run-log-card"):
                    global webui_log_file
                    # 固定成绝对路径：进度解析与日志组件都用同一份文件，不受工作目录变化影响
                    webui_log_file = generate_unique_log_path("EtA_WebUI").resolve()
                    webui_log_file.touch()
                    # tail 默认只有 100：页面在生成中途打开/刷新时只能看到最后 100 行，
                    # 看起来就像"日志不全"。这里放宽到 2000 行，并同步加大终端回滚缓冲。
                    # height 同时包含顶部文件信息行；默认 240px 会让 xterm 底部被裁切。
                    # CSS 会把可视高度限制在 1600~3000px（优先 200vh），并回收
                    # xterm 内层多余留白，让终端在当前视口内尽可能大且不裁底。
                    Log(str(webui_log_file), dark=False, height=2800, xterm_font_size=12,
                        elem_id="run_log",
                        tail=3000, xterm_scrollback=8000)

            # ════════════ 设置页 ════════════
            with gr.Tab("⚙️ 设置", id="tab_settings"):
                gr.HTML('<div class="hero"><h1>设置</h1><p>配置 TTS 模型 API 和系统参数。</p></div>')
                
                # 登录状态
                login_state = gr.State(False)
                
                # 登录表单
                with gr.Group(elem_classes="app-card") as login_card:
                    gr.HTML('<p class="card-title"><span class="card-num">🔐</span>管理员登录</p>')
                    gr.HTML('<p class="card-desc">请输入管理员密码以访问设置页面。</p>')
                    admin_password = gr.Textbox(label="管理员密码", type="password", placeholder="请输入密码")
                    login_btn = gr.Button("登录", elem_classes="btn-primary")
                    login_msg = gr.HTML("")
                
                # 设置内容（登录后显示）
                with gr.Group(visible=False, elem_classes="app-card") as settings_card:
                    gr.HTML('<p class="card-title"><span class="card-num">🔑</span>TTS API 配置</p>')
                    gr.HTML('<p class="card-desc">配置各 TTS 引擎的 API Key 和相关参数。配置文件优先级高于环境变量。</p>')
                    
                    with gr.Tabs(elem_classes="engine-tabs") as api_tabs:
                        # MiMo 配置
                        with gr.Tab("✨ MiMo", id="api_mimo"):
                            gr.HTML('<p class="card-desc">MiMo TTS API 配置（基于 OpenAI 兼容接口）</p>')
                            mimo_api_key = gr.Textbox(label="API Key", placeholder="请输入 MiMo API Key", type="password")
                            mimo_api_key_display = gr.HTML("")
                            mimo_show_key = gr.Checkbox(label="显示 API Key", value=False, elem_classes="toggle")
                            mimo_base_url = gr.Textbox(label="Base URL", value="https://token-plan-cn.xiaomimimo.com/v1", placeholder="请输入 Base URL")
                            with gr.Row():
                                mimo_test_btn = gr.Button("🔍 测试连接", elem_classes="btn-ghost")
                                mimo_save_btn = gr.Button("💾 保存配置", elem_classes="btn-primary")
                            mimo_msg = gr.HTML("")
                        
                        # MiniMax 配置
                        with gr.Tab("🎙️ MiniMax", id="api_minimax"):
                            gr.HTML('<p class="card-desc">MiniMax TTS API 配置</p>')
                            minimax_api_key = gr.Textbox(label="API Key", placeholder="请输入 MiniMax API Key", type="password")
                            minimax_api_key_display = gr.HTML("")
                            minimax_show_key = gr.Checkbox(label="显示 API Key", value=False, elem_classes="toggle")
                            with gr.Row():
                                minimax_test_btn = gr.Button("🔍 测试连接", elem_classes="btn-ghost")
                                minimax_save_btn = gr.Button("💾 保存配置", elem_classes="btn-primary")
                            minimax_msg = gr.HTML("")
                        
                        # Qwen 配置
                        with gr.Tab("🤖 Qwen TTS", id="api_qwen"):
                            gr.HTML('<p class="card-desc">Qwen TTS API 配置</p>')
                            qwen_api_key = gr.Textbox(label="API Key", placeholder="请输入 Qwen API Key", type="password")
                            qwen_api_key_display = gr.HTML("")
                            qwen_show_key = gr.Checkbox(label="显示 API Key", value=False, elem_classes="toggle")
                            qwen_base_url = gr.Textbox(label="Base URL", value="https://gpu.ncut.edu.cn/v1", placeholder="请输入 Base URL")
                            qwen_model = gr.Textbox(label="Model", value="qwen3-tts-12hz-1.7b-voicedesign", placeholder="请输入模型名称")
                            with gr.Row():
                                qwen_test_btn = gr.Button("🔍 测试连接", elem_classes="btn-ghost")
                                qwen_save_btn = gr.Button("💾 保存配置", elem_classes="btn-primary")
                            qwen_msg = gr.HTML("")

                # 修改密码区域
                with gr.Group(visible=False, elem_classes="app-card") as password_card:
                    gr.HTML('<p class="card-title"><span class="card-num">🔒</span>修改密码</p>')
                    old_password = gr.Textbox(label="原密码", type="password", placeholder="请输入原密码")
                    new_password = gr.Textbox(label="新密码", type="password", placeholder="请输入新密码（至少4位）")
                    confirm_password = gr.Textbox(label="确认新密码", type="password", placeholder="请再次输入新密码")
                    change_pwd_btn = gr.Button("修改密码", elem_classes="btn-ghost")
                    change_pwd_msg = gr.HTML("")

        # ════════════ 事件绑定 ════════════
        # 引擎标签切换 → 同步 provider_state（服务端）+ 更新徽标文字（客户端 js）
        # js 在 Tab 被选中时立即执行，不经过服务端 queue，零延迟更新徽标
        _PROVIDER_IDS = {"MiMo": "Mimo", "MiniMax": "MiniMax", "Edge": "Edge", "Qwen": "Qwen",
                         "Chatterbox": "Chatterbox", "VoxCPM": "VoxCPM"}
        for _tab, _display in [(mimo_tab, "MiMo"), (minimax_tab, "MiniMax"),
                            (edge_tab, "Edge"), (qwen_tab, "Qwen"),
                            (chatterbox_tab, "Chatterbox"),
                            (voxcpm_tab, "VoxCPM")]:
            _id = _PROVIDER_IDS[_display]
            _js = f"() => {{ const el = document.getElementById('engine_badge_name'); if (el) el.textContent = '{_display}'; }}"
            _tab.select(fn=lambda n=_id: n,
                        inputs=None, outputs=provider_state, show_progress="hidden",
                        js=_js)

        role_mode.change(
            fn=lambda enabled: gr.update(visible=bool(enabled)),
            inputs=role_mode,
            outputs=role_config_panel,
            show_progress="hidden",
        )
        voice_catalog_import_btn.click(
            fn=import_voice_catalog_document_ui,
            inputs=[
                voice_catalog_file,
                voice_catalog_text,
                voice_catalog_provider,
                voice_catalog_language,
            ],
            outputs=[voice_catalog_status, voices, minimax_voice],
            show_progress="hidden",
        )
        voice_catalog_clear_btn.click(
            fn=clear_voice_catalog_ui,
            inputs=None,
            outputs=[voice_catalog_status, voices, minimax_voice],
            show_progress="hidden",
        )
        _auto_split_inputs = [
            input_file,
            role_mode,
            auto_role_split,
            provider_state,
            chapter_start,
            chapter_end,
            title_mode,
            new_line_mode,
            remove_endnotes,
            remove_reference_numbers,
            search_and_replace_file,
            deepseek_api_key,
            deepseek_base_url,
            deepseek_model,
            fullbook_index_ack,
        ]
        _auto_split_outputs = [
            role_script_file,
            role_table,
            role_validation_summary,
            role_preview_role,
            role_verification_summary,
            role_verification_panel,
            role_split_confirmed,
            role_split_generated,
            role_confirmed_signature,
            role_confirmation_probe_host,
        ]
        # 书籍上传后才触发；关闭角色模式时不会创建 Provider，也不会调用 DeepSeek。
        input_file.change(
            fn=auto_split_role_script,
            inputs=_auto_split_inputs,
            outputs=_auto_split_outputs,
            show_progress="full",
        )
        # 允许先上传书再开启角色模式，或直接点击“重新生成”。
        role_mode.change(
            fn=auto_split_role_script,
            inputs=_auto_split_inputs,
            outputs=_auto_split_outputs,
            show_progress="full",
        )
        role_regenerate_btn.click(
            fn=split_role_script_now,
            inputs=_auto_split_inputs,
            outputs=_auto_split_outputs,
            show_progress="full",
        )
        role_calibrate_btn.click(
            fn=calibrate_role_pace,
            inputs=[provider_state, role_script_file, role_table, role_preview_text,
                    model, voices, speed, instructions, enable_stream],
            outputs=[role_table, role_calibration_status],
            show_progress="full",
        )
        role_review_load_btn.click(
            fn=load_role_review, inputs=role_script_file,
            outputs=[role_review_segment, role_review_entity, role_merge_source,
                     role_merge_target, role_review_info], show_progress="hidden",
        )
        role_review_segment.change(
            fn=role_review_details, inputs=[role_script_file, role_review_segment],
            outputs=role_review_info, show_progress="hidden",
        )
        for review_button, operation in [
            (role_review_confirm_btn, "confirm"),
            (role_review_lock_btn, "lock"),
            (role_merge_btn, "merge"),
        ]:
            review_button.click(
                fn=lambda file_obj, segment_id, entity_id, source_id, target_id, op=operation:
                    apply_role_review(file_obj, op, segment_id, entity_id, source_id, target_id),
                inputs=[role_script_file, role_review_segment, role_review_entity,
                        role_merge_source, role_merge_target],
                outputs=[role_review_segment, role_table, role_review_info,
                         role_split_confirmed, role_confirmed_signature, role_confirmation_probe_host],
                show_progress="hidden",
            )
        role_confirm_btn.click(
            fn=confirm_auto_role_script,
            inputs=[
                role_script_file,
                role_table,
                provider_state,
                openai_output_format,
                minimax_output_format,
            ],
            outputs=[
                role_split_confirmed,
                role_verification_summary,
                role_validation_summary,
                role_confirmed_signature,
                role_confirmation_probe_host,
            ],
            show_progress="hidden",
        )
        role_script_file.change(
            fn=manual_role_script_uploaded,
            inputs=[
                role_script_file,
                provider_state,
                openai_output_format,
                minimax_output_format,
                role_split_confirmed,
                role_split_generated,
                role_confirmed_signature,
            ],
            outputs=[
                role_table,
                role_validation_summary,
                role_preview_role,
                role_verification_summary,
                role_verification_panel,
                role_split_confirmed,
                role_split_generated,
                role_confirmed_signature,
                role_confirmation_probe_host,
            ],
            show_progress="hidden",
        )
        role_table.change(
            fn=role_table_changed,
            inputs=[
                role_script_file,
                provider_state,
                openai_output_format,
                minimax_output_format,
                role_split_confirmed,
                role_confirmed_signature,
                role_table,
            ],
            outputs=[
                role_validation_summary,
                role_preview_role,
                role_split_confirmed,
                role_confirmed_signature,
                role_confirmation_probe_host,
            ],
            show_progress="hidden",
        )
        role_preview_btn.click(
            fn=preview_role_segment,
            inputs=[provider_state, role_script_file, role_table, role_preview_role, role_preview_text,
                    model, voices, speed, instructions, enable_stream, openai_output_format,
                    minimax_model, minimax_voice, minimax_output_format],
            outputs=[role_preview_audio],
            show_progress="hidden",
        )

        voxcpm_preview_btn.click(
            fn=voxcpm_preview_voice,
            inputs=[voxcpm_voice, voxcpm_model, voxcpm_device, voxcpm_voice_dir,
                    voxcpm_cfg_value, voxcpm_inference_timesteps, voxcpm_regenerate_voice],
            outputs=[voxcpm_preview_audio],
            show_progress="hidden",
        )

        # 开始 / 停止
        start_btn.click(
            fn=process_form,
            inputs=[provider_state, input_file, output_dir, worker_count, log_level, output_text, preview,
                    search_and_replace_file, title_mode, new_line_mode, chapter_start, chapter_end,
                    remove_endnotes, remove_reference_numbers,
                    model, voices, speed, openai_output_format, instructions, enable_stream,
                    minimax_model, minimax_voice, minimax_output_format,
                    edge_language, edge_voice, edge_output_format, proxy, edge_voice_rate,
                    edge_volume, edge_pitch, edge_break_duration,
                    qwen_language, qwen_voice,
                    chatterbox_model, chatterbox_device, chatterbox_output_format,
                    chatterbox_reference_audio, chatterbox_exaggeration, chatterbox_cfg_weight, chatterbox_speed,
                    voxcpm_model, voxcpm_mode, voxcpm_voice, voxcpm_voice_dir, voxcpm_voice_description,
                    voxcpm_regenerate_voice, voxcpm_reference_audio, voxcpm_reference_text, voxcpm_auto_transcribe,
                    voxcpm_device, voxcpm_denoise, voxcpm_normalize, voxcpm_cfg_value,
                    voxcpm_inference_timesteps, voxcpm_speed, voxcpm_chunk_chars, voxcpm_optimize,
                    voxcpm_output_format,
                    role_mode, auto_role_split, role_script_file, role_table,
                    role_split_confirmed, role_split_generated, role_confirmed_signature,
                    allow_role_text_override, allow_role_title_mismatch, allow_role_fallback,
                    role_quality_enabled, role_quality_max_rate,
                    deepseek_api_key, deepseek_base_url, deepseek_model],
            outputs=[progress_state, progress_timer])
        stop_btn.click(fn=terminate_generator, inputs=None, outputs=[progress_state, progress_timer])

        # 进度条定时更新
        progress_timer.tick(fn=get_progress_info, inputs=None, outputs=[progress_state, progress_timer], show_progress="hidden")
        # 页面加载/刷新时同步一次状态：新会话也能看到当前进度，并在有批次在跑时自动开始轮询
        ui.load(fn=get_progress_info, inputs=None, outputs=[progress_state, progress_timer], show_progress="hidden")

        # 资源库
        refresh_btn.click(fn=refresh_batches, inputs=None, outputs=[folder_dropdown, file_selector], show_progress="hidden")
        folder_dropdown.change(fn=load_files_for_folder, inputs=folder_dropdown, outputs=file_selector, show_progress="hidden")
        select_all_btn.click(fn=lambda f: gr.update(value=get_files_in_folder(f)), inputs=folder_dropdown, outputs=file_selector, show_progress="hidden")
        deselect_all_btn.click(fn=lambda: gr.update(value=[]), inputs=None, outputs=file_selector, show_progress="hidden")
        delete_btn.click(fn=delete_selected_files, inputs=[folder_dropdown, file_selector],
                         outputs=[folder_dropdown, file_selector, download_card, real_download_file])
        delete_folder_btn.click(fn=delete_entire_folder, inputs=folder_dropdown,
                                outputs=[folder_dropdown, file_selector, download_card, real_download_file])
        generate_btn.click(fn=generate_download, inputs=[folder_dropdown, file_selector, auto_delete_cb],
                           outputs=[folder_dropdown, file_selector, download_card, real_download_file])

        # 持久化开关
        output_text.change(fn=lambda v: _save_checkbox("output_text", v), inputs=output_text, outputs=None, show_progress="hidden")
        preview.change(fn=lambda v: _save_checkbox("preview", v), inputs=preview, outputs=None, show_progress="hidden")
        remove_endnotes.change(fn=lambda v: _save_checkbox("remove_endnotes", v), inputs=remove_endnotes, outputs=None, show_progress="hidden")
        remove_reference_numbers.change(fn=lambda v: _save_checkbox("remove_reference_numbers", v),
                                        inputs=remove_reference_numbers, outputs=None, show_progress="hidden")
        show_voice_instructions.change(fn=lambda v: _save_checkbox("show_voice_instructions", v),
                                        inputs=show_voice_instructions, outputs=None, show_progress="hidden")

        # ════════════ 设置页事件绑定 ════════════
        
        # 登录验证
        def handle_login(password, current_state):
            try:
                if current_state:
                    return current_state, "", gr.update(visible=True), gr.update(visible=True)
                if _verify_admin_password(password):
                    return (
                        True,
                        '<div style="color: var(--apple-green); font-weight: 600;">✅ 登录成功</div>',
                        gr.update(visible=True),
                        gr.update(visible=True),
                    )
                else:
                    return False, '<div style="color: var(--apple-red); font-weight: 600;">❌ 密码错误</div>', gr.update(visible=False), gr.update(visible=False)
            except Exception as e:
                return False, f'<div style="color: var(--apple-red); font-weight: 600;">❌ 登录出错: {e}</div>', gr.update(visible=False), gr.update(visible=False)
        
        login_btn.click(
            fn=handle_login,
            inputs=[admin_password, login_state],
            outputs=[login_state, login_msg, settings_card, password_card],
            show_progress="hidden"
        )
        
        # MiMo API Key 显示/隐藏
        def toggle_mimo_key(show, api_key):
            if show:
                return api_key, ""
            else:
                return "", mimo_mask_api_key(api_key) if api_key else ""
        
        mimo_show_key.change(
            fn=toggle_mimo_key,
            inputs=[mimo_show_key, mimo_api_key],
            outputs=[mimo_api_key, mimo_api_key_display],
            show_progress="hidden"
        )
        
        # MiMo 保存
        mimo_save_btn.click(
            fn=_save_mimo_api_config,
            inputs=[mimo_api_key, mimo_base_url],
            outputs=mimo_msg,
            show_progress="hidden"
        )
        
        # MiMo 测试连接
        mimo_test_btn.click(
            fn=_test_mimo_api,
            inputs=[mimo_api_key, mimo_base_url],
            outputs=mimo_msg,
            show_progress="hidden"
        )
        
        # MiniMax API Key 显示/隐藏
        def toggle_minimax_key(show, api_key):
            if show:
                return api_key, ""
            else:
                return "", minimax_mask_api_key(api_key) if api_key else ""
        
        minimax_show_key.change(
            fn=toggle_minimax_key,
            inputs=[minimax_show_key, minimax_api_key],
            outputs=[minimax_api_key, minimax_api_key_display],
            show_progress="hidden"
        )
        
        # MiniMax 保存
        minimax_save_btn.click(
            fn=_save_minimax_api_config,
            inputs=[minimax_api_key],
            outputs=minimax_msg,
            show_progress="hidden"
        )
        
        # MiniMax 测试连接
        minimax_test_btn.click(
            fn=_test_minimax_api,
            inputs=[minimax_api_key],
            outputs=minimax_msg,
            show_progress="hidden"
        )
        
        # Qwen API Key 显示/隐藏
        def toggle_qwen_key(show, api_key):
            if show:
                return api_key, ""
            else:
                return "", qwen_mask_api_key(api_key) if api_key else ""
        
        qwen_show_key.change(
            fn=toggle_qwen_key,
            inputs=[qwen_show_key, qwen_api_key],
            outputs=[qwen_api_key, qwen_api_key_display],
            show_progress="hidden"
        )
        
        # Qwen 保存
        qwen_save_btn.click(
            fn=_save_qwen_api_config,
            inputs=[qwen_api_key, qwen_base_url, qwen_model],
            outputs=qwen_msg,
            show_progress="hidden"
        )
        
        # Qwen 测试连接
        qwen_test_btn.click(
            fn=_test_qwen_api,
            inputs=[qwen_api_key, qwen_base_url, qwen_model],
            outputs=qwen_msg,
            show_progress="hidden"
        )

        # DeepSeek API Key 显示/隐藏（只用于多角色脚本自动拆分）
        def toggle_deepseek_key(show, api_key):
            if show:
                return api_key, ""
            return "", deepseek_mask_api_key(api_key) if api_key else ""

        deepseek_show_key.change(
            fn=toggle_deepseek_key,
            inputs=[deepseek_show_key, deepseek_api_key],
            outputs=[deepseek_api_key, deepseek_api_key_display],
            show_progress="hidden"
        )
        deepseek_save_btn.click(
            fn=_save_deepseek_api_config,
            inputs=[deepseek_api_key, deepseek_base_url, deepseek_model],
            outputs=deepseek_msg,
            show_progress="hidden"
        )
        deepseek_test_btn.click(
            fn=_test_deepseek_api,
            inputs=[deepseek_api_key, deepseek_base_url, deepseek_model],
            outputs=deepseek_msg,
            show_progress="hidden"
        )
        
        # 修改密码
        def handle_change_password(old_pwd, new_pwd, confirm_pwd):
            if new_pwd != confirm_pwd:
                return '<div style="color: var(--apple-red); font-weight: 600;">❌ 两次输入的新密码不一致</div>'
            success, msg = _change_admin_password(old_pwd, new_pwd)
            if success:
                return f'<div style="color: var(--apple-green); font-weight: 600;">✅ {msg}</div>'
            else:
                return f'<div style="color: var(--apple-red); font-weight: 600;">❌ {msg}</div>'
        
        change_pwd_btn.click(
            fn=handle_change_password,
            inputs=[old_password, new_password, confirm_password],
            outputs=change_pwd_msg,
            show_progress="hidden"
        )
        
        # 页面加载时初始化 API 配置
        def init_api_configs():
            configs = _load_api_configs()
            return (
                configs["mimo_api_key"],
                configs["mimo_api_key_masked"],
                configs["mimo_base_url"],
                configs["minimax_api_key"],
                configs["minimax_api_key_masked"],
                configs["qwen_api_key"],
                configs["qwen_api_key_masked"],
                configs["qwen_base_url"],
                configs["qwen_model"],
                configs["deepseek_api_key"],
                configs["deepseek_api_key_masked"],
                configs["deepseek_base_url"],
                configs["deepseek_model"],
            )
        
        # 初始化配置（隐藏 API Key）
        ui.load(
            fn=init_api_configs,
            inputs=None,
            outputs=[mimo_api_key, mimo_api_key_display, mimo_base_url,
                    minimax_api_key, minimax_api_key_display,
                    qwen_api_key, qwen_api_key_display, qwen_base_url, qwen_model,
                    deepseek_api_key, deepseek_api_key_display,
                    deepseek_base_url, deepseek_model],
            show_progress="hidden"
        )

    temp_dir = os.path.join(get_output_dir(), ".temp_downloads")
    ui.launch(
        server_name=config.host,
        server_port=config.port,
        prevent_thread_lock=False,
        allowed_paths=[get_output_dir(), temp_dir],
    )
