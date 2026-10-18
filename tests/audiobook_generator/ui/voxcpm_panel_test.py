"""真实 Gradio 组件配置、模式切换及提交参数的回归检查，不加载模型。"""
import ast
import inspect
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import gradio as gr

from audiobook_generator.config.general_config import GeneralConfig
from audiobook_generator.ui.voxcpm_panel import (
    build_voxcpm_panel, update_voxcpm_mode, update_voxcpm_preview_availability,
)

ROOT = Path(__file__).resolve().parents[3]


class VoxCPMPanelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch("audiobook_generator.ui.voxcpm_panel.get_voxcpm_supported_devices",
                   return_value=["auto", "cpu", "cuda"]):
            with gr.Blocks() as cls.demo:
                cls.panel = build_voxcpm_panel()
        cls.config = cls.demo.get_config_file()
        cls.components = {c["props"].get("elem_id"): c for c in cls.config["components"]}

    def test_default_page_keeps_advanced_and_clone_controls_closed(self):
        for key in ("voxcpm_advanced", "voxcpm_style_section"):
            self.assertFalse(self.components[key]["props"]["open"])
        for key in ("voxcpm_reference_section", "voxcpm_transcript_section"):
            self.assertFalse(self.components[key]["props"]["visible"])
        self.assertEqual(self.panel.mode.value, "design")
        self.assertTrue(self.panel.denoise.value)
        self.assertTrue(self.panel.normalize.value)
        self.assertEqual(self.panel.output_format.value, "mp3")
        self.assertFalse(self.panel.preview_audio.visible)

    def test_advanced_settings_have_three_named_sections(self):
        labels = [c["props"].get("label") for c in self.config["components"] if c["type"] == "tabitem"]
        self.assertEqual(labels, ["音频处理", "生成质量", "模型音色"])

    def test_all_generation_parameters_remain_components(self):
        fields = ("model", "mode", "voice", "voice_dir", "voice_description",
                  "regenerate_voice", "reference_audio", "reference_text", "auto_transcribe",
                  "device", "denoise", "normalize", "cfg_value", "inference_timesteps",
                  "speed", "chunk_chars", "optimize", "output_format")
        ids = {c["id"] for c in self.config["components"]}
        for name in fields:
            self.assertIn(getattr(self.panel, name)._id, ids)

    def test_mode_switch_is_wired_and_keeps_input_values(self):
        deps = [d for d in self.config["dependencies"] if d["api_name"] == "update_voxcpm_mode"]
        self.assertEqual(deps[0]["inputs"], [self.panel.mode._id])
        self.assertEqual(deps[0]["outputs"], [self.components[key]["id"] for key in (
            "voxcpm_reference_section", "voxcpm_transcript_section", "voxcpm_style_section")])
        for mode, expected in (("design", (False, False, True)),
                               ("clone", (True, False, True)), ("hifi", (True, True, False))):
            changes = update_voxcpm_mode(mode)
            self.assertEqual(tuple(change["visible"] for change in changes), expected)
            self.assertTrue(all("value" not in change for change in changes))

    def test_preview_is_only_enabled_for_presets(self):
        self.assertTrue(update_voxcpm_preview_availability("preset:温柔女声")["interactive"])
        self.assertFalse(update_voxcpm_preview_availability("file:voice.wav")["interactive"])

    def test_successful_preview_reveals_audio_player(self):
        tree = ast.parse((ROOT / "audiobook_generator/ui/web_ui.py").read_text())
        callback = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                        and n.name == "voxcpm_preview_voice")
        ns = {"gr": gr, "_voxcpm_preview_busy": False, "running_process": None,
              "resolve_voxcpm_voice": lambda *args: {"kind": "preset"},
              "preview_voxcpm_preset_audio": lambda **kwargs: "audition.wav", "logger": MagicMock()}
        exec(compile(ast.Module(body=[callback], type_ignores=[]), "web_ui.py", "exec"), ns)
        update = ns["voxcpm_preview_voice"]("preset:沉稳男声", "openbmb/VoxCPM2", "cuda", "voices", 2, 10, False)
        self.assertEqual(update["value"], "audition.wav")
        self.assertTrue(update["visible"])

    def test_form_wiring_keeps_all_parameters_in_signature_order(self):
        tree = ast.parse((ROOT / "audiobook_generator/ui/web_ui.py").read_text())
        form = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "process_form")
        parameters = [a.arg for a in form.args.args]
        click = next(n for n in ast.walk(tree) if isinstance(n, ast.Call)
                     and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name)
                     and n.func.value.id == "start_btn" and n.func.attr == "click")
        inputs = next(k.value for k in click.keywords if k.arg == "inputs")
        names = [item.id for item in inputs.elts]
        aliases = {"provider_state": "provider", "deepseek_api_key": "role_quality_deepseek_api_key",
                   "deepseek_base_url": "role_quality_deepseek_base_url", "deepseek_model": "role_quality_deepseek_model",
                   "book_chapter_catalog": "chapter_catalog_state"}
        self.assertEqual([aliases.get(name, name) for name in names], parameters)
        for name in parameters:
            if name.startswith("voxcpm_"):
                assignments = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)
                               and any(isinstance(t, ast.Name) and t.id == name for t in n.targets)]
                self.assertEqual(len(assignments), 1, name)
                self.assertEqual(assignments[0].value.attr, name.removeprefix("voxcpm_"))

    def test_form_submits_denoise_and_ignores_hidden_clone_values(self):
        tree = ast.parse((ROOT / "audiobook_generator/ui/web_ui.py").read_text())
        form = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "process_form")
        launch = MagicMock()
        ns = {"gr": MagicMock(), "os": os, "Path": Path, "GeneralConfig": GeneralConfig,
              "launch_batch": launch, "get_progress_info": lambda: None,
              # 此处只隔离检查参数；真实装饰器的并发行为由 lifecycle 测试覆盖。
              "_role_project_operation": lambda callback: callback}
        exec(compile(ast.Module(body=[form], type_ignores=[]), "web_ui.py", "exec"), ns)
        with tempfile.TemporaryDirectory() as folder:
            params = {name: None for name in inspect.signature(ns["process_form"]).parameters}
            params.update(provider="VoxCPM", input_file=["book.epub"], output_dir=folder,
                          role_mode=False, preview=False, voxcpm_denoise=True,
                          voxcpm_reference_audio="recording.wav", voxcpm_reference_text="录音原文",
                          voxcpm_auto_transcribe=True)
            for mode in ("design", "clone", "hifi"):
                params["voxcpm_mode"] = mode
                ns["process_form"](**params)
                config = launch.call_args.args[0][0]
                self.assertIs(config.voxcpm_denoise, True)
                self.assertEqual(config.voxcpm_reference_audio, None if mode == "design" else "recording.wav")
                self.assertEqual(config.voxcpm_reference_text, "录音原文" if mode == "hifi" else None)
                self.assertEqual(config.voxcpm_auto_transcribe, mode == "hifi")
