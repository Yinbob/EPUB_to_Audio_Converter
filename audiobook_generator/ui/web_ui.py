"""
Apple 风格 WebUI —— 全新设计的有声书生成工作台。

设计理念：
- 完全摒弃旧版单页堆叠式表单，改用「二级页面 + 弹窗」结构。
- 顶部胶囊导航在「转换 / 资源库 / 日志」三个主页面间切换。
- TTS 引擎配置以卡片选择 + 浮层弹窗（Modal）形式呈现。
- 苹果风视觉：留白、毛玻璃、SF 字体、克制动效、渐变高亮。

生成、配音与资源下载按步骤组织，当前为项目唯一的 WebUI。
入口：main_ui.py
"""

from multiprocessing import Process, get_context
from typing import Optional
from pathlib import Path
from dataclasses import asdict, replace
from functools import wraps
import hashlib
import html
import inspect
import os
import json
import logging
import math
import signal
import tempfile
import threading
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
    preview_voxcpm_preset_audio,
)
from audiobook_generator.utils.voxcpm_voices import (
    resolve_voxcpm_voice,
)
from audiobook_generator.utils.log_handler import generate_unique_log_path
from audiobook_generator.ui.ambient_background import AMBIENT_CSS, AMBIENT_LAYER_HTML
from audiobook_generator.ui.progress_parser import decide_progress_state, parse_progress
from audiobook_generator.ui.workflow import WORKFLOW_CSS, WORKFLOW_HEAD_HTML, workflow_steps_html
from audiobook_generator.ui.role_studio import (
    ROLE_STUDIO_CSS, ROLE_SPLIT_HEAD, split_result_status, render_split_status, iter_split_events,
)
from audiobook_generator.ui.chapters import (
    CHAPTER_CSS, CHAPTER_HEAD_HTML, CHAPTER_OVERVIEW_HTML,
    chapter_catalog, chapter_choices, range_payload,
)
from audiobook_generator.ui.library import selection_details, create_archive, selected_paths
from audiobook_generator.ui.log_layout import LOG_LAYOUT_HEAD_HTML
from audiobook_generator.ui.theme import THEME_CSS, THEME_HEAD_HTML, THEME_TOKENS_CSS
from audiobook_generator.ui.voxcpm_panel import build_voxcpm_panel
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
    assign_chapter_narrator, confirm_segment_speaker, lock_entity_voice, merge_entities, pending_segments,
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
    return gr.update(value=path, visible=True)


# ── 多角色剧本 ───────────────────────────────────────────────────
ROLE_TABLE_HEADERS = [
    "role_id", "display_name", "voice", "voice_id", "speed",
    "instructions", "pitch", "volume", "声音档案（由声音设置填写）",
]
from audiobook_generator.ui.role_voices import MIMO_PROFILE_FIELDS, make_voice_profile, role_voice_choices, saved_role_voice_key

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


def role_provider_changed(provider: str):
    """切换引擎只更新兼容性提示，保留剧本与多角色开关，避免静默改成单音色。"""
    supported = _role_provider_id(provider) is not None
    message = (
        "当前引擎支持多角色模式；剧本必须与所选引擎一致。"
        if supported else
        f"⚠️ {provider} 不支持多角色模式。请切回 MiMo / MiniMax，或关闭多角色模式后生成。已有剧本和角色设置会保留。"
    )
    return provider, message, gr.update(interactive=supported)


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
_ROLE_PREVIEW_BINDINGS = {}


_ROLE_SCRIPT_ORIGINS = {}
_ROLE_SCRIPT_ALIASES = {}
_ROLE_SPLITTING_PROJECTS = set()
_ROLE_RECONFIRM_PROJECTS = set()
_ROLE_SPLIT_LOCK = threading.RLock()


def _role_project_operation(fn):
    """本地校验至保存／启动是一个操作，不能被拆分入口穿插。

    仅串行化短暂的本地操作；远端拆分请求期间不持有此锁。
    """
    @wraps(fn)
    def guarded(*args, **kwargs):
        with _ROLE_SPLIT_LOCK:
            return fn(*args, **kwargs)
    return guarded


def _begin_role_split(input_file):
    """按书籍指纹占用项目；在首帧反馈前作废旧确认，不读取或更改旧剧本。"""
    files = input_file if isinstance(input_file, (list, tuple)) else [input_file]
    if len(files) != 1:
        return None
    raw = _uploaded_file_path(files[0])
    if not raw or not Path(raw).is_file():
        return None  # 无效输入交给原有拆分校验报告。
    key = str(project_path(get_output_dir(), _sha256_file_ui(raw)).resolve())
    with _ROLE_SPLIT_LOCK:
        if running_process and running_process.is_alive():
            raise ValueError('请等待当前音频生成结束或停止后，再重新拆分剧本')
        if key in _ROLE_SPLITTING_PROJECTS:
            raise ValueError('这本书正在拆分，请等待当前拆分完成')
        _ROLE_SPLITTING_PROJECTS.add(key)
        _ROLE_RECONFIRM_PROJECTS.add(key)
        _ROLE_CONFIRMED_SCRIPTS.pop(key, None)
    return key


def _end_role_split(key):
    with _ROLE_SPLIT_LOCK:
        _ROLE_SPLITTING_PROJECTS.discard(key)


def _role_project_is_splitting(file_obj):
    path = _role_script_path(file_obj)
    if not path:
        return False
    with _ROLE_SPLIT_LOCK:
        return str(Path(path).resolve()) in _ROLE_SPLITTING_PROJECTS


def _role_project_needs_reconfirmation(file_obj):
    path = _role_script_path(file_obj)
    if not path:
        return False
    with _ROLE_SPLIT_LOCK:
        return str(Path(path).resolve()) in _ROLE_RECONFIRM_PROJECTS


def _guarded_split_events(values):
    try:
        key = _begin_role_split(values[0])
    except (OSError, TypeError, ValueError) as exc:
        yield {'state': 'failed', 'message': str(exc)}
        return
    yield from iter_split_events(auto_split_role_script, values,
                                 on_finish=lambda: _end_role_split(key))


def _register_role_script_origin(path):
    """只登记本服务生成的项目，不能依据客户端提供的路径建立信任。"""
    canonical = Path(path).resolve()
    roots = [Path(get_output_dir()).resolve() / name for name in (".role_projects", ".role_generated")]
    if not canonical.is_file() or not any(canonical.is_relative_to(root) for root in roots):
        raise ValueError("自动剧本不在项目目录中")
    _ROLE_SCRIPT_ORIGINS[_sha256_file_ui(str(canonical))] = str(canonical)


def _role_script_path(file_obj):
    """恢复已登记剧本的真实项目路径，兼容Gradio的传输缓存副本。"""
    raw = _uploaded_file_path(file_obj)
    if not raw or not Path(raw).is_file():
        return raw
    digest = _sha256_file_ui(raw)
    alias = (os.path.abspath(raw), digest)
    canonical = _ROLE_SCRIPT_ALIASES.get(alias) or _ROLE_SCRIPT_ORIGINS.get(digest)
    if canonical and Path(canonical).is_file():
        _ROLE_SCRIPT_ALIASES[alias] = canonical
        return canonical
    return raw


def _remember_role_confirmation(file_obj, signature: str) -> None:
    """把人工确认结果落到服务端缓存，避免前端 State 被竞态覆盖。"""
    path = _role_script_path(file_obj)
    if not path or not signature:
        return
    try:
        key = os.path.abspath(path)
    except (TypeError, ValueError):
        return
    with _ROLE_SPLIT_LOCK:
        if str(Path(key).resolve()) in _ROLE_SPLITTING_PROJECTS:
            return
        _ROLE_CONFIRMED_SCRIPTS[key] = str(signature)
        _ROLE_RECONFIRM_PROJECTS.discard(str(Path(key).resolve()))


def _forget_role_confirmation(file_obj) -> None:
    """剧本被重新生成时清掉旧的确认记录（同一路径、内容已变）。"""
    path = _role_script_path(file_obj)
    if not path:
        return
    try:
        key = os.path.abspath(path)
    except (TypeError, ValueError):
        return
    _ROLE_CONFIRMED_SCRIPTS.pop(key, None)


def _recall_role_confirmation(file_obj) -> str:
    """读取服务端人工确认记录；文件或内容变化时由调用方做指纹比对兜底。"""
    if _role_project_is_splitting(file_obj):
        return ""
    path = _role_script_path(file_obj)
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
    path = _role_script_path(file_obj)
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
            params.get("speed", 1.0),
            params.get("instructions", ""),
            params.get("pitch", 0.0),
            params.get("volume", 1.0),
            json.dumps({k: v for k, v in params.items() if k in MIMO_PROFILE_FIELDS}, ensure_ascii=False),
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
        original_role = script.roles.get(role_id)
        params = dict(original_role.provider_params) if original_role else {}
        if script.provider == "openai":
            profile = _role_text(values[8])
            if profile:
                settings = json.loads(profile)
                if not isinstance(settings, dict) or set(settings) - MIMO_PROFILE_FIELDS:
                    raise ValueError("声音档案包含未知字段")
                for name in MIMO_PROFILE_FIELDS:
                    params.pop(name, None)
                params.update(settings)
            for name in ("voice", "instructions", "speed"):
                params.pop(name, None)
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
            for name in ("voice_id", "speed", "pitch", "volume"):
                params.pop(name, None)
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


def load_role_voice_settings(file_obj, table, selected):
    """从当前表格加载声音设置，不调用模型。"""
    script, report = _load_uploaded_role_script(file_obj)
    if not script or not report.ok or not selected:
        return (gr.update(),) * 8
    try:
        script = _apply_role_table(script, table)
        role_id = selected.split(" — ", 1)[0]
        params = script.roles[role_id].provider_params
        saved_voice = saved_role_voice_key(params)
        return ("preset" if saved_voice else params.get("voice_mode", "preset"), saved_voice or params.get("voice") or "mimo_default",
                params.get("voice_description", ""), params.get("reference_audio_path"),
                params.get("voice_language") or detect_role_script_language(script),
                params.get("speed", 1.0), params.get("instructions", ""),
                "已载入当前角色。修改后点击「应用声音设置」，再试听与确认剧本。")
    except (ValueError, KeyError) as exc:
        return *((gr.update(),) * 7), f"声音设置读取失败：{exc}"


def use_preview_as_role_reference(file_obj, table, selected, audio, language, pace, instructions):
    """用户选用当前试听作为固定参考；本步只保存本地文件。"""
    script, report = _load_uploaded_role_script(file_obj)
    try:
        if not script or not report.ok:
            raise ValueError("请先生成角色剧本")
        current = _apply_role_table(script, table)
        current = _ensure_role_voice_diversity(current, ValidationReport(schema_version=current.schema_version))
        role_id = str(selected or "").split(" — ", 1)[0]
        path = _uploaded_file_path(audio)
        expected = (role_id, _role_confirmation_signature(current),
                    _sha256_file_ui(path) if path and Path(path).is_file() else None)
        if not path or expected not in _ROLE_PREVIEW_BINDINGS.values():
            raise ValueError("请先用当前角色和参数重新试听，再固定该试听音色")
    except (ValueError, OSError) as exc:
        return gr.update(), str(exc), gr.update(), gr.update()
    rows, message = apply_role_voice_settings(file_obj, table, selected, "clone", None, None,
                                             audio, language, pace, instructions)
    if isinstance(rows, dict):
        return rows, message, gr.update(), gr.update()
    role_id = str(selected).split(" — ", 1)[0]
    row = next(row for row in rows if row[0] == role_id)
    params = json.loads(row[8])
    return rows, message, "clone", params["reference_audio_path"]


