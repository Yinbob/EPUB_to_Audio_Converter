from multiprocessing import Process
from typing import Optional
from pathlib import Path
import os
import json
import urllib.parse
import zipfile
import tempfile
import shutil
from datetime import datetime

import gradio as gr
from gradio_log import Log

# ── WebUI 持久化设置 ──────────────────────────────────────────────
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
    """从磁盘读取已保存的设置，缺失项用默认值补全。"""
    merged = dict(_DEFAULT_SETTINGS)
    if os.path.exists(_SETTINGS_PATH):
        try:
            with open(_SETTINGS_PATH, "r", encoding="utf-8") as f:
                merged.update(json.load(f))
        except Exception:
            pass
    return merged


def _save_checkbox(key: str, value: bool):
    """将单个开关的最新状态写回磁盘。"""
    settings = _load_settings()
    settings[key] = value
    with open(_SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2, ensure_ascii=False)

from audiobook_generator.config.general_config import GeneralConfig
from audiobook_generator.tts_providers.edge_tts_provider import get_edge_tts_supported_voices, \
    get_edge_tts_supported_language, get_edge_tts_supported_output_formats
from audiobook_generator.tts_providers.openai_tts_provider import get_openai_supported_models, \
    get_openai_supported_voices, get_openai_instructions_example, get_openai_supported_output_formats
from audiobook_generator.tts_providers.piper_tts_provider import get_piper_supported_languages, \
    get_piper_supported_voices, get_piper_supported_qualities, get_piper_supported_speakers
from audiobook_generator.tts_providers.minimax_tts_provider import get_minimax_supported_models, \
    get_minimax_supported_output_formats, get_minimax_voice_choices, get_minimax_voice_id_from_choice
from audiobook_generator.tts_providers.chatterbox_tts_provider import get_chatterbox_supported_devices, \
    get_chatterbox_supported_output_formats, get_chatterbox_reference_audio_info, \
    get_chatterbox_supported_models, get_chatterbox_model_info
from audiobook_generator.utils.log_handler import generate_unique_log_path
from main import main

selected_tts = "Mimo"  # 默认选中优化后的 Mimo 标签页
running_process: Optional[Process] = None
webui_log_file = None


def on_tab_change(evt: gr.SelectData):
    print(f"{evt.value} tab selected")
    global selected_tts
    selected_tts = evt.value


def update_output_dir_from_file(file_objs):
    """根据上传的 EPUB 文件名自动生成输出目录（支持多文件）"""
    if not file_objs:
        return gr.update()
    # 兼容单文件（单个对象）和多文件（列表）两种情况
    if not isinstance(file_objs, list):
        file_objs = [file_objs]
    if len(file_objs) == 0:
        return gr.update()
    # 取第一个文件的书名作为输出目录
    first = file_objs[0]
    file_path = first.name if hasattr(first, "name") else first
    if not file_path:
        return gr.update()
    book_name = Path(file_path).stem  # 去掉 .epub 后缀
    safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in book_name)
    if len(file_objs) > 1:
        safe_name += f" 等{len(file_objs)}本书"
    output_path = os.path.join("audiobook_output", safe_name)
    return gr.update(value=output_path)


def get_edge_voices_by_language(language):
    voices_list = [voice for voice in get_edge_tts_supported_voices() if voice.startswith(language)]
    return gr.Dropdown(voices_list, value=voices_list[0], label="Voice", interactive=True, info="Select the voice")


def get_piper_supported_voices_gui(language):
    voices_list = get_piper_supported_voices(language)
    return gr.Dropdown(voices_list, value=voices_list[0], label="Voice", interactive=True, info="Select the voice")


def get_piper_supported_qualities_gui(language, voice):
    qualities_list = get_piper_supported_qualities(language, voice)
    return gr.Dropdown(qualities_list, value=qualities_list[0], label="Quality", interactive=True,
                       info="Select the quality")


def get_piper_supported_speakers_gui(language, voice, quality):
    speakers_list = get_piper_supported_speakers(language, voice, quality)
    return gr.Dropdown(speakers_list, value=speakers_list[0], label="Speaker", interactive=True,
                       info="Select the speaker")


