"""
Apple 风格 WebUI —— 全新设计的有声书生成工作台。

设计理念：
- 完全摒弃旧版单页堆叠式表单，改用「二级页面 + 弹窗」结构。
- 顶部胶囊导航在「转换 / 资源库 / 日志」三个主页面间切换。
- TTS 引擎配置以卡片选择 + 浮层弹窗（Modal）形式呈现。
- 苹果风视觉：留白、毛玻璃、SF 字体、克制动效、渐变高亮。

功能与旧版 web_ui.py 完全等价，仅 UI 层重写，未修改任何原有文件。
入口：main_ui_apple.py
"""

from multiprocessing import Process
from typing import Optional
from pathlib import Path
import os
import json
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
from audiobook_generator.tts_providers.minimax_tts_provider import (
    get_minimax_supported_models,
    get_minimax_supported_output_formats,
    get_minimax_voice_choices,
    get_minimax_voice_id_from_choice,
)
from audiobook_generator.tts_providers.chatterbox_tts_provider import (
    get_chatterbox_supported_models,
    get_chatterbox_supported_devices,
    get_chatterbox_supported_output_formats,
)
from audiobook_generator.utils.log_handler import generate_unique_log_path
from audiobook_generator.utils.mimo_config import (
    load_mimo_config, save_mimo_config, mask_api_key as mimo_mask_api_key, test_mimo_connection
)
from audiobook_generator.utils.minimax_config import (
    load_minimax_config, save_minimax_config, mask_api_key as minimax_mask_api_key, test_minimax_connection
)
from audiobook_generator.utils.qwen_config import (
    load_qwen_config, save_qwen_config, mask_api_key as qwen_mask_api_key, test_qwen_connection
)
from main import main

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
import hashlib

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


# ── 运行态 ────────────────────────────────────────────────────────
running_process: Optional[Process] = None
webui_log_file = None

_PROVIDER_LABEL = {
    "Mimo": "MiMo",
    "MiniMax": "MiniMax",
    "Edge": "Edge",
    "Qwen": "Qwen TTS",
    "Chatterbox": "Chatterbox",
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
                 chatterbox_reference_audio, chatterbox_exaggeration, chatterbox_cfg_weight):
    if not input_file:
        gr.Warning("请先选择至少一个书籍文件")
        return gr.Timer(active=False)
    gr.Info("🚀 有声书生成已开始！请在日志页查看实时进度。")
    if not isinstance(input_file, list):
        input_file = [input_file]

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

        config.preview = preview
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
        else:
            raise ValueError("Unsupported TTS provider selected")

        configs.append(config)

    launch_batch(configs)
    return gr.Timer(active=True)


def _batch_worker(config_list, log_file_path):
    """子进程逐个处理每个 EPUB（须在模块顶层以便 spawn pickle）。"""
    total = len(config_list)
    for idx, cfg in enumerate(config_list):
        book_name = Path(cfg.input_file).stem
        print(f"\n{'=' * 60}")
        print(f"📚 [{idx + 1}/{total}] 开始转换: {book_name}")
        print(f"{'=' * 60}")
        try:
            main(cfg, log_file_path)
            print(f"✅ [{idx + 1}/{total}] 完成: {book_name}")
        except Exception as e:
            print(f"❌ [{idx + 1}/{total}] 失败: {book_name} — {e}")
    print(f"\n🎉 全部处理完毕！共 {total} 本书")


def launch_batch(configs):
    global running_process
    if running_process and running_process.is_alive():
        print("Audiobook generator already running")
        return
    running_process = Process(target=_batch_worker, args=(configs, str(webui_log_file.absolute())))
    running_process.start()



