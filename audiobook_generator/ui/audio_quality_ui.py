"""音频检查面板：生成设置与报告复核分开呈现。"""
from typing import NamedTuple

import gradio as gr

from .audio_quality import local_quality_status


QUALITY_CSS = """
#quality_setup .card-title { margin-bottom: 4px; }
#quality_setup .quality-models { color: var(--apple-text-2); font-size: .8rem; }
#quality_setup .quality-models p { margin: 0 0 12px; }
#quality_setup .quality-tabs > .tab-nav { margin-bottom: 20px; }
#quality_setup .quality-options { gap: 16px; }
#quality_setup .quality-options > .toggle { flex: 1 1 240px !important; min-width: 0 !important; }
#quality_setup .quality-options .info { color: var(--apple-text-2); font-size: .8rem; line-height: 1.6; }
#quality_setup .quality-note { color: var(--apple-text-2); font-size: .8rem; line-height: 1.7; }
#quality_setup .quality-note p { margin: 4px 0; }
#quality_setup .quality-details { margin-top: 16px; }
#quality_setup .quality-report-toolbar { align-items: end; gap: 12px; }
#quality_setup .quality-report-toolbar button { margin-bottom: 1px; }
#quality_setup .quality-field { min-width: 0 !important; }
#quality_setup .quality-field input { border-radius: 12px !important; }
#quality_setup .quality-field:focus-within { outline-offset: 3px; }
#quality_setup .quality-field > label.float {
  display: flex !important; position: static !important; width: auto;
  padding: 8px 12px; background: transparent !important;
}
#quality_setup #quality_rows { max-width: 100%; min-width: 0; }
#quality_setup #quality_rows .table-wrap { overflow-x: auto; }
#quality_setup #quality_rows table { font-variant-numeric: tabular-nums; }
#quality_setup .quality-listen { gap: 20px; margin-top: 8px; }
@media (max-width: 640px) {
  #quality_setup .quality-options { flex-direction: column; gap: 12px; }
  #quality_setup .quality-options > .toggle { flex-basis: auto !important; }
  #quality_setup .quality-report-toolbar { flex-direction: column; align-items: stretch; }
  #quality_setup .quality-report-toolbar > * { width: 100%; flex-basis: auto !important; }
  #quality_setup .quality-listen { flex-direction: column; }
  #quality_setup .quality-uploads { flex-direction: column; }
  #quality_setup .quality-listen > * { min-width: 0 !important; }
}
"""


class QualityControls(NamedTuple):
    enabled: gr.Checkbox
    repair: gr.Checkbox
    settings_file: gr.File
    casting_file: gr.File
    refresh: gr.Button
    report_file: gr.Dropdown
    summary: gr.Markdown
    rows: gr.Dataframe
    download: gr.File
    scope: gr.Dropdown
    audio: gr.Audio


def build_audio_quality():
    with gr.Group(elem_classes="app-card", elem_id="quality_setup"):
        gr.HTML('<p class="card-title">音频检查与修复</p>')
        gr.Markdown(local_quality_status(), elem_classes="quality-models")
        with gr.Tabs(elem_classes="quality-tabs"):
            with gr.Tab("生成设置", id="quality-settings"):
                with gr.Row(elem_classes="quality-options"):
                    enabled = gr.Checkbox(label="检查生成的音频", value=True,
                        info="MiMo · 核对内容、拼接和角色声音", elem_classes="toggle", elem_id="audio_core_enabled")
                    repair = gr.Checkbox(label="自动修复问题片段", value=False,
                        info="按次数与时限执行，会增加合成请求", elem_classes="toggle", elem_id="audio_core_repair")
                with gr.Accordion("高级设置", open=False, elem_classes="quality-details"):
                    with gr.Row(elem_classes="quality-uploads"):
                        settings_file = gr.File(label="模型与资源设置（JSON）", file_types=[".json"], height=160, elem_classes="quality-field")
                        casting_file = gr.File(label="已核验的角色选角（JSON）", file_types=[".json"], height=160, elem_classes="quality-field")
                    gr.Markdown("可选上传。原音频与报告会保留；疑似异常、未完成检查会分别标记，未校准的声音差异不直接判错。",
                                elem_classes="quality-note")
            with gr.Tab("检查结果", id="quality-results"):
                with gr.Row(elem_classes="quality-report-toolbar"):
                    report_file = gr.Dropdown(label="选择检查报告", choices=[], interactive=True, scale=4,
                        elem_classes="quality-field", elem_id="quality_report_file")
                    refresh = gr.Button("刷新报告", size="sm", scale=1, min_width=110,
                        elem_classes="btn-ghost", elem_id="quality_refresh")
                summary = gr.Markdown("生成完成后可在这里查看报告，也可刷新读取输出目录。", elem_classes="quality-note", elem_id="quality_summary")
                rows = gr.Dataframe(headers=["位置", "检查项", "发现的问题", "判断", "时间（秒）"],
                    value=[], interactive=False, label="检查明细", max_height=280, wrap=True,
                    column_widths=[140, 100, 300, 120, 100], elem_id="quality_rows")
                with gr.Row(elem_classes="quality-listen"):
                    with gr.Column(scale=3, min_width=240):
                        scope = gr.Dropdown(label="选择片段或拼接处", choices=[], interactive=True, elem_classes="quality-field")
                        audio = gr.Audio(label="试听问题附近的音频", interactive=False)
                    with gr.Column(scale=2, min_width=200):
                        download = gr.File(label="完整检查报告", height=120, interactive=False, elem_classes="quality-field")
    return QualityControls(enabled, repair, settings_file, casting_file, refresh, report_file,
                           summary, rows, download, scope, audio)