def process_ui_form(input_file, output_dir, worker_count, log_level, output_text, preview,
                    search_and_replace_file, title_mode, new_line_mode, chapter_start, chapter_end, remove_endnotes,
                    remove_reference_numbers,
                    model, voices, speed, openai_output_format, instructions, enable_stream,
                    minimax_model, minimax_voice, minimax_output_format,
                    edge_language, edge_voice, edge_output_format, proxy, edge_voice_rate, edge_volume, edge_pitch,
                    edge_break_duration,
                    piper_executable_path, piper_docker_image, piper_language, piper_voice, piper_quality,
                    piper_speaker,
                    piper_noise_scale, piper_noise_w_scale, piper_length_scale, piper_sentence_silence,
                    chatterbox_model, chatterbox_device, chatterbox_output_format, chatterbox_reference_audio,
                    chatterbox_exaggeration, chatterbox_cfg_weight):

    # --- 兼容多文件：统一为列表 ---
    if not input_file:
        print("❌ 请先选择至少一个 EPUB 文件")
        return
    if not isinstance(input_file, list):
        input_file = [input_file]

    global selected_tts

    # --- 为每个文件生成独立的 config ---
    configs = []
    for idx, single_file in enumerate(input_file):
        config = GeneralConfig(None)
        file_path = single_file.name if hasattr(single_file, 'name') else single_file
        config.input_file = file_path

        # 多文件时，每个文件生成以书名为名的子文件夹
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
        config.search_and_replace_file = search_and_replace_file.name if hasattr(search_and_replace_file,
                                                                                 'name') else search_and_replace_file

        if "Mimo" in selected_tts or "OpenAI" in selected_tts:
            config.tts = "openai"
            config.output_format = openai_output_format
            config.voice_name = voices
            config.model_name = model
            config.instructions = instructions
            config.speed = speed
            config.stream = enable_stream
        elif selected_tts == "MiniMax":
            config.tts = "minimax"
            config.model_name = minimax_model
            config.voice_name = get_minimax_voice_id_from_choice(minimax_voice)
            config.output_format = minimax_output_format
        elif selected_tts == "Edge":
            config.tts = "edge"
            config.language = edge_language
            config.voice_name = edge_voice
            config.output_format = edge_output_format
            config.proxy = proxy
            config.voice_rate = f"{edge_voice_rate:+}%"
            config.voice_volume = f"{edge_volume:+}%"
            config.voice_pitch = f"{edge_pitch:+}Hz"
            config.break_duration = edge_break_duration
        elif selected_tts == "Piper":
            config.tts = "piper"
            config.piper_path = piper_executable_path
            config.piper_docker_image = piper_docker_image
            config.model_name = f"{piper_language}-{piper_voice}-{piper_quality}"
            config.piper_speaker = piper_speaker
            config.piper_noise_scale = piper_noise_scale
            config.piper_noise_w_scale = piper_noise_w_scale
            config.piper_length_scale = piper_length_scale
            config.piper_sentence_silence = piper_sentence_silence
        elif selected_tts == "Chatterbox":
            config.tts = "chatterbox"
            config.model_name = chatterbox_model
            config.output_format = chatterbox_output_format
            config.chatterbox_device = chatterbox_device
            config.chatterbox_reference_audio = chatterbox_reference_audio.name if hasattr(chatterbox_reference_audio, 'name') else chatterbox_reference_audio
            config.chatterbox_exaggeration = chatterbox_exaggeration
            config.chatterbox_cfg_weight = chatterbox_cfg_weight
        else:
            raise ValueError("Unsupported TTS provider selected")

        configs.append(config)

    launch_audiobook_generator_batch(configs)


def _batch_worker(config_list, log_file_path):
    """子进程中逐个处理每个 EPUB（必须在模块顶层，spawn 模式下才能被 pickle）"""
    total = len(config_list)
    for idx, cfg in enumerate(config_list):
        book_name = Path(cfg.input_file).stem
        print(f"\n{'='*60}")
        print(f"📚 [{idx + 1}/{total}] 开始转换: {book_name}")
        print(f"{'='*60}")
        try:
            main(cfg, log_file_path)
            print(f"✅ [{idx + 1}/{total}] 完成: {book_name}")
        except Exception as e:
            print(f"❌ [{idx + 1}/{total}] 失败: {book_name} — {e}")
    print(f"\n🎉 全部处理完毕！共 {total} 本书")


def launch_audiobook_generator_batch(configs):
    """批量启动有声书生成：逐个处理多个 EPUB 文件"""
    global running_process
    if running_process and running_process.is_alive():
        print("Audiobook generator already running")
        return

    running_process = Process(target=_batch_worker, args=(configs, str(webui_log_file.absolute())))
    running_process.start()


def terminate_audiobook_generator():
    global running_process
    if running_process and running_process.is_alive():
        running_process.terminate()
        running_process = None
        print("Audiobook generator terminated manually")


def get_output_dir():
    current_dir = os.path.abspath(os.path.dirname(__file__))
    project_root = os.path.abspath(os.path.join(current_dir, "../../"))
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


def get_empty_html(msg="请在左侧选择批次并勾选文件<br>支持多选，点击上方按钮打包"):
    return f'''
    <div style="padding: 30px; text-align: center; color: #64748b; background: #f8fafc; border-radius: 10px; border: 1px dashed #cbd5e1; display: flex; align-items: center; justify-content: center; flex-direction: column; min-height: 180px; margin-top: 10px;">
        <span style="font-size: 2.5em; margin-bottom: 15px;">👈</span>
        <span style="font-size: 1.1em; font-weight: 500; line-height: 1.5;">{msg}</span>
    </div>
    '''


# ==================== 彻底删除某个批次文件夹 ====================
def delete_entire_folder(folder_name):
    if not folder_name:
        return gr.update(), gr.update(choices=[], value=[]), gr.update(
            value=get_empty_html("未选择任何批次")), gr.update(visible=False)

    output_absolute_path = get_output_dir()
    folder_path = os.path.join(output_absolute_path, folder_name)

    if os.path.exists(folder_path) and os.path.isdir(folder_path):
        try:
            # 物理销毁整个文件夹及其所有内容
            shutil.rmtree(folder_path, ignore_errors=True)
        except Exception as e:
            print(f"删除文件夹失败: {e}")

    # 获取最新的文件夹列表，选中第一个
    new_folders = get_folders_list()
    new_val = new_folders[0] if new_folders else None
    new_files = get_files_in_folder(new_val) if new_val else []

    success_msg = f"批次 <b style='color:#ef4444;'>{folder_name}</b><br>已被整体删除"
    return gr.update(choices=new_folders, value=new_val), gr.update(choices=new_files, value=new_files), gr.update(
        value=get_empty_html(success_msg)), gr.update(value=None, visible=False)


