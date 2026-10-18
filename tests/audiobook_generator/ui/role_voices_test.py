"""声音页面到固定档案、真实音频导出和报告的离线检验。"""
import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import soundfile as sf

from audiobook_generator.ui import web_ui
from audiobook_generator.ui.role_voices import make_voice_profile, role_voice_choices, SAVED_ROLE_VOICES
from audiobook_generator.ui.audio_quality import apply_local_quality_defaults, apply_quality_settings, find_quality_reports
from audiobook_generator.tts_providers.mimo_voice import resolve_voice
from audiobook_generator.role_script.project_store import save_project, project_path
from tests.audiobook_generator.role_script.v2_io_test import _script


class RoleVoiceWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.script, _ = _script()
        self.path = project_path(self.root, self.script.book_sha256)
        save_project(self.script, self.path)
        self.patcher = patch.object(web_ui, 'get_output_dir', return_value=str(self.root))
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        web_ui._ROLE_CONFIRMED_SCRIPTS.clear()
        web_ui._ROLE_PREVIEW_BINDINGS.clear()
        web_ui._ROLE_SCRIPT_ORIGINS.clear()
        web_ui._ROLE_SCRIPT_ALIASES.clear()

    def reference(self):
        path = self.root / 'preview.wav'
        sf.write(path, .1 * np.sin(np.arange(48000) * .05), 16000, subtype='PCM_16')
        return path

    def apply(self, mode, reference=None):
        return web_ui.apply_role_voice_settings(str(self.path), [], 'narrator — 旁白', mode,
                                                'mimo_default', 'A youthful clear American voice.',
                                                reference, 'en', 1.0, '')

    def test_missing_numeric_cells_have_explicit_valid_defaults(self):
        script = replace(self.script, roles={key: replace(role, provider_params={"voice": role.provider_params["voice"]})
                                             for key, role in self.script.roles.items()})
        rows = web_ui._role_table_rows(script)
        self.assertTrue(all(row[4] == 1.0 and row[6] == 0.0 and row[7] == 1.0 for row in rows))
        # Gradio numeric cells must receive numbers, never empty strings coerced to zero.
        frame = web_ui.gr.Dataframe(headers=web_ui.ROLE_TABLE_HEADERS,
                                   datatype=["str", "str", "str", "str", "number", "str", "number", "number", "str"])
        wire = frame.postprocess(rows).model_dump()
        edited = web_ui._apply_role_table(script, wire)
        self.assertTrue(all(role.provider_params['speed'] == 1.0 for role in edited.roles.values()))

    def test_table_edit_invalidates_server_confirmation_even_with_old_frontend_state(self):
        signature = web_ui._role_confirmation_signature(self.script)
        web_ui._remember_role_confirmation(str(self.path), signature)
        rows = web_ui._role_table_rows(self.script)
        rows[0][4] = .9
        result = web_ui.role_table_changed(str(self.path), 'Mimo', 'wav', 'mp3', True, signature, rows)
        self.assertFalse(result[2])
        self.assertEqual(web_ui._recall_role_confirmation(str(self.path)), '')

    def test_design_table_confirm_persist_and_provider_route(self):
        rows, message = self.apply('design')
        self.assertIn('已应用', message)
        edited = web_ui._apply_role_table(self.script, rows)
        params = edited.roles['narrator'].provider_params
        self.assertNotIn('voice', params)
        self.assertEqual(resolve_voice(SimpleNamespace(), params)['model'], 'mimo-v2.5-tts-voicedesign')
        # 兼容旧8列表格编辑，不可再丢失声音身份。
        legacy = [row[:8] for row in rows]
        preserved = web_ui._apply_role_table(edited, legacy)
        self.assertEqual(preserved.roles['narrator'].provider_params, params)
        result = web_ui.confirm_auto_role_script(str(self.path), rows, 'Mimo', 'wav', 'mp3')
        self.assertTrue(result[0])
        restored, report = web_ui._load_uploaded_role_script(str(self.path))
        self.assertTrue(report.ok)
        self.assertEqual(restored.roles['narrator'].provider_params, params)
        # 模式切回内置时，不能残留设计或参考音条件。
        rows2, _ = web_ui.apply_role_voice_settings(str(self.path), rows, 'narrator — 旁白',
                                                   'preset', 'mimo_default', '', None, 'en', 1, '')
        switched = web_ui._apply_role_table(restored, rows2).roles['narrator'].provider_params
        self.assertNotIn('voice_description', switched)
        self.assertEqual(resolve_voice(SimpleNamespace(), switched)['mode'], 'preset')
        self.assertEqual(web_ui._recall_role_confirmation(str(self.path)), '')

    def test_clone_reference_survives_upload_deletion_and_tamper_is_rejected(self):
        source = self.reference()
        params = make_voice_profile('narrator', 'clone', None, None, str(source), 'en', 1, '', self.root)
        source.unlink()
        request = resolve_voice(SimpleNamespace(), params)
        self.assertTrue(Path(request['reference_audio_path']).is_file())
        Path(request['reference_audio_path']).write_bytes(b'tampered')
        with self.assertRaises(ValueError):
            resolve_voice(SimpleNamespace(), params)

    def test_saved_bryce_applies_confirms_and_reloads_as_selectable_preset(self):
        key = 'saved_bryce_young_en'
        source = self.reference()
        patcher = patch.dict(SAVED_ROLE_VOICES, {key: {
            **SAVED_ROLE_VOICES[key], 'path': source,
            'sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        }})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.assertIn(('青年男声 · Bryce（英语）', key), role_voice_choices())
        rows, message = web_ui.apply_role_voice_settings(
            str(self.path), [], 'narrator — 旁白', 'preset', key, '', None, 'en', 1, '')
        self.assertIn('已应用', message)
        params = web_ui._apply_role_table(self.script, rows).roles['narrator'].provider_params
        self.assertEqual(params['reference_audio_sha256'], SAVED_ROLE_VOICES[key]['sha256'])
        self.assertNotIn('voice', params)
        self.assertNotIn('voice_description', params)
        self.assertTrue(Path(params['reference_audio_path']).is_relative_to(self.root.resolve()))
        route = resolve_voice(SimpleNamespace(), params)
        self.assertEqual(route['mode'], 'clone')
        self.assertEqual(route['model'], 'mimo-v2.5-tts-voiceclone')
        self.assertTrue(web_ui.confirm_auto_role_script(str(self.path), rows, 'Mimo', 'wav', 'mp3')[0])
        loaded = web_ui.load_role_voice_settings(str(self.path), rows, 'narrator — 旁白')
        self.assertEqual(loaded[:2], ('preset', key))
        # 切换回 MiMo 内置音色时不能残留克隆参考。
        switched, _ = web_ui.apply_role_voice_settings(
            str(self.path), rows, 'narrator — 旁白', 'preset', 'mimo_default', '', None, 'en', 1, '')
        params = web_ui._apply_role_table(self.script, switched).roles['narrator'].provider_params
        self.assertEqual(resolve_voice(SimpleNamespace(), params)['mode'], 'preset')
        self.assertNotIn('reference_audio_path', params)

    def test_saved_voice_rejects_changed_or_missing_library_reference(self):
        source = self.reference()
        registered = {'label': '测试参考', 'path': source, 'sha256': hashlib.sha256(source.read_bytes()).hexdigest()}
        with patch.dict(SAVED_ROLE_VOICES, {'saved_test': registered}):
            source.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, '指纹不符'):
                make_voice_profile('narrator', 'preset', 'saved_test', '', None, 'en', 1, '', self.root)
            source.unlink()
            with self.assertRaises(ValueError):
                make_voice_profile('narrator', 'preset', 'saved_test', '', None, 'en', 1, '', self.root)

    def test_freeze_rejects_another_role_or_edited_table(self):
        source = self.reference()
        binding = ('narrator', web_ui._role_confirmation_signature(self.script),
                   hashlib.sha256(source.read_bytes()).hexdigest())
        web_ui._ROLE_PREVIEW_BINDINGS[str(source)] = binding
        wrong = web_ui.use_preview_as_role_reference(str(self.path), [], 'char_1 — 林黛玉', str(source), 'en', 1, '')
        self.assertIn('重新试听', wrong[1])
        right = web_ui.use_preview_as_role_reference(str(self.path), [], 'narrator — 旁白', str(source), 'en', 1, '')
        self.assertEqual(right[2], 'clone')
        self.assertTrue(Path(right[3]).is_file())
        rows = web_ui._role_table_rows(self.script)
        rows[0][4] = .9
        wrong = web_ui.use_preview_as_role_reference(str(self.path), rows, 'narrator — 旁白', str(source), 'en', 1, '')
        self.assertIn('重新试听', wrong[1])

    def test_audio_component_cache_path_can_freeze_the_same_verified_preview(self):
        from gradio.processing_utils import move_files_to_cache
        source = self.reference()
        web_ui._ROLE_PREVIEW_BINDINGS[str(source)] = (
            'narrator', web_ui._role_confirmation_signature(self.script),
            hashlib.sha256(source.read_bytes()).hexdigest())
        audio = web_ui.gr.Audio(type='filepath')
        audio.GRADIO_CACHE = str(self.root / 'audio-cache')
        payload = move_files_to_cache(audio.postprocess(str(source)), audio, postprocess=True)
        from gradio.data_classes import FileData
        received = audio.preprocess(FileData(**payload))
        self.assertNotEqual(str(source), received)
        frozen = web_ui.use_preview_as_role_reference(str(self.path), [], 'narrator — 旁白', received, 'en', 1, '')
        self.assertEqual(frozen[2], 'clone', frozen[1])
        Path(received).write_bytes(b'changed cache')
        refused = web_ui.use_preview_as_role_reference(str(self.path), [], 'narrator — 旁白', received, 'en', 1, '')
        self.assertIn('重新试听', refused[1])

    def test_file_cache_preserves_generated_origin_review_and_confirmed_project(self):
        from gradio.processing_utils import move_files_to_cache
        from gradio.data_classes import FileData
        web_ui._register_role_script_origin(self.path)
        file = web_ui.gr.File(type='filepath')
        file.GRADIO_CACHE = str(self.root / 'file-cache')
        wire = move_files_to_cache(file.postprocess(str(self.path)), file, postprocess=True)
        received = file.preprocess(FileData(**wire))
        self.assertNotEqual(str(self.path), str(received))
        result = web_ui.manual_role_script_uploaded(received, 'Mimo', 'wav', 'mp3', False, True, '')
        self.assertFalse(result[5], '自动生成的缓存副本不可被当成手动确认')
        reviewed = web_ui.apply_role_review(received, 'confirm', 'ch1_s2', 'char_1', None, None)
        self.assertIn('已保存', reviewed[2])
        rows, _ = web_ui.apply_role_voice_settings(received, [], 'narrator — 旁白', 'design', None,
                                                  'A youthful clear English voice.', None, 'en', 1, '')
        confirmed = web_ui.confirm_auto_role_script(received, rows, 'Mimo', 'wav', 'mp3')
        self.assertTrue(confirmed[0])
        restored, report = web_ui._load_uploaded_role_script(str(self.path))
        self.assertTrue(report.ok)
        self.assertEqual(restored.roles['narrator'].provider_params['voice_mode'], 'design')
        # 同一客户端仍持有旧缓存副本时，后续生成读取的是新保存的项目。
        aliased, _ = web_ui._load_uploaded_role_script(received)
        self.assertEqual(aliased, restored)

    def test_invalid_settings_leave_current_table_unchanged(self):
        for mode, reference in [('design', None), ('clone', None)]:
            description = '' if mode == 'design' else None
            result = web_ui.apply_role_voice_settings(str(self.path), [], 'narrator — 旁白', mode,
                                                      None, description, reference, 'en', 1, '')
            self.assertIsInstance(result[0], dict)
            self.assertIn('未应用', result[1])
        self.assertEqual(web_ui._load_uploaded_role_script(str(self.path))[0], self.script)

    def test_local_models_discovered_but_explicit_settings_override(self):
        model = self.root / '.audio_quality_models' / 'SenseVoiceSmall'
        model.mkdir(parents=True)
        (model / 'config.yaml').write_text('fixture')
        config = SimpleNamespace()
        apply_local_quality_defaults(config, self.root)
        self.assertEqual(config.audio_core_asr_model, str(model.resolve()))
        explicit = self.root / 'settings.json'
        explicit.write_text(json.dumps({'asr_model': None, 'no_asr': True}))
        self.assertFalse(apply_quality_settings(config, explicit).enable_asr)
        self.assertIsNone(config.audio_core_asr_model)

    def test_ui_profile_reaches_generated_audio_report_and_library(self):
        from audiobook_generator.audio_core.pipeline import run_chapter
        from audiobook_generator.audio_core.models import CoreOptions
        from audiobook_generator.audio_core.store import fingerprint
        from audiobook_generator.core.audio_tags import AudioTags
        from audiobook_generator.ui.library import selection_details
        from tests.audiobook_generator.audio_core.pipeline_test import plan_for
        rows, _ = self.apply('clone', str(self.reference()))
        params = web_ui._apply_role_table(self.script, rows).roles['narrator'].provider_params
        plan = plan_for(('Please wait beside the bridge.', 'I will arrive soon.'))
        plan = replace(plan, units=tuple(replace(u, profile=replace(u.profile, provider_params=params)) for u in plan.units))
        requests = []
        class Provider:
            provider_id = 'openai'
            def synthesize_observed_chunk(inner, text, profile, store, run_id, **kwargs):
                route = resolve_voice(SimpleNamespace(), profile.provider_params)
                requests.append(route)
                key = fingerprint({'text': text, 'route': route})
                reservation = store.reserve(run_id, key, len(text), repair=False)
                path = store.save_sample(key, self.reference().read_bytes(), 'wav')
                store.settle(reservation, artifact=path)
                return path
        output = self.root / 'Book' / 'chapter.wav'
        output.parent.mkdir()
        result = run_chapter(plan, Provider(), output, AudioTags('Chapter', 'Author', 'Book', 1),
                             self.root / '.audio_projects' / 'book',
                             options=CoreOptions(enable_asr=False, enable_speaker=False, language='en'))
        self.assertEqual(result['generation_status'], 'generated')
        self.assertEqual(len(requests), 2)
        self.assertTrue(all(r['mode'] == 'clone' for r in requests))
        self.assertEqual(len(find_quality_reports(self.root)), 1)
        _, paths, audio = selection_details(self.root, 'Book', ['chapter.wav'])
        self.assertEqual(paths, [str(output.resolve())])
        self.assertEqual(audio, ['chapter.wav'])
