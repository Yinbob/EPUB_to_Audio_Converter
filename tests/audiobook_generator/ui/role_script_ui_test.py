"""多角色 WebUI 接线与输入边界测试。"""

import inspect
import os
import pickle
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

try:
    import gradio as gr

    from audiobook_generator.config.ui_config import UiConfig
    from audiobook_generator.ui import web_ui
except Exception as exc:  # pragma: no cover - 仅在可选 UI 依赖缺失时跳过
    gr = None
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


@unittest.skipIf(gr is None, f"Gradio/WebUI 依赖不可用：{IMPORT_ERROR}")
class TestRoleScriptUiHelpers(unittest.TestCase):
    def setUp(self):
        self.example_path = os.path.join(REPO_ROOT, "examples", "role_script.example.json")
        web_ui._ROLE_CONFIRMED_SCRIPTS.clear()
        self.script, self.report = web_ui._load_uploaded_role_script(self.example_path)
        self.assertTrue(self.report.ok, self.report.to_dict())
        self.assertIsNotNone(self.script)

    def test_upload_parses_to_pickle_safe_domain_model(self):
        restored = pickle.loads(pickle.dumps(self.script))
        self.assertEqual(restored.provider, "openai")
        self.assertIn("narrator", restored.roles)
        self.assertEqual(restored.chapters[0].segments[0].text[:4], "这是用于")

    def test_v2_review_persists_and_invalidates_confirmation(self):
        from tests.audiobook_generator.role_script.v2_io_test import _script
        from audiobook_generator.role_script.project_store import project_path, save_project
        script, _source = _script()
        with tempfile.TemporaryDirectory() as folder:
            path = project_path(folder, script.book_sha256)
            save_project(script, path)
            with patch.object(web_ui, "get_output_dir", return_value=folder):
                queue, entities, _source_choices, _target_choices, _message = web_ui.load_role_review(str(path))
                self.assertEqual(queue["value"], "ch1_s2")
                self.assertTrue(entities["choices"])
                web_ui._remember_role_confirmation(str(path), "old-signature")
                outputs = web_ui.apply_role_review(str(path), "confirm", "ch1_s2", "char_1", None, None)
                self.assertIn("已保存", outputs[2])
                self.assertFalse(outputs[3])
                self.assertEqual(web_ui._recall_role_confirmation(str(path)), "")
            saved, report = web_ui._load_uploaded_role_script(str(path))
            self.assertTrue(report.ok)
            self.assertEqual(saved.chapters[0].segments[1].speaker.status, "confirmed")

    def test_role_table_writeback_handles_nan_blank_rows_and_numeric_cells(self):
        rows = web_ui._role_table_rows(self.script)
        rows[0][2] = "茉莉"
        rows[0][4] = 0.91
        rows.insert(0, [None, float("nan"), "", "", "", "", "", ""])
        edited = web_ui._apply_role_table(self.script, rows)
        self.assertEqual(edited.roles["narrator"].provider_params["voice"], "茉莉")
        self.assertEqual(edited.roles["narrator"].provider_params["speed"], 0.91)
        self.assertEqual(len(edited.roles), len(self.script.roles))

    def test_provider_mismatch_and_invalid_final_format_are_structured(self):
        normalized, report = web_ui._validate_uploaded_role_script(
            self.script, "MiniMax", "mp3"
        )
        self.assertIsNone(normalized)
        self.assertIn("provider_mismatch", {item.code for item in report.errors})

        _, report = web_ui._validate_uploaded_role_script(self.script, "Mimo", "pcm")
        self.assertIn("unsupported_role_output_format", {item.code for item in report.errors})

    def test_upload_callback_returns_table_summary_and_role_choices(self):
        rows, summary, role_update = web_ui.role_script_upload_changed(
            self.example_path, "Mimo", "wav", "mp3"
        )
        self.assertEqual(rows, web_ui._role_table_rows(self.script))
        self.assertIn("校验通过", summary)
        self.assertEqual(role_update["choices"][0][1], "narrator")

    def test_voice_catalog_import_callback_saves_and_refreshes_voice_choices(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"TTS_VOICE_CATALOG_PATH": os.path.join(temp_dir, "voices.json")},
        ):
            status, mimo_update, minimax_update = (
                web_ui.import_voice_catalog_document_ui(
                    None,
                    (
                        "voice_id,display_name,language,gender,description\n"
                        "UserEnglish,User English,English,female,recommended narrator"
                    ),
                    "MiMo",
                    "英语",
                )
            )

        self.assertIn("解析并保存成功", status)
        self.assertIn("UserEnglish", status)
        self.assertIn("UserEnglish", mimo_update["choices"])
        self.assertIn("choices", minimax_update)

    def test_confirmation_returns_raw_state_values_and_content_signature(self):
        with patch.object(
            web_ui,
            "_load_uploaded_role_script",
            return_value=(self.script, self.report),
        ), patch.object(
            web_ui,
            "_apply_role_table",
            return_value=self.script,
        ), patch.object(
            web_ui,
            "_validate_uploaded_role_script",
            return_value=(self.script, self.report),
        ):
            confirmed, _, _, signature, probe = web_ui.confirm_auto_role_script(
                self.example_path, [], "Mimo", "wav", "mp3"
            )

        # gr.State 只接受原始值；gr.update(value=...) 会被 Gradio 当成属性更新而跳过写值。
        self.assertIs(confirmed, True)
        self.assertNotIsInstance(confirmed, dict)
        self.assertEqual(len(signature), 64)
        self.assertEqual(signature, web_ui._role_confirmation_signature(self.script))
        # 确认成功后前端探针必须变成“已确认”，否则“完成”仍会被门禁拦下。
        self.assertEqual(probe["value"].count('data-confirmed="1"'), 1)
        self.assertIn("data-gate=\"0\"", probe["value"])

    def test_confirmation_is_remembered_server_side(self):
        with patch.object(
            web_ui,
            "_load_uploaded_role_script",
            return_value=(self.script, self.report),
        ), patch.object(
            web_ui,
            "_apply_role_table",
            return_value=self.script,
        ), patch.object(
            web_ui,
            "_validate_uploaded_role_script",
            return_value=(self.script, self.report),
        ):
            web_ui.confirm_auto_role_script(self.example_path, [], "Mimo", "wav", "mp3")

        # 人工确认必须在服务端留痕，供被 Gradio 竞态覆盖 State 的 start 事件兜底。
        self.assertEqual(
            web_ui._recall_role_confirmation(self.example_path),
            web_ui._role_confirmation_signature(self.script),
        )

    def test_forgetting_clears_server_side_confirmation(self):
        web_ui._remember_role_confirmation(self.example_path, "deadbeef")
        self.assertEqual(web_ui._recall_role_confirmation(self.example_path), "deadbeef")
        web_ui._forget_role_confirmation(self.example_path)
        self.assertEqual(web_ui._recall_role_confirmation(self.example_path), "")

    def test_process_form_uses_server_side_confirmation_when_state_is_stale(self):
        """已点过「确认使用」但 State 被竞态覆盖时，不能再提示“等待 DeepSeek”。"""
        values = {name: None for name in inspect.signature(web_ui.process_form).parameters}
        with tempfile.TemporaryDirectory() as root:
            book_path = os.path.join(root, "book.epub")
            with open(book_path, "wb") as file_obj:
                file_obj.write(b"placeholder")
            values.update({
                "provider": "Mimo",
                "input_file": [SimpleNamespace(name=book_path)],
                "output_dir": root,
                "worker_count": 1,
                "output_text": False,
                "preview": False,
                "chapter_start": 1,
                "chapter_end": -1,
                "model": "mimo-v2.5-tts",
                "voices": "冰糖",
                "speed": 1.0,
                "openai_output_format": "wav",
                "instructions": "",
                "enable_stream": False,
                "audio_core_enabled": True,
                "role_mode": True,
                "auto_role_split": True,
                "role_script_file": self.example_path,
                "role_table": [],
                # 冷启动事件快照：State 全是空值，但服务端已有确认记录。
                "role_split_confirmed": False,
                "role_split_generated": True,
                "role_confirmed_signature": "",
                "allow_role_text_override": False,
                "allow_role_title_mismatch": False,
                "allow_role_fallback": False,
            })
            captured = {}

            def capture(configs):
                captured["configs"] = configs

            with patch.object(
                web_ui,
                "_load_uploaded_role_script",
                return_value=(self.script, self.report),
            ), patch.object(
                web_ui, "_apply_role_table", return_value=self.script
            ), patch.object(
                web_ui,
                "_validate_uploaded_role_script",
                return_value=(self.script, self.report),
            ):
                web_ui._remember_role_confirmation(
                    self.example_path, web_ui._role_confirmation_signature(self.script)
                )
                with patch.object(web_ui, "launch_batch", side_effect=capture), patch.object(
                    web_ui,
                    "get_progress_info",
                    return_value=(gr.update(), gr.Timer(active=False)),
                ), patch.object(web_ui.gr, "Warning") as warning:
                    web_ui.process_form(**values)

        self.assertIn("configs", captured, "服务端确认记录未放行转换")
        self.assertTrue(captured["configs"][0].audio_core_enabled)
        self.assertEqual(captured["configs"][0].worker_count, 1)
        warning.assert_not_called()

    def test_provider_switch_reports_support_without_changing_role_data(self):
        for provider in ("Edge", "Qwen", "Chatterbox", "VoxCPM"):
            with self.subTest(provider=provider):
                selected, message, button = web_ui.role_provider_changed(provider)
                self.assertEqual(selected, provider)
                self.assertIn("不支持多角色模式", message)
                self.assertIn("保留", message)
                self.assertFalse(button["interactive"])
        for provider in ("Mimo", "MiniMax"):
            selected, message, button = web_ui.role_provider_changed(provider)
            self.assertEqual(selected, provider)
            self.assertIn("剧本必须与所选引擎一致", message)
            self.assertTrue(button["interactive"])

    def test_unsupported_engine_blocks_before_confirmation_or_script_loading(self):
        values = {name: None for name in inspect.signature(web_ui.process_form).parameters}
        values.update(input_file=["book.epub"], role_mode=True)
        for provider in ("Edge", "Qwen", "Chatterbox", "VoxCPM"):
            for confirmed in (False, True):
                with self.subTest(provider=provider, confirmed=confirmed):
                    values.update(provider=provider, role_split_confirmed=confirmed)
                    with patch.object(web_ui.gr, "Warning") as warning, patch.object(
                        web_ui, "_load_uploaded_role_script"
                    ) as load_script, patch.object(web_ui, "launch_batch") as launch:
                        web_ui.process_form(**values)
                    self.assertIn("不支持多角色模式", warning.call_args[0][0])
                    load_script.assert_not_called()
                    launch.assert_not_called()

    def test_process_form_still_blocks_unconfirmed_script(self):
        values = {name: None for name in inspect.signature(web_ui.process_form).parameters}
        values.update({
            "provider": "Mimo",
            "input_file": ["book.epub"],
            "role_mode": True,
            "auto_role_split": True,
            "role_script_file": self.example_path,
            "role_table": [],
            "role_split_confirmed": False,
            "role_split_generated": True,
            "role_confirmed_signature": "",
            "allow_role_text_override": False,
            "allow_role_title_mismatch": False,
            "allow_role_fallback": False,
        })
        with patch.object(web_ui.gr, "Warning") as warning, patch.object(
            web_ui, "launch_batch"
        ) as launch_batch:
            web_ui.process_form(**values)
        launch_batch.assert_not_called()
        self.assertIn("确认剧本与角色参数", warning.call_args[0][0])

    def test_repeated_table_change_keeps_confirmation_only_when_content_is_unchanged(self):
        signature = web_ui._role_confirmation_signature(self.script)
        rows = web_ui._role_table_rows(self.script)

        _, _, confirmed, same_signature, probe = web_ui.role_table_changed(
            self.example_path,
            "Mimo",
            "wav",
            "mp3",
            True,
            signature,
            rows,
        )
        self.assertIs(confirmed, True)
        self.assertEqual(same_signature, signature)
        self.assertEqual(probe["value"].count('data-confirmed="1"'), 1)

        rows[0][2] = "茉莉"
        _, _, confirmed, changed_signature, probe = web_ui.role_table_changed(
            self.example_path,
            "Mimo",
            "wav",
            "mp3",
            True,
            signature,
            rows,
        )
        self.assertIs(confirmed, False)
        self.assertEqual(changed_signature, "")
        self.assertEqual(probe["value"].count('data-confirmed="0"'), 1)

    def test_preview_failure_is_isolated(self):
        with tempfile.TemporaryDirectory() as root, patch.object(
            web_ui, "get_output_dir", return_value=root
        ), patch.object(
            web_ui, "get_tts_provider", side_effect=RuntimeError("未配置凭证")
        ), patch.object(web_ui.gr, "Warning") as warning:
            result = web_ui.preview_role_segment(
                "Mimo",
                self.example_path,
                [],
                "narrator — 旁白",
                "试听文本",
                "mimo-v2.5-tts",
                "冰糖",
                1.0,
                "",
                False,
                "wav",
                "speech-2.8-hd",
                "male-qn-qingse",
                "mp3",
            )
        self.assertIsInstance(result, dict)
        warning.assert_called_once()

    def test_preview_uses_edited_role_table_params(self):
        rows = web_ui._role_table_rows(self.script)
        narrator_row = [row for row in rows if row[0] == "narrator"][0]
        narrator_row[2] = "茉莉"
        narrator_row[4] = 0.91
        captured = {}

        class FakeProvider:
            def synthesize_segment(self, text, profile, work_dir, progress):
                captured["text"] = text
                captured["profile"] = profile
                path = os.path.join(work_dir, "preview.wav")
                import wave
                from audiobook_generator.role_script.audio_pipeline import build_audio_artifact
                with wave.open(path, "wb") as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(24000)
                    wav.writeframes(b"\x00\x00" * 24000)
                return build_audio_artifact(path)

        with tempfile.TemporaryDirectory() as root, patch.object(
            web_ui, "get_output_dir", return_value=root
        ), patch.object(
            web_ui, "get_tts_provider", return_value=FakeProvider()
        ), patch.object(web_ui.gr, "Info"), patch.object(web_ui.gr, "Warning") as warning:
            result = web_ui.preview_role_segment(
                "Mimo",
                self.example_path,
                [narrator_row],
                "narrator — 旁白",
                "试听文本",
                "mimo-v2.5-tts",
                "冰糖",
                1.0,
                "",
                False,
                "wav",
                "speech-2.8-hd",
                "male-qn-qingse",
                "mp3",
            )
            self.assertIn("value", result)
            self.assertTrue(os.path.isfile(result["value"]))

        warning.assert_not_called()
        self.assertEqual(captured["text"], "试听文本")
        self.assertEqual(captured["profile"].provider_params["voice"], "茉莉")
        self.assertEqual(captured["profile"].provider_params["speed"], 0.91)


    def test_generated_script_change_event_preserves_confirmation_states(self):
        with tempfile.TemporaryDirectory() as root:
            generated_dir = os.path.join(root, ".role_generated")
            os.makedirs(generated_dir)
            path = os.path.join(generated_dir, "script.json")
            with open(path, "w", encoding="utf-8") as file_obj:
                file_obj.write("{}")

            with patch.object(web_ui, "get_output_dir", return_value=root):
                result = web_ui.manual_role_script_uploaded(
                    path, "Mimo", "wav", "mp3", True, True, "a" * 64
                )

        # 前 5 个普通输出不动，后 3 个 State 必须保持原值。
        self.assertEqual(len(result), 9)
        self.assertIs(result[5], True)
        self.assertIs(result[6], True)
        self.assertEqual(result[7], "a" * 64)

    def test_empty_script_does_not_reveal_verification_or_show_error(self):
        result = web_ui.manual_role_script_uploaded(None, "Mimo", "wav", "mp3")
        self.assertFalse(result[4]["visible"])
        self.assertNotIn("失败", result[1])
        self.assertIs(result[5], False)

    def test_explicit_split_ignores_upload_automation_preference(self):
        values = [None, True, False] + [None] * 11
        with patch.object(web_ui, "auto_split_role_script") as split:
            web_ui.split_role_script_now(*values)
        self.assertIs(split.call_args.args[2], True)

    def test_calibration_updates_all_roles_only_after_success(self):
        durations = {"narrator": 5000, "lin_daiyu": 7000}
        class FakeProvider:
            def synthesize_segment(self, text, profile, work_dir, progress):
                return SimpleNamespace(duration_ms=durations[profile.role_id])

        with tempfile.TemporaryDirectory() as root, patch.object(
            web_ui, "get_output_dir", return_value=root
        ), patch.object(web_ui, "get_tts_provider", return_value=FakeProvider()):
            table, status = web_ui.calibrate_role_pace(
                "Mimo", self.example_path, [], "这是用于各角色语速校准的同一段完整试听文本，请自然朗读。",
                "mimo-v2.5-tts", "冰糖", 1, "", False,
            )
        rows = {row[0]: row for row in table["value"]}
        self.assertEqual(rows["narrator"][4], 1)
        self.assertEqual(rows["lin_daiyu"][4], 1.4)
        self.assertIn("下一步", status)
        self.assertEqual(rows["lin_daiyu"][2], self.script.roles["lin_daiyu"].provider_params["voice"])

    def test_calibration_failure_preserves_table(self):
        class FakeProvider:
            def synthesize_segment(self, text, profile, work_dir, progress):
                if profile.role_id == "lin_daiyu":
                    raise RuntimeError("网络暂时不可用")
                return SimpleNamespace(duration_ms=5000)

        with tempfile.TemporaryDirectory() as root, patch.object(
            web_ui, "get_output_dir", return_value=root
        ), patch.object(web_ui, "get_tts_provider", return_value=FakeProvider()):
            table, status = web_ui.calibrate_role_pace(
                "Mimo", self.example_path, [], "这是用于各角色语速校准的同一段完整试听文本，请自然朗读。",
                "mimo-v2.5-tts", "冰糖", 1, "", False,
            )
        self.assertNotIn("value", table)
        self.assertIn("原有参数已保留", status)

    def test_role_confirmation_does_not_block_advanced_settings_close(self):
        script = web_ui.HEAD_HTML
        self.assertIn("function syncRoleGate()", script)
        self.assertIn("doneBtn.disabled = false", script)
        self.assertNotIn("doneBtn.disabled = true", script)
        self.assertIn("aria-disabled", script)
        # 探针必须真实渲染，不能再被 Gradio 的 visible=False 隐藏。
        source = inspect.getsource(web_ui.host_ui)
        self.assertIn('elem_id="role_confirmation_probe_host"', source)
        self.assertNotIn('elem_id="role_confirmation_probe_host", visible=False', source)
        self.assertIn("#role_confirmation_probe_host", web_ui.CUSTOM_CSS)
        self.assertIn("#advanced_modal .modal-done[disabled]", web_ui.CUSTOM_CSS)

    def test_partial_role_table_edit_preserves_roles_and_adds_new_role(self):
        rows = web_ui._role_table_rows(self.script)
        narrator_row = [row for row in rows if row[0] == "narrator"][0]
        narrator_row[2] = "茉莉"
        rows.append(["new_role", "新角色", "白桦", "", "", "", "", ""])

        edited = web_ui._apply_role_table(self.script, rows)

        self.assertEqual(edited.roles["narrator"].provider_params["voice"], "茉莉")
        self.assertIn("lin_daiyu", edited.roles)
        self.assertEqual(edited.roles["new_role"].display_name, "新角色")
        self.assertEqual(edited.roles["new_role"].provider_params, {"voice": "白桦"})

    def test_only_editing_narrator_row_does_not_drop_other_roles(self):
        rows = web_ui._role_table_rows(self.script)
        narrator_row = [row for row in rows if row[0] == "narrator"][0]
        narrator_row[4] = 1.1

        edited = web_ui._apply_role_table(self.script, [narrator_row])

        self.assertIn("narrator", edited.roles)
        self.assertIn("lin_daiyu", edited.roles)
        self.assertEqual(edited.roles["narrator"].provider_params["speed"], 1.1)

    def test_role_mode_ignores_persisted_preview_and_uses_edited_role_table(self):
        signature = inspect.signature(web_ui.process_form).parameters
        values = {name: None for name in signature}
        rows = web_ui._role_table_rows(self.script)
        narrator_row = [row for row in rows if row[0] == "narrator"][0]
        narrator_row[2] = "茉莉"
        captured = {}

        with tempfile.TemporaryDirectory() as root:
            book_path = os.path.join(root, "book.epub")
            with open(book_path, "wb") as file_obj:
                file_obj.write(b"placeholder")
            values.update({
                "provider": "Mimo",
                "input_file": [SimpleNamespace(name=book_path)],
                "output_dir": root,
                "worker_count": 1,
                "output_text": False,
                # 模拟 .webui_settings.json 中遗留的预览开关；角色模式仍必须真实合成。
                "preview": True,
                "chapter_start": 1,
                "chapter_end": -1,
                "model": "mimo-v2.5-tts",
                "voices": "冰糖",
                "speed": 1.0,
                "openai_output_format": "wav",
                "instructions": "",
                "enable_stream": False,
                "role_mode": True,
                "auto_role_split": True,
                "role_script_file": self.example_path,
                "role_table": [narrator_row],
                "role_split_confirmed": True,
                "role_split_generated": True,
                "allow_role_text_override": False,
                "allow_role_title_mismatch": False,
                "allow_role_fallback": False,
            })

            def capture(configs):
                captured["configs"] = configs

            with patch.object(web_ui, "launch_batch", side_effect=capture), patch.object(
                web_ui, "get_progress_info", return_value=(gr.update(), gr.Timer(active=False))
            ), patch.object(web_ui.gr, "Warning") as warning:
                web_ui.process_form(**values)

        config = captured["configs"][0]
        self.assertFalse(config.preview)
        warning.assert_called_once()
        self.assertEqual(
            config.role_script.roles["narrator"].provider_params["voice"], "茉莉"
        )
        self.assertIn("lin_daiyu", config.role_script.roles)

    def test_process_form_rejects_multiple_books_in_role_mode(self):
        values = {name: None for name in inspect.signature(web_ui.process_form).parameters}
        values.update({
            "provider": "Mimo",
            "input_file": ["book-a.epub", "book-b.epub"],
            "role_mode": True,
            "auto_role_split": True,
            "role_script_file": self.example_path,
            "role_table": [],
            "role_split_confirmed": True,
            "role_split_generated": True,
            "allow_role_text_override": False,
            "allow_role_title_mismatch": False,
            "allow_role_fallback": False,
        })
        with patch.object(web_ui.gr, "Warning") as warning, patch.object(
            web_ui, "launch_batch"
        ) as launch_batch:
            web_ui.process_form(**values)
        warning.assert_called_once()
        launch_batch.assert_not_called()


