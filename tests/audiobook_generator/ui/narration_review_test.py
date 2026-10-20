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

    def test_character_narration_is_default_voice_selection_but_manual_choice_is_kept(self):
        chapter = self.script.chapters[0]
        female = replace(self.script, chapters=(replace(chapter, segments=(
            replace(chapter.segments[0], role_id='char_1'), chapter.segments[1])),))
        self.assertEqual(web_ui._role_choice_update(female)['value'], 'char_1')
        self.assertEqual(web_ui._role_choice_update(female, 'narrator')['value'], 'narrator')
        self.assertIn('独立于人物自述', web_ui._role_choice_update(female)['choices'][0][0])
        report = web_ui.ValidationReport(schema_version=2)
        with patch.object(web_ui, '_load_uploaded_role_script', return_value=(female, report)):
            self.assertEqual(web_ui.select_chapter_narration_voice('test.json', 1)['value'], 'char_1')
            self.assertNotIn('value', web_ui.select_chapter_narration_voice('test.json', 99))
            self.assertIn('林黛玉（茉莉）', web_ui.load_narration_controls('test.json')[3])
        # 只有一个旁白或多视角时不能猜一个女性人物替换归属。
        self.assertEqual(web_ui._role_choice_update(self.script)['value'], 'narrator')

    def test_voice_selection_follows_alternating_chapters_without_changing_script(self):
        first = self.script.chapters[0]
        second = replace(first, chapter_index=2, segments=(replace(first.segments[0], role_id='char_1'), first.segments[1]))
        script = replace(self.script, chapters=(first, second))
        report = web_ui.ValidationReport(schema_version=2)
        with patch.object(web_ui, '_load_uploaded_role_script', return_value=(script, report)):
            self.assertEqual(web_ui.select_chapter_narration_voice('test.json', 1)['value'], 'narrator')
            self.assertEqual(web_ui.select_chapter_narration_voice('test.json', 2)['value'], 'char_1')
        self.assertEqual(script.chapters[0].segments[0].role_id, 'narrator')

    def test_requested_chapter_wins_over_first_saved_and_missing_never_falls_back(self):
        base = self.script.chapters[0]
        script = replace(self.script, chapters=(replace(base, chapter_index=5, title='First'),
                                               replace(base, chapter_index=11, title='Get a Grip, Man')))
        report = web_ui.ValidationReport(schema_version=2)
        with patch.object(web_ui, '_load_uploaded_role_script', return_value=(script, report)):
            chosen = web_ui.load_narration_controls('test.json', 11)
            self.assertEqual(chosen[0]['value'], 11)
            self.assertTrue(chosen[2]['interactive'])
            missing = web_ui.load_narration_controls('test.json', 12)
            self.assertEqual(missing[0]['value'], 12)
            self.assertIn('尚未生成剧本', missing[0]['choices'][-1][0])
            self.assertEqual(missing[1]['choices'], [])
            self.assertFalse(missing[1]['interactive'])
            self.assertFalse(missing[2]['interactive'])
            self.assertIn('第 12 章', missing[3])
            self.assertEqual(web_ui.filter_role_review_with_voice('test.json', chapter_index=12)[2]['choices'], [])
            self.assertEqual(web_ui.refresh_review_people('test.json', 12)[1]['choices'], [])

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