# ==================== 智能删除文件及空壳 ====================
def delete_selected_files(folder_name, selected_files):
    if not folder_name or not selected_files or len(selected_files) == 0:
        return gr.update(), gr.update(), gr.update(value=get_empty_html("未选择任何文件，无需删除")), gr.update(
            visible=False)

    if isinstance(selected_files, str):
        selected_files = [selected_files]

    output_absolute_path = get_output_dir()
    folder_path = os.path.join(output_absolute_path, folder_name)

    # 1. 删除选中的文件
    deleted_count = 0
    for file_name in selected_files:
        abs_path = os.path.join(folder_path, file_name)
        if os.path.isfile(abs_path):
            try:
                os.remove(abs_path)
                deleted_count += 1
            except Exception as e:
                pass

    # 2. 核心：检查文件夹是否为空壳，如果是则销毁
    folder_deleted = False
    if os.path.exists(folder_path) and not os.listdir(folder_path):
        try:
            os.rmdir(folder_path)
            folder_deleted = True
        except:
            pass

    if folder_deleted:
        # 文件夹消失了，需要重置左侧的选择框
        new_folders = get_folders_list()
        new_val = new_folders[0] if new_folders else None
        new_files = get_files_in_folder(new_val) if new_val else []
        return gr.update(choices=new_folders, value=new_val), gr.update(choices=new_files, value=new_files), gr.update(
            value=get_empty_html("文件已清空，且系统已自动回收空文件夹")), gr.update(visible=False)
    else:
        # 文件夹还在，只刷新文件列表
        new_files = get_files_in_folder(folder_name)
        success_msg = f"已成功删除 {deleted_count} 个文件"
        return gr.update(), gr.update(choices=new_files, value=[]), gr.update(
            value=get_empty_html(success_msg)), gr.update(visible=False)


def generate_download_link(folder_name, selected_files, auto_delete):
    if not folder_name or not selected_files or len(selected_files) == 0:
        return gr.update(), gr.update(), gr.update(value=get_empty_html("请至少选择一个文件进行打包")), gr.update(
            visible=False)

    if isinstance(selected_files, str):
        selected_files = [selected_files]

    output_absolute_path = get_output_dir()
    folder_path = os.path.join(output_absolute_path, folder_name)

    def build_html_prompt(display_name, warning=""):
        return f'''
        <div style="padding: 20px 20px 10px 20px; background: #f0f9ff; border-radius: 10px; border: 1px solid #bae6fd; text-align: center; margin-top: 10px; margin-bottom: -5px;">
            <div style="font-size: 2.5em; margin-bottom: 5px;">✅</div>
            <h3 style="color: #0369a1; margin-bottom: 10px; margin-top: 0; font-size: 1.25em; font-weight: 700;">资源组装完毕</h3>
            <p style="color: #0c4a6e; font-size: 0.95em; word-break: break-all; margin-bottom: 10px;">
                {display_name}<br><b style="color: #0284c7; margin-top: 10px; display: inline-block;">👇 直接点击下方出现的文件名，即可开始下载</b>
            </p>
            {warning}
        </div>
        '''

    temp_dir = os.path.join(output_absolute_path, ".temp_downloads")
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
        display_name = f"已将选中的 <b style='font-size:1.1em;'>{len(selected_files)}</b> 个文件打包为 ZIP"

    warning_html = ""
    folder_update = gr.update()
    checkbox_update = gr.update()

    # 开启自动清理逻辑
    if auto_delete:
        for file_name in selected_files:
            abs_path = os.path.join(folder_path, file_name)
            if os.path.isfile(abs_path):
                try:
                    os.remove(abs_path)
                except:
                    pass

        # 同样检测文件夹是否为空
        folder_deleted = False
        if os.path.exists(folder_path) and not os.listdir(folder_path):
            try:
                os.rmdir(folder_path)
                folder_deleted = True
            except:
                pass

        if folder_deleted:
            new_folders = get_folders_list()
            new_val = new_folders[0] if new_folders else None
            new_files = get_files_in_folder(new_val) if new_val else []
            folder_update = gr.update(choices=new_folders, value=new_val)
            checkbox_update = gr.update(choices=new_files, value=new_files)
            warning_html = "<div style='color: #ef4444; font-size: 0.85em; font-weight: bold; background: #fee2e2; padding: 6px; border-radius: 6px; display: inline-block; margin-top: 5px;'>⚠️ 阅后即焚已触发：源文件及空文件夹已被删除，请务必保存下方副本！</div>"
        else:
            new_files = get_files_in_folder(folder_name)
            checkbox_update = gr.update(choices=new_files, value=[])
            warning_html = "<div style='color: #ef4444; font-size: 0.85em; font-weight: bold; background: #fee2e2; padding: 6px; border-radius: 6px; display: inline-block; margin-top: 5px;'>⚠️ 源文件已被自动删除，请务必及时保存下方通道中的副本！</div>"

    return folder_update, checkbox_update, gr.update(value=build_html_prompt(display_name, warning_html)), gr.update(
        value=serve_file_path, visible=True)


