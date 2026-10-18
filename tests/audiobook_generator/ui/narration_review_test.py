"""叙述声音人工纠错保存与确认门禁；全部在临时项目运行。"""
from dataclasses import replace
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from audiobook_generator.ui import web_ui
from audiobook_generator.role_script.project_store import project_path, save_project
from tests.audiobook_generator.role_script.v2_io_test import _script


class NarrationReviewTest(unittest.TestCase):
    def setUp(self):
        script, _ = _script()
        chapter = script.chapters[0]
        self.script = replace(script, chapters=(replace(chapter,
            segments=(replace(chapter.segments[0], text_kind='narration'),
                      replace(chapter.segments[1], text_kind='dialogue'))),))

    def test_save_preserves_current_voice_edits_and_requires_reconfirmation(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(web_ui, 'get_output_dir', return_value=folder):
            path = save_project(self.script, project_path(folder, self.script.book_sha256))
            rows = web_ui._role_table_rows(self.script)
            next(row for row in rows if row[0] == 'char_1')[4] = .81
            web_ui._remember_role_confirmation(str(path), 'old')
            result = web_ui.apply_chapter_narration(str(path), rows, 1, 'char_1')
            self.assertIn('已保存', result[1])
            self.assertFalse(result[2])
            self.assertEqual(web_ui._recall_role_confirmation(str(path)), '')
            loaded, report = web_ui._load_uploaded_role_script(str(path))
            self.assertTrue(report.ok)
            self.assertEqual(loaded.roles['char_1'].provider_params['speed'], .81)
            self.assertEqual(loaded.chapters[0].segments[0].role_id, 'char_1')
            self.assertEqual(loaded.chapters[0].segments[1], self.script.chapters[0].segments[1])
            self.assertIn('林黛玉', result[5]['value'])

    def test_failed_save_retains_file_and_prior_confirmation_for_both_review_paths(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(web_ui, 'get_output_dir', return_value=folder):
            path = save_project(self.script, project_path(folder, self.script.book_sha256))
            original = path.read_bytes()
            web_ui._remember_role_confirmation(str(path), 'old')
            with patch.object(web_ui, 'save_project', side_effect=OSError('disk full')):
                bulk = web_ui.apply_chapter_narration(str(path), web_ui._role_table_rows(self.script), 1, 'char_1')
                individual = web_ui.apply_role_review(str(path), 'confirm', 'ch1_s2', 'char_1', None, None)
            self.assertIn('disk full', bulk[1])
            self.assertIn('disk full', individual[2])
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(web_ui._recall_role_confirmation(str(path)), 'old')

    def test_individual_review_does_not_discard_unsaved_voice_settings(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(web_ui, 'get_output_dir', return_value=folder):
            path = save_project(self.script, project_path(folder, self.script.book_sha256))
            rows = web_ui._role_table_rows(self.script)
            next(row for row in rows if row[0] == 'char_1')[4] = .88
            result = web_ui.apply_role_review(str(path), 'confirm', 'ch1_s2', 'char_1', None, None, rows)
            self.assertIn('已保存', result[2])
            loaded, report = web_ui._load_uploaded_role_script(str(path))
            self.assertTrue(report.ok)
            self.assertEqual(loaded.roles['char_1'].provider_params['speed'], .88)

    def test_running_batch_and_external_project_cannot_be_modified(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(web_ui, 'get_output_dir', return_value=folder):
            path = save_project(self.script, project_path(folder, self.script.book_sha256))
            original = path.read_bytes()
            with patch.object(web_ui, 'running_process', SimpleNamespace(is_alive=lambda: True)), \
                 patch.object(web_ui, 'save_project') as save:
                result = web_ui.apply_chapter_narration(str(path), None, 1, 'char_1')
                self.assertIn('当前生成', result[1])
                save.assert_not_called()
            external = save_project(self.script, Path(folder) / 'external.json')
            result = web_ui.apply_chapter_narration(str(external), None, 1, 'char_1')
            self.assertIn('自动生成的 V2 项目', result[1])
            self.assertEqual(path.read_bytes(), original)

    def test_controls_disable_legacy_and_show_only_narration_chapters(self):
        report = web_ui.ValidationReport(schema_version=2)
        with patch.object(web_ui, '_load_uploaded_role_script', return_value=(self.script, report)):
            chapter, entity, button, status = web_ui.load_narration_controls('test.json')
            self.assertEqual(chapter['value'], 1)
            self.assertEqual(entity['value'], 'narrator')
            self.assertTrue(button['interactive'])
            self.assertIn('1 段叙述', status)
        legacy, _ = _script()
        with patch.object(web_ui, '_load_uploaded_role_script', return_value=(legacy, report)):
            chapter, entity, button, status = web_ui.load_narration_controls('test.json')
            self.assertFalse(button['interactive'])
            self.assertFalse(chapter['interactive'])
            self.assertIn('重新拆分', status)


if __name__ == '__main__':
    unittest.main()
