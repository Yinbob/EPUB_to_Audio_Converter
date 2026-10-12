"""VoxCPM 的常用设置与按模式展开的高级设置。"""

from dataclasses import dataclass

import gradio as gr

from audiobook_generator.tts_providers.voxcpm_tts_provider import (
    DEFAULT_VOXCPM_MODEL,
    DEFAULT_VOXCPM_OUTPUT_FORMAT,
    DEFAULT_VOXCPM_SPEED,
    DEFAULT_VOXCPM_CFG_VALUE,
    DEFAULT_VOXCPM_INFERENCE_TIMESTEPS,
    DEFAULT_VOXCPM_CHUNK_CHARS,
    get_voxcpm_supported_devices,
    get_voxcpm_supported_output_formats,
    get_voxcpm_speed_range,
)
from audiobook_generator.utils.voxcpm_voices import (
    VOXCPM_DEFAULT_VOICE_VALUE,
    get_default_voxcpm_voice_dir,
    get_voxcpm_voice_choices,
)


@dataclass
class VoxCPMPanel:
    model: gr.Textbox
    mode: gr.Radio
    voice: gr.Dropdown
    voice_dir: gr.Textbox
    regenerate_voice: gr.Checkbox
    voice_description: gr.TextArea
    reference_audio: gr.File
    reference_text: gr.Textbox
    auto_transcribe: gr.Checkbox
    device: gr.Dropdown
    denoise: gr.Checkbox
    normalize: gr.Checkbox
    cfg_value: gr.Slider
    inference_timesteps: gr.Slider
    speed: gr.Slider
    chunk_chars: gr.Slider
    optimize: gr.Checkbox
    output_format: gr.Dropdown
    preview_btn: gr.Button
    preview_audio: gr.Audio


def update_voxcpm_mode(mode):
    """只切换可见性，保留用户填写的值，方便在模式间来回比较。"""
    return (
        gr.update(visible=mode in ("clone", "hifi")),
        gr.update(visible=mode == "hifi"),
        gr.update(visible=mode != "hifi"),
    )


def update_voxcpm_preview_availability(voice):
    return gr.update(interactive=str(voice or "").startswith("preset:"))