def get_progress_info():
    """解析日志文件获取生成进度，同时控制定时器开关"""
    global webui_log_file
    if not webui_log_file or not webui_log_file.exists():
        return _progress_html(0, "等待开始", "", 0, 0), gr.Timer(active=False)

    try:
        log_content = webui_log_file.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return _progress_html(0, "等待开始", "", 0, 0), gr.Timer(active=True)

    import re

    # 解析当前书名: [idx/total] 开始转换: book_name
    book_match = re.findall(r"\[\d+/\d+\] 开始转换: (.+)$", log_content, re.MULTILINE)
    current_book = book_match[-1] if book_match else ""

    # 解析总章节数: Chapters count: X
    chapters_count_match = re.findall(r"Chapters count: (\d+)", log_content, re.MULTILINE)
    total_chapters = int(chapters_count_match[-1]) if chapters_count_match else 0

    # 解析章节范围: Converting chapters from X to Y
    range_match = re.findall(r"Converting chapters from (\d+) to (\d+)", log_content, re.MULTILINE)
    if range_match:
        chapter_start, chapter_end = int(range_match[-1][0]), int(range_match[-1][1])
        total_chapters = chapter_end - chapter_start + 1

    # 解析已完成章节: ✅ Converted chapter X
    completed_match = re.findall(r"✅ Converted chapter (\d+)", log_content, re.MULTILINE)
    completed = len(completed_match)

    # 检查是否全部完成
    is_done = "全部处理完毕" in log_content

    if is_done and total_chapters > 0:
        return _progress_html(100, "✅ 全部完成", current_book, total_chapters, total_chapters), gr.Timer(active=False)

    if total_chapters > 0:
        pct = min(100, int(completed / total_chapters * 100))
        return _progress_html(pct, f"正在生成...", current_book, total_chapters, completed), gr.Timer(active=True)

    if current_book:
        return _progress_html(5, "正在初始化...", current_book, 0, 0), gr.Timer(active=True)

    return _progress_html(0, "等待开始", "", 0, 0), gr.Timer(active=True)


def _progress_html(pct, status, book_name, total, done):
    """生成进度条 HTML"""
    if pct == 0 and not book_name:
        return """<div class="progress-container idle">
            <div class="progress-status">等待开始生成...</div>
        </div>"""
    
    book_display = f'<span class="progress-book">📖 {book_name}</span>' if book_name else ""
    detail = f"章节 {done}/{total}" if total > 0 else ""
    
    return f"""<div class="progress-container active">
        <div class="progress-header">
            <span class="progress-status">{status}</span>
            <span class="progress-detail">{detail}</span>
            <span class="progress-pct">{pct}%</span>
        </div>
        {book_display}
        <div class="progress-track">
            <div class="progress-fill" style="width: {pct}%"></div>
        </div>
    </div>"""

