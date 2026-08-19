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
from audiobook_generator.tts_providers.piper_tts_provider import (
    get_piper_supported_languages,
    get_piper_supported_voices,
    get_piper_supported_qualities,
    get_piper_supported_speakers,
)
from audiobook_generator.tts_providers.minimax_tts_provider import (
    get_minimax_supported_models,
    get_minimax_supported_output_formats,
    get_minimax_voice_choices,
    get_minimax_voice_id_from_choice,
)
from audiobook_generator.utils.log_handler import generate_unique_log_path
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


# ── 运行态 ────────────────────────────────────────────────────────
running_process: Optional[Process] = None
webui_log_file = None

_PROVIDER_LABEL = {
    "Mimo": "MiMo 情绪语音",
    "MiniMax": "MiniMax 高清语音",
    "Edge": "Edge 在线语音",
    "Piper": "Piper 离线语音",
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


def get_piper_voices_gui(language):
    voices_list = get_piper_supported_voices(language)
    return gr.Dropdown(voices_list, value=voices_list[0] if voices_list else None,
                       label="音色 Voice", interactive=True)


def get_piper_qualities_gui(language, voice):
    q = get_piper_supported_qualities(language, voice)
    return gr.Dropdown(q, value=q[0] if q else None, label="质量 Quality", interactive=True)


def get_piper_speakers_gui(language, voice, quality):
    s = get_piper_supported_speakers(language, voice, quality)
    return gr.Dropdown(s, value=s[0] if s else None, label="说话人 Speaker", interactive=True)


# ── 转换核心 ──────────────────────────────────────────────────────
def process_form(provider,
                 input_file, output_dir, worker_count, log_level, output_text, preview,
                 search_and_replace_file, title_mode, new_line_mode, chapter_start, chapter_end,
                 remove_endnotes, remove_reference_numbers,
                 model, voices, speed, openai_output_format, instructions, enable_stream,
                 minimax_model, minimax_voice, minimax_output_format,
                 edge_language, edge_voice, edge_output_format, proxy, edge_voice_rate,
                 edge_volume, edge_pitch, edge_break_duration,
                 piper_executable_path, piper_docker_image, piper_language, piper_voice,
                 piper_quality, piper_speaker, piper_noise_scale, piper_noise_w_scale,
                 piper_length_scale, piper_sentence_silence):
    if not input_file:
        print("❌ 请先选择至少一个书籍文件")
        return
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
        elif provider == "Piper":
            config.tts = "piper"
            config.piper_path = piper_executable_path
            config.piper_docker_image = piper_docker_image
            config.model_name = f"{piper_language}-{piper_voice}-{piper_quality}"
            config.piper_speaker = piper_speaker
            config.piper_noise_scale = piper_noise_scale
            config.piper_noise_w_scale = piper_noise_w_scale
            config.piper_length_scale = piper_length_scale
            config.piper_sentence_silence = piper_sentence_silence
        else:
            raise ValueError("Unsupported TTS provider selected")

        configs.append(config)

    launch_batch(configs)


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


def terminate_generator():
    global running_process
    if running_process and running_process.is_alive():
        running_process.terminate()
        running_process = None
        print("Audiobook generator terminated manually")


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
body, .gradio-container {
  background: var(--apple-bg) !important;
  color: var(--apple-text) !important;
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text",
               "Helvetica Neue", "PingFang SC", "Microsoft YaHei", sans-serif !important;
  -webkit-font-smoothing: antialiased;
}
.gradio-container { max-width: 1080px !important; margin: 0 auto !important;
  padding: 0 clamp(14px, 4vw, 32px) 64px !important; width: 100% !important; }

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
.app-card:hover { box-shadow: 0 1px 2px rgba(0,0,0,0.04), 0 16px 40px rgba(0,0,0,0.07) !important; }
@keyframes fadeUp { from { opacity: 0; transform: translateY(16px); } to { opacity: 1; transform: none; } }

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
  background-size: 200% auto; -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent; margin: 0 0 10px !important;
  animation: shimmer 6s ease-in-out infinite;
}
@keyframes shimmer { 0%,100% { background-position: 0% center; } 50% { background-position: 100% center; } }
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

