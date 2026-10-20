"""人物检索、保存后继续及折叠原文上下文的离线回归。"""
import unittest
from dataclasses import replace
from unittest.mock import patch
from audiobook_generator.ui import web_ui
from audiobook_generator.role_script.review_context import CONTEXT_MAX_CHARS, segment_context, review_segments
from audiobook_generator.role_script.models import SegmentScript, ChapterScript, SpeakerDecision
from audiobook_generator.ui.role_voices import review_voice_identity, review_voice_choices
from tests.audiobook_generator.role_script.v2_io_test import _script


class SegmentFilterTest(unittest.TestCase):
    def setUp(self):
        self.script, _ = _script()
        old = self.script.chapters[0]
        segments = (
            SegmentScript('char_1', '第一段叙述。', segment_id='one', text_kind='narration', speaker=SpeakerDecision('char_1', 'confirmed')),
            SegmentScript('narrator', '旁白。', segment_id='two', text_kind='narration', speaker=SpeakerDecision('narrator', 'proposed')),
            SegmentScript('char_1', '她说你好。', segment_id='three', text_kind='dialogue', speaker=SpeakerDecision('char_1', 'proposed')))
        self.script = replace(self.script, chapters=(replace(old, segments=segments),))
        patcher = patch.object(web_ui, '_load_uploaded_role_script', return_value=(self.script, web_ui.ValidationReport(schema_version=2)))
        patcher.start(); self.addCleanup(patcher.stop)

    def test_shared_chapter_counts_candidates_and_segments(self):
        first = replace(self.script.chapters[0], segments=(self.script.chapters[0].segments[0],))
        second = replace(first, chapter_index=2, title='Second', segments=(
            SegmentScript('narrator', '另一章旁白。', segment_id='other', text_kind='narration'),))
        script = replace(self.script, chapters=(first, second))
        with patch.object(web_ui, '_load_uploaded_role_script', return_value=(script, web_ui.ValidationReport(schema_version=2))):
            for chapter, expected in ((1, 'char_1'), (2, 'narrator')):
                narrator = web_ui.load_narration_controls('x', chapter)[1]
                people, voices, segments, _ = web_ui.filter_role_review_with_voice('x', chapter_index=chapter)
                assignment = web_ui.review_assignment_choices('x', chapter)
                self.assertEqual([key for _, key in narrator['choices']], [expected])
                self.assertEqual(narrator['choices'], assignment['choices'])
                self.assertEqual(people['choices'][1:], narrator['choices'])
                self.assertTrue(all('本章 1 段' in label for label, _ in narrator['choices']))
                self.assertEqual(len(segments['choices']), 1)
                self.assertEqual(len(voices['choices']), 2)
            expanded = web_ui.load_narration_controls('x', 1, True)[1]
            self.assertEqual(len(expanded['choices']), 2)
            self.assertTrue(any('本章 0 段' in label and key == 'narrator' for label, key in expanded['choices']))
            # 展开候选范围不会将其他章的段落混入当前章。
            self.assertEqual(len(web_ui.filter_role_review_with_voice('x', chapter_index=1, show_all=True)[2]['choices']), 1)
            next_segment = web_ui.filter_role_review('x', selected='one', advance=True, chapter_index=1)[1]
            self.assertEqual(next_segment['value'], 'one')
            dialogue = replace(script, chapters=(replace(first, segments=(replace(first.segments[0], text_kind='dialogue'),)),))
            with patch.object(web_ui, '_load_uploaded_role_script', return_value=(dialogue, web_ui.ValidationReport(schema_version=2))):
                controls = web_ui.load_narration_controls('x', 1)
                self.assertTrue(controls[0]['interactive'])
                self.assertFalse(controls[2]['interactive'])

    def test_person_filter_includes_confirmed_and_scope_switches(self):
        person, choices, _ = web_ui.filter_role_review('x', 'char_1', 'all')
        self.assertEqual([key for _label, key in choices['choices']], ['one', 'three'])
        self.assertEqual(person['value'], 'char_1')
        for scope in ('pending', 'dialogue'):
            self.assertEqual([s.segment_id for _c, s in review_segments(self.script, 'char_1', scope)], ['three'])
        self.assertEqual(web_ui.filter_role_review('x', 'deleted')[0]['value'], '__all__')

    def test_save_next_stays_with_current_person_and_handles_empty(self):
        result = web_ui.filter_role_review('x', 'char_1', 'all', 'one', advance=True)
        self.assertEqual(result[1]['value'], 'three')
        result = web_ui.filter_role_review('x', 'char_1', 'pending', 'three', advance=True)
        self.assertEqual(result[1]['value'], 'three')
        result = web_ui.filter_role_review('x', 'narrator', 'dialogue')
        self.assertIsNone(result[1]['value']); self.assertIn('没有段落', result[2])
        emptied = replace(self.script, chapters=(replace(self.script.chapters[0], segments=tuple(
            replace(s, role_id='narrator') for s in self.script.chapters[0].segments)),))
        with patch.object(web_ui, '_load_uploaded_role_script', return_value=(emptied, web_ui.ValidationReport(schema_version=2))):
            person, segments, notice = web_ui.filter_role_review('x', 'char_1', 'all', 'one', advance=True)
        self.assertEqual(person['value'], 'char_1')
        self.assertEqual(segments['choices'], [])
        self.assertIsNone(segments['value']); self.assertIn('没有段落', notice)

    def test_voice_filter_combines_person_scope_and_save_next(self):
        key, label = review_voice_identity(self.script, 'char_1')
        self.assertEqual(label, '茉莉')
        person, voice, segments, detail = web_ui.filter_role_review_with_voice('x', '__all__', 'all', voice=key)
        self.assertEqual(voice['value'], key)
        self.assertEqual([value for _label, value in segments['choices']], ['one', 'three'])
        self.assertIn('配置音色', detail)
        self.assertIn('茉莉', detail)
        self.assertEqual([value for _label, value in web_ui.filter_role_review_with_voice('x', 'char_1', 'pending', voice=key)[2]['choices']], ['three'])
        empty = web_ui.filter_role_review_with_voice('x', 'narrator', 'all', voice=key)
        self.assertEqual(empty[1]['value'], key)
        self.assertIsNone(empty[2]['value']); self.assertIn('没有段落', empty[3])
        next_segment = web_ui.filter_role_review('x', 'char_1', 'all', 'one', advance=True, voice=key)[1]
        self.assertEqual(next_segment['value'], 'three')
        self.assertEqual(web_ui.filter_role_review_with_voice('x', voice='removed')[1]['value'], '__all__')

    def test_voice_filter_uses_current_table_without_saving(self):
        rows = web_ui._role_table_rows(self.script)
        next(row for row in rows if row[0] == 'char_1')[2] = 'Chloe'
        _person, voice, _segments, detail = web_ui.filter_role_review_with_voice('x', 'char_1', table=rows)
        self.assertTrue(any('Chloe' in label for label, _key in voice['choices']))
        self.assertIn('Chloe', detail)
        self.assertEqual(self.script.roles['char_1'].provider_params['voice'], '茉莉')

    def test_voice_groups_shared_presets_and_reference_fingerprints(self):
        base = self.script.roles['char_1']
        roles = dict(self.script.roles)
        roles['narrator'] = replace(base, display_name='旁白', provider_params={**base.provider_params, 'speed': .8})
        shared = replace(self.script, roles=roles)
        self.assertEqual(review_voice_identity(shared, 'char_1')[0], review_voice_identity(shared, 'narrator')[0])
        self.assertIn('3 段', review_voice_choices(shared)[1][0])
        roles = {key: replace(role, provider_params={'voice_mode': 'clone', 'reference_audio_sha256': 'a'*64,
                  'reference_audio_path': '/different/' + key + '.wav'}) for key, role in roles.items()}
        clones = replace(self.script, roles=roles)
        self.assertEqual(review_voice_identity(clones, 'char_1')[0], review_voice_identity(clones, 'narrator')[0])
        roles['narrator'] = replace(roles['narrator'], provider_params={'voice_mode': 'clone', 'reference_audio_sha256': 'b'*64})
        self.assertNotEqual(review_voice_identity(replace(clones, roles=roles), 'char_1')[0], review_voice_identity(replace(clones, roles=roles), 'narrator')[0])

    def test_details_context_is_closed_escaped_and_same_chapter(self):
        chapter = ChapterScript(1, 'One', (
            SegmentScript('narrator', '<script>bad</script>' + '前文。'*160, segment_id='before'),
            SegmentScript('char_1', '相同句。', segment_id='target'),
            SegmentScript('narrator', '后文。'*160 + '<img src=x>', segment_id='after')))
        before, after = segment_context(chapter, 'target')
        for context in (before, after):
            self.assertGreaterEqual(len(context), 180)
            self.assertLessEqual(len(context), CONTEXT_MAX_CHARS + 1)
        self.assertTrue(before.startswith('…')); self.assertTrue(after.endswith('…'))
        for segment_id in ('one', 'three'):
            detail = web_ui.role_review_details('x', segment_id)
            self.assertIn('<details class="role-segment-context">', detail)
            self.assertNotIn('<details open', detail)
            self.assertIn('每侧最多 300 字符', detail)
        self.assertIn('<strong>【当前段落】她说你好。</strong>', detail)
        repeated = replace(chapter, segments=(SegmentScript('narrator','first.',segment_id='a'),
            SegmentScript('narrator','same.',segment_id='b'), SegmentScript('narrator','second.',segment_id='c'),
            SegmentScript('narrator','same.',segment_id='d'), SegmentScript('narrator','last.',segment_id='e')))
        before, after = segment_context(repeated, 'd')
        self.assertTrue(before.endswith('second.')); self.assertEqual(after, 'last.')
        escaped = replace(chapter, segments=(
            SegmentScript('narrator', '<img src=x onerror=bad>', segment_id='a'),
            SegmentScript('char_1', 'target', segment_id='b'),
            SegmentScript('narrator', '<script>bad</script>', segment_id='c')))
        with patch.object(web_ui, '_load_uploaded_role_script', return_value=(
                replace(self.script, chapters=(escaped,)), web_ui.ValidationReport(schema_version=2))):
            detail = web_ui.role_review_details('x', 'b')
        self.assertNotIn('<img', detail); self.assertNotIn('<script>', detail)
        self.assertIn('&lt;script&gt;', detail)

    def test_english_context_keeps_words_and_segment_breaks(self):
        chapter = ChapterScript(1, 'English', (
            SegmentScript('narrator', 'These are the earlier words without punctuation ' * 15, segment_id='a'),
            SegmentScript('char_1', 'Previous sentence.', segment_id='b'),
            SegmentScript('char_1', 'Target sentence.', segment_id='target'),
            SegmentScript('narrator', 'Next sentence.', segment_id='c'),
            SegmentScript('narrator', 'These are the following words without punctuation ' * 15, segment_id='d')))
        before, after = segment_context(chapter, 'target')
        self.assertIn('\nPrevious sentence.', before)
        self.assertIn('Next sentence.\n', after)
        self.assertIn(before[1:].split()[0], {'These', 'are', 'the', 'earlier', 'words', 'without', 'punctuation'})
        self.assertIn(after[:-1].split()[-1], {'These', 'are', 'the', 'following', 'words', 'without', 'punctuation'})
        for context in (before, after):
            self.assertGreaterEqual(len(context), 180)
            self.assertLessEqual(len(context), CONTEXT_MAX_CHARS + 1)


if __name__ == '__main__': unittest.main()
