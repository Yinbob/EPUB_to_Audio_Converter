"""归属保存结果与人物工具的离线工作流回归。"""
import tempfile
import unittest
from dataclasses import replace
from unittest.mock import patch

from audiobook_generator.ui import web_ui
from audiobook_generator.ui.role_studio import review_notice
from audiobook_generator.role_script.models import CharacterEntity, RoleDefinition, SpeakerDecision
from audiobook_generator.role_script.project_store import project_path, save_project
from tests.audiobook_generator.role_script.v2_io_test import _script


class AttributionWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patcher = patch.object(web_ui, 'get_output_dir', return_value=self.temp.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        script, _ = _script()
        roles = {**script.roles, 'char_2': RoleDefinition('黛玉', {'voice': '冰糖', 'speed': 1.0})}
        entities = {**script.entities, 'char_2': CharacterEntity('黛玉', voice_profile_id='voice_2')}
        chapter = script.chapters[0]
        self.script = replace(script, roles=roles, entities=entities, chapters=(replace(chapter, segments=(
            replace(chapter.segments[0], text_kind='narration'),
            replace(chapter.segments[1], role_id='char_2', speaker=SpeakerDecision('char_2', 'proposed', .5)),
        )),))
        self.path = str(save_project(self.script, project_path(self.temp.name, self.script.book_sha256)))

    def test_merge_preview_does_not_save_and_result_survives_details_refresh(self):
        preview, button = web_ui.preview_role_merge(self.path, 'char_2', 'char_1')
        self.assertTrue(button['interactive'])
        self.assertIn('黛玉 → 林黛玉', preview)
        self.assertIn('1 段', preview)
        self.assertIn('char_2', web_ui._load_uploaded_role_script(self.path)[0].entities)
        web_ui._remember_role_confirmation(self.path, 'old')
        events = web_ui.apply_role_review_ui(self.path, 'merge', None, None, 'char_2', 'char_1', [])
        initial = next(events)
        self.assertIn('data-state="pending"', initial[2])
        self.assertFalse(initial[-1]['interactive'])
        self.assertIn('char_2', web_ui._load_uploaded_role_script(self.path)[0].entities)
        saved = next(events)
        self.assertIn('data-state="success"', saved[2])

        self.assertIn('黛玉', saved[2])
        self.assertIn('林黛玉', saved[2])
        self.assertFalse(saved[3])
        self.assertTrue(saved[-1]['interactive'])
        loaded, report = web_ui._load_uploaded_role_script(self.path)
        self.assertTrue(report.ok)
        self.assertNotIn('char_2', loaded.entities)
        self.assertEqual(loaded.roles['char_1'], self.script.roles['char_1'])
        for picker in web_ui.refresh_review_people(self.path):
            self.assertNotIn('char_2', [value for _, value in picker['choices']])
        # 详情刷新与保存结果使用不同控件和返回值，不再互相覆盖。
        details = web_ui.role_review_details(self.path, 'ch1_s2')
        self.assertIn('林黛玉', details)
        self.assertIn('data-state="success"', saved[2])

    def test_narrator_is_selectable_for_segment_and_lock_but_never_merge(self):
        _, people, sources, targets, _ = web_ui.load_role_review(self.path)
        self.assertIn('narrator', [value for _, value in people['choices']])
        for picker in (sources, targets):
            self.assertNotIn('narrator', [value for _, value in picker['choices']])
        people, sources, targets, lock = web_ui.refresh_review_people(self.path)
        for picker in (people, lock):
            self.assertIn('narrator', [value for _, value in picker['choices']])
        for picker in (sources, targets):
            self.assertNotIn('narrator', [value for _, value in picker['choices']])

    def test_merge_candidates_follow_chapter_and_whole_book_toggle(self):
        first = self.script.chapters[0]
        second = replace(first, chapter_index=2, segments=(
            replace(first.segments[1], role_id='char_1', segment_id='ch2_s1'),))
        script = replace(self.script, chapters=(first, second))
        with patch.object(web_ui, '_load_uploaded_role_script', return_value=(script, web_ui.ValidationReport(schema_version=2))):
            people, source, target, _ = web_ui.refresh_review_people(self.path, 1)
            self.assertEqual(source['choices'], target['choices'])
            self.assertEqual(source['choices'], [c for c in people['choices'] if c[1] != 'narrator'])
            self.assertEqual([key for _, key in source['choices']], ['char_2'])
            self.assertIn('本章 1 段', source['choices'][0][0])
            expanded = web_ui.refresh_review_people(self.path, 1, True)[1]
            self.assertEqual({key for _, key in expanded['choices']}, {'char_1', 'char_2'})
            self.assertTrue(any('本章 0 段' in label and key == 'char_1' for label, key in expanded['choices']))
            other = web_ui.refresh_review_people(self.path, 2)[1]
            self.assertEqual([key for _, key in other['choices']], ['char_1'])
            self.assertNotIn('narrator', [key for _, key in expanded['choices']])
            # 初始化/刷新入口也必须遵循相同范围，而非短暂返回全书列表。
            self.assertEqual(web_ui.load_role_review(self.path, 1)[2]['choices'], source['choices'])

    def test_invalid_merge_and_write_failure_do_not_show_success(self):
        _, button = web_ui.preview_role_merge(self.path, 'char_2', 'char_2')
        self.assertFalse(button['interactive'])
        _, button = web_ui.preview_role_merge(self.path, 'narrator', 'char_1')
        self.assertFalse(button['interactive'])
        web_ui._remember_role_confirmation(self.path, 'old')
        with patch.object(web_ui, 'save_project', side_effect=OSError('disk full')):
            events = list(web_ui.apply_role_review_ui(self.path, 'merge', None, None, 'char_2', 'char_1', []))
        self.assertIn('data-state="error"', events[-1][2])
        self.assertIn('disk full', events[-1][2])
        self.assertEqual(web_ui._recall_role_confirmation(self.path), 'old')
        self.assertIn('char_2', web_ui._load_uploaded_role_script(self.path)[0].entities)

    def test_narration_save_feedback_and_notice_escaping(self):
        events = list(web_ui.apply_chapter_narration_ui(self.path, [], 1, 'char_1'))
        self.assertIn('data-state="pending"', events[0][1])
        self.assertIn('data-state="success"', events[1][1])
        self.assertIn('林黛玉', events[1][1])
        self.assertFalse(events[1][2])
        notice = review_notice('<script>bad</script>', 'error')
        self.assertNotIn('<script>', notice)
        self.assertIn('&lt;script&gt;', notice)


if __name__ == '__main__':
    unittest.main()