/* ── 引擎分段选择器（原生 Tabs） ── */
.engine-tabs { gap: 0 !important; }
.engine-tabs > .tab-nav {
  display: grid !important; grid-template-columns: repeat(4, 1fr) !important;
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

.engine-badge {
  display: inline-flex; align-items: center; gap: 8px; padding: 8px 16px;
  background: linear-gradient(135deg, #e8f1fd 0%, #f0eefe 100%);
  border: 1px solid #cfe3fc; border-radius: 980px; margin-bottom: 14px;
  animation: fadeUp 0.4s ease both;
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
.toggle .checkbox { display: none !important; }
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

/* 大屏：限制内容列宽，避免超宽屏拉伸 */
@media (min-width: 1200px) {
  .gradio-container { max-width: 1120px !important; }
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
                    <p>上传书籍，选择语音引擎，一键生成属于你的有声书。多引擎、多格式、批量处理，尽在掌控。</p>
                </div>''')

                # —— Step 1 文件 + 章节范围 ——
                with gr.Group(elem_classes="app-card"):
                    gr.HTML('<p class="card-title"><span class="card-num">1</span>上传书籍文件</p>')
                    gr.HTML('<p class="card-desc">支持 EPUB / DOC / DOCX，可多选。输出目录将根据书名自动生成。</p>')
                    input_file = gr.File(label="书籍文件", file_types=[".epub", ".doc", ".docx"],
                                         file_count="multiple", interactive=True)
                    output_dir = gr.Textbox(label="输出目录", value=default_output_dir, interactive=True,
                                            info="多文件时每本书自动生成以书名为名的子文件夹")
                    input_file.change(fn=update_output_dir_from_file, inputs=input_file, outputs=output_dir, show_progress="hidden")
                    gr.HTML('<div class="section-divider"></div>')
                    gr.HTML('<p class="card-sub-title">章节范围</p>')
                    with gr.Row():
                        chapter_start = gr.Slider(minimum=1, maximum=100, step=1, label="起始章节页码", value=1, interactive=True)
                        chapter_end = gr.Slider(minimum=-1, maximum=100, step=1, label="结束章节页码", value=-1, info="-1 代表处理至最后一章", interactive=True)

                # —— Step 2 引擎 ——
                with gr.Group(elem_classes="app-card"):
                    gr.HTML('<p class="card-title"><span class="card-num">2</span>选择语音引擎</p>')
                    gr.HTML('<p class="card-desc">点击下方标签切换引擎，所选引擎的参数随即显示。</p>')
                    engine_badge = gr.HTML(_badge_html("Mimo"))
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
                        # ── Piper ──
                        with gr.Tab("💻 Piper", id="Piper") as piper_tab:
                            piper_deployment = gr.Dropdown(["Docker", "Local"], label="部署方式", value="Docker", interactive=True)
                            with gr.Group(visible=True) as docker_group:
                                piper_docker_image = gr.Textbox(label="Piper Docker 镜像", value="lscr.io/linuxserver/piper:latest", interactive=True)
                            with gr.Group(visible=False) as local_group:
                                piper_executable_path = gr.Textbox(label="Piper 可执行文件路径", interactive=True)
                                piper_file_upload = gr.File(label="上传 Piper 可执行文件", file_count="single", interactive=True)
                                piper_file_upload.change(fn=lambda x: x.name if x else "", inputs=piper_file_upload, outputs=piper_executable_path, show_progress="hidden")
                            piper_deployment.change(
                                fn=lambda x: (gr.update(visible=x == "Local"), gr.update(visible=x == "Docker")),
                                inputs=piper_deployment, outputs=[local_group, docker_group], show_progress="hidden")
                            with gr.Row():
                                piper_language = gr.Dropdown(get_piper_supported_languages(), label="语言", value="en_US", interactive=True)
                                piper_voice = gr.Dropdown(get_piper_supported_voices("en_US"), label="音色", interactive=True)
                            with gr.Row():
                                piper_quality = gr.Dropdown(get_piper_supported_qualities("en_US", get_piper_supported_voices("en_US")[0]), label="质量", interactive=True)
                                piper_speaker = gr.Dropdown(get_piper_supported_speakers("en_US", get_piper_supported_voices("en_US")[0], get_piper_supported_qualities("en_US", get_piper_supported_voices("en_US")[0])[0]), label="说话人", interactive=True)
                            piper_language.change(fn=get_piper_voices_gui, inputs=piper_language, outputs=piper_voice, show_progress="hidden")
                            piper_voice.change(fn=get_piper_qualities_gui, inputs=[piper_language, piper_voice], outputs=piper_quality, show_progress="hidden")
                            piper_quality.change(fn=get_piper_speakers_gui, inputs=[piper_language, piper_voice, piper_quality], outputs=piper_speaker, show_progress="hidden")
                            with gr.Row():
                                piper_noise_scale = gr.Slider(minimum=0.0, maximum=2.0, step=0.01, label="噪声尺度", value=0.667)
                                piper_noise_w_scale = gr.Slider(minimum=0.0, maximum=2.0, step=0.1, label="宽度噪声", value=0.8)
                            with gr.Row():
                                piper_length_scale = gr.Slider(minimum=0.0, maximum=5.0, step=0.1, label="语速长度", value=1.0)
                                piper_sentence_silence = gr.Slider(minimum=0.0, maximum=2.0, step=0.1, label="句间静音", value=0.2)

                # —— Step 3 高级（生成选项 + 解析设置，手风琴展开） ——
                with gr.Group(elem_classes="app-card"):
                    gr.HTML('<p class="card-title"><span class="card-num">3</span>高级设置</p>')
                    gr.HTML('<p class="card-desc">生成开关、解析模式、文本替换等进阶选项，点击展开。</p>')
                    with gr.Accordion("展开高级设置", open=False):
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
                        search_and_replace_file = gr.File(label="文本替换规则文件 (.txt，可选)", file_types=[".txt"], file_count="single", interactive=True)

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

        # ════════════ 事件绑定 ════════════
        # 引擎标签切换 → 同步当前引擎状态 + 徽标（标签内容切换为原生客户端行为，即时显示）
        for _tab, _name in [(mimo_tab, "Mimo"), (minimax_tab, "MiniMax"),
                            (edge_tab, "Edge"), (piper_tab, "Piper")]:
            _tab.select(fn=lambda n=_name: (n, _badge_html(n)),
                        inputs=None, outputs=[provider_state, engine_badge], show_progress="hidden")

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
                    piper_executable_path, piper_docker_image, piper_language, piper_voice,
                    piper_quality, piper_speaker, piper_noise_scale, piper_noise_w_scale,
                    piper_length_scale, piper_sentence_silence],
            outputs=None)
        stop_btn.click(fn=terminate_generator, inputs=None, outputs=None)

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

    temp_dir = os.path.join(get_output_dir(), ".temp_downloads")
    ui.launch(
        server_name=config.host,
        server_port=config.port,
        prevent_thread_lock=False,
        allowed_paths=[get_output_dir(), temp_dir],
    )