def terminate_generator():
    global running_process
    if running_process and running_process.is_alive():
        running_process.terminate()
        running_process = None
        print("Audiobook generator terminated manually")
    return gr.Timer(active=False)


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
CUSTOM_CSS = """
:root {
  --apple-bg: #f5f5f7;
  --apple-surface: #ffffff;
  --apple-surface-2: #fbfbfd;
  --apple-text: #1d1d1f;
  --apple-text-2: #6e6e73;
  --apple-text-3: #86868b;
  --apple-border: #d2d2d7;
  --apple-border-soft: #e8e8ed;
  --apple-blue: #0071e3;
  --apple-blue-hover: #0077ed;
  --apple-blue-soft: #e8f1fd;
  --apple-indigo: #5e5ce6;
  --apple-green: #34c759;
  --apple-red: #ff3b30;
  --apple-shadow: 0 1px 2px rgba(0,0,0,0.04), 0 8px 24px rgba(0,0,0,0.04);
  --apple-shadow-lg: 0 24px 60px rgba(0,0,0,0.14);
  --apple-shadow-blue: 0 8px 20px rgba(0,113,227,0.28);
  --radius: 20px;
  --radius-sm: 14px;
}
* { box-sizing: border-box; }
html, body, #root, .gradio-container, .main, footer,
.gradio-container > .main { background: var(--apple-bg) !important;
  color: var(--apple-text) !important;
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text",
               "Helvetica Neue", "PingFang SC", "Microsoft YaHei", sans-serif !important;
  -webkit-font-smoothing: antialiased; }
.gradio-container { margin: 0 auto !important;
  padding: 0 clamp(14px, 4vw, 48px) 64px !important; width: 100% !important; }

/* ── 顶部品牌栏 ── */
.app-header {
  position: sticky; top: 0; z-index: 100;
  display: flex; align-items: center; justify-content: space-between;
  gap: 10px; padding: 14px 4px; margin-bottom: 8px;
  padding-top: max(14px, env(safe-area-inset-top));
  background: rgba(251,251,253,0.72);
  backdrop-filter: saturate(180%) blur(20px);
  -webkit-backdrop-filter: saturate(180%) blur(20px);
  border-bottom: 1px solid rgba(210,210,215,0.5);
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
.tab-nav button:hover { color: var(--apple-text) !important; background: rgba(0,0,0,0.04) !important; }
.tab-nav button.selected {
  color: #fff !important;
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
.app-card:hover { box-shadow: 0 1px 2px rgba(0,0,0,0.04), 0 16px 40px rgba(0,0,0,0.07) !important; }
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
  background: linear-gradient(120deg, #1d1d1f 0%, #0071e3 55%, #5e5ce6 100%);
  -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent; margin: 0 0 10px !important;
}
.hero p { color: var(--apple-text-2); font-size: clamp(0.92rem, 2.6vw, 1.05rem); margin: 0 auto; max-width: 560px; line-height: 1.5; }

/* ── 输入控件统一 ── */
input, textarea, select {
  border-radius: var(--radius-sm) !important; background: var(--apple-surface-2) !important;
  border: 1px solid var(--apple-border-soft) !important; color: var(--apple-text) !important;
  font-size: 0.92em !important; transition: border-color 0.2s ease, box-shadow 0.2s ease, background 0.2s ease !important;
}
input:hover, textarea:hover, select:hover { border-color: var(--apple-border) !important; }
input:focus, textarea:focus, select:focus {
  border-color: var(--apple-blue) !important; background: #fff !important;
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
  background: linear-gradient(135deg, var(--apple-blue-soft) 0%, #f0eefe 100%) !important;
  border: 1px solid #d8e7fc !important;
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
  margin: 0 0 16px; padding: 16px 20px;
  background: var(--apple-surface); border-radius: var(--radius);
  border: 1px solid var(--apple-border-soft);
  transition: all 0.3s ease;
}
.progress-container.idle { opacity: 0.5; }
.progress-container.active {
  background: linear-gradient(135deg, rgba(0,113,227,0.04), rgba(94,92,230,0.04));
  border-color: rgba(0,113,227,0.15);
}
.progress-header {
  display: flex; align-items: center; gap: 12px;
  margin-bottom: 8px;
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
}
.progress-book {
  display: inline-block; margin-bottom: 10px;
  font-size: 0.85rem; color: var(--apple-text-2);
  background: var(--apple-surface-2); padding: 4px 12px;
  border-radius: 8px;
}
.progress-track {
  height: 8px; background: var(--apple-surface-2);
  border-radius: 4px; overflow: hidden;
}
.progress-fill {
  height: 100%; border-radius: 4px;
  background: linear-gradient(90deg, var(--apple-blue), #5e5ce6);
  transition: width 0.5s cubic-bezier(0.16,1,0.3,1);
  position: relative;
}
.progress-fill::after {
  content: ""; position: absolute; inset: 0;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.3), transparent);
  animation: shimmer 2s infinite;
}
@keyframes shimmer {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(100%); }
}

/* 隐藏 Gradio Timer 组件本身的可见元素（拖拽横条等） */
.progress-bar-wrap + .gr-timer,
.progress-bar-wrap ~ [data-testid="timer"],
.gradio-timer { display: none !important; height: 0 !important; overflow: hidden !important; }
/* 隐藏所有 Timer 渲染出的分隔/拖拽条 */
div:has(> .progress-bar-wrap) ~ .gr-group:empty,
div:has(> .progress-bar-wrap) ~ .gr-box:empty { display: none !important; }

/* ── 引擎分段选择器（原生 Tabs） ── */
.engine-tabs { gap: 0 !important; }
.engine-tabs > .tab-nav {
  display: grid !important; grid-template-columns: repeat(5, 1fr) !important;
  gap: 4px !important; padding: 4px !important; margin: 0 0 16px !important;
  background: var(--apple-surface-2) !important; border-radius: var(--radius-sm) !important;
  border: 1px solid var(--apple-border-soft) !important;
}
@media (max-width: 560px) {
  .engine-tabs > .tab-nav { grid-template-columns: repeat(2, 1fr) !important; }
}
.engine-tabs > .tab-nav button {
  border: none !important; background: transparent !important;
  font-weight: 600 !important; color: var(--apple-text-2) !important;
  font-size: 0.86rem !important; padding: 10px 6px !important;
  border-radius: 10px !important; margin: 0 !important; text-align: center !important;
  transition: color 0.2s ease, background 0.2s ease, box-shadow 0.25s ease !important; box-shadow: none !important;
}
.engine-tabs > .tab-nav button:hover { color: var(--apple-text) !important; background: rgba(255,255,255,0.7) !important; }
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
  background: linear-gradient(135deg, #e8f1fd 0%, #f0eefe 100%);
  border: 1px solid #cfe3fc; border-radius: 980px; margin-bottom: 0;
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
  border: 1px solid #ffd1ce !important; border-radius: 980px !important;
  font-weight: 500 !important; font-size: 0.85rem !important; padding: 9px 18px !important;
  transition: background 0.2s ease, border-color 0.2s ease !important; cursor: pointer !important;
}
.btn-danger:hover { background: #fff0ef !important; border-color: var(--apple-red) !important; }

.btn-mini {
  background: #f5f5f7 !important; color: var(--apple-text-2) !important; border: none !important;
  border-radius: 980px !important; font-size: 0.82rem !important; font-weight: 500 !important;
  padding: 7px 15px !important; transition: all 0.18s ease !important; cursor: pointer !important;
}
.btn-mini:hover { background: #ebebed !important; color: var(--apple-text) !important; }

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
.toggle label::before { content: ''; display: block; width: 38px; height: 22px; background: #e8e8ed;
  border-radius: 980px; margin-right: 12px; transition: background 0.3s ease; flex-shrink: 0; }
.toggle label::after { content: ''; position: absolute; left: 3px; top: 50%; transform: translateY(-50%);
  width: 16px; height: 16px; background: #fff; border-radius: 50%; box-shadow: 0 1px 3px rgba(0,0,0,0.2);
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
  background: #f5f5f7; border-radius: 16px; border: 1px dashed var(--apple-border); min-height: 180px;
  display: flex; flex-direction: column; align-items: center; justify-content: center; }
.lib-empty-icon { font-size: 2.4rem; margin-bottom: 12px; }
.lib-empty-text { font-size: 0.95rem; font-weight: 500; line-height: 1.6; }
.lib-ready { padding: 24px; text-align: center; background: linear-gradient(135deg,#f0f9ff,#f0eefe);
  border-radius: 16px; border: 1px solid #cfe3fc; margin-top: 12px; }
.lib-ready-icon { font-size: 2.2rem; margin-bottom: 6px; }
.lib-ready h3 { color: #0369a1; margin: 0 0 8px; font-size: 1.1rem; font-weight: 700; }
.lib-ready p { color: #0c4a6e; font-size: 0.92rem; word-break: break-all; margin: 0; }
.lib-warn { color: var(--apple-red); font-size: 0.8rem; font-weight: 600; background: #fff0ef;
  padding: 7px 12px; border-radius: 10px; display: inline-block; margin-top: 10px; }
.custom-download-zone a { color: var(--apple-blue) !important; font-weight: 600 !important; }

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
body.modal-open::before {
  content: "" !important;
  position: fixed !important; inset: 0 !important; z-index: 999 !important;
  background: rgba(0,0,0,0.08) !important;
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
  overflow: hidden !important; }
#advanced_modal .styler { display: flex !important; align-items: center !important;
  justify-content: center !important; width: 100% !important; overflow: visible !important;
  max-height: 100% !important; min-height: 0 !important; }
#advanced_modal .modal-box, #advanced_modal .modal-box .styler {
  background: #fff !important; border: none !important;
  box-shadow: 0 0 0 1px rgba(0,0,0,0.04), 0 24px 80px rgba(0,0,0,0.28) !important;
  border-radius: 22px !important; padding: 24px !important;
  width: min(760px, 94vw) !important; max-width: 94vw !important;
  max-height: 80vh !important; overflow-y: auto !important;
  overflow-x: hidden !important;
  overscroll-behavior: contain !important;
  -webkit-overflow-scrolling: touch !important;
}
/* modal-box 内层 wrapper：使用充足的底部 padding 避免最后一个元素被滚动视口裁切 */
#advanced_modal .modal-box .styler { box-shadow: none !important; background: transparent !important;
  overflow: visible !important; max-height: none !important; min-height: 0 !important;
  padding: 4px 0 36px 0 !important; display: flex !important; flex-direction: column !important;
  align-items: stretch !important; width: 100% !important; gap: 0 !important; }
#advanced_modal .modal-box { background: #fff !important; animation: modalIn 0.3s cubic-bezier(0.16,1,0.3,1);
  display: block !important; }
@keyframes modalIn { from { opacity:0; transform: translateY(14px) scale(0.97); } to { opacity:1; transform:none; } }
#advanced_modal .modal-header { display:flex !important; align-items:center !important; justify-content:space-between !important; margin-bottom:4px; }
#advanced_modal .modal-title { font-size: clamp(1.05rem, 3vw, 1.25rem); font-weight:700; margin:0; color: var(--apple-text); }
#advanced_modal .modal-desc { color: var(--apple-text-2); font-size:0.9rem; margin:0 0 14px; }
#advanced_modal .modal-close-btn { width:34px !important; height:34px !important; min-width:34px !important;
  border-radius:50% !important; padding:0 !important; font-size:1.1rem;
  background: var(--apple-surface-2) !important; border:none !important; color: var(--apple-text) !important; }
/* 完成按钮底部预留安全边距，避免被视口下沿裁切 */
#advanced_modal .modal-done { width: 100%; margin-top: 14px; margin-bottom: 8px; }
#advanced_modal .modal-trigger { width:100%; }

/* 大屏：放宽内容列宽，避免超宽屏拉伸 */
@media (min-width: 1200px) {
  .gradio-container { max-width: 1280px !important; }
}
/* 超宽屏：放宽容器，居中留白 */
@media (min-width: 1440px) {
  .gradio-container { max-width: 1320px !important; }
}
"""