def apply_role_voice_settings(file_obj, table, selected, mode, voice, description,
                              reference, language, pace, instructions):
    """将界面声音档案回填角色表；上传的参考仅保存本地。"""
    script, report = _load_uploaded_role_script(file_obj)
    try:
        if not script or not report.ok or script.provider != "openai":
            raise ValueError("请先生成 MiMo 角色剧本")
        role_id = str(selected or "").split(" — ", 1)[0]
        script = _apply_role_table(script, table)
        if role_id not in script.roles:
            raise ValueError("请先选择要设置的角色")
        params = make_voice_profile(role_id, mode, voice, description,
                                    _uploaded_file_path(reference), language, pace, instructions,
                                    get_output_dir())
        roles = dict(script.roles)
        roles[role_id] = replace(roles[role_id], provider_params=params)
        updated = replace(script, roles=roles)
        result = validate_role_script(updated)
        if not result.ok:
            raise ValueError(_format_role_validation_report(result.report, "声音设置校验"))
        _forget_role_confirmation(file_obj)
        return _role_table_rows(updated), "已应用声音设置。请试听后重新确认剧本；参考音将在试听或生成时发送至 MiMo。"
    except (ValueError, OSError, TypeError) as exc:
        gr.Warning(str(exc))
        return gr.update(), f"未应用：{exc}"


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


def _role_choice_update(script, selected=None):
    choices, names = [], {}
    for role_id, role in script.roles.items():
        name = ' '.join(str(role.display_name).split()) or role_id
        names[name] = names.get(name, 0) + 1
        label = name if names[name] == 1 else f'{name}（{names[name]}）'
        choices.append((label, role_id))
    current = str(selected or '').split(' — ', 1)[0]
    return gr.update(choices=choices, value=current if current in script.roles else (choices[0][1] if choices else None))


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
    return rows, _format_role_validation_report(report), _role_choice_update(script)