def build_voxcpm_panel() -> VoxCPMPanel:
    gr.HTML('<p class="card-desc">选好音色即可生成。复刻已有声音时，切换到声音克隆。</p>')
    mode = gr.Radio(
        [("预设与描述", "design"), ("声音克隆", "clone"), ("精细克隆", "hifi")],
        value="design", label="合成模式", interactive=True,
        elem_id="voxcpm_mode",
    )
    voice = gr.Dropdown(
        get_voxcpm_voice_choices(), value=VOXCPM_DEFAULT_VOICE_VALUE,
        label="音色", interactive=True, allow_custom_value=True,
        info="内置预设会自动缓存；上传参考音频时优先使用上传的声音。",
        elem_id="voxcpm_voice",
    )
    with gr.Row(elem_classes="voxcpm-audition"):
        preview_btn = gr.Button("🎧 试听预设", elem_classes="btn-ghost", scale=0)
        preview_audio = gr.Audio(label="试听", type="filepath", interactive=False,
                                 visible=False, elem_id="voxcpm_audition", scale=1)

    with gr.Column(visible=False, elem_id="voxcpm_reference_section") as reference_section:
        reference_audio = gr.File(
            label="参考音频", file_count="single", file_types=["audio"],
            elem_id="voxcpm_reference_audio",
        )
        gr.HTML('<p class="card-desc">上传一段清晰的人声；不上传时使用上方音色。参考音频默认开启降噪，可在更多设置中关闭。</p>')
        with gr.Column(visible=False, elem_id="voxcpm_transcript_section") as transcript_section:
            reference_text = gr.Textbox(
                label="参考音频原文", lines=2,
                placeholder="填写参考音频里实际说的话，尽量逐字一致。",
                info="手填优先。内置预设自带原文；上传的音频可开启自动转写。",
                interactive=True, elem_id="voxcpm_reference_text",
            )
            auto_transcribe = gr.Checkbox(
                label="自动转写参考音频", value=False, interactive=True, elem_classes="toggle",
                info="原文留空时用 SenseVoice 识别，首次使用需下载转写模型。",
                elem_id="voxcpm_auto_transcribe",
            )

    with gr.Accordion("声音风格（可选）", open=False,
                      elem_id="voxcpm_style_section") as style_section:
        voice_description = gr.TextArea(
            label="声音描述", lines=2,
            placeholder="例如：成熟稳重的男声，语气温和。",
            info="留空使用预设风格；声音克隆时可调整语气，精细克隆由参考音频决定。",
            interactive=True, elem_id="voxcpm_voice_description",
        )

    with gr.Row():
        speed_min, speed_max = get_voxcpm_speed_range()
        speed = gr.Slider(
            minimum=speed_min, maximum=speed_max, step=0.05,
            label="语速", value=DEFAULT_VOXCPM_SPEED, interactive=True,
            info="1.0 为标准语速", elem_id="voxcpm_speed",
        )
        output_format = gr.Dropdown(
            get_voxcpm_supported_output_formats(), value=DEFAULT_VOXCPM_OUTPUT_FORMAT,
            label="输出格式", interactive=True, elem_id="voxcpm_output_format",
        )

    with gr.Accordion("更多设置", open=False, elem_id="voxcpm_advanced"):
        with gr.Tabs(elem_classes="voxcpm-settings-tabs"):
            with gr.Tab("音频处理"):
                denoise = gr.Checkbox(
                    label="参考音频降噪", value=True, interactive=True, elem_classes="toggle",
                    info="默认开启。首次生成需下载 ZipEnhancer；降噪可能改变参考音色。",
                    elem_id="voxcpm_denoise",
                )
                normalize = gr.Checkbox(
                    label="文本规范化", value=True, interactive=True, elem_classes="toggle",
                    info="将数字、日期等转换为适合朗读的文本。",
                    elem_id="voxcpm_normalize",
                )
            with gr.Tab("生成质量"):
                with gr.Row():
                    cfg_value = gr.Slider(
                        minimum=0.5, maximum=8.0, step=0.1, label="音色贴合度（CFG）",
                        value=DEFAULT_VOXCPM_CFG_VALUE, interactive=True,
                        info="越高越贴合描述或参考声音，建议保持 2.0。",
                        elem_id="voxcpm_cfg_value",
                    )
                    inference_timesteps = gr.Slider(
                        minimum=1, maximum=50, step=1, label="推理步数",
                        value=DEFAULT_VOXCPM_INFERENCE_TIMESTEPS, interactive=True,
                        info="步数增加会更慢，建议先使用 10 步。",
                        elem_id="voxcpm_inference_timesteps",
                    )
                chunk_chars = gr.Slider(
                    minimum=50, maximum=1200, step=50, label="分块字数",
                    value=DEFAULT_VOXCPM_CHUNK_CHARS, interactive=True,
                    info="按句分块以保持长文稳定，默认 400 字。",
                    elem_id="voxcpm_chunk_chars",
                )
                optimize = gr.Checkbox(
                    label="推理加速（torch.compile）", value=True, interactive=True, elem_classes="toggle",
                    info="首次生成需要预热。出现 CUDA Graphs 错误时可关闭；章节并行保持 1。",
                    elem_id="voxcpm_optimize",
                )
            with gr.Tab("模型音色"):
                model = gr.Textbox(
                    value=DEFAULT_VOXCPM_MODEL, label="模型", interactive=True,
                    info="模型 ID 或服务器上的本地模型目录。", elem_id="voxcpm_model",
                )
                device = gr.Dropdown(
                    get_voxcpm_supported_devices(), value="auto", label="运行设备",
                    interactive=True, allow_custom_value=True,
                    info="auto 自动选择设备；多卡可填 cuda:0、cuda:1。",
                    elem_id="voxcpm_device",
                )
                voice_dir = gr.Textbox(
                    value=get_default_voxcpm_voice_dir(), label="音色库目录",
                    interactive=True, elem_id="voxcpm_voice_dir",
                )
                regenerate_voice = gr.Checkbox(
                    label="重新生成预设音色", value=False, interactive=True, elem_classes="toggle",
                    info="忽略已有试听缓存，下一次试听或生成时重建预设。",
                    elem_id="voxcpm_regenerate_voice",
                )

    mode.change(
        fn=update_voxcpm_mode, inputs=mode,
        outputs=[reference_section, transcript_section, style_section],
        show_progress="hidden", queue=False,
    )
    voice.change(
        fn=update_voxcpm_preview_availability, inputs=voice, outputs=preview_btn,
        show_progress="hidden", queue=False,
    )
    return VoxCPMPanel(
        model=model, mode=mode, voice=voice, voice_dir=voice_dir,
        regenerate_voice=regenerate_voice, voice_description=voice_description,
        reference_audio=reference_audio, reference_text=reference_text,
        auto_transcribe=auto_transcribe, device=device, denoise=denoise,
        normalize=normalize, cfg_value=cfg_value, inference_timesteps=inference_timesteps,
        speed=speed, chunk_chars=chunk_chars, optimize=optimize, output_format=output_format,
        preview_btn=preview_btn, preview_audio=preview_audio,
    )
