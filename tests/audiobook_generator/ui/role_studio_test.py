"""角色工作区布局、摘要和等待阶段；不调用外部接口。"""
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch

from gradio.helpers import special_args
from audiobook_generator.ui import web_ui
from audiobook_generator.ui.role_studio import split_result_status, render_split_status
from tests.audiobook_generator.role_script.v2_io_test import _script


class RoleStudioTest(unittest.TestCase):
    def test_real_phase_highlight_and_elapsed_survive_stage_change(self):
        with patch('audiobook_generator.ui.role_studio.time.time', return_value=100):
            first = render_split_status('running', '正在建立人物表：第 1 章', started=35000)
            second = render_split_status('running', 'DeepSeek 正在拆分第 1 章（1/1）', started=35000)
            unknown = render_split_status('running', '等待服务响应', started=35000)
        self.assertIn('aria-current="step">梳理人物', first)
        self.assertIn('aria-current="step">拆分剧本', second)
        self.assertIn('已等待 1 分 5 秒', first)
        self.assertIn('已等待 1 分 5 秒', second)
        self.assertNotIn('aria-current="step"', unknown)
        self.assertNotIn('aria-valuenow', unknown)
        self.assertNotIn('role-split-track', render_split_status('done'))

    def test_confirmation_waits_for_backend_and_recovers_on_failure(self):
        for success in (True, False):
            result = (success, 'result', web_ui.gr.skip(), 'signature' if success else '',
                      web_ui.gr.update(value=web_ui._role_confirmation_probe(success)))
            with patch.object(web_ui, 'confirm_auto_role_script', return_value=result) as confirm:
                stream = web_ui.confirm_auto_role_script_ui('roles.json', [], 'Mimo', 'wav', 'mp3')
                first = next(stream)
                confirm.assert_not_called()
                self.assertFalse(first[-1]['interactive'])
                last = next(stream)
            self.assertEqual(last[:5], result)
            self.assertTrue(last[-1]['interactive'])
        with patch.object(web_ui, 'confirm_auto_role_script', side_effect=RuntimeError('offline test')):
            last = list(web_ui.confirm_auto_role_script_ui('roles.json', [], 'Mimo', 'wav', 'mp3'))[-1]
        self.assertFalse(last[0])
        self.assertIn('data-confirmed="0"', last[4]['value'])
        self.assertTrue(last[-1]['interactive'])

    def test_narration_identity_is_visible_in_summary_and_review_details(self):
        script, _ = _script()
        chapter = script.chapters[0]
        narrative = replace(chapter.segments[1], text_kind='narration')
        script = replace(script, chapters=(replace(chapter, segments=(chapter.segments[0], narrative)),))
        summary = web_ui._role_script_summary(script)
        self.assertIn('叙述声音', summary)
        self.assertIn('林黛玉', summary.split('| 1 ·')[1])
        report = web_ui.ValidationReport(schema_version=2)
        with patch.object(web_ui, '_load_uploaded_role_script', return_value=(script, report)):
            details = web_ui.role_review_details('test.json', narrative.segment_id)
        self.assertIn('叙述（可由故事人物自述）', details)
        self.assertIn('朗读声音：林黛玉', details)

    def test_summary_is_bounded_and_uses_names_instead_of_segment_id_chains(self):
        script, _ = _script()
        first = script.chapters[0]
        script = replace(script, chapters=tuple(replace(first, chapter_index=i,
                         title='A | <script> * long title') for i in range(1, 31)))
        text = web_ui._role_script_summary(script)
        self.assertNotIn(' → ', text)
        self.assertNotIn('<script>', text)
        self.assertIn('其余 18 章', text)
        self.assertEqual(sum(line.startswith('| ') for line in text.splitlines()), 14)
        self.assertLess(len(text), 2500)

    def test_current_character_survives_applying_settings(self):
        script, _ = _script()
        role = next(key for key in script.roles if key != 'narrator')
        report = web_ui.ValidationReport(schema_version=2)
        with patch.object(web_ui, '_load_uploaded_role_script', return_value=(script, report)):
            result = web_ui.role_table_changed('test.json', 'Mimo', 'wav', 'mp3', False, '',
                                               web_ui._role_table_rows(script), role)
        self.assertEqual(result[1]['value'], role)
        self.assertIn((script.roles[role].display_name, role), result[1]['choices'])
        self.assertFalse(result[2])

    def test_gradio_injects_progress_for_both_automatic_and_manual_actions(self):
        for fn in (web_ui.auto_split_role_script, web_ui.split_role_script_now):
            values, progress_index, _ = special_args(fn, [None] * 19)
            self.assertEqual(progress_index, 19)
            self.assertEqual(len(values), 20)
            self.assertIsInstance(values[19], web_ui.gr.Progress)

    def test_split_stage_feedback_reaches_progress_and_finishes_only_after_save(self):
        script, _ = _script()
        updates = []
        def progress(value, desc):
            updates.append((value, desc))
        def generate(*args, **kwargs):
            kwargs['progress']('正在建立人物表：第 1 章')
            kwargs['progress']('DeepSeek 正在拆分第 1 章（1/1）')
            return script
        with tempfile.TemporaryDirectory() as folder, \
             patch.object(web_ui, '_auto_split_chapters', return_value=([('One', 'Text')], 1, 1, script.book_sha256, None)), \
             patch.object(web_ui, 'get_output_dir', return_value=folder), \
             patch.object(web_ui, 'load_project', return_value=None), \
             patch.object(web_ui, 'generate_v2_for_book', side_effect=generate):
            values = [None, True, False, 'Mimo', 1, 1, 'auto', 'double', False, False,
                      None, 'dummy', 'https://example.invalid', 'model', False, None, None, None, None, progress]
            result = web_ui.split_role_script_now(*values)
            self.assertTrue(result[7])
            self.assertFalse(result[6])
            self.assertEqual(updates[0][0], 0)
            self.assertEqual([value for value, _ in updates[1:-1]], [None, None])
            self.assertEqual(updates[-1][0], 1)
            updates.clear()
            with patch.object(web_ui, 'save_project', side_effect=OSError('保存失败')):
                result = web_ui.split_role_script_now(*values)
            self.assertFalse(result[7])
            self.assertNotIn(1, [value for value, _ in updates])
            status = split_result_status(False, result[2]['value'])
            self.assertIn('保存失败', status)
            self.assertNotIn('高级工具', status)


if __name__ == '__main__':
    unittest.main()