def role_table_changed(
    file_obj,
    provider,
    openai_output_format,
    minimax_output_format,
    role_split_confirmed,
    role_confirmed_signature,
    table_value,
    selected_role=None,
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
    confirmed_signature = str(role_confirmed_signature or "") or _recall_role_confirmation(file_obj)
    # 程序化 / 无内容变化的 change 事件也带 role_split_confirmed=False 的旧快照；
    # 只要内容指纹仍与已确认指纹一致，就不能把人工确认打回未确认状态。
    still_confirmed = normalized is not None and bool(confirmed_signature) and new_signature == confirmed_signature
    if not still_confirmed:
        _forget_role_confirmation(file_obj)
    return (
        _format_role_validation_report(report),
        _role_choice_update(effective_script, selected_role),
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

    _ROLE_PREVIEW_BINDINGS[os.path.abspath(destination)] = (
        role_id, _role_confirmation_signature(normalized), _sha256_file_ui(destination))
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


def _chapter_directory_source(input_file, provider, title_mode, new_line_mode,
                              remove_endnotes, remove_reference_numbers, search_and_replace_file):
    files = input_file if isinstance(input_file, (list, tuple)) else [input_file] if input_file else []
    paths = [_uploaded_file_path(file_obj) for file_obj in files]
    book_hashes = [_sha256_file_ui(path) for path in paths]
    replacement = _uploaded_file_path(search_and_replace_file)
    source = parser_fingerprint({
        "books": book_hashes, "provider": provider, "title_mode": title_mode or "auto",
        "newline_mode": new_line_mode or "double", "remove_endnotes": bool(remove_endnotes),
        "remove_reference_numbers": bool(remove_reference_numbers),
        "replacements": _sha256_file_ui(replacement) if replacement else None,
    })
    return source, paths, book_hashes


def resolve_book_chapter_range(input_file, provider, title_mode, new_line_mode,
                               remove_endnotes, remove_reference_numbers, search_and_replace_file,
                               start, end, catalog_state, selection_source, first, last):
    """执行入口读当前下拉值，拒绝换书/改设置期间的旧目录与旧控件快照。"""
    if catalog_state is None:
        return start, end  # 兼容既有非网页调用，仍由原生成链路校验。
    source, _, _ = _chapter_directory_source(
        input_file, provider, title_mode, new_line_mode,
        remove_endnotes, remove_reference_numbers, search_and_replace_file)
    if not catalog_state or source != catalog_state.get('source') or source != selection_source:
        raise ValueError("章节目录正在更新，请等待当前书籍目录载入，再选择范围后开始")
    if catalog_state.get('mode') == 'batch':
        return int(start), int(end)
    if catalog_state.get('mode') != 'single' or first is None or last is None:
        raise ValueError("请先读取有效的章节目录并选择起止章节")
    start, end = int(first), int(last)
    if not 1 <= start <= end <= len(catalog_state['chapters']):
        raise ValueError("章节范围正在更新，请等待选择完成后重试")
    return start, end


def read_book_chapters(input_file, provider, title_mode, new_line_mode,
                       remove_endnotes, remove_reference_numbers, search_and_replace_file):
    """上传时只在本地读取目录，章号与实际转换过滤空章后的章号一致。"""
    files = input_file if isinstance(input_file, (list, tuple)) else [input_file] if input_file else []
    catalog = []
    context = {}
    source = ""
    loaded_book = ""
    message = "上传书籍后，这里会显示章节目录。"
    try:
        if files:
            source, paths, book_hashes = _chapter_directory_source(
                files, provider, title_mode, new_line_mode, remove_endnotes,
                remove_reference_numbers, search_and_replace_file)
            context = {"source": source, "files": paths, "mode": "batch" if len(files) > 1 else "error", "chapters": []}
    except (OSError, TypeError, ValueError) as exc:
        message = f"目录读取失败：{exc}。请检查文件后重新读取目录。"
    if len(files) > 1:
        message = "已选择多本书。请按数字设置各本书共用的章节范围；保留一本书可按章节名称选择。"
    elif files:
        try:
            config = GeneralConfig(None)
            config.input_file = _uploaded_file_path(files[0])
            config.title_mode = title_mode or "auto"
            config.newline_mode = new_line_mode or "double"
            config.remove_endnotes = bool(remove_endnotes)
            config.remove_reference_numbers = bool(remove_reference_numbers)
            config.search_and_replace_file = _uploaded_file_path(search_and_replace_file)
            # 读取目录不创建 Provider，也不读取 API 凭证。
            break_string = "   " if provider in ("Mimo", "Chatterbox", "VoxCPM") else " @BRK#"
            parser = get_book_parser(config)
            catalog = chapter_catalog([(title, text) for title, text in parser.get_chapters(break_string) if text.strip()])
            if not catalog:
                raise ValueError("书籍中没有可转换的章节")
            if not source:
                raise ValueError("书籍指纹读取失败")
            context.update(mode="single", chapters=catalog)
            loaded_book = book_hashes[0]
        except Exception as exc:
            logger.warning("读取书籍目录失败：%s", exc)
            catalog = []
            message = f"目录读取失败：{exc}。请检查文件或高级解析设置后，点击重新读取目录。"
    choices = chapter_choices(catalog)
    return (
        context,
        gr.update(choices=choices, value=1 if catalog else None, interactive=bool(catalog)),
        gr.update(choices=choices, value=len(catalog) if catalog else None, interactive=bool(catalog)),
        gr.update(value=1), gr.update(value=-1),
        range_payload(catalog, message=message),
        gr.update(visible=len(files) > 1),
        gr.update(visible=len(files) <= 1),
        source,
        loaded_book,
    )


def select_book_chapter(start, end, catalog, endpoint, selection_source=None):
    """范围反向时把另一端收拢到本章，保留用户刚选的端点。"""
    if isinstance(catalog, dict):
        if selection_source != catalog.get('source') or catalog.get('mode') != 'single':
            return tuple(gr.skip() for _ in range(5))
        catalog = catalog.get('chapters', [])
    if not catalog:
        return gr.update(), gr.update(), gr.update(), gr.update(), range_payload([])
    start = int(start or 1)
    end = int(end or len(catalog))
    if not 1 <= start <= len(catalog) or not 1 <= end <= len(catalog):
        raise gr.Error("章节目录已更新，请重新选择起止章节")
    if start > end:
        if endpoint == "start":
            end = start
        else:
            start = end
    return (gr.update(value=start), gr.update(value=end),
            start, end, range_payload(catalog, start, end))


def _role_script_summary(script: RoleScriptV1, heading: str = "自动拆分结果") -> str:
    def display(value, limit=64):
        value = ' '.join(str(value).split())
        value = value[:limit] + ('…' if len(value) > limit else '')
        return html.escape(value).replace('|', '／').replace('`', '').replace('*', '').replace('_', ' ')
    names = [display(role.display_name, 32) for role in script.roles.values()]
    has_narration = any(segment.text_kind is not None for chapter in script.chapters for segment in chapter.segments)
    lines = [f"**{display(heading)}**", "",
             f"{len(script.roles)} 位角色 · {len(script.chapters)} 章 · "
             f"{sum(len(chapter.segments) for chapter in script.chapters)} 段", "",
             '人物：' + '、'.join(names[:12]) + ('等' if len(names) > 12 else ''), "",
             '| 章节 | 段数 |', '| --- | ---: |']
    if has_narration:
        lines[-2:] = ['| 章节 | 段数 | 叙述声音 |', '| --- | ---: | --- |']
    for chapter in script.chapters[:12]:
        row = f'| {chapter.chapter_index} · {display(chapter.title)} | {len(chapter.segments)} |'
        if has_narration:
            narrators = list(dict.fromkeys(
                ('默认旁白（请核对）' if segment.role_id == 'narrator' else
                 display(script.roles[segment.role_id].display_name, 20))
                for segment in chapter.segments if segment.text_kind == 'narration' and segment.role_id in script.roles))
            row += ' ' + ('、'.join(narrators[:3]) + ('等' if len(narrators) > 3 else '') if narrators else '未识别／旧剧本') + ' |'
        lines.append(row)
    if len(script.chapters) > 12:
        lines.extend(['', f'其余 {len(script.chapters) - 12} 章见可下载的完整剧本。'])
    if isinstance(script, RoleScriptV2):
        pending = sum(
            1 for chapter in script.chapters for segment in chapter.segments
            if segment.speaker and segment.speaker.status in {"needs_review", "unknown", "proposed"}
        )
        registry_scope = "全书人物索引已完成" if script.registry_complete else "仅已分析章节的人物索引；全书尚未分析完"
        lines.extend(['', f'{registry_scope}；待核对 {pending} 段。可在下方查看原文归属。'])
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
            kind = {'narration': '叙述（可由故事人物自述）', 'dialogue': '对白', 'unknown': '待判断'}.get(segment.text_kind, '旧剧本未区分')
            name = script.roles[segment.role_id].display_name if segment.role_id in script.roles else segment.role_id
            return (f"第 {chapter.chapter_index} 章 · `{segment_id}`\n\n"
                    f"段落类型：{kind}；朗读声音：{html.escape(name)}\n\n"
                    f"原文：{segment.text}\n\n"
                    f"当前人物：`{speaker.entity_id if speaker else 'unknown'}`；"
                    f"状态：`{speaker.status if speaker else 'unknown'}`；"
                    f"未校准分数：{speaker.confidence if speaker else '无'}\n\n"
                    f"原文证据：{evidence or '无；请根据上下文人工判断'}")
    return "找不到指定段落。"


def _editable_role_project(file_obj, table=None):
    if _role_project_is_splitting(file_obj):
        raise ValueError('剧本正在重新拆分，请完成后再修改归属')
    if running_process and running_process.is_alive():
        raise ValueError('请等待当前生成结束或停止后，再修改归属')
    path = _role_script_path(file_obj)
    project_root = os.path.realpath(os.path.join(get_output_dir(), ".role_projects"))
    if not path or not os.path.realpath(path).startswith(project_root + os.sep):
        raise ValueError('只能在自动生成的 V2 项目中保存人工复核')
    script, report = _load_uploaded_role_script(path)
    if not report.ok or not isinstance(script, RoleScriptV2):
        raise ValueError('V2 项目读取失败')
    return path, _apply_role_table(script, table) if table is not None else script


def load_narration_controls(file_obj, selected_chapter=None):
    script, report = _load_uploaded_role_script(file_obj)
    eligible = [c for c in script.chapters if any(s.text_kind == 'narration' for s in c.segments)] if report.ok and isinstance(script, RoleScriptV2) else []
    if not eligible:
        return (gr.update(choices=[], value=None, interactive=False),
                gr.update(choices=[], value=None, interactive=False), gr.update(interactive=False),
                '当前剧本未记录叙述段。重新拆分后可按章设置；旧剧本仍可使用逐段归属。')
    chapter = next((c for c in eligible if c.chapter_index == selected_chapter), eligible[0])
    narrators = {s.role_id for s in chapter.segments if s.text_kind == 'narration'}
    entities = [(('默认旁白' if key == 'narrator' else role.display_name), key)
                for key, role in script.roles.items() if key in script.entities]
    return (gr.update(choices=[(f'{c.chapter_index} · {c.title}', c.chapter_index) for c in eligible],
                      value=chapter.chapter_index, interactive=True),
            gr.update(choices=entities, value=next(iter(narrators)) if len(narrators) == 1 else None, interactive=True),
            gr.update(interactive=True),
            f'本章有 {sum(s.text_kind == "narration" for s in chapter.segments)} 段叙述；当前使用 {len(narrators)} 种声音。修改后需重新确认剧本。')


def refresh_role_summary(file_obj):
    script, report = _load_uploaded_role_script(file_obj)
    return _role_script_summary(script, '当前剧本') if script and report.ok else gr.skip()


@_role_project_operation
def apply_chapter_narration(file_obj, table, chapter_index, entity_id):
    try:
        path, script = _editable_role_project(file_obj, table)
        updated, count = assign_chapter_narrator(script, chapter_index, entity_id)
        result = validate_role_script(updated)
        if not result.ok:
            raise ValueError(_format_role_validation_report(result.report, '归属校验'))
        save_project(result.script, path)
        _forget_role_confirmation(path)
        _register_role_script_origin(path)
        return (gr.update(value=_role_table_rows(result.script)),
                f'已保存：第 {chapter_index} 章 {count} 段叙述使用「{script.roles[entity_id].display_name}」。请重新确认剧本后生成。',
                False, '', gr.update(value=_role_confirmation_probe(False, '', gate=True)),
                gr.update(value=_role_script_summary(result.script, '当前剧本')))
    except (ValueError, OSError, TypeError) as exc:
        signature = _recall_role_confirmation(file_obj)
        return (gr.skip(), f'未修改：{exc}', bool(signature), signature,
                gr.update(value=_role_confirmation_probe(bool(signature), signature, gate=not bool(signature))), gr.skip())


@_role_project_operation
def apply_role_review(file_obj, operation, segment_id, entity_id, source_id, target_id, table=None):
    try:
        path, script = _editable_role_project(file_obj, table)
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
        save_project(result.script, path)
        _forget_role_confirmation(path)
        _register_role_script_origin(path)
        queue = pending_segments(result.script)
        choices = [(f"第 {chapter} 章 · {excerpt}", sid) for sid, chapter, excerpt in queue]
        return (
            gr.update(choices=choices, value=choices[0][1] if choices else None),
            gr.update(value=_role_table_rows(result.script)),
            f"✅ 已保存复核；剩余 {len(queue)} 段待复核。请重新确认剧本后生成。",
            False, "", gr.update(value=_role_confirmation_probe(False, "", gate=True)),
        )
    except (ValueError, OSError, TypeError) as exc:
        signature = _recall_role_confirmation(file_obj)
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
    chapter_catalog_state=None, chapter_selection_source=None,
    chapter_from_name=None, chapter_to_name=None,
    progress=gr.Progress(),
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
        if progress:
            progress(0, desc="正在读取书籍与所选章节…")
        if isinstance(input_file, (list, tuple)) and len(input_file) > 1:
            raise ValueError("角色拆分每次只支持一本书")
        chapter_start, chapter_end = resolve_book_chapter_range(
            input_file, provider, title_mode, new_line_mode, remove_endnotes,
            remove_reference_numbers, search_and_replace_file, chapter_start, chapter_end,
            chapter_catalog_state, chapter_selection_source, chapter_from_name, chapter_to_name)
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
            index_full_book=bool(fullbook_index_ack),
            progress=lambda message: _split_progress(message, progress),
        )
        result = _ensure_role_voice_diversity(result, report)
        script_path = save_project(result, script_path)
        _register_role_script_origin(script_path)
        # 同一路径重新生成后，旧的“已确认”记录必须作废。
        _forget_role_confirmation(script_path)
        rows = _role_table_rows(result)
        validation_text = _format_role_validation_report(report, "DeepSeek 剧本校验")
        summary = _role_script_summary(result)
        if progress:
            progress(1, desc="剧本已保存，请选择人物试听")
        return (
            gr.update(value=str(script_path)),
            gr.update(value=rows),
            gr.update(value=validation_text),
            _role_choice_update(result),
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


def _split_progress(message, progress):
    logger.info("%s", message)
    if progress:
        progress(None, desc=message)


# 显式按钮沿用自动拆分的输入与 Progress 注入；不把进度对象当作界面字段。
split_role_script_now.__signature__ = inspect.signature(auto_split_role_script)


def _stream_role_script(values):
    """界面专用流式反馈；同步入口仍供脚本和离线验证使用。"""
    enabled = _role_provider_id(values[3]) is not None
    if not values[1] or not values[2]:
        yield (*auto_split_role_script(*values), render_split_status(), gr.update(interactive=enabled))
        return
    started = time.time() * 1000
    for event in _guarded_split_events(values):
        state = event['state']
        if state == 'heartbeat':
            yield tuple(gr.skip() for _ in range(12))
        elif state in ('starting', 'running'):
            updates = [gr.skip() for _ in range(10)]
            if state == 'starting':
                updates[6:10] = [False, False, '', gr.update(value=_role_confirmation_probe(False))]
            yield (*updates, render_split_status(state, event['message'], started),
                   gr.update(interactive=False))
        elif state == 'result':
            result = event['result']
            generated = result[7]
            detail = split_result_status(generated, result[2].get('value', ''))
            yield (*result, render_split_status('done' if generated else 'failed', detail),
                   gr.update(interactive=enabled))
        else:
            # 保护工作线程中的意外异常；常规失败由同步入口返回校验结果。
            message = '拆分失败：' + event['message'] + '。请检查连接和章节后重试。'
            updates = [gr.skip() for _ in range(10)]
            updates[2] = gr.update(value=message)
            updates[6:10] = [False, False, '', gr.update(value=_role_confirmation_probe(False))]
            yield (*updates, render_split_status('failed', message), gr.update(interactive=enabled))


def auto_split_role_script_ui(*args):
    yield from _stream_role_script(list(args))


def split_role_script_now_ui(*args):
    values = list(args)
    values[2] = True
    yield from _stream_role_script(values)


_split_ui_signature = inspect.signature(auto_split_role_script).replace(
    parameters=[p for name, p in inspect.signature(auto_split_role_script).parameters.items() if name != 'progress'])
auto_split_role_script_ui.__signature__ = _split_ui_signature
split_role_script_now_ui.__signature__ = _split_ui_signature


@_role_project_operation
def confirm_auto_role_script(
    role_script_file,
    role_table,
    provider,
    openai_output_format,
    minimax_output_format,
):
    """人工确认自动拆分结果；校验失败时保持未确认状态。"""
    if _role_project_is_splitting(role_script_file):
        return (False, '剧本正在重新拆分，请等待完成后再确认。', gr.update(), '',
                gr.update(value=_role_confirmation_probe(False)))
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
    summary += "\n\n✅ 已确认。下一步：在页面下方点击「开始生成」。"
    if isinstance(normalized, RoleScriptV2):
        project_root = Path(get_output_dir()).resolve() / ".role_projects"
        path = Path(_role_script_path(role_script_file)).resolve()
        if path.is_relative_to(project_root):
            try:
                save_project(normalized, path)
                _register_role_script_origin(path)
            except OSError as exc:
                return (False, f"角色设置保存失败：{exc}", gr.update(), "",
                        gr.update(value=_role_confirmation_probe(False, "", gate=True)))
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


def confirm_auto_role_script_ui(role_script_file, role_table, provider, openai_output_format, minimax_output_format):
    """先显示核对状态；成功标记仍只读取后台确认结果。"""
    yield (*[gr.skip() for _ in range(5)], gr.update(interactive=False))
    try:
        result = confirm_auto_role_script(role_script_file, role_table, provider,
                                          openai_output_format, minimax_output_format)
    except Exception as exc:
        logger.warning('角色确认失败：%s', exc, exc_info=True)
        result = (False, gr.update(value=f'确认失败：{exc}。请检查后重试。'), gr.skip(), '',
                  gr.update(value=_role_confirmation_probe(False)))
    yield (*result, gr.update(interactive=True))


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
    uploaded_path = _role_script_path(role_script_file)
    if not uploaded_path:
        return (
            gr.update(value=[]), "先生成剧本，或上传已有剧本。",
            gr.update(choices=[], value=None), gr.update(value=""),
            gr.update(visible=False), False, False, "",
            gr.update(value=_role_confirmation_probe(False)),
        )
    generated_roots = [
        os.path.realpath(os.path.join(get_output_dir(), name))
        for name in (".role_generated", ".role_projects")
    ]
    if uploaded_path and any(
        os.path.realpath(uploaded_path).startswith(root + os.sep) for root in generated_roots
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
    validation = _format_role_validation_report(report, "角色剧本校验")
    summary = _role_script_summary(normalized or script, "手动上传的剧本")
    summary += "\n\n已确认当前剧本。修改声音或归属后，请重新确认。"
    confirmed = normalized is not None
    signature = _role_confirmation_signature(normalized) if confirmed else ""
    if confirmed:
        _remember_role_confirmation(role_script_file, signature)
    return (
        gr.update(value=rows),
        gr.update(value=validation),
        _role_choice_update(normalized or script),
        gr.update(value=summary),
        gr.update(visible=True),
        confirmed,
        False,
        signature,
        gr.update(value=_role_confirmation_probe(confirmed, signature)),
    )


# ── 转换核心 ──────────────────────────────────────────────────────
@_role_project_operation
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
                 role_quality_deepseek_model=None,
                 audio_core_enabled=False, audio_core_repair=False,
                 audio_core_settings_file=None, audio_core_casting_file=None,
                 chapter_catalog_state=None, chapter_selection_source=None,
                 chapter_from_name=None, chapter_to_name=None):
    if not input_file:
        gr.Warning("请先选择至少一个书籍文件")
        # 保持进度条现状，只关掉轮询
        return gr.update(), gr.Timer(active=False)
    if not isinstance(input_file, list):
        input_file = [input_file]

    try:
        if chapter_catalog_state is not None:
            chapter_start, chapter_end = resolve_book_chapter_range(
                input_file, provider, title_mode, new_line_mode, remove_endnotes,
                remove_reference_numbers, search_and_replace_file, chapter_start, chapter_end,
                chapter_catalog_state, chapter_selection_source, chapter_from_name, chapter_to_name)
    except (OSError, TypeError, ValueError) as exc:
        gr.Warning(str(exc))
        return gr.update(), gr.Timer(active=False)

    if audio_core_enabled and _role_provider_id(provider) != "openai":
        gr.Warning("统一质量核心首轮仅支持 MiMo，请切换引擎后使用")
        return gr.update(), gr.Timer(active=False)

    role_script = None
    if role_mode:
        if _role_provider_id(provider) is None:
            gr.Warning(f"{provider} 不支持多角色模式，请切回 MiMo / MiniMax，或在「多角色配音」模块关闭多角色模式")
            return gr.update(), gr.Timer(active=False)
        if len(input_file) != 1:
            gr.Warning("角色模式首版只支持单本书，请只选择一个书籍文件")
            return gr.update(), gr.Timer(active=False)
        if _role_project_is_splitting(role_script_file):
            gr.Warning("剧本正在重新拆分，请等待完成并确认后再开始生成")
            return gr.update(), gr.Timer(active=False)
        if _role_project_needs_reconfirmation(role_script_file):
            gr.Warning("剧本已重新拆分或上次拆分失败，请核对当前剧本并重新确认后再开始生成")
            return gr.update(), gr.Timer(active=False)
        # 人工确认以“内容指纹”为准：确认按钮会写入 role_confirmed_signature，
        # 服务端再记一份（role_split_confirmed 布尔在 Gradio 事件竞态里可能被旧快照覆盖，
        # 只信布尔会出现“已确认却仍提示等待 DeepSeek”的假阴性）。
        confirmed_signature = str(role_confirmed_signature or "") or _recall_role_confirmation(
            role_script_file
        )
        if not role_split_confirmed and not confirmed_signature:
            if auto_role_split and role_split_generated:
                gr.Warning("自动拆分结果尚未人工确认，请先在「多角色配音」模块核对并点击「确认剧本与角色参数」")
            elif auto_role_split:
                gr.Warning("请先等待 DeepSeek 自动拆分完成，并在「多角色配音」模块人工确认")
            else:
                gr.Warning("请先在「多角色配音」生成或导入剧本，试听后点击「确认剧本与角色参数」")
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
            gr.Warning("剧本内容已修改，请回到「多角色配音」模块重新点击「确认剧本与角色参数」")
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
        config.audio_core_enabled = bool(audio_core_enabled)
        config.audio_core_repair = bool(audio_core_repair)
        if config.audio_core_enabled:
            from audiobook_generator.ui.audio_quality import apply_quality_settings, apply_local_quality_defaults
            try:
                apply_local_quality_defaults(config)
                apply_quality_settings(config, _uploaded_file_path(audio_core_settings_file))
                config.audio_core_casting = _uploaded_file_path(audio_core_casting_file)
                config.worker_count = 1
            except (ValueError, OSError, TypeError) as exc:
                gr.Warning(f"质量配置无效：{exc}")
                return gr.update(), gr.Timer(active=False)
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
        config.role_quality_enabled = bool(role_quality_enabled) and not config.audio_core_enabled if role_mode else False
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
            # 隐藏的克隆参数保留在界面里，但只在对应模式提交，避免切回预设时仍用旧录音。
            config.voxcpm_reference_audio = (
                voxcpm_reference_audio.name if hasattr(voxcpm_reference_audio, 'name')
                else voxcpm_reference_audio
            ) if voxcpm_mode in ("clone", "hifi") else None
            config.voxcpm_reference_text = voxcpm_reference_text if voxcpm_mode == "hifi" else None
            config.voxcpm_auto_transcribe = bool(voxcpm_auto_transcribe) if voxcpm_mode == "hifi" else False
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
    msg = f"批次 <b style='color:var(--apple-red);'>{html.escape(folder_name)}</b> 已被整体删除"
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


def generate_download(folder_name, selected_files, auto_delete=False):
    try:
        path, count = create_archive(get_output_dir(), folder_name, selected_files)
    except (ValueError, OSError) as exc:
        gr.Warning(str(exc))
        return gr.update(), gr.update(), gr.update(value=_placeholder_html(html.escape(str(exc)))), gr.update(value=None, visible=False)
    return (gr.update(), gr.update(), gr.update(value=f'<div class="lib-ready"><h3>ZIP 已准备好</h3><p>{count} 个文件 · 源文件保留<br>点击下方按钮保存到本地。</p></div>'), gr.update(value=path, visible=True))


def refresh_batches():
    return gr.update(choices=get_folders_list(), value=None), gr.update(choices=[], value=[])


def refresh_library_on_open(folder_name, selected_files):
    """进入资源库时重新扫描磁盘，保留仍存在的批次与文件勾选。"""
    folders = get_folders_list()
    selected_folder = folder_name if folder_name in folders else (folders[0] if folders else None)
    files = get_files_in_folder(selected_folder) if selected_folder else []
    if selected_folder == folder_name:
        selected = [name for name in (selected_files or []) if name in files]
    else:
        selected = files
    return gr.update(choices=folders, value=selected_folder), gr.update(choices=files, value=selected)


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
HEAD_HTML = AMBIENT_LAYER_HTML + THEME_HEAD_HTML + LOG_LAYOUT_HEAD_HTML + WORKFLOW_HEAD_HTML + CHAPTER_HEAD_HTML + ROLE_SPLIT_HEAD + """
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
    box.dataset.mode = mode;
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

    // 结果留在独立模块内；不抢焦点，也不把用户带进高级设置。
    panel.setAttribute('aria-live', 'polite');
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
    // 高级设置的关闭不再受独立配音模块的确认状态影响。
    doneBtn.disabled = false;
    doneBtn.removeAttribute('aria-disabled');
    if (doneBtn.classList.contains('is-gated')) doneBtn.classList.remove('is-gated');
    doneBtn.removeAttribute('title');
    var hint = document.getElementById('role_workflow_hint');
    var probe = document.getElementById('role_confirmation_probe');
    var message = roleGateActive()
      ? '下一步：调整音色并试听，再点击「确认剧本与角色参数」。'
      : (probe && probe.getAttribute('data-confirmed') === '1'
        ? '已确认。下一步：在下方确认生成。'
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
      var btn = event.target && event.target.closest && event.target.closest(
        '.btn-primary, .btn-ghost, .btn-mini, .btn-danger, .tab-nav button, .engine-tab');
      // 剧本生成使用 CSS 按压反馈，避免叠加水波纹与异步表单更新。
      if (!btn || btn.disabled || btn.id === 'role_split_btn') return;
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
      if (!btn || btn.id !== 'generation_start' || btn.disabled) return;
      // 只滚动，不强行展开：真正展开由新的状态载荷触发（例如"正在启动"），
      // 这样若表单校验失败（没选文件）也不会把已经收起的进度条留在页面上。
      window.setTimeout(function () {
        window.scrollTo({ top: 0, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
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
    window.scrollTo({ top: 0, behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
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
  transition: color 160ms ease, background-color 160ms ease, box-shadow 160ms ease !important;
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
/* 日志框限制在当前视口内；文件信息行占自然高度，终端填满剩余空间。
   历史日志由 xterm 的 viewport 内部滚动，不能靠加高组件展示回滚缓冲。 */
#run_log {
  display: flex !important;
  flex-direction: column !important;
  height: clamp(240px, calc(100dvh - 300px), 640px) !important;
  min-height: 0 !important;
  padding-bottom: 0 !important;
  box-sizing: border-box !important;
  overflow: hidden !important;
}
.run-log-card {
  margin-bottom: 0 !important;
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
  flex: 1 1 0 !important;
  height: auto !important;
  min-height: 0 !important;
  margin-bottom: 0 !important;
  padding-bottom: 0 !important;
  box-sizing: border-box !important;
  overflow: visible !important;
}
#run_log .xterm,
#run_log .xterm-viewport { height: 100% !important; }
#run_log .xterm-viewport {
  padding-bottom: 0 !important;
  overflow-y: auto !important;
  overscroll-behavior-y: contain;
  scrollbar-gutter: stable;
  scrollbar-color: var(--ata-scroll-thumb) transparent;
}
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
  padding: 7px 15px !important; transition: color 160ms ease, background-color 160ms ease, border-color 160ms ease !important; cursor: pointer !important;
}
.btn-mini:hover { background: var(--ata-hover-strong) !important; color: var(--apple-text) !important; }

/* ── 开关组（苹果风 toggle） ── */
.toggle-grid { display: grid; grid-template-columns: 1fr; gap: 10px; }
@media (min-width: 560px) { .toggle-grid { grid-template-columns: 1fr 1fr; } }
.toggle {
  background: var(--apple-surface) !important; border: 1px solid var(--apple-border-soft) !important;
  border-radius: 14px !important; padding: 12px 16px !important; transition: background-color 160ms ease, border-color 160ms ease !important;
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
  transition: background-color 160ms ease, border-color 160ms ease !important; cursor: pointer !important;
}
.file-checks label:hover { border-color: var(--apple-blue) !important; background: var(--apple-blue-soft) !important; }
.file-checks label:has(input:checked) {
  background: linear-gradient(135deg, #0071e3 0%, #5e5ce6 100%) !important; color: #fff !important;
  border-color: transparent !important; box-shadow: 0 4px 12px rgba(0,113,227,0.32) !important; }

/* ── 资源库空态 / 就绪 ── */
/* VoxCPM：常用选项优先，二级设置保持原生可展开交互。 */
#voxcpm_mode label {
  min-height: 44px;
  padding: 10px 14px !important;
  border-radius: var(--radius-sm) !important;
  background-color: var(--ata-glass-soft) !important;
  border-color: var(--apple-border-soft) !important;
  color: var(--apple-text) !important;
}
#voxcpm_mode label:has(input:checked) {
  background-color: var(--apple-blue-soft) !important;
  border-color: var(--apple-blue) !important;
}
#voxcpm_mode label:focus-within {
  outline: 2px solid var(--apple-blue);
  outline-offset: 2px;
}
.voxcpm-audition { align-items: center !important; }
.voxcpm-audition button { white-space: nowrap !important; }
.voxcpm-settings-tabs :is(.tab-nav, .tab-container) > button {
  min-height: 44px;
  padding: 10px 12px !important;
}
@media (max-width: 520px) {
  /* 同步调整 Gradio 隐藏的测量按钮，避免三类设置被挤进省略菜单。 */
  .voxcpm-settings-tabs :is(.tab-nav, .tab-container) > button {
    font-size: 0.8125rem !important;
    padding: 10px 3px !important;
  }
}
#voxcpm_advanced, #voxcpm_style_section { overflow: visible !important; }

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
/* 批次面板是 fixed，但仍被祖先层叠上下文约束。必须提升整条祖先链，
   只提升卡片的一层子元素无法越过下一张卡片或 Tabs 的边框。
   仅在该菜单展开时生效，关闭后恢复原层级；不创建 fixed 包含块。 */
.gradio-container .tabs:has(#library_folder_picker ul.options:not([inert])),
#library_tab:has(#library_folder_picker ul.options:not([inert])),
#library_tab *:has(#library_folder_picker ul.options:not([inert])) {
  position: relative;
  z-index: 120 !important;
  overflow: visible !important;
}
#library_folder_picker ul.options {
  z-index: 121 !important;
  min-width: 0 !important;
  max-width: calc(100vw - 32px) !important;
  background-color: var(--apple-surface) !important;
  color: var(--apple-text) !important;
  overflow-y: auto !important;
  overflow-x: hidden !important;
  overscroll-behavior: contain;
}
/* 保留 Gradio 按视口计算的 top / bottom / max-height，长名称在菜单内换行。 */
#library_folder_picker ul.options .item,
#library_folder_picker ul.options .inner-item {
  min-width: 0;
  white-space: normal !important;
  overflow-wrap: anywhere;
  word-break: normal;
  text-overflow: clip;
  line-height: 1.5;
}
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
/* Gradio 会把开关包在 overflow-x:auto / overflow-y:hidden 的 .form 中，
   按压反馈与外阴影会被裁切；只释放这个包装层，不影响表格和弹窗滚动。 */
#advanced_modal .form:has(> #role_mode_toggle) {
  overflow: visible !important;
  background: transparent !important;
}
#advanced_modal #role_split_btn {
  margin: 4px 0 8px;
  transform: scale(1);
  transition: transform 160ms cubic-bezier(0.23, 1, 0.32, 1) !important;
}
#advanced_modal #role_split_btn:hover { transform: scale(1); }
#advanced_modal #role_split_btn:active:not(:disabled) { transform: scale(0.985); }
#advanced_modal #role_split_btn:disabled {
  opacity: 0.5 !important; cursor: not-allowed !important;
  transform: none !important; box-shadow: none !important;
}
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

/* 多角色模式：按压与释放由 CSS transition 衔接，快速重复点击不重启动画。 */
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
  transform: scale(1);
  transition: transform 160ms cubic-bezier(0.23, 1, 0.32, 1) !important;
}
#advanced_modal .toggle.advanced-switch::before {
  content: ''; position: absolute; left: 0; top: 14px; bottom: 14px; width: 3px;
  border-radius: 0 8px 8px 0; background-color: var(--apple-blue);
  opacity: 0.48; transition: opacity 160ms cubic-bezier(0.23, 1, 0.32, 1);
}
#advanced_modal .toggle.advanced-switch::after {
  content: ''; position: absolute; right: -34px; top: -50px; width: 132px; height: 132px;
  border-radius: 50%; pointer-events: none; opacity: 0.5;
  background: radial-gradient(circle, rgba(94, 92, 230, 0.2), transparent 68%);
  transition: opacity 160ms cubic-bezier(0.23, 1, 0.32, 1);
}
@media (hover: hover) and (pointer: fine) {
#advanced_modal .toggle.advanced-switch:hover {
  border-color: rgba(0, 113, 227, 0.48) !important;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.38), 0 10px 26px rgba(0, 113, 227, 0.13) !important;
}
}
#advanced_modal .toggle.advanced-switch:active { transform: scale(0.985) !important; }
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
  transition: transform 160ms cubic-bezier(0.23, 1, 0.32, 1) !important;
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
@media (prefers-reduced-motion: reduce) {
  #advanced_modal .toggle.advanced-switch:active,
  #advanced_modal #role_split_btn:active:not(:disabled) { transform: none !important; }
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
""" + AMBIENT_CSS + THEME_CSS + WORKFLOW_CSS + CHAPTER_CSS + ROLE_STUDIO_CSS

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

        with gr.Tabs(selected="tab_convert", elem_id="studio_tabs") as main_tabs:
            # ════════════ 转换页 ════════════
            with gr.Tab("生成有声书", id="tab_convert"):
                gr.HTML('''
                <div class="hero">
                    <h1>让文字化作声音</h1>
                    <p>从一本书开始，选好声音，再生成和下载。</p>
                </div>''')
                gr.HTML(workflow_steps_html())
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
                # —— Step 1 文件 + 章节范围 ——
                with gr.Group(elem_classes="app-card", elem_id="book_setup"):
                    gr.HTML('<p class="card-title"><span class="card-num">1</span>上传书籍文件</p>')
                    gr.HTML('<p class="card-desc">支持 EPUB / DOC / DOCX，可多选。输出目录将根据书名自动生成。</p>')
                    input_file = gr.File(label="书籍文件", file_types=[".epub", ".doc", ".docx"],
                                         file_count="multiple", interactive=True, elem_classes="book-file-upload")
                    output_dir = gr.Textbox(label="输出目录", value=default_output_dir, interactive=True,
                                            info="多文件时每本书自动生成以书名为名的子文件夹")
                    input_file.change(fn=update_output_dir_from_file, inputs=input_file, outputs=output_dir, show_progress="hidden")
                    gr.HTML('<div class="section-divider"></div>')
                    gr.HTML('<p class="card-sub-title">章节范围</p>')
                    book_chapter_catalog = gr.State({})
                    book_directory_loaded = gr.State("")
                    chapter_selection_source = gr.Textbox(value="", visible=False)
                    with gr.Column(elem_id="chapter_catalog_panel"):
                        with gr.Row(elem_id="chapter_named_range") as chapter_named_range:
                            chapter_from_name = gr.Dropdown([], label="起始章节", value=None, interactive=False,
                                                            filterable=True, elem_id="chapter_from_name")
                            chapter_to_name = gr.Dropdown([], label="结束章节", value=None, interactive=False,
                                                          filterable=True, elem_id="chapter_to_name")
                        gr.HTML(CHAPTER_OVERVIEW_HTML, elem_id="chapter_overview")
                        chapter_range_state = gr.HTML(range_payload([]), elem_id="chapter_range_state")
                        chapter_reload = gr.Button("重新读取目录", elem_classes="btn-mini", size="sm")
                        with gr.Row(visible=False) as chapter_numeric_range:
                            chapter_start = gr.Number(minimum=1, precision=0, label="从第几章开始", value=1, interactive=True)
                            chapter_end = gr.Number(minimum=-1, precision=0, label="到第几章结束", value=-1,
                                                    info="-1 代表处理至最后一章", interactive=True)
                    gr.HTML('<div class="section-divider"></div>')
                    gr.HTML('<button type="button" class="btn-ghost modal-trigger" onclick="openAdvancedModal(event)" style="width:100%;padding:12px;border-radius:14px;font-size:1rem;cursor:pointer;">⚙\u00a0\u00a0高级设置</button>')

                # —— Step 2 引擎 ——
                with gr.Group(elem_classes="app-card", elem_id="voice_setup"):
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
                                edge_language = gr.Dropdown(get_edge_tts_supported_language(), value="zh-CN", label="语言", interactive=True)
                                edge_voice = get_edge_voices_by_language("zh-CN")
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
                            voxcpm_panel = build_voxcpm_panel()
                            voxcpm_model = voxcpm_panel.model
                            voxcpm_mode = voxcpm_panel.mode
                            voxcpm_voice = voxcpm_panel.voice
                            voxcpm_voice_dir = voxcpm_panel.voice_dir
                            voxcpm_regenerate_voice = voxcpm_panel.regenerate_voice
                            voxcpm_voice_description = voxcpm_panel.voice_description
                            voxcpm_reference_audio = voxcpm_panel.reference_audio
                            voxcpm_reference_text = voxcpm_panel.reference_text
                            voxcpm_auto_transcribe = voxcpm_panel.auto_transcribe
                            voxcpm_device = voxcpm_panel.device
                            voxcpm_denoise = voxcpm_panel.denoise
                            voxcpm_normalize = voxcpm_panel.normalize
                            voxcpm_cfg_value = voxcpm_panel.cfg_value
                            voxcpm_inference_timesteps = voxcpm_panel.inference_timesteps
                            voxcpm_speed = voxcpm_panel.speed
                            voxcpm_chunk_chars = voxcpm_panel.chunk_chars
                            voxcpm_optimize = voxcpm_panel.optimize
                            voxcpm_output_format = voxcpm_panel.output_format
                            voxcpm_preview_btn = voxcpm_panel.preview_btn
                            voxcpm_preview_audio = voxcpm_panel.preview_audio

                with gr.Group(elem_classes="app-card role-studio", elem_id="role_studio"):
                    gr.HTML('''<div class="advanced-section-head">
  <span class="card-num">3</span><div class="advanced-section-copy">
    <h3>多角色配音 <span class="optional-label">可选</span></h3>
    <p>生成剧本，为人物选择声音，试听满意后确认生成。每次处理一本书。</p>
  </div></div>''')
                    role_mode = gr.Checkbox(label="为旁白和人物使用不同声音", value=False,
                        elem_classes="toggle advanced-switch", elem_id="role_mode_toggle")
                    role_provider_hint = gr.Markdown("当前引擎支持多角色模式；剧本必须与所选引擎一致。", elem_id="role_provider_hint")
                    with gr.Group(visible=False, elem_id="role_config_panel") as role_config_panel:
                        gr.HTML('<p id="role_workflow_hint" class="role-workflow-hint" role="status" aria-live="polite">下一步：先生成剧本，或上传已有剧本。</p>')
                        with gr.Tabs(elem_classes="role-setup-tabs", elem_id="role_setup_tabs"):
                            with gr.Tab("生成剧本"):
                                gr.HTML('<div class="role-section-title"><h4>准备所选章节的剧本</h4><p>使用上方已选书籍与章节。DeepSeek 逐章识别叙述者，再拆分人物与对白；人物自述与本人对白共用声音。每个所选章节额外进行一次叙述视角分析。</p></div>')
                                role_regenerate_btn = gr.Button("生成 / 重新拆分剧本", elem_classes="btn-primary", elem_id="role_split_btn")
                            with gr.Tab("DeepSeek 连接"):
                                gr.Markdown("首次使用时配置，已保存的连接会自动读取。")
                                deepseek_api_key = gr.Textbox(label="DeepSeek API Key", placeholder="请输入 API Key", type="password", elem_classes="role-field")
                                deepseek_show_key = gr.Checkbox(label="显示 API Key", value=False, elem_classes="toggle advanced-compact-toggle")
                                deepseek_api_key_display = gr.HTML("")
                                with gr.Row():
                                    deepseek_base_url = gr.Textbox(label="服务地址", value=DEEPSEEK_DEFAULT_BASE_URL, placeholder="https://api.deepseek.com", elem_classes="role-field")
                                    deepseek_model = gr.Textbox(label="DeepSeek 模型", value=DEEPSEEK_DEFAULT_MODEL, placeholder="deepseek-chat", elem_classes="role-field")
                                with gr.Row(elem_classes="role-action-row"):
                                    deepseek_test_btn = gr.Button("测试连接", elem_classes="btn-ghost")
                                    deepseek_save_btn = gr.Button("保存连接", elem_classes="btn-primary")
                                deepseek_msg = gr.HTML("")
                            with gr.Tab("导入与选项"):
                                role_script_file = gr.File(label="导入已有剧本 / 下载当前剧本（JSON）", file_types=[".json"], file_count="single", type="filepath", interactive=True, elem_classes="role-field")
                                auto_role_split = gr.Checkbox(label="上传书籍后自动调用 DeepSeek 拆分角色", value=False, elem_classes="toggle", elem_id="auto_role_split_toggle")
                                fullbook_index_ack = gr.Checkbox(label="同时分析全书人物（也向 DeepSeek 发送未选章节，增加调用量）", value=False, elem_classes="toggle")
                                gr.Markdown("默认只分析所选章节，逐章扩展时复用已保存的人物声音。", elem_classes="role-caption")
                        role_split_status = gr.HTML(render_split_status(), elem_id="role_split_status")
                        with gr.Group(visible=False, elem_id="role_editor") as role_editor:
                            role_split_confirmed = gr.State(False)
                            role_split_generated = gr.State(False)
                            role_confirmed_signature = gr.State("")
                            # 保留 DOM 状态载体，供流程提示读取；CSS 负责视觉隐藏。
                            role_confirmation_probe_host = gr.HTML("", elem_id="role_confirmation_probe_host")
                            with gr.Tabs(elem_classes="role-workspace-tabs", elem_id="role_workspace_tabs"):
                                with gr.Tab("角色声音"):
                                    gr.HTML('<div class="role-section-title"><h4>为每个人物选好声音</h4><p>选人物 → 调整并应用 → 试听。主要人物可将满意的试听固定为参考音。</p></div>')
                                    with gr.Row(elem_classes="role-voice-columns"):
                                        with gr.Column(scale=6, min_width=260):
                                            role_preview_role = gr.Dropdown(choices=[], label="当前人物", interactive=True, allow_custom_value=False, elem_classes="role-field", elem_id="role_current_character")
                                            with gr.Group(elem_id="role_voice_controls") as role_voice_controls:
                                                with gr.Row():
                                                    role_voice_mode = gr.Dropdown(label="声音来源", choices=[("预设声音", "preset"), ("描述声音", "design"), ("参考音克隆", "clone")], value="preset", elem_classes="role-field")
                                                    role_voice_language = gr.Dropdown(label="朗读语言", choices=[("英语", "en"), ("中文", "zh")], value="en", elem_classes="role-field")
                                                role_voice_builtin = gr.Dropdown(label="预设声音", choices=role_voice_choices(), value="mimo_default", info="青年男声 Bryce 使用已核验的固定参考音；其他选项为 MiMo 内置声音。", elem_classes="role-field", elem_id="role_voice_preset")
                                                role_voice_description = gr.Textbox(label="声音描述", visible=False, lines=3, placeholder="例如：年轻男性，清晰的美式英语，声音轻快，语速适中。", elem_classes="role-field")
                                                role_voice_reference = gr.File(label="参考音（PCM16 WAV）", visible=False, file_types=[".wav"], type="filepath", elem_classes="role-field")
                                                role_voice_pace = gr.Slider(label="当前人物语速", minimum=0.25, maximum=4, value=1, step=0.05, info="1.0 为当前声音的原始倍率；越小越慢。", elem_classes="role-field")
                                                role_voice_instructions = gr.Textbox(label="朗读要求（可选）", placeholder="例如：平静、自然地朗读。", lines=2, elem_classes="role-field")
                                                role_voice_apply = gr.Button("应用当前人物的声音设置", elem_classes="btn-primary", elem_id="role_voice_apply")
                                                role_voice_status = gr.Markdown("请先选择角色。", elem_classes="role-caption")
                                        with gr.Column(scale=5, min_width=260, elem_classes="role-listen-pane"):
                                            role_preview_text = gr.Textbox(label="试听文本", value="Do you remember where we agreed to meet? Please wait beside the bridge until I arrive.", lines=4, interactive=True, elem_classes="role-field")
                                            role_preview_btn = gr.Button("试听当前人物", elem_classes="btn-primary", elem_id="role_preview_btn")
                                            role_preview_audio = gr.Audio(label="试听结果", type="filepath", interactive=False, elem_classes="role-field", elem_id="role_preview_audio")
                                            role_voice_freeze = gr.Button("固定这次试听的音色", elem_classes="btn-ghost", elem_id="role_voice_freeze")
                                            gr.Markdown("固定只保存到本地。下次试听或生成时，该参考音会发送给 MiMo；描述声音的多次生成可能变化。", elem_classes="role-caption")
                                with gr.Tab("剧本与归属"):
                                    with gr.Group(visible=False, elem_id="role_verification_panel") as role_verification_panel:
                                        gr.HTML('<div class="role-section-title"><h4>剧本概览</h4><p>核对人物、章节及叙述声音；视角切换时复用对应人物声音，身份不明保留默认旁白待核对。</p></div>')
                                        role_verification_summary = gr.Markdown("", elem_classes="role-summary")
                                    gr.HTML('<div class="role-section-title"><h4>本章叙述声音</h4><p>单一叙述者的章节可一次指定人物，并复用其声音设置。将覆盖本章所有已识别的叙述段；对白保持原归属，章内多视角请逐段修改。</p></div>')
                                    with gr.Row():
                                        role_narration_chapter = gr.Dropdown(label="叙述章节", choices=[], interactive=False, elem_classes="role-field", elem_id="role_narration_chapter")
                                        role_narration_entity = gr.Dropdown(label="由哪位人物叙述", choices=[], interactive=False, elem_classes="role-field", elem_id="role_narration_entity")
                                    role_narration_apply = gr.Button("应用本章叙述声音", interactive=False, elem_classes="btn-ghost", elem_id="role_narration_apply")
                                    role_narration_status = gr.Markdown("生成剧本后可选择。", elem_classes="role-caption")
                                    gr.HTML('<div class="role-section-title"><h4>核对说话人</h4><p>V2 剧本支持查看原文证据、修正归属，或合并同一人物的别名。</p></div>')
                                    role_review_load_btn = gr.Button("读取需要复核的段落", elem_classes="btn-ghost")
                                    role_review_segment = gr.Dropdown(label="待复核段落", choices=[], interactive=True, elem_classes="role-field")
                                    role_review_info = gr.Markdown("点击上方按钮读取。", elem_classes="role-summary")
                                    role_review_entity = gr.Dropdown(label="这段由谁说话", choices=[], interactive=True, elem_classes="role-field")
                                    with gr.Row(elem_classes="role-action-row"):
                                        role_review_confirm_btn = gr.Button("确认此段说话人", elem_classes="btn-primary")
                                        role_review_lock_btn = gr.Button("锁定该人物音色", elem_classes="btn-ghost")
                                    with gr.Accordion("合并同一人物的不同称呼", open=False):
                                        with gr.Row():
                                            role_merge_source = gr.Dropdown(label="别名人物（并入后移除）", choices=[], interactive=True, elem_classes="role-field")
                                            role_merge_target = gr.Dropdown(label="目标人物（保留声音）", choices=[], interactive=True, elem_classes="role-field")
                                        role_merge_btn = gr.Button("确认同一人物并合并", elem_classes="btn-ghost")
                                with gr.Tab("高级工具"):
                                    gr.HTML('<div class="role-section-title"><h4>统一各人物的语速</h4><p>仅在音色间快慢明显时使用。先调好旁白语速，再用同一试听文本比较。</p></div>')
                                    gr.Markdown("将为每个角色调用一次 MiMo，使用「角色声音」中的试听文本（20～400 字）估算倍率；没有旁白时以首个角色为基准。校准后仍需试听。", elem_classes="role-caption")
                                    role_calibrate_btn = gr.Button("以旁白为基准校准所有人物", elem_classes="btn-ghost", elem_id="role_calibrate_btn")
                                    role_calibration_status = gr.Markdown("尚未校准。", elem_classes="role-summary")
                                    gr.HTML('<div class="role-section-title"><h4>完整人物参数</h4><p>日常音色和语速在「角色声音」调整；这里用于批量编辑。</p></div>')
                                    role_table = gr.Dataframe(headers=ROLE_TABLE_HEADERS,
                                        datatype=["str", "str", "str", "str", "number", "str", "number", "number", "str"], value=[],
                                        label="完整人物参数表", interactive=True, wrap=False, max_height=300,
                                        column_widths=[120, 100, 100, 170, 90, 280, 80, 80, 160], elem_id="role_parameter_table", show_fullscreen_button=True)
                                    gr.HTML('<div class="role-section-title"><h4>校验详情</h4></div>')
                                    role_validation_summary = gr.Markdown("尚未生成剧本。", elem_classes="role-diagnostics")
                            with gr.Row(elem_classes="role-confirm-bar"):
                                with gr.Column(scale=2, min_width=240):
                                    gr.Markdown("音色、语速和归属检查完后确认。修改设置会要求重新确认，之后再点击页面下方的「开始生成」。")
                                role_confirm_btn = gr.Button("确认剧本与角色参数", elem_classes="btn-primary", elem_id="role_confirm_btn", scale=1)
                        with gr.Accordion("更多兼容选项", open=False, elem_classes="role-details"):
                            with gr.Tabs():
                                with gr.Tab("补充音色目录"):
                                    gr.Markdown("内置声音可直接使用。仅在需要补充其他音色时导入官网说明，之后重新拆分剧本。")
                                    voice_catalog_file = gr.File(label="TTS 官网音色说明", file_types=_VOICE_CATALOG_FILE_TYPES, file_count="single", type="filepath", interactive=True, elem_classes="role-field")
                                    voice_catalog_text = gr.TextArea(label="或粘贴音色说明", placeholder="支持 JSON、CSV、Markdown/文本表格；上传文件优先。", lines=4, interactive=True, elem_classes="role-field")
                                    with gr.Row():
                                        voice_catalog_provider = gr.Dropdown(choices=list(_VOICE_CATALOG_PROVIDERS), value="自动识别", label="对应引擎", interactive=True, elem_classes="role-field")
                                        voice_catalog_language = gr.Dropdown(choices=list(_VOICE_CATALOG_LANGUAGES), value="自动识别", label="默认语言", interactive=True, elem_classes="role-field")
                                    with gr.Row(elem_classes="role-action-row"):
                                        voice_catalog_clear_btn = gr.Button("清空用户音色目录", elem_classes="btn-ghost")
                                        voice_catalog_import_btn = gr.Button("解析并保存音色目录", elem_classes="btn-primary")
                                    voice_catalog_status = gr.Markdown(_voice_catalog_overview_markdown(), elem_id="voice_catalog_status")
                                with gr.Tab("匹配与容错"):
                                    allow_role_text_override = gr.Checkbox(label="允许剧本文本覆盖书籍正文", value=False, elem_classes="toggle")
                                    allow_role_title_mismatch = gr.Checkbox(label="允许章节标题不匹配", value=False, elem_classes="toggle")
                                    allow_role_fallback = gr.Checkbox(label="缺失角色回退到旁白 / 全局声音", value=False, elem_classes="toggle")
                                with gr.Tab("旧版质量测评"):
                                    role_quality_enabled = gr.Checkbox(label="启用旧版逐段测评（仅未启用下方统一音频检查时生效）", value=False, elem_classes="toggle")
                                    role_quality_max_rate = gr.Slider(minimum=2.0, maximum=7.0, step=0.1, value=4.3, label="中文语速上限（汉字/秒）", elem_classes="role-field")
                                    gr.Markdown("旧版结果写入 role_quality_reports。需要本地 SenseVoice；失败片段可能将诊断发送至 DeepSeek，并增加一次 MiMo 合成。日常建议使用下方统一音频检查。", elem_classes="role-caption")


                with gr.Group(elem_classes="app-card", elem_id="quality_setup"):
                    gr.HTML('<p class="card-title">音频检查与修复</p>')
                    audio_core_enabled = gr.Checkbox(label="MiMo 生成时检查内容、拼接与角色一致性", value=True, elem_classes="toggle")
                    audio_core_repair = gr.Checkbox(label="按次数与时限自动修复问题片段", value=False, elem_classes="toggle")
                    from audiobook_generator.ui.audio_quality import local_quality_status
                    gr.Markdown(local_quality_status())
                    gr.Markdown("默认保留原音频并生成检查报告。开启自动修复会增加合成请求；未校准的声音差异不会直接认定为缺陷。")
                    with gr.Accordion("高级质量配置（可选）", open=False):
                        audio_core_settings_file = gr.File(label="可选：本地模型与资源设置 JSON", file_types=[".json"])
                        audio_core_casting_file = gr.File(label="可选：已审查角色选角 JSON", file_types=[".json"])
                    with gr.Accordion("生成后查看检查结果", open=False):
                        quality_refresh = gr.Button("读取输出目录中的质量报告", size="sm")
                        quality_report_file = gr.Dropdown(label="质量报告", choices=[], interactive=True)
                        quality_summary = gr.Markdown("尚未读取报告")
                        quality_rows = gr.Dataframe(headers=["位置", "维度", "问题", "判断", "时间（秒）"], interactive=False)
                        quality_download = gr.File(label="下载完整报告", interactive=False)
                        quality_scope = gr.Dropdown(label="选择片段或拼接处试听", choices=[], interactive=True)
                        quality_audio = gr.Audio(label="问题上下文试听", interactive=False)


                # —— 高级设置弹窗（纯客户端控制；默认 display:none，JS 切换 .show） ——
                with gr.Group(elem_classes="modal-overlay", elem_id="advanced_modal") as advanced_modal:
                    with gr.Column(elem_classes="modal-box"):
                        gr.HTML('''
<div class="modal-header">
  <div>
    <p class="modal-title">高级设置</p>
    <p class="modal-subtitle">调整生成行为和章节解析；多角色配音在生成页独立配置。</p>
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
  <span class="advanced-section-badge">2</span>
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

                # —— 生成前检查与操作 ——
                with gr.Group(elem_classes="app-card", elem_id="generation_setup"):
                    gr.HTML('<p class="card-title"><span class="card-num">4</span>确认并生成</p>')
                    generation_summary = gr.HTML('<div class="generation-summary" data-files="0">先上传书籍，再选择声音。生成完成后可到资源库试听和下载。</div>', elem_id="generation_summary")
                    with gr.Row(elem_classes="row-cta"):
                        stop_btn = gr.Button("停止转换", elem_classes="btn-ghost", elem_id="generation_stop", interactive=False)
                        start_btn = gr.Button("开始生成有声书", elem_classes="btn-primary", variant="primary", interactive=False, elem_id="generation_start")
                    result_library_btn = gr.Button("前往资源库试听与下载 →", elem_classes="btn-ghost", elem_id="result_library_btn")
                result_library_btn.click(fn=lambda: gr.update(selected="tab_library"), outputs=main_tabs, show_progress="hidden")

            # ════════════ 资源库页 ════════════
            with gr.Tab("资源库", id="tab_library", elem_id="library_tab") as library_tab:
                gr.HTML('<div class="hero library-hero"><h1>资源库</h1><p>选择一本书，试听章节，直接下载或导出 ZIP。</p></div>')
                with gr.Group(elem_classes="app-card lib-card", elem_id="library_workspace"):
                    with gr.Row(elem_classes="library-toolbar"):
                        folder_dropdown = gr.Dropdown(choices=get_folders_list(), label="选择书籍 / 批次", interactive=True, scale=4, elem_id="library_folder_picker")
                        refresh_btn = gr.Button("刷新列表", elem_classes="btn-mini", scale=0, min_width=100)
                    with gr.Row(elem_classes="library-columns"):
                        with gr.Column(scale=3, min_width=280, elem_id="library_files"):
                            gr.HTML('<h3 class="library-heading">章节与文件</h3>')
                            library_search = gr.Textbox(label="查找文件", placeholder="输入章节名或文件名", elem_id="library_search")
                            with gr.Row(elem_classes="lib-row"):
                                select_all_btn = gr.Button("全选", elem_classes="btn-mini", scale=0, min_width=80)
                                deselect_all_btn = gr.Button("取消全选", elem_classes="btn-mini", scale=0, min_width=100)
                            file_selector = gr.CheckboxGroup(choices=[], label="选择要下载的文件", interactive=True, elem_classes="file-checks", elem_id="library_file_list")
                        with gr.Column(scale=2, min_width=280, elem_id="library_export"):
                            library_selection_summary = gr.HTML('<p class="card-desc">生成完成后，选择书籍即可查看文件。</p>')
                            library_preview_choice = gr.Dropdown(choices=[], label="试听章节", interactive=True)
                            library_preview_audio = gr.Audio(label="章节试听", interactive=False, type="filepath")
                            download_mode = gr.Radio(["逐个下载", "ZIP 打包"], value="逐个下载", label="下载方式")
                            direct_download_files = gr.File(label="点击文件右侧下载图标保存", file_count="multiple", interactive=False, elem_id="library_direct_download")
                            with gr.Group(visible=False, elem_id="library_zip_panel") as library_zip_panel:
                                generate_btn = gr.Button("准备 ZIP 下载", elem_classes="btn-primary lib-generate", interactive=False)
                                download_card = gr.HTML(_placeholder_html("勾选文件后准备 ZIP，再点击下载。"))
                                real_download_file = gr.DownloadButton("下载 ZIP", visible=False, elem_classes="btn-primary", elem_id="library_zip_download")
                            auto_delete_cb = gr.State(False)
                    with gr.Accordion("清理文件", open=False, elem_id="library_cleanup"):
                        gr.Markdown("下载会保留源文件。确认已保存到本地后，再手动清理；删除后无法恢复。")
                        cleanup_ack = gr.Checkbox(label="我已保存需要的文件，确认可以删除", value=False)
                        with gr.Row(elem_classes="lib-row"):
                            delete_btn = gr.Button("删除选中文件", elem_classes="btn-danger", scale=0, min_width=150, interactive=False)
                            delete_folder_btn = gr.Button("删除整个批次", elem_classes="btn-danger", scale=0, min_width=150, interactive=False)

            # ════════════ 日志页 ════════════
            with gr.Tab("日志", id="tab_logs"):
                gr.HTML('<div class="hero logs-hero"><h1>运行日志</h1><p>实时查看转换进度与详细信息。</p></div>')
                with gr.Group(elem_classes="app-card run-log-card"):
                    global webui_log_file
                    # 固定成绝对路径：进度解析与日志组件都用同一份文件，不受工作目录变化影响
                    webui_log_file = generate_unique_log_path("EtA_WebUI").resolve()
                    webui_log_file.touch()
                    # tail 默认只有 100：页面在生成中途打开/刷新时只能看到最后 100 行，
                    # 看起来就像"日志不全"。保留 3000 行读取窗口和 8000 行终端回滚缓冲。
                    # CSS 按视口限制可视高度，历史日志在终端内部滚动查看。
                    Log(str(webui_log_file), dark=False, height=480, xterm_font_size=12,
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
            _tab.select(fn=lambda n=_id: role_provider_changed(n),
                        inputs=None,
                        outputs=[provider_state, role_provider_hint, role_regenerate_btn],
                        show_progress="hidden", js=_js)

        role_mode.change(
            fn=lambda enabled: gr.update(visible=bool(enabled)),
            inputs=role_mode,
            outputs=role_config_panel,
            show_progress="hidden",
        )
        role_script_file.change(fn=lambda file_obj: gr.update(visible=bool(file_obj)), inputs=role_script_file, outputs=role_editor, show_progress="hidden")
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
            book_chapter_catalog, chapter_selection_source, chapter_from_name, chapter_to_name,
        ]
        _chapter_catalog_inputs = [input_file, provider_state, title_mode, new_line_mode,
                                   remove_endnotes, remove_reference_numbers, search_and_replace_file]
        gr.on(
            triggers=[input_file.change, provider_state.change, title_mode.change, new_line_mode.change,
                      remove_endnotes.change, remove_reference_numbers.change,
                      search_and_replace_file.change, chapter_reload.click],
            fn=read_book_chapters, inputs=_chapter_catalog_inputs,
            outputs=[book_chapter_catalog, chapter_from_name, chapter_to_name,
                     chapter_start, chapter_end, chapter_range_state, chapter_numeric_range, chapter_named_range,
                     chapter_selection_source, book_directory_loaded],
            show_progress="hidden", trigger_mode="always_last",
            concurrency_id="chapter-directory", concurrency_limit=1,
        )
        for selector, endpoint in [(chapter_from_name, "start"), (chapter_to_name, "end")]:
            selector.input(
                fn=lambda start, end, catalog, source, which=endpoint: select_book_chapter(start, end, catalog, which, source),
                inputs=[chapter_from_name, chapter_to_name, book_chapter_catalog, chapter_selection_source],
                outputs=[chapter_from_name, chapter_to_name, chapter_start, chapter_end, chapter_range_state],
                show_progress="hidden", trigger_mode="always_last",
                concurrency_id="chapter-directory", concurrency_limit=1,
            )
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
            role_split_status,
            role_regenerate_btn,
        ]
        # 当前书籍目录载入后才触发；重读同一本书的目录不会额外调用 DeepSeek。
        book_directory_loaded.change(
            fn=auto_split_role_script_ui, api_name="auto_split_role_script",
            inputs=_auto_split_inputs,
            outputs=_auto_split_outputs,
            show_progress="hidden",
            concurrency_id="role-script-split", concurrency_limit=1,
            trigger_mode="once",
        )
        # 允许先上传书再开启角色模式，或直接点击“重新生成”。
        role_mode.change(
            fn=auto_split_role_script_ui, api_name="auto_split_role_script",
            inputs=_auto_split_inputs,
            outputs=_auto_split_outputs,
            show_progress="hidden",
            concurrency_id="role-script-split", concurrency_limit=1,
            trigger_mode="once",
        )
        role_regenerate_btn.click(
            fn=split_role_script_now_ui, api_name="split_role_script_now",
            inputs=_auto_split_inputs,
            outputs=_auto_split_outputs,
            show_progress="hidden",
            concurrency_id="role-script-split", concurrency_limit=1,
            trigger_mode="once",
        )
        role_calibrate_btn.click(
            fn=calibrate_role_pace,
            inputs=[provider_state, role_script_file, role_table, role_preview_text,
                    model, voices, speed, instructions, enable_stream],
            outputs=[role_table, role_calibration_status],
            show_progress="full",
            show_progress_on=[role_calibration_status],
        )
        role_review_load_btn.click(
            fn=load_role_review, inputs=role_script_file,
            outputs=[role_review_segment, role_review_entity, role_merge_source,
                     role_merge_target, role_review_info], show_progress="hidden",
        ).then(fn=load_narration_controls, inputs=[role_script_file, role_narration_chapter],
               outputs=[role_narration_chapter, role_narration_entity, role_narration_apply, role_narration_status],
               show_progress="hidden")
        role_script_file.change(fn=load_narration_controls, inputs=[role_script_file, role_narration_chapter],
            outputs=[role_narration_chapter, role_narration_entity, role_narration_apply, role_narration_status],
            show_progress="hidden")
        role_narration_chapter.input(fn=lambda file_obj, chapter: load_narration_controls(file_obj, chapter)[1:],
            inputs=[role_script_file, role_narration_chapter],
            outputs=[role_narration_entity, role_narration_apply, role_narration_status], show_progress="hidden")
        role_narration_apply.click(fn=apply_chapter_narration,
            inputs=[role_script_file, role_table, role_narration_chapter, role_narration_entity],
            outputs=[role_table, role_narration_status, role_split_confirmed, role_confirmed_signature,
                     role_confirmation_probe_host, role_verification_summary],
            show_progress="hidden", concurrency_id="role-project-review", concurrency_limit=1,
        ).then(fn=load_role_review, inputs=role_script_file,
            outputs=[role_review_segment, role_review_entity, role_merge_source, role_merge_target, role_review_info],
            show_progress="hidden")
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
                fn=lambda file_obj, segment_id, entity_id, source_id, target_id, table, op=operation:
                    apply_role_review(file_obj, op, segment_id, entity_id, source_id, target_id, table),
                inputs=[role_script_file, role_review_segment, role_review_entity,
                        role_merge_source, role_merge_target, role_table],
                outputs=[role_review_segment, role_table, role_review_info,
                         role_split_confirmed, role_confirmed_signature, role_confirmation_probe_host],
                show_progress="hidden",
                concurrency_id="role-project-review", concurrency_limit=1,
            ).then(fn=refresh_role_summary, inputs=role_script_file, outputs=role_verification_summary,
                   show_progress="hidden"
            ).then(fn=load_narration_controls, inputs=[role_script_file, role_narration_chapter],
                   outputs=[role_narration_chapter, role_narration_entity, role_narration_apply, role_narration_status],
                   show_progress="hidden")
        role_confirm_btn.click(
            fn=confirm_auto_role_script_ui, api_name="confirm_auto_role_script",
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
                role_confirm_btn,
            ],
            show_progress="hidden",
            concurrency_id="role-project-review", concurrency_limit=1,
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
                role_preview_role,
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
        role_preview_role.change(
            fn=load_role_voice_settings, inputs=[role_script_file, role_table, role_preview_role],
            outputs=[role_voice_mode, role_voice_builtin, role_voice_description, role_voice_reference,
                     role_voice_language, role_voice_pace, role_voice_instructions, role_voice_status],
            show_progress="hidden",
        )
        provider_state.change(fn=lambda provider: (gr.update(visible=provider == "Mimo"),
                                                   gr.update(visible=provider == "Mimo")),
                              inputs=provider_state, outputs=[role_voice_controls, role_voice_freeze],
                              show_progress="hidden")
        role_voice_mode.change(
            fn=lambda mode: (gr.update(visible=mode == "preset"), gr.update(visible=mode == "design"),
                             gr.update(visible=mode == "clone")),
            inputs=role_voice_mode, outputs=[role_voice_builtin, role_voice_description, role_voice_reference],
            show_progress="hidden",
        )
        role_voice_apply.click(
            fn=apply_role_voice_settings,
            inputs=[role_script_file, role_table, role_preview_role, role_voice_mode, role_voice_builtin,
                    role_voice_description, role_voice_reference, role_voice_language, role_voice_pace,
                    role_voice_instructions], outputs=[role_table, role_voice_status],
        )
        role_preview_btn.click(
            fn=preview_role_segment,
            inputs=[provider_state, role_script_file, role_table, role_preview_role, role_preview_text,
                    model, voices, speed, instructions, enable_stream, openai_output_format,
                    minimax_model, minimax_voice, minimax_output_format],
            outputs=[role_preview_audio],
            show_progress="full", show_progress_on=[role_preview_audio],
        )

        role_voice_freeze.click(
            fn=use_preview_as_role_reference,
            inputs=[role_script_file, role_table, role_preview_role, role_preview_audio,
                    role_voice_language, role_voice_pace, role_voice_instructions],
            outputs=[role_table, role_voice_status, role_voice_mode, role_voice_reference],
        )

        voxcpm_preview_btn.click(
            fn=voxcpm_preview_voice,
            inputs=[voxcpm_voice, voxcpm_model, voxcpm_device, voxcpm_voice_dir,
                    voxcpm_cfg_value, voxcpm_inference_timesteps, voxcpm_regenerate_voice],
            outputs=[voxcpm_preview_audio],
            show_progress="hidden",
        )

        def update_generation_summary(files, provider, roles, confirmed, parse_only, script_file=None, catalog_state=None):
            count = len(files or [])
            mismatch = False
            if roles:
                confirmed = (bool(script_file) and not _role_project_is_splitting(script_file)
                             and not _role_project_needs_reconfirmation(script_file)
                             and (bool(confirmed) or bool(_recall_role_confirmation(script_file))))
                if confirmed:
                    script, report = _load_uploaded_role_script(script_file)
                    confirmed = bool(script and report.ok)
                    mismatch = bool(script and script.provider != _role_provider_id(provider))
            ready = bool(count) and (not roles or (count == 1 and bool(confirmed) and not mismatch and provider in ("Mimo", "MiniMax")))
            directory_ready = catalog_state is None or (
                catalog_state.get('mode') in ('single', 'batch')
                and catalog_state.get('files') == [_uploaded_file_path(file_obj) for file_obj in (files or [])])
            ready = ready and directory_ready
            engine = html.escape(_PROVIDER_LABEL.get(provider, provider))
            if not count:
                message = "下一步：在第 1 步上传书籍。"
            elif not directory_ready:
                message = "正在准备当前书籍目录，请等待载入完成；读取失败时可重新读取目录。"
            elif roles and count != 1:
                message = "多角色配音每次处理一本书，请保留一个书籍文件。"
            elif roles and provider not in ("Mimo", "MiniMax"):
                message = "多角色配音支持 MiMo / MiniMax，请在第 2 步切换引擎。"
            elif roles and mismatch:
                message = "当前剧本与所选引擎不匹配，请切回剧本对应的引擎，或重新拆分剧本。"
            elif roles and not confirmed:
                message = "下一步：在第 3 步生成或上传剧本，试听并确认角色参数。"
            else:
                mode = "多角色配音" if roles else ("仅解析文本，不生成音频" if parse_only else "单声音朗读")
                message = f"已准备 {count} 本书 · {engine} · {mode}。" + ("点击开始解析，完成后到日志查看章节与字数。" if parse_only and not roles else "点击开始生成，完成后在资源库试听与下载。")
            return f'<div class="generation-summary" data-files="{count}" data-ready="{int(ready)}" data-parse-only="{int(bool(parse_only and not roles))}" role="status">{message}</div>', gr.update(interactive=ready, value="开始解析书籍" if parse_only and not roles else "开始生成有声书")

        for source in (input_file, provider_state, role_mode, role_split_confirmed, role_confirmed_signature, role_script_file, preview, book_chapter_catalog):
            source.change(fn=update_generation_summary, inputs=[input_file, provider_state, role_mode, role_split_confirmed, preview, role_script_file, book_chapter_catalog], outputs=[generation_summary, start_btn], show_progress="hidden")

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
                    deepseek_api_key, deepseek_base_url, deepseek_model,
                    audio_core_enabled, audio_core_repair, audio_core_settings_file, audio_core_casting_file,
                    book_chapter_catalog, chapter_selection_source, chapter_from_name, chapter_to_name],
            outputs=[progress_state, progress_timer])
        def refresh_quality_reports(folder):
            from audiobook_generator.ui.audio_quality import find_quality_reports
            reports = find_quality_reports(folder)
            return gr.update(choices=reports, value=reports[0] if reports else None)

        def show_quality_report(path):
            if not path:
                return "尚无报告", [], None, gr.update(choices=[], value=None)
            from audiobook_generator.ui.audio_quality import load_quality_report, resource_summary_text
            try:
                report, rows, previews = load_quality_report(path)
                generation = "音频已导出；请按报告核验" if report.get("generation_status") == "generated" else f"生成失败：{report.get('error_type', '未知原因')}"
                return (f"第 {report['chapter_index']} 章：{report['quality_status']}；{generation}。\n\n{resource_summary_text(report)}",
                        rows, path, gr.update(choices=list(previews), value=None))
            except (OSError, ValueError, KeyError) as exc:
                gr.Warning(f"报告读取失败：{exc}")
                return "报告不可用", [], None, gr.update(choices=[], value=None)

        def play_quality_issue(path, scope):
            if not path or not scope:
                return None
            from audiobook_generator.ui.audio_quality import preview_quality_issue
            try:
                return preview_quality_issue(path, scope)
            except (OSError, ValueError, KeyError):
                return None

        provider_state.change(fn=lambda provider: provider == "Mimo", inputs=provider_state,
                              outputs=audio_core_enabled, show_progress="hidden")
        quality_reports_seen = gr.State("")
        def refresh_quality_after_progress(progress, folder, seen):
            try:
                mode = json.loads(progress or "{}").get("mode")
            except (ValueError, TypeError):
                return gr.update(), seen
            if mode not in {"finished", "failed", "interrupted"}:
                return gr.update(), seen
            from audiobook_generator.ui.audio_quality import find_quality_reports
            reports = find_quality_reports(folder)
            fingerprint = json.dumps([(path, Path(path).stat().st_mtime_ns) for path in reports])
            if not reports or fingerprint == seen:
                return gr.update(), seen
            return gr.update(choices=reports, value=reports[0]), fingerprint

        progress_state.change(fn=refresh_quality_after_progress,
                              inputs=[progress_state, output_dir, quality_reports_seen],
                              outputs=[quality_report_file, quality_reports_seen], show_progress="hidden")
        quality_refresh.click(fn=refresh_quality_reports, inputs=output_dir, outputs=quality_report_file)
        quality_report_file.change(fn=show_quality_report, inputs=quality_report_file,
                                   outputs=[quality_summary, quality_rows, quality_download, quality_scope])
        quality_scope.change(fn=play_quality_issue, inputs=[quality_report_file, quality_scope], outputs=quality_audio)
        stop_btn.click(fn=terminate_generator, inputs=None, outputs=[progress_state, progress_timer])

        # 进度条定时更新
        progress_timer.tick(fn=get_progress_info, inputs=None, outputs=[progress_state, progress_timer], show_progress="hidden")
        # 页面加载/刷新时同步一次状态：新会话也能看到当前进度，并在有批次在跑时自动开始轮询
        ui.load(fn=get_progress_info, inputs=None, outputs=[progress_state, progress_timer], show_progress="hidden")

        # 资源库
        library_tab.select(
            fn=refresh_library_on_open, inputs=[folder_dropdown, file_selector],
            outputs=[folder_dropdown, file_selector], show_progress="hidden", queue=False,
        )
        refresh_btn.click(fn=refresh_batches, inputs=None, outputs=[folder_dropdown, file_selector], show_progress="hidden")
        # 仅用户切换批次时默认全选，避免自动刷新回写下拉框时覆盖保留的勾选。
        folder_dropdown.input(fn=load_files_for_folder, inputs=folder_dropdown, outputs=file_selector, show_progress="hidden")
        select_all_btn.click(fn=lambda f, query: gr.update(value=[name for name in get_files_in_folder(f) if (query or "").casefold() in name.casefold()]), inputs=[folder_dropdown, library_search], outputs=file_selector, show_progress="hidden")
        deselect_all_btn.click(fn=lambda: gr.update(value=[]), inputs=None, outputs=file_selector, show_progress="hidden")
        cleanup_ack.change(fn=lambda ack: (gr.update(interactive=bool(ack)), gr.update(interactive=bool(ack))), inputs=cleanup_ack, outputs=[delete_btn, delete_folder_btn], show_progress="hidden")
        folder_dropdown.change(fn=lambda: False, outputs=cleanup_ack, show_progress="hidden")
        delete_btn.click(fn=delete_selected_files, inputs=[folder_dropdown, file_selector],
                         outputs=[folder_dropdown, file_selector, download_card, real_download_file])
        delete_folder_btn.click(fn=delete_entire_folder, inputs=folder_dropdown,
                                outputs=[folder_dropdown, file_selector, download_card, real_download_file])
        generate_btn.click(fn=generate_download, inputs=[folder_dropdown, file_selector, auto_delete_cb],
                           outputs=[folder_dropdown, file_selector, download_card, real_download_file])

        def update_library_selection(folder, selected):
            summary, paths, audio_choices = selection_details(get_output_dir(), folder, selected)
            return summary, gr.update(value=paths or None), gr.update(choices=audio_choices, value=None), gr.update(value=None), gr.update(interactive=bool(paths)), gr.update(value=None, visible=False), gr.update(value=_placeholder_html("勾选文件后准备 ZIP，再点击下载。"))

        def filter_library_files(folder, query, selected):
            files = get_files_in_folder(folder)
            matches = [name for name in files if (query or "").casefold() in name.casefold()]
            # 搜索只缩小当前操作集，隐藏的文件不参与打包或删除。
            return gr.update(choices=matches, value=[name for name in (selected or []) if name in matches])

        file_selector.change(fn=update_library_selection, inputs=[folder_dropdown, file_selector], outputs=[library_selection_summary, direct_download_files, library_preview_choice, library_preview_audio, generate_btn, real_download_file, download_card], show_progress="hidden", queue=False)
        folder_dropdown.change(fn=lambda: ("", gr.update(value=None, visible=False)), outputs=[library_search, real_download_file], show_progress="hidden")
        library_search.input(fn=filter_library_files, inputs=[folder_dropdown, library_search, file_selector], outputs=file_selector, show_progress="hidden")
        download_mode.change(fn=lambda mode: (gr.update(visible=mode == "逐个下载"), gr.update(visible=mode == "ZIP 打包")), inputs=download_mode, outputs=[direct_download_files, library_zip_panel], show_progress="hidden")
        def preview_library_file(folder, name):
            _, paths, _ = selection_details(get_output_dir(), folder, [name] if name else [])
            return paths[0] if paths else None
        library_preview_choice.change(fn=preview_library_file, inputs=[folder_dropdown, library_preview_choice], outputs=library_preview_audio, show_progress="hidden")

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