@unittest.skipIf(gr is None, f"Gradio/WebUI 依赖不可用：{IMPORT_ERROR}")
class TestRoleScriptUiWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.captured = {}
        cls._original_launch = gr.Blocks.launch
        gr.Blocks.launch = lambda self, *args, **kwargs: cls.captured.setdefault("ui", self)
        web_ui.host_ui(UiConfig(SimpleNamespace(host="127.0.0.1", port=7999)))
        cls.config = cls.captured["ui"].get_config_file()

    @classmethod
    def tearDownClass(cls):
        gr.Blocks.launch = cls._original_launch

    def _components(self):
        return self.config["components"]

    def _dependency(self, api_name):
        return next((
            dep for dep in self.config["dependencies"]
            if dep.get("api_name") == api_name
        ), None)

    def _component_by_label(self, label):
        return next((
            component for component in self._components()
            if str(component.get("props", {}).get("label") or "") == label
        ), None)

    def _component_is_inside(self, component_id, elem_id="advanced_modal"):
        advanced_modal = next((
            component for component in self._components()
            if component.get("props", {}).get("elem_id") == elem_id
        ), None)
        if advanced_modal is None:
            return False

        parents = {}

        def walk(node, parent_id=None):
            if isinstance(node, dict):
                node_id = node.get("id")
                if node_id is not None and parent_id is not None:
                    parents[node_id] = parent_id
                for child in node.get("children") or []:
                    walk(child, node_id)
            if isinstance(node, list):
                for child in node:
                    walk(child, parent_id)

        walk(self.config["layout"])
        current = component_id
        while current in parents:
            current = parents[current]
            if current == advanced_modal["id"]:
                return True
        return False

    def test_process_form_role_and_audio_core_inputs_match_components(self):
        signature_names = list(inspect.signature(web_ui.process_form).parameters)[-23:-4]
        self.assertEqual(
            signature_names,
            [
                "role_mode",
                "auto_role_split",
                "role_script_file",
                "role_table",
                "role_split_confirmed",
                "role_split_generated",
                "role_confirmed_signature",
                "allow_role_text_override",
                "allow_role_title_mismatch",
                "allow_role_fallback",
                "role_quality_enabled",
                "role_quality_max_rate",
                "role_quality_deepseek_api_key",
                "role_quality_deepseek_base_url",
                "role_quality_deepseek_model",
                "audio_core_enabled",
                "audio_core_repair",
                "audio_core_settings_file",
                "audio_core_casting_file",
            ],
        )
        process_form = self._dependency("process_form")
        self.assertIsNotNone(process_form)
        inputs = process_form.get("inputs") or []
        self.assertEqual(len(inputs), len(inspect.signature(web_ui.process_form).parameters))
        components = {component["id"]: component for component in self._components()}
        expected_labels = [
            "为旁白和人物使用不同声音",
            "上传书籍后自动调用 DeepSeek 拆分角色",
            "导入已有剧本 / 下载当前剧本",
            "完整人物参数表",
            None,
            None,
            None,
            "允许剧本文本覆盖书籍正文",
            "允许章节标题不匹配",
            "缺失角色回退",
            "启用旧版逐段测评",
            "中文语速上限",
            "DeepSeek API Key",
            "服务地址",
            "DeepSeek 模型",
            "MiMo 生成时检查内容、拼接与角色一致性",
            "按次数与时限自动修复问题片段",
            "可选：本地模型与资源设置 JSON",
            "可选：已审查角色选角 JSON",
        ]
        for component_id, label in zip(inputs[-23:-4], expected_labels):
            if label is None:
                continue
            actual = str(components[component_id].get("props", {}).get("label") or "")
            self.assertTrue(actual.startswith(label), (actual, label))

    def test_role_events_are_wired(self):
        auto_split = self._dependency("auto_split_role_script")
        self.assertIsNotNone(auto_split)
        self.assertEqual(len(auto_split.get("inputs") or []), 19)
        self.assertEqual(len(auto_split.get("outputs") or []), 12)

        upload = self._dependency("manual_role_script_uploaded")
        self.assertIsNotNone(upload)
        # 4 个原输入 + 3 个确认 State：自动拆分写回文件时必须原样透传，
        # 否则文件 change 事件会把刚写入的确认状态冲成默认值。
        self.assertEqual(len(upload.get("inputs") or []), 7)
        self.assertEqual(len(upload.get("outputs") or []), 9)

        confirm = self._dependency("confirm_auto_role_script")
        self.assertIsNotNone(confirm)
        self.assertEqual(len(confirm.get("inputs") or []), 5)
        self.assertEqual(len(confirm.get("outputs") or []), 6)

        table_change = self._dependency("role_table_changed")
        self.assertIsNotNone(table_change)
        self.assertEqual(len(table_change.get("inputs") or []), 8)
        self.assertEqual(len(table_change.get("outputs") or []), 5)

        preview = self._dependency("preview_role_segment")
        self.assertIsNotNone(preview)
        self.assertEqual(len(preview.get("inputs") or []), 14)
        self.assertEqual(len(preview.get("outputs") or []), 1)

        calibration = self._dependency("calibrate_role_pace")
        self.assertIsNotNone(calibration)
        self.assertEqual(len(calibration["inputs"]), 9)
        self.assertIsNotNone(self._dependency("split_role_script_now"))

    def test_role_verification_panel_is_auto_revealed(self):
        panel = next((
            component for component in self._components()
            if component.get("props", {}).get("elem_id") == "role_verification_panel"
        ), None)
        self.assertIsNotNone(panel, "人工核验面板需要稳定的 elem_id")
        self.assertTrue(
            self._component_is_inside(panel["id"], "role_studio"),
            "人工核验面板应位于独立多角色配音模块内",
        )

        script = web_ui.HEAD_HTML
        self.assertIn("roleVerificationObserver", script)
        self.assertIn("role_verification_panel", script)
        self.assertIn("ataAutoOpenedKey", script)

    def test_advanced_modal_keeps_scrolled_content_inside_glass_shell(self):
        css = web_ui.CUSTOM_CSS
        self.assertIn("#advanced_modal .modal-scroll > *", css)
        self.assertIn("flex: 0 0 auto !important", css)
        self.assertIn("overflow: visible !important", css)
        self.assertIn("#advanced_modal #role_verification_panel", css)
        self.assertIn("height: auto !important", css)

    def test_advanced_modal_buttons_are_explicit_and_layout_is_grouped(self):
        source = inspect.getsource(web_ui.host_ui)
        self.assertIn('type="button" class="btn-ghost modal-trigger"', source)
        self.assertIn('type="button" class="modal-close-btn"', source)
        self.assertIn('type="button" class="btn-primary modal-done"', source)
        self.assertIn("openAdvancedModal(event)", source)
        self.assertIn("closeAdvancedModal(event)", source)
        self.assertIn('elem_classes="toggle advanced-switch"', source)
        self.assertEqual(source.count('elem_classes="advanced-section"'), 2)

        script = web_ui.HEAD_HTML
        self.assertIn("function openAdvancedModal(event)", script)
        self.assertIn("document.body.dataset.ataModalScrollY", script)
        self.assertIn("var alreadyLocked =", script)
        # 弹窗打开时必须用固定 body 的滚动锁钉住底层页面，
        # 否则 Gradio 重排后点“完成”会整页回到顶部。
        self.assertIn("function lockPageScroll()", script)
        self.assertIn("function unlockPageScroll()", script)
        self.assertIn("document.body.style.position = 'fixed'", script)
        self.assertIn("function closeAdvancedModal(event)", script)
        self.assertIn("var restoreScroll = function", script)
        self.assertIn("var savedScroll = unlockPageScroll();", script)
        self.assertIn("ataUserScrolled", script)
        self.assertNotIn("openAdvancedModal();", script)
        self.assertIn("ataRoleVerificationDismissed", script)
        self.assertIn("requestAnimationFrame", script)

        css = web_ui.CUSTOM_CSS
        for selector in (
            "#advanced_modal .advanced-section",
            "#advanced_modal .advanced-section-head",
            "#advanced_modal .modal-header-wrap",
            "#advanced_modal .modal-footer",
            "#advanced_modal .modal-footer .modal-done",
            "#advanced_modal .toggle.advanced-switch",
            "#advanced_modal .toggle.advanced-switch:active",
            ":root:root.dark #advanced_modal .toggle.advanced-switch",
            "#advanced_modal #role_split_btn:active:not(:disabled)",
        ):
            self.assertIn(selector, css)

    def test_advanced_modal_field_rows_use_aligned_two_column_grid(self):
        """高级设置字段行必须两列等宽、label 对齐，按钮等宽右对齐。"""
        css = web_ui.CUSTOM_CSS
        self.assertIn("#advanced_modal .advanced-field-row {", css)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr)) !important", css,
                      "字段行没有统一成两列等宽网格")
        self.assertIn("align-items: start !important", css,
                      "字段行没有顶部对齐，label 会高低不齐")
        self.assertIn("#advanced_modal .advanced-field-row > * { min-width: 0 !important;", css)
        self.assertIn("justify-content: flex-end !important", css,
                      "操作按钮没有右对齐")
        self.assertIn("#advanced_modal .advanced-action-row button {", css)
        self.assertIn("flex: 0 1 172px !important", css,
                      "操作按钮没有统一宽度")
        self.assertIn("#advanced_modal .toggle.advanced-compact-toggle {", css,
                      "「显示 API Key」没有收成紧凑开关")
        self.assertIn("width: fit-content !important", css)
        # 窄屏必须退回单列，否则两列网格会把控件挤爆
        self.assertIn("grid-template-columns: 1fr !important", css)
        self.assertIn("#advanced_modal .advanced-preview-row { align-items: end !important; }", css)

    def test_deepseek_settings_are_wired(self):
        for api_name in (
            "toggle_deepseek_key",
            "_save_deepseek_api_config",
            "_test_deepseek_api",
        ):
            self.assertIsNotNone(self._dependency(api_name), api_name)

        for label in ("DeepSeek API Key", "服务地址", "DeepSeek 模型"):
            component = self._component_by_label(label)
            self.assertIsNotNone(component, label)
            self.assertTrue(
                self._component_is_inside(component["id"], "role_studio"),
                f"{label} 应位于独立多角色配音模块内",
            )

    def test_voice_catalog_import_is_wired_inside_role_studio(self):
        for label in (
            "TTS 官网音色说明",
            "或粘贴音色说明",
            "对应引擎",
            "默认语言",
        ):
            component = self._component_by_label(label)
            self.assertIsNotNone(component, label)
            self.assertTrue(
                self._component_is_inside(component["id"], "role_studio"),
                f"{label} 应位于独立多角色配音模块内",
            )

        import_event = self._dependency("import_voice_catalog_document_ui")
        self.assertIsNotNone(import_event)
        self.assertEqual(len(import_event.get("inputs") or []), 4)
        self.assertEqual(len(import_event.get("outputs") or []), 3)

        clear_event = self._dependency("clear_voice_catalog_ui")
        self.assertIsNotNone(clear_event)
        self.assertEqual(len(clear_event.get("outputs") or []), 3)


if __name__ == "__main__":
    unittest.main()