def host_ui(config):
    default_output_dir = os.path.join("audiobook_output", datetime.now().strftime("%Y-%m-%d_%H-%M-%S"))
    output_absolute_path = get_output_dir()
    saved = _load_settings()          # 读取持久化设置

    custom_css = """
    body { background-color: #fcfcfd; color: #111827; margin: 0; padding: 0; }
    .gradio-container { max-width: 100% !important; width: 100% !important; padding: 24px 32px !important; margin: 0 !important; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif !important; }
    .gr-box, .gr-panel, .gr-form { border-radius: 10px !important; border: 1px solid #f2f4f7 !important; background: #ffffff !important; box-shadow: 0 1px 2px 0 rgba(16, 24, 40, 0.05) !important; }
    input, textarea, select, .secondary { border-radius: 8px !important; background-color: #f9fafb !important; border: 1px solid #d0d5dd !important; color: #101828 !important; font-size: 0.95em !important; }
    input:focus, textarea:focus { border-color: #0ea5e9 !important; background-color: #ffffff !important; box-shadow: 0 0 0 4px #e0f2fe !important; }

    .tabs { border-bottom: 1px solid #eaecf0 !important; background: transparent !important; gap: 8px !important; }
    .tabitem { font-weight: 600 !important; color: #667085 !important; padding: 8px 14px !important; border: none !important; transition: all 0.15s ease; }
    .tabitem.selected { color: #0284c7 !important; background: #f0f9ff !important; border-radius: 6px !important; }

    .btn-primary-custom { background: linear-gradient(135deg, #38bdf8 0%, #0284c7 100%) !important; color: #ffffff !important; border: 1px solid #38bdf8 !important; border-radius: 8px !important; font-weight: 600 !important; transition: all 0.2s ease; cursor: pointer; box-shadow: 0 1px 2px 0 rgba(2, 132, 199, 0.08) !important; }
    .btn-primary-custom:hover { background: #0284c7 !important; transform: translateY(-0.5px); box-shadow: 0 4px 8px -2px rgba(2, 132, 199, 0.2) !important; }
    .btn-stop-custom { background-color: #ffffff !important; color: #344054 !important; border: 1px solid #d0d5dd !important; border-radius: 8px !important; transition: all 0.2s ease; font-weight: 600 !important; cursor: pointer; }
    .btn-stop-custom:hover { background-color: #fef3f2 !important; color: #b42318 !important; border-color: #fda29b !important; }

    .btn-refresh-custom { background: #ffffff !important; color: #475467 !important; border: 1px solid #d0d5dd !important; border-radius: 6px !important; font-size: 0.9em !important; font-weight: 600 !important; padding: 4px 12px !important; transition: all 0.15s ease; cursor: pointer; }
    .btn-refresh-custom:hover { background: #f9fafb !important; border-color: #98a2b3 !important; color: #1d2939 !important;}

    .btn-delete-custom { background: #fef2f2 !important; color: #dc2626 !important; border: 1px solid #fecaca !important; border-radius: 6px !important; font-size: 0.9em !important; font-weight: 600 !important; padding: 4px 12px !important; transition: all 0.15s ease; cursor: pointer; }
    .btn-delete-custom:hover { background: #fee2e2 !important; border-color: #f87171 !important; color: #b91c1c !important;}

    .file-selector-group { border: none !important; background: transparent !important; box-shadow: none !important; padding: 0 !important; margin-top: 10px !important; margin-bottom: 10px !important;}
    .file-selector-group label { background: #ffffff !important; border: 1px solid #e2e8f0 !important; border-radius: 8px !important; padding: 10px 14px !important; transition: all 0.2s ease !important; box-shadow: 0 1px 2px rgba(0,0,0,0.02) !important; cursor: pointer !important; }
    .file-selector-group label:hover { border-color: #7dd3fc !important; background: #f0f9ff !important; }
    .file-selector-group label:has(input:checked) { background: linear-gradient(135deg, #0ea5e9 0%, #0284c7 100%) !important; color: white !important; border-color: #0284c7 !important; box-shadow: 0 4px 8px -2px rgba(2, 132, 199, 0.4) !important; }

    .toggle-switch { background: #ffffff !important; border: 1px solid #e2e8f0 !important; border-radius: 8px !important; padding: 6px 14px !important; margin-bottom: 8px !important; box-shadow: 0 1px 2px rgba(0,0,0,0.02) !important;}
    .toggle-switch .checkbox { display: none !important; }
    .toggle-switch label { position: relative; display: flex !important; align-items: center !important; cursor: pointer !important; font-weight: 600 !important; color: #64748b !important; transition: all 0.3s ease; }
    .toggle-switch label::before { content: ''; display: block; width: 40px; height: 22px; background-color: #e2e8f0; border-radius: 22px; margin-right: 12px; transition: background-color 0.3s ease; flex-shrink: 0; box-shadow: inset 0 1px 2px rgba(0,0,0,0.06); }
    .toggle-switch label::after { content: ''; position: absolute; left: 3px; top: 50%; transform: translateY(-50%); width: 16px; height: 16px; background-color: #ffffff; border-radius: 50%; box-shadow: 0 1px 3px rgba(0,0,0,0.15); transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1); }
    .toggle-switch label:has(input:checked)::before { background: linear-gradient(135deg, #7dd3fc 0%, #38bdf8 100%) !important; }
    .toggle-switch label:has(input:checked)::after { transform: translate(18px, -50%); }
    .toggle-switch label:has(input:checked) { color: #0284c7 !important; }

    .custom-download-zone .file-preview-item, .custom-download-zone tbody tr { position: relative !important; cursor: pointer !important; transition: background-color 0.2s ease !important; }
    .custom-download-zone .file-preview-item:hover, .custom-download-zone tbody tr:hover { background-color: #f0f9ff !important; }
    .custom-download-zone .file-preview-item [download]::after, .custom-download-zone tbody tr td:last-child a::after, .custom-download-zone a.download::after { content: "" !important; position: absolute !important; top: 0 !important; left: 0 !important; right: 0 !important; bottom: 0 !important; z-index: 99 !important; }
    .custom-download-zone .file-name, .custom-download-zone tbody tr td:first-child { color: #0284c7 !important; font-weight: 600 !important; text-decoration: underline !important; text-decoration-color: #bae6fd !important; text-underline-offset: 4px !important; }

    h1 { font-weight: 700 !important; color: #101828 !important; font-size: 1.65em !important; letter-spacing: -0.02em !important; }
    h3 { font-size: 1.05em !important; color: #344054 !important; font-weight: 600 !important; margin-bottom: 8px !important; margin-top: 5px !important;}
    """

    theme = gr.themes.Soft(primary_hue="sky", secondary_hue="slate", neutral_hue="slate").set(
        body_background_fill="#fcfcfd", block_background_fill="#ffffff", block_border_width="1px", block_radius="10px",
        button_large_radius="8px"
    )

    with gr.Blocks(theme=theme, css=custom_css, analytics_enabled=False, title="Book to Audiobook Converter") as ui:
        with gr.Row():
            with gr.Column():
                gr.Markdown(
                    "# 🎧 Book to Audiobook Converter\n<p style='color: #475467; font-size: 1.05em; margin-top: -6px;'>EPUB/DOC/DOCX 音频生成工作台</p>")

        with gr.Row():
            with gr.Column(scale=3):
                gr.Markdown("### 📂 核心文件与输出设置")
                input_file = gr.File(label="选择待处理的书籍文件（支持 EPUB/DOC/DOCX，多选）", file_types=[".epub", ".doc", ".docx"], file_count="multiple",
                                     interactive=True)
                output_dir = gr.Textbox(label="输出目录设置", value=default_output_dir, interactive=True,
                                        info="多文件时每本书自动生成以书名为名的子文件夹")
                input_file.change(fn=update_output_dir_from_file, inputs=input_file, outputs=output_dir)

                with gr.Accordion("📂 自定义文本替换规则文件 (可选)", open=False):
                    search_and_replace_file = gr.File(label="选择替换规则文件 (.txt)", file_types=[".txt"],
                                                      file_count="single", interactive=True)

            with gr.Column(scale=2):
                gr.Markdown("### ⚙️ 运行线程与解析过滤")
                log_level = gr.Dropdown(["INFO", "DEBUG", "WARNING", "ERROR", "CRITICAL"], label="日志控制级别",
                                        value="INFO", interactive=True)
                worker_count = gr.Slider(minimum=1, maximum=8, step=1, label="并行线程数 (Worker Count)", value=1,
                                         info="多线程并行可加速处理，请依配置微调")

                with gr.Group():
                    output_text = gr.Checkbox(label="同步导出各章节纯文本 (.txt)", value=saved["output_text"],
                                              elem_classes="toggle-switch")
                    preview = gr.Checkbox(label="开启预解析模式 (不消耗生成额度)", value=saved["preview"],
                                          info="勾选此项仅拆分章节并预估成本，不实际合成音频",
                                          elem_classes="toggle-switch")
                    remove_endnotes = gr.Checkbox(label="自动剔除书末尾注 (Endnotes)", value=saved["remove_endnotes"],
                                                  elem_classes="toggle-switch")
                    remove_reference_numbers = gr.Checkbox(label="智能清理文本中的数字文献引用标签",
                                                            value=saved["remove_reference_numbers"],
                                                            elem_classes="toggle-switch")

        gr.Markdown("<br>")

        with gr.Accordion("🔍 章节匹配与换行解析微调", open=True):
            with gr.Row():
                title_mode = gr.Dropdown(["auto", "tag_text", "first_few"], label="章节标题匹配模式", value="auto",
                                         interactive=True)
                new_line_mode = gr.Dropdown(["single", "double", "none"], label="段落换行检测模式", value="double",
                                            interactive=True)
                chapter_start = gr.Slider(minimum=1, maximum=100, step=1, label="起始章节页码", value=1,
                                          interactive=True)
                chapter_end = gr.Slider(minimum=-1, maximum=100, step=1, label="结束章节页码", value=-1,
                                        info="输入 -1 代表自动处理至全书最后一章", interactive=True)

        gr.Markdown("<br>")
        gr.Markdown("### 🎙️ TTS 语音合成驱动配置")

        with gr.Tabs(selected="openai_tab_id"):
            with gr.Tab("Mimo", id="openai_tab_id") as open_ai_tab:
                gr.Markdown(
                    "<p style='color: #0284c7; font-size: 0.95em; margin-bottom: 12px; font-weight: 500;'>✨ 预设就绪：当前已默认选择自定义情绪控制模型 <code>mimo-v2.5-tts</code>。</p>")
                with gr.Row():
                    model = gr.Dropdown(get_openai_supported_models(), value="mimo-v2.5-tts", label="模型 (Model)",
                                        interactive=True, allow_custom_value=True)
                    voices = gr.Dropdown(get_openai_supported_voices(), label="音色风格 (Voice)", interactive=True,
                                         allow_custom_value=True)
                    speed = gr.Slider(minimum=0.25, maximum=4.0, step=0.1, label="生成语速 (Speed)", value=1.0,
                                      info="1.0 为正常自然语速")
                    openai_output_format = gr.Dropdown(get_openai_supported_output_formats(), label="音频输出格式",
                                                       interactive=True)
                with gr.Row():
                    enable_stream = gr.Checkbox(
                        label="启用流式调用模式 (Streaming)",
                        value=False,
                        info="使用 PCM16 流式传输，实时收集音频片段并合成为 WAV",
                        elem_classes="toggle-switch",
                    )
                show_voice_instructions = gr.Checkbox(
                    label="展开高级语音情绪/语气控制面板",
                    value=saved["show_voice_instructions"],
                    elem_classes="toggle-switch",
                )
                with gr.Row(visible=saved["show_voice_instructions"]) as voice_instructions_row:
                    instructions = gr.TextArea(label="高级语音情绪/语气控制指令 (Voice Instructions)", interactive=True,
                                               lines=3, value=get_openai_instructions_example())
                show_voice_instructions.change(
                    fn=lambda x: gr.update(visible=x),
                    inputs=show_voice_instructions,
                    outputs=voice_instructions_row,
                )
                open_ai_tab.select(on_tab_change, inputs=None, outputs=None)

            with gr.Tab("MiniMax", id="minimax_tab_id") as minimax_tab:
                gr.Markdown(
                    "<p style='color: #0284c7; font-size: 0.95em; margin-bottom: 12px; font-weight: 500;'>✨ 使用 MiniMax TTS API，请先设置环境变量 <code>MINIMAX_API_KEY</code>。</p>")
                with gr.Row(equal_height=True):
                    minimax_model = gr.Dropdown(get_minimax_supported_models(), value="speech-2.8-hd", label="模型 (Model)",
                                               interactive=True, allow_custom_value=True)
                    minimax_voice = gr.Dropdown(get_minimax_voice_choices(), value=get_minimax_voice_choices()[0],
                                               label="音色 (Voice)", interactive=True, allow_custom_value=True)
                    minimax_output_format = gr.Dropdown(get_minimax_supported_output_formats(), value="mp3",
                                                        label="输出格式 (Output Format)", interactive=True)
                minimax_tab.select(on_tab_change, inputs=None, outputs=None)

            with gr.Tab("Edge", id="edge_tab_id") as edge_tab:
                with gr.Row(equal_height=True):
                    edge_language = gr.Dropdown(get_edge_tts_supported_language(), value="en-US", label="Language",
                                                interactive=True)
                    edge_voice = get_edge_voices_by_language(edge_language.value)
                    edge_output_format = gr.Dropdown(get_edge_tts_supported_output_formats(), label="Output Format",
                                                     interactive=True)
                    proxy = gr.Textbox(label="Proxy", value="", interactive=True)
                    edge_voice_rate = gr.Slider(minimum=-50, maximum=100, step=1, label="Voice Rate", value=0)
                    edge_volume = gr.Slider(minimum=-100, maximum=100, step=1, label="Voice Volume", value=0)
                    edge_pitch = gr.Slider(minimum=-100, maximum=100, step=1, label="Voice Pitch", value=0)
                    edge_break_duration = gr.Slider(minimum=0, maximum=5000, step=1, label="Break Duration", value=1250)
                    edge_language.change(fn=get_edge_voices_by_language, inputs=edge_language, outputs=edge_voice)
                edge_tab.select(on_tab_change, inputs=None, outputs=None)

            with gr.Tab("Piper", id="piper_tab_id") as piper_tab:
                piper_tab.select(on_tab_change, inputs=None, outputs=None)
                with gr.Row(equal_height=True):
                    with gr.Column():
                        piper_deployment = gr.Dropdown(["Docker", "Local"], label="Select Piper Deployment",
                                                       interactive=True)
                        local_group = gr.Group(visible=False)
                        with local_group:
                            piper_executable_path = gr.Textbox(label="Piper executable path", interactive=True)
                            piper_file_upload = gr.File(label="Upload Piper executable", file_count="single",
                                                        interactive=True)
                            piper_file_upload.change(fn=lambda x: x.name if x else "", inputs=piper_file_upload,
                                                     outputs=piper_executable_path)
                        docker_group = gr.Row(visible=True, equal_height=True)
                        with docker_group:
                            piper_docker_image = gr.Textbox(label="Piper Docker Image",
                                                            value="lscr.io/linuxserver/piper:latest", interactive=True)
                    piper_deployment.change(
                        fn=lambda x: (gr.update(visible=x == "Local"), gr.update(visible=x == "Docker")),
                        inputs=piper_deployment, outputs=[local_group, docker_group])
                    with gr.Column():
                        with gr.Row(equal_height=True):
                            piper_language = gr.Dropdown(get_piper_supported_languages(), label="Language",
                                                         value="en_US", interactive=True)
                            piper_voice = gr.Dropdown(get_piper_supported_voices(piper_language.value), label="Voice",
                                                      interactive=True)
                        with gr.Row(equal_height=True):
                            piper_quality = gr.Dropdown(
                                get_piper_supported_qualities(piper_language.value, piper_voice.value), label="Quality",
                                interactive=True)
                            piper_speaker = gr.Dropdown(
                                get_piper_supported_speakers(piper_language.value, piper_voice.value,
                                                             piper_quality.value), label="Speaker", interactive=True)
                    piper_language.change(fn=get_piper_supported_voices_gui, inputs=piper_language, outputs=piper_voice)
                    piper_voice.change(fn=get_piper_supported_qualities_gui, inputs=[piper_language, piper_voice],
                                       outputs=piper_quality)
                    piper_quality.change(fn=get_piper_supported_speakers_gui,
                                         inputs=[piper_language, piper_voice, piper_quality], outputs=piper_speaker)
                    with gr.Column():
                        with gr.Row(equal_height=True):
                            piper_noise_scale = gr.Slider(minimum=0.0, maximum=2.0, step=0.01,
                                                          label="Audio Noise Scale", value=0.667)
                            piper_noise_w_scale = gr.Slider(minimum=0.0, maximum=2.0, step=0.1,
                                                            label="Width Noise Scale", value=0.8)
                        with gr.Row(equal_height=True):
                            piper_length_scale = gr.Slider(minimum=0.0, maximum=5.0, step=0.1,
                                                           label="Audio Length Scale", value=1.0)
                            piper_sentence_silence = gr.Slider(minimum=0.0, maximum=2.0, step=0.1,
                                                               label="Sentence Silence", value=0.2)

            with gr.Tab("Chatterbox", id="chatterbox_tab_id") as chatterbox_tab:
                gr.Markdown(
                    "<p style='color: #0284c7; font-size: 0.95em; margin-bottom: 12px; font-weight: 500;'>🎯 轻量级本地 TTS 模型，支持语音克隆，完全离线运行。首次使用需安装 <code>pip install chatterbox-tts</code>。</p>")
                with gr.Row(equal_height=True):
                    chatterbox_model = gr.Dropdown(
                        get_chatterbox_supported_models(),
                        value="chatterbox-multilingual-v3",
                        label="模型版本 (Model)",
                        interactive=True,
                        info="multilingual-v3 支持中文，v0.5 仅支持英文"
                    )
                    chatterbox_device = gr.Dropdown(
                        get_chatterbox_supported_devices(),
                        value="auto" if "auto" in get_chatterbox_supported_devices() else get_chatterbox_supported_devices()[0],
                        label="运行设备 (Device)",
                        interactive=True,
                        info="auto 会自动选择最佳设备 (CUDA/MPS/CPU)"
                    )
                    chatterbox_output_format = gr.Dropdown(
                        get_chatterbox_supported_output_formats(),
                        value="wav",
                        label="输出格式 (Output Format)",
                        interactive=True
                    )
                with gr.Row():
                    chatterbox_reference_audio = gr.File(
                        label="参考音频 (Reference Audio) - 可选",
                        file_count="single",
                        file_types=["audio"],
                        info="上传音频文件用于语音克隆，留空使用默认声音"
                    )
                with gr.Row(equal_height=True):
                    chatterbox_exaggeration = gr.Slider(
                        minimum=0.0, maximum=1.0, step=0.05,
                        label="表现力 (Exaggeration)",
                        value=0.5,
                        info="控制语音的情感表现力，0=平淡, 1=夸张"
                    )
                    chatterbox_cfg_weight = gr.Slider(
                        minimum=0.0, maximum=1.0, step=0.05,
                        label="稳定性 (CFG Weight)",
                        value=0.5,
                        info="控制生成的稳定性，越高越稳定但可能略显单调"
                    )
                chatterbox_tab.select(on_tab_change, inputs=None, outputs=None)

        gr.Markdown("<br>")

        with gr.Row():
            with gr.Column(scale=1):
                gr.Button("🛑 停止转换", elem_classes="btn-stop-custom").click(fn=terminate_audiobook_generator,
                                                                              inputs=None, outputs=None)
            with gr.Column(scale=3):
                gr.Button("🚀 开始生成有声书", variant="primary", elem_classes="btn-primary-custom").click(
                    fn=process_ui_form,
                    inputs=[
                        input_file, output_dir, worker_count, log_level, output_text, preview,
                        search_and_replace_file, title_mode, new_line_mode, chapter_start, chapter_end, remove_endnotes,
                        remove_reference_numbers,
                        model, voices, speed, openai_output_format, instructions, enable_stream,
                        minimax_model, minimax_voice, minimax_output_format,
                        edge_language, edge_voice, edge_output_format, proxy, edge_voice_rate, edge_volume, edge_pitch,
                        edge_break_duration,
                        piper_executable_path, piper_docker_image, piper_language, piper_voice, piper_quality,
                        piper_speaker,
                        piper_noise_scale, piper_noise_w_scale, piper_length_scale, piper_sentence_silence,
                        chatterbox_model, chatterbox_device, chatterbox_output_format, chatterbox_reference_audio,
                        chatterbox_exaggeration, chatterbox_cfg_weight
                    ],
                    outputs=None)

        gr.Markdown("<br>")
        with gr.Row():
            with gr.Column(scale=3):
                with gr.Row():
                    gr.Markdown("### 📁 1. 选择要导出的批次")
                    refresh_btn = gr.Button("🔄 刷新", elem_classes="btn-refresh-custom", min_width=60)
                    delete_folder_btn = gr.Button("🗑️ 删除文件夹", elem_classes="btn-delete-custom", min_width=80)

                folder_dropdown = gr.Dropdown(choices=get_folders_list(), label="", show_label=False, interactive=True)

                gr.Markdown("### 📝 2. 点选下方分卷 (默认全选)")
                file_selector = gr.CheckboxGroup(
                    choices=[],
                    label="",
                    show_label=False,
                    interactive=True,
                    elem_classes="file-selector-group"
                )

                with gr.Row():
                    select_all_btn = gr.Button("全选", size="sm", min_width=60)
                    deselect_all_btn = gr.Button("取消", size="sm", min_width=60)
                    delete_btn = gr.Button("🗑️ 删除选中文件", size="sm", elem_classes="btn-delete-custom")

            with gr.Column(scale=2):
                gr.Markdown("### ⚙️ 3. 下载与清理配置")

                with gr.Group():
                    auto_delete_cb = gr.Checkbox(label="自动删除 (打包后物理删除源文件)", value=False,
                                                 elem_classes="toggle-switch")
                    generate_btn = gr.Button("⚡ 确认打包并生成下载通道", elem_classes="btn-primary-custom")

                download_card = gr.HTML(get_empty_html())
                real_download_file = gr.File(label="📦 下载通道", interactive=False, visible=False,
                                             elem_classes="custom-download-zone")

        # --- 事件绑定区域 ---

        # 0. 删除整个批次（新功能）
        delete_folder_btn.click(
            fn=delete_entire_folder,
            inputs=folder_dropdown,
            outputs=[folder_dropdown, file_selector, download_card, real_download_file]
        )

        # 1. 刷新批次
        refresh_btn.click(
            fn=lambda: (gr.update(choices=get_folders_list(), value=None), gr.update(choices=[], value=[])),
            inputs=None,
            outputs=[folder_dropdown, file_selector]
        )

        # 2. 文件夹联动自动展开全选
        folder_dropdown.change(
            fn=lambda f: gr.update(choices=get_files_in_folder(f), value=get_files_in_folder(f)),
            inputs=folder_dropdown,
            outputs=file_selector
        )

        # 3. 辅助按键
        select_all_btn.click(
            fn=lambda f: gr.update(value=get_files_in_folder(f)),
            inputs=folder_dropdown,
            outputs=file_selector
        )
        deselect_all_btn.click(
            fn=lambda: gr.update(value=[]),
            inputs=None,
            outputs=file_selector
        )

        # 4. 手动删除选定文件（带空文件夹检测清理）
        delete_btn.click(
            fn=delete_selected_files,
            inputs=[folder_dropdown, file_selector],
            outputs=[folder_dropdown, file_selector, download_card, real_download_file]
        )

        # 5. 打包生成下载通道（带自动清理源文件及空文件夹检测）
        generate_btn.click(
            fn=generate_download_link,
            inputs=[folder_dropdown, file_selector, auto_delete_cb],
            outputs=[folder_dropdown, file_selector, download_card, real_download_file]
        )

        # ── 持久化开关状态：每次变动立即写入磁盘 ──
        output_text.change(fn=lambda v: _save_checkbox("output_text", v), inputs=output_text, outputs=None)
        preview.change(fn=lambda v: _save_checkbox("preview", v), inputs=preview, outputs=None)
        remove_endnotes.change(fn=lambda v: _save_checkbox("remove_endnotes", v), inputs=remove_endnotes, outputs=None)
        remove_reference_numbers.change(fn=lambda v: _save_checkbox("remove_reference_numbers", v),
                                        inputs=remove_reference_numbers, outputs=None)
        show_voice_instructions.change(fn=lambda v: _save_checkbox("show_voice_instructions", v),
                                       inputs=show_voice_instructions, outputs=None)

        with gr.Row():
            global webui_log_file
            webui_log_file = generate_unique_log_path("EtA_WebUI")
            webui_log_file.touch()
            Log(str(webui_log_file.absolute()), dark=False, xterm_font_size=12)

    temp_dir = os.path.join(output_absolute_path, ".temp_downloads")

    ui.launch(
        server_name=config.host,
        server_port=config.port,
        prevent_thread_lock=False,
        allowed_paths=[output_absolute_path, temp_dir]
    )