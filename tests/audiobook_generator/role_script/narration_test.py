"""第一人称叙述归属到人物声音；离线模型替身，不发送书籍或合成请求。"""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from audiobook_generator.role_script import deepseek_splitter as splitter
from audiobook_generator.role_script.loader import parse_role_script
from audiobook_generator.role_script.errors import ValidationReport
from audiobook_generator.role_script.models import CharacterEntity, ChapterScript, RoleDefinition, RoleScriptV1, SegmentScript
from audiobook_generator.role_script.narration import request_narration_context, complete_narration_evidence, ground_narration_segments
from audiobook_generator.role_script.planner import build_synthesis_plans
from audiobook_generator.role_script.project_store import load_project, save_project
from audiobook_generator.role_script.review import confirm_segment_speaker
from audiobook_generator.role_script.v2_generation import generate_v2_for_book, upgrade_generated_script


def response(payload):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])


def narrator(role_id, name, quote, gender='unknown'):
    return {'perspective': 'character', 'narrators': [{
        'role_id': role_id, 'display_name': name, 'gender': gender,
        'evidence': [{'quote': quote, 'kind': 'narrator_identity'}]}]}


class NarrationTest(unittest.TestCase):
    def test_present_role_with_unknown_gender_keeps_female_chapter_identity(self):
        source = 'I am Juli. I waited for Bryce.'
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(
            return_value=response(narrator('juli', 'Juli', 'I am Juli.', 'female'))))))
        # 角色已存在于分段结果时，原先 setdefault 不会补回女性信息。
        payload = {'roles': {'other': {'display_name': 'Other'},
                             'juli': {'display_name': 'Juli', 'gender': 'unknown'}},
                   'segments': [{'role_id': 'juli', 'text_kind': 'narration', 'text': source}]}
        with patch.object(splitter, '_create_client', return_value=client), \
             patch.object(splitter, '_request_chunk', return_value=payload):
            result = splitter.split_chapters_with_deepseek([('Two', source)], 1, 1, 'openai',
                'a' * 64, 'dummy', 'https://example.invalid', 'test', analyze_narration=True)
        self.assertEqual(result.roles['juli'].gender, 'female')
        self.assertIn(result.roles['juli'].provider_params['voice'], ('Chloe', 'Mia'))
        self.assertEqual(result.chapters[0].segments[0].role_id, 'juli')
        self.assertEqual(client.chat.completions.create.call_count, 1)
        upgraded = upgrade_generated_script(result, [('Two', source)], {
            'narrator': CharacterEntity('Narrator'), 'stable_juli': CharacterEntity('Juli')},
            parser_fingerprint='parser', model='test')
        plans = build_synthesis_plans(upgraded, [('Two', source)], expected_book_sha256='a' * 64,
            provider='openai', chapter_start=1, chapter_end=1, output_format='wav')
        self.assertTrue(plans.ok)
        self.assertEqual(plans.plans[0].units[0].role_id, 'stable_juli')
        self.assertIn(plans.plans[0].units[0].profile.provider_params['voice'], ('Chloe', 'Mia'))

    def test_missing_kind_uses_existing_retry_budget_and_keeps_character_identity(self):
        source = 'I am Alex. He walked away.'
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(
            return_value=response(narrator('alex', 'Alex', 'I am Alex.'))))))
        incomplete = {'roles': {'alex': {'display_name': 'Alex'}},
                      'segments': [{'role_id': 'alex', 'text': source}]}
        complete = {'roles': {}, 'segments': [{'role_id': 'alex', 'text_kind': 'narration', 'text': source}]}
        with patch.object(splitter, '_create_client', return_value=client), \
             patch.object(splitter, '_request_chunk', side_effect=[incomplete, complete]) as request:
            result = splitter.split_chapters_with_deepseek([('One', source)], 1, 1, 'openai',
                'a' * 64, 'dummy', 'https://example.invalid', 'test', analyze_narration=True)
        self.assertEqual(request.call_count, splitter.MAX_ATTEMPTS_PER_CHUNK)
        self.assertNotIn('validation_feedback', request.call_args_list[0].kwargs['narration_context'])
        self.assertIn('text_kind', request.call_args_list[1].kwargs['narration_context']['validation_feedback'])
        segment = result.chapters[0].segments[0]
        self.assertEqual((segment.role_id, segment.text_kind, segment.text), ('alex', 'narration', source))
        self.assertEqual(segment.evidence_candidates, (('I am Alex.', 'narrator_identity'),))

    def test_missing_kind_feedback_reaches_model_and_corrected_response_is_used(self):
        source = 'I am Alex. He walked away.'
        incomplete = {'roles': {'alex': {'display_name': 'Alex'}},
                      'segments': [{'role_id': 'alex', 'text': source}]}
        complete = {'roles': {'alex': {'display_name': 'Alex'}},
                    'segments': [{'role_id': 'alex', 'text_kind': 'narration', 'text': source}]}
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(side_effect=[
            response(narrator('alex', 'Alex', 'I am Alex.')), response(incomplete), response(complete)]))))
        with patch.object(splitter, '_create_client', return_value=client):
            result = splitter.split_chapters_with_deepseek([('One', source)], 1, 1, 'openai',
                'a' * 64, 'dummy', 'https://example.invalid', 'test', analyze_narration=True)
        calls = client.chat.completions.create.call_args_list
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(calls[1].kwargs['messages']), 2)
        self.assertEqual(len(calls[2].kwargs['messages']), 3)
        self.assertIn('text_kind', calls[2].kwargs['messages'][-1]['content'])
        segment = result.chapters[0].segments[0]
        self.assertEqual((segment.role_id, segment.text_kind, segment.text), ('alex', 'narration', source))

    def test_repeated_missing_kind_preserves_source_as_unknown_without_extra_retry(self):
        source = 'I am Alex. He walked away.'
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(
            return_value=response(narrator('alex', 'Alex', 'I am Alex.'))))))
        incomplete = {'roles': {'alex': {'display_name': 'Alex'}},
                      'segments': [{'role_id': 'alex', 'text': source}]}
        report = ValidationReport()
        with patch.object(splitter, '_create_client', return_value=client), \
             patch.object(splitter, '_request_chunk', return_value=incomplete) as request:
            result = splitter.split_chapters_with_deepseek([('One', source)], 1, 1, 'openai',
                'a' * 64, 'dummy', 'https://example.invalid', 'test', analyze_narration=True, report=report)
        self.assertEqual(request.call_count, splitter.MAX_ATTEMPTS_PER_CHUNK)
        segment = result.chapters[0].segments[0]
        self.assertEqual((segment.role_id, segment.text_kind, segment.text), ('alex', 'unknown', source))
        self.assertEqual(result.roles['alex'].display_name, 'Alex')
        self.assertTrue(any(w.code == 'deepseek_chunk_partial' for w in report.warnings))

    def test_chapter_identity_reused_only_for_explicitly_selected_candidate(self):
        source = 'I am Alex. He walked away. I am Blair.'
        context = {'chapter_narration': narrator('alex', 'Alex', 'I am Alex.')}
        segments = [SegmentScript(role_id, 'He walked away.', text_kind=kind)
                    for role_id, kind in [('alex', 'narration'), ('narrator', 'narration'),
                                          ('other', 'narration'), ('alex', 'dialogue'), ('alex', 'unknown')]]
        result = ground_narration_segments(complete_narration_evidence(segments, source, context), source)
        self.assertEqual([s.role_id for s in result], ['alex', 'narrator', 'narrator', 'alex', 'alex'])
        self.assertEqual(result[0].evidence_candidates, (('I am Alex.', 'narrator_identity'),))
        self.assertTrue(all(not s.evidence_candidates for s in result[1:]))
        self.assertTrue(all(not s.evidence_candidates for s in segments))

    def test_chapter_identity_cannot_leak_across_chapters_or_third_person(self):
        segment = SegmentScript('alex', 'He walked away.', text_kind='narration')
        context = {'chapter_narration': narrator('alex', 'Alex', 'I am Alex.')}
        result = ground_narration_segments(complete_narration_evidence([segment], segment.text, context), segment.text)
        self.assertEqual(result[0].role_id, 'narrator')
        context['chapter_narration']['perspective'] = 'third_person'
        source = 'I am Alex. He walked away.'
        result = ground_narration_segments(complete_narration_evidence([segment], source, context), source)
        self.assertEqual(result[0].role_id, 'narrator')

    def test_mixed_viewpoints_keep_explicit_id_and_existing_valid_identity(self):
        source = 'I am Alex. I am Blair. Alex is my name.'
        context = {'chapter_narration': {'perspective': 'mixed', 'narrators': [
            *narrator('alex', 'Alex', 'I am Alex.')['narrators'],
            *narrator('blair', 'Blair', 'I am Blair.')['narrators']]}}
        segments = [SegmentScript('alex', 'I am Alex.', text_kind='narration',
                                 evidence_candidates=(('Alex is my name.', 'narrator_identity'),)),
                    SegmentScript('blair', 'I am Blair.', text_kind='narration')]
        result = complete_narration_evidence(segments, source, context)
        self.assertEqual(result[0].evidence_candidates, segments[0].evidence_candidates)
        self.assertEqual(result[1].evidence_candidates, (('I am Blair.', 'narrator_identity'),))
        self.assertEqual([s.role_id for s in result], ['alex', 'blair'])

    def test_two_perspectives_reuse_character_voice_through_save_and_synthesis_plan(self):
        chapters = [('One', 'I am Alex. I waited. “Hello,” I said.'),
                    ('Two', 'I am Blair. I arrived. “Wait,” I said.')]
        payloads = []
        for role_id, name, gender, (_title, source), split_at in [
                ('alex', 'Alex', 'male', chapters[0], 20),
                ('blair', 'Blair', 'female', chapters[1], 22)]:
            quote = f'I am {name}.'
            payloads.extend([narrator(role_id, name, quote, gender), {
                'roles': {role_id: {'display_name': name, 'gender': gender}},
                'segments': [
                    {'role_id': role_id, 'text_kind': 'narration', 'text': source[:split_at],
                     'evidence': [] if name == 'Alex' else [{'quote': quote, 'kind': 'narrator_identity'}]},
                    {'role_id': role_id, 'text_kind': 'dialogue', 'text': source[split_at:]}]}])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
            create=Mock(side_effect=[response(p) for p in payloads]))))
        with patch.object(splitter, '_create_client', return_value=client), \
             patch('audiobook_generator.role_script.v2_generation._request_character_chunk',
                   return_value=[{'name': 'Alex'}, {'name': 'Blair'}]):
            script = generate_v2_for_book(chapters, 1, 2, 'openai', 'a' * 64, 'dummy',
                'https://example.invalid', 'test', parser_fingerprint='parser', index_full_book=False)
        self.assertEqual(client.chat.completions.create.call_count, 4)
        ids = [chapter.segments[0].role_id for chapter in script.chapters]
        self.assertNotEqual(*ids)
        for chapter, expected in zip(script.chapters, ['Alex', 'Blair']):
            self.assertEqual([s.text_kind for s in chapter.segments], ['narration', 'dialogue'])
            self.assertEqual(len({s.role_id for s in chapter.segments}), 1)
            self.assertEqual(script.roles[chapter.segments[0].role_id].display_name, expected)
            self.assertEqual(chapter.segments[0].speaker.status, 'proposed')
            self.assertEqual(''.join(s.text for s in chapter.segments), chapters[chapter.chapter_index - 1][1])
        # 重新载入与计划阶段不能把人物叙述改回默认旁白。
        with tempfile.TemporaryDirectory() as folder:
            path = save_project(script, Path(folder) / 'project.json')
            loaded = load_project(path, book_sha256='a' * 64)
        plans = build_synthesis_plans(loaded, chapters, expected_book_sha256='a' * 64,
            provider='openai', chapter_start=1, chapter_end=2, output_format='wav')
        self.assertTrue(plans.ok, plans.report.to_dict())
        voices = []
        for plan, role_id in zip(plans.plans, ids):
            self.assertTrue(all(unit.role_id == role_id for unit in plan.units))
            self.assertEqual(len({unit.profile.provider_params['voice'] for unit in plan.units}), 1)
            voices.append(plan.units[0].profile.provider_params['voice'])
        self.assertNotEqual(*voices)

    def _upgrade(self, segments, source, previous=None):
        roles = {'narrator': RoleDefinition('Narrator', {'voice': 'Milo'}),
                 'alex': RoleDefinition('Alex', {'voice': 'Dean'}, 'male')}
        generated = RoleScriptV1(1, 'openai', 'a' * 64, 250, roles,
                                (ChapterScript(1, 'One', tuple(segments)),))
        return upgrade_generated_script(generated, [('One', source)],
            {'narrator': CharacterEntity('Narrator'), 'alex': CharacterEntity('Alex')},
            parser_fingerprint='parser', model='test', previous=previous)

    def test_missing_or_fabricated_identity_evidence_falls_back_for_review(self):
        for candidates in [(), (('invented quote', 'narrator_identity'),), (('I waited.', 'coreference'),)]:
            script = self._upgrade([SegmentScript('alex', 'I waited.', text_kind='narration',
                                    evidence_candidates=candidates)], 'I waited.')
            segment = script.chapters[0].segments[0]
            self.assertEqual(segment.role_id, 'narrator')
            self.assertEqual(segment.speaker.status, 'needs_review')
            self.assertEqual(segment.speaker.confidence, 0)

    def test_identity_evidence_can_be_elsewhere_in_same_chapter(self):
        prefix = 'I am Alex. ' + 'We waited by the gate. ' * 50
        source = prefix + 'Then I left.'
        script = self._upgrade([
            SegmentScript('narrator', prefix, text_kind='unknown'),
            SegmentScript('alex', 'Then I left.', text_kind='narration',
                          evidence_candidates=(('I am Alex.', 'narrator_identity'),))], source)
        segment = script.chapters[0].segments[1]
        self.assertGreater(segment.source_span.start, 600)
        self.assertEqual(segment.role_id, 'alex')
        self.assertEqual(segment.speaker.evidence[0].span.start, 0)

    def test_reanalysis_preserves_human_decision_but_not_old_machine_default(self):
        source = 'I am Alex.'
        legacy = self._upgrade([SegmentScript('narrator', source)], source)
        new = [SegmentScript('alex', source, text_kind='narration',
                             evidence_candidates=((source, 'narrator_identity'),))]
        self.assertEqual(self._upgrade(new, source, previous=legacy).chapters[0].segments[0].role_id, 'alex')
        human = confirm_segment_speaker(legacy, legacy.chapters[0].segments[0].segment_id, 'narrator')
        retained = self._upgrade(new, source, previous=human).chapters[0].segments[0]
        self.assertEqual(retained.role_id, 'narrator')
        self.assertEqual(retained.speaker.confidence_kind, 'human')

    def test_preanalysis_failure_is_once_per_selected_chapter_and_does_not_leak_viewpoint(self):
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(side_effect=RuntimeError('offline')))))
        contexts = []
        def chunk(client, model, chapter_index, title, text, provider, language, narration_context):
            contexts.append(narration_context)
            return {'roles': {}, 'segments': [{'role_id': 'narrator', 'text_kind': 'narration', 'text': text}]}
        with patch.object(splitter, '_create_client', return_value=client), patch.object(splitter, '_request_chunk', side_effect=chunk):
            report = ValidationReport()
            script = splitter.split_chapters_with_deepseek([('Skip', 'private'), ('B', 'I waited.'), ('C', 'I left.')],
                2, 3, 'openai', 'a' * 64, 'dummy', 'https://example.invalid', 'test', analyze_narration=True, report=report)
        self.assertEqual(client.chat.completions.create.call_count, 2)
        self.assertTrue(all('chapter_narration' not in context for context in contexts))
        self.assertTrue(all(s.role_id == 'narrator' for c in script.chapters for s in c.segments))
        for call in client.chat.completions.create.call_args_list:
            self.assertNotIn('private', call.kwargs['messages'][1]['content'])
        self.assertEqual([w.code for w in report.warnings].count('narrator_analysis_failed'), 2)

    def test_long_chapter_preanalysis_is_bounded_and_rejects_unlocatable_evidence(self):
        source = 'I am Alex.' + 'x' * 30000 + 'The end.'
        raw = narrator('alex', 'Alex', 'made up')
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(return_value=response(raw)))))
        result = request_narration_context(client, 'test', 1, 'One', source, [])
        self.assertEqual(result['narrators'], [])
        from audiobook_generator.role_script.context_budget import check_messages
        calls = client.chat.completions.create.call_args_list
        self.assertGreater(len(calls), 1)
        parts = []
        for call in calls:
            check_messages(call.kwargs['messages'], call.kwargs['max_tokens'])
            parts.append(call.kwargs['messages'][1]['content'].split('\n原文：\n', 1)[1])
        self.assertEqual(''.join(parts), source)

    def test_invalid_kind_is_rejected_and_legacy_field_remains_optional(self):
        source = 'I waited.'
        script = self._upgrade([SegmentScript('narrator', source)], source)
        raw = splitter.role_script_to_dict(script)
        for kind in ['bad', [], 42]:
            raw['chapters'][0]['segments'][0]['text_kind'] = kind
            report = ValidationReport()
            self.assertIsNone(parse_role_script(raw, report))
            self.assertFalse(report.ok)
        raw['chapters'][0]['segments'][0].pop('text_kind')
        report = ValidationReport()
        self.assertIsNotNone(parse_role_script(raw, report))
        self.assertTrue(report.ok)


if __name__ == '__main__':
    unittest.main()