# ── 主装配 ────────────────────────────────────────────────────────
def host_ui(config):
    default_output_dir = os.path.join("audiobook_output", datetime.now().strftime("%Y-%m-%d_%H-%M-%S"))
    saved = _load_settings()

    theme = gr.themes.Default(primary_hue="blue", secondary_hue="slate", neutral_hue="slate",
                              font=[gr.themes.GoogleFont("Inter"), "system-ui", "sans-serif"]).set(
        body_background_fill="#fbfbfd",
        block_background_fill="#ffffff", block_border_width="0px", block_radius="18px",
        button_large_radius="980px", input_background_fill="#f5f5f7", input_border_color="#e8e8ed",
    )

    with gr.Blocks(theme=theme, css=CUSTOM_CSS, analytics_enabled=False,
                   title="有声书工坊 · Audiobook Studio") as ui:
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
                progress_bar = gr.HTML(_progress_html(0, "等待开始", "", 0, 0), elem_classes="progress-bar-wrap")
                with gr.Group(visible=False, elem_classes="timer-hidden"):
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
                    gr.HTML('<button class="btn-ghost modal-trigger" onclick="var m=document.querySelector(\'#advanced_modal\');m.classList.add(\'show\');m.style.setProperty(\'background-color\',\'transparent\',\'important\');m.style.setProperty(\'--block-background-fill\',\'transparent\',\'important\');m.style.setProperty(\'--group-background-fill\',\'transparent\',\'important\');document.body.classList.add(\'modal-open\')" style="width:100%;padding:12px;border-radius:14px;font-size:1rem;cursor:pointer;">⚙\u00a0\u00a0高级设置</button>')

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
                                value="wav",
                                label="输出格式",
                                interactive=True
                            )
                            chatterbox_reference_audio = gr.File(
                                label="参考音频（可选）",
                                file_count="single",
                                file_types=["audio"],
                                info="上传音频文件用于语音克隆，留空使用默认声音"
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

                # —— 高级设置弹窗（纯客户端控制；默认 display:none，JS 切换 .show） ——
                with gr.Group(elem_classes="modal-overlay", elem_id="advanced_modal") as advanced_modal:
                    with gr.Column(elem_classes="modal-box"):
                        gr.HTML('<div class="modal-header"><p class="modal-title">高级设置</p><button class="modal-close-btn" onclick="document.querySelector(\'#advanced_modal\').classList.remove(\'show\');document.body.classList.remove(\'modal-open\')">✕</button></div>')
                        gr.HTML('<p class="modal-desc">生成开关、解析模式、文本替换等进阶选项。</p>')
                        gr.HTML('<p class="card-sub-title">生成选项</p>')
                        with gr.Group(elem_classes="toggle-grid"):
                            output_text = gr.Checkbox(label="同步导出章节纯文本", value=saved["output_text"], elem_classes="toggle")
                            preview = gr.Checkbox(label="预解析模式（不消耗额度）", value=saved["preview"], elem_classes="toggle")
                            remove_endnotes = gr.Checkbox(label="剔除书末尾注", value=saved["remove_endnotes"], elem_classes="toggle")
                            remove_reference_numbers = gr.Checkbox(label="清理数字文献引用", value=saved["remove_reference_numbers"], elem_classes="toggle")
                        with gr.Row():
                            worker_count = gr.Slider(minimum=1, maximum=8, step=1, label="并行线程数", value=1, info="多线程加速，依配置微调")
                            log_level = gr.Dropdown(["INFO", "DEBUG", "WARNING", "ERROR", "CRITICAL"], label="日志级别", value="INFO")
                        gr.HTML('<div class="section-divider"></div>')
                        gr.HTML('<p class="card-sub-title">解析设置</p>')
                        with gr.Row():
                            title_mode = gr.Dropdown(["auto", "tag_text", "first_few"], label="章节标题匹配模式", value="auto", interactive=True)
                            new_line_mode = gr.Dropdown(["single", "double", "none"], label="段落换行检测模式", value="double", interactive=True)
                        search_and_replace_file = gr.File(label="文本替换规则文件 (.txt，可选)", file_types=[".txt"], file_count="single", interactive=True, elem_classes="rules-file-upload")
                        gr.HTML('<button class="btn-primary modal-done" onclick="document.querySelector(\'#advanced_modal\').classList.remove(\'show\');document.body.classList.remove(\'modal-open\')" style="width:100%;margin-top:14px;padding:12px;border-radius:14px;font-size:1rem;cursor:pointer;">完成</button>')

                # —— CTA ——
                with gr.Row(elem_classes="row-cta"):
                    stop_btn = gr.Button("停止转换", elem_classes="btn-ghost")
                    start_btn = gr.Button("🚀 开始生成有声书", elem_classes="btn-primary pulse", variant="primary")

            # ════════════ 资源库页 ════════════
            with gr.Tab("资源库", id="tab_library"):
                gr.HTML('<div class="hero"><h1>资源库</h1><p>管理已生成的音频文件：批量下载、打包导出、一键清理。</p></div>')
                with gr.Row(elem_classes="row-stack"):
                    with gr.Column(scale=3):
                        with gr.Group(elem_classes="app-card"):
                            gr.HTML('<p class="card-title">选择导出批次</p>')
                            with gr.Row():
                                folder_dropdown = gr.Dropdown(choices=get_folders_list(), label="批次", show_label=False, interactive=True, scale=4)
                                refresh_btn = gr.Button("🔄 刷新", elem_classes="btn-mini", scale=1)
                                delete_folder_btn = gr.Button("🗑️ 删除批次", elem_classes="btn-danger", scale=1)
                        with gr.Group(elem_classes="app-card"):
                            gr.HTML('<p class="card-title">选择分卷文件（默认全选）</p>')
                            file_selector = gr.CheckboxGroup(choices=[], label="", show_label=False, interactive=True, elem_classes="file-checks")
                            with gr.Row():
                                select_all_btn = gr.Button("全选", elem_classes="btn-mini")
                                deselect_all_btn = gr.Button("取消", elem_classes="btn-mini")
                                delete_btn = gr.Button("🗑️ 删除选中", elem_classes="btn-danger")
                    with gr.Column(scale=2):
                        with gr.Group(elem_classes="app-card"):
                            gr.HTML('<p class="card-title">下载与清理</p>')
                            gr.HTML('<p class="card-desc">勾选「阅后即焚」将在打包后自动删除源文件。</p>')
                            auto_delete_cb = gr.Checkbox(label="阅后即焚（打包后删除源文件）", value=False, elem_classes="toggle")
                            generate_btn = gr.Button("⚡ 打包并生成下载通道", elem_classes="btn-primary")
                            download_card = gr.HTML(_placeholder_html())
                            real_download_file = gr.File(label="下载通道", interactive=False, visible=False, elem_classes="custom-download-zone")

            # ════════════ 日志页 ════════════
            with gr.Tab("日志", id="tab_logs"):
                gr.HTML('<div class="hero"><h1>运行日志</h1><p>实时查看转换进度与详细信息。</p></div>')
                with gr.Group(elem_classes="app-card"):
                    global webui_log_file
                    webui_log_file = generate_unique_log_path("EtA_WebUI")
                    webui_log_file.touch()
                    Log(str(webui_log_file.absolute()), dark=False, xterm_font_size=12)

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
        _PROVIDER_IDS = {"MiMo": "Mimo", "MiniMax": "MiniMax", "Edge": "Edge", "Qwen": "Qwen", "Chatterbox": "Chatterbox"}
        for _tab, _display in [(mimo_tab, "MiMo"), (minimax_tab, "MiniMax"),
                            (edge_tab, "Edge"), (qwen_tab, "Qwen"),
                            (chatterbox_tab, "Chatterbox")]:
            _id = _PROVIDER_IDS[_display]
            _js = f"() => {{ const el = document.getElementById('engine_badge_name'); if (el) el.textContent = '{_display}'; }}"
            _tab.select(fn=lambda n=_id: n,
                        inputs=None, outputs=provider_state, show_progress="hidden",
                        js=_js)

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
                    chatterbox_reference_audio, chatterbox_exaggeration, chatterbox_cfg_weight],
            outputs=progress_timer)
        stop_btn.click(fn=terminate_generator, inputs=None, outputs=progress_timer)

        # 进度条定时更新
        progress_timer.tick(fn=get_progress_info, inputs=None, outputs=[progress_bar, progress_timer], show_progress="hidden")

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
            )
        
        # 初始化配置（隐藏 API Key）
        ui.load(
            fn=init_api_configs,
            inputs=None,
            outputs=[mimo_api_key, mimo_api_key_display, mimo_base_url,
                    minimax_api_key, minimax_api_key_display,
                    qwen_api_key, qwen_api_key_display, qwen_base_url, qwen_model],
            show_progress="hidden"
        )

    temp_dir = os.path.join(get_output_dir(), ".temp_downloads")
    ui.launch(
        server_name=config.host,
        server_port=config.port,
        prevent_thread_lock=False,
        allowed_paths=[get_output_dir(), temp_dir],
    )
