"""长篇全书自动选声：离线模型替身、覆盖证据、断点和过期方案。"""
import copy
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from audiobook_generator.audio_core.hybrid_casting import hybrid_casting, role_usage
from audiobook_generator.role_script.models import CharacterEntity, RoleDefinition, SpeakerDecision, SegmentScript, ChapterScript, RoleScriptV2, SourceSpan
from audiobook_generator.role_script.project_store import chapter_hashes
from audiobook_generator.role_script.split_control import SplitControl, SplitAborted, split_control_scope
from audiobook_generator.ui.book_casting import BookCasting, coverage, draft_rows, fit_matrix, load_bank, read_json
from tests.audiobook_generator.audio_core.hybrid_casting_test import fixture, bank


def long_book():
    old = fixture()
    chapters = []
    for chapter in old.chapters:
        cursor, segments = 0, []
        for i, segment in enumerate(chapter.segments):
            segments.append(replace(segment, source_span=SourceSpan(chapter.chapter_index, cursor, cursor + len(segment.text)),
                segment_id=f'ch{chapter.chapter_index}_s{i}', speaker=SpeakerDecision(segment.role_id, 'proposed' if segment.role_id != 'narrator' else 'confirmed'),
                text_kind='narration' if segment.role_id in {'narrator', 'late'} else 'dialogue'))
            cursor += len(segment.text)
        chapters.append(replace(chapter, segments=tuple(segments)))
    parsed = [(c.title, ''.join(s.text for s in c.segments)) for c in chapters]
    script = RoleScriptV2(2, 'openai', old.book_sha256, 200, old.roles, tuple(chapters),
                         {r: CharacterEntity(r) for r in old.roles}, 'parser', chapter_hashes(parsed), True)
    return script, parsed


class CardsClient:
    def __init__(self, fail_at=None):
        self.calls = []
        self.fail_at = fail_at
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
    def create(self, **kwargs):
        context = json.loads(kwargs['messages'][1]['content'])
        self.calls.append(context)
        if len(self.calls) == self.fail_at:
            raise TimeoutError('offline request failed')
        cards = {role: {'voice_description': 'Clear middle register, neutral English articulation.',
                        'instructions': 'Read naturally.'} for role in context['roles']}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(cards)))])


class BookCastingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.full, self.parsed = long_book()
        self.source = replace(self.full, chapters=(self.full.chapters[0],))
        self.controller = BookCasting(self.temp.name, self.parsed, 'parser', self.source)

    def fake_generate(self, chapters, start, end, provider, book_sha, key, url, model, **kwargs):
        self.assertEqual(start, end)
        self.assertFalse(kwargs['index_full_book'])
        previous = kwargs['previous']
        return replace(self.full, chapters=tuple(sorted(previous.chapters + (self.full.chapters[start-1],), key=lambda c:c.chapter_index)))

    def complete(self):
        self.controller.analyze(api_key='dummy', base_url='https://example.invalid', model='mock', generate=self.fake_generate)

    def test_registry_and_hashes_cannot_claim_full_coverage(self):
        proof = self.controller.progress()
        self.assertEqual(proof['complete'], [1])
        self.assertEqual(len(proof['missing']), 11)
        self.assertFalse(proof['full_book'])
        with self.assertRaisesRegex(ValueError, '尚缺'):
            self.controller.make_draft(bank(), 'en', client=CardsClient(), model='mock')
        tampered = replace(self.full, chapters=(replace(self.full.chapters[0], segments=self.full.chapters[0].segments[:-1]),) + self.full.chapters[1:])
        self.assertNotIn(1, coverage(tampered, self.parsed, 'parser', self.full.book_sha256)['complete'])
        self.assertFalse(coverage(self.full, self.parsed, 'changed', self.full.book_sha256)['full_book'])

    def test_resume_keeps_completed_chapters_after_failure(self):
        calls = []
        def generate(*args, **kwargs):
            calls.append(args[1])
            if args[1] == 4:
                raise TimeoutError('offline timeout')
            return self.fake_generate(*args, **kwargs)
        with self.assertRaises(TimeoutError):
            self.controller.analyze(api_key='dummy', base_url='', model='mock', generate=generate)
        self.assertEqual(self.controller.progress()['complete'], [1, 2, 3])
        self.complete()
        self.assertTrue(self.controller.progress()['full_book'])
        self.assertEqual(self.source.chapters, (self.full.chapters[0],))
        calls = []
        self.controller.analyze(api_key='', base_url='', model='mock', generate=lambda *a, **kw: calls.append(a))
        self.assertFalse(calls)

    def test_cancel_discards_incomplete_chapter_but_resumes_prior_success(self):
        control = SplitControl()
        def generate(*args, **kwargs):
            if args[1] == 3:
                control.cancelled.set()
            return self.fake_generate(*args, **kwargs)
        with split_control_scope(control), self.assertRaises(SplitAborted):
            self.controller.analyze(api_key='dummy', base_url='', model='mock', generate=generate)
        self.assertEqual(self.controller.progress()['complete'], [1, 2])
        self.complete()
        self.assertTrue(self.controller.progress()['full_book'])

    def test_draft_counts_first_person_late_talker_and_gap_without_confirming(self):
        self.complete()
        usage, proof = self.controller.usage('en')
        self.assertEqual(usage['ranked_roles'][0], 'late')
        self.assertEqual(usage['roles']['guest']['gap_max'], 5)
        self.assertEqual(usage['roles']['late']['max_absent_chapters'], 9)
        self.assertGreater(usage['roles']['late']['pending_segments'], 0)
        draft = self.controller.make_draft(bank(), 'en', client=CardsClient(), model='mock')
        applied = self.controller.apply(bank(), draft['draft_id'], draft_rows(draft))
        self.assertEqual(applied.chapters, self.full.chapters)
        self.assertTrue(any(s.speaker.status == 'proposed' for c in applied.chapters for s in c.segments))
        self.assertEqual(draft['manifest']['profiles']['late']['voice_mode'], 'preset')
        self.assertEqual(draft['manifest']['usage']['scope_evidence'], 'parsed_chapter_text_verified')
        with self.assertRaisesRegex(ValueError, '待核验'):
            role_usage(self.full, language='en', full_book=True)

    def test_unknown_separate_and_no_false_interaction(self):
        chapter = self.full.chapters[0]
        unknown = replace(chapter.segments[0], role_id='narrator', speaker=SpeakerDecision(None, 'unknown'))
        script = replace(self.full, chapters=(replace(chapter, segments=(chapter.segments[1], unknown, chapter.segments[-1])),))
        usage = role_usage(script, language='en', attribution_policy='draft')
        self.assertEqual(usage['unassigned']['segments'], 1)
        self.assertEqual(usage['roles']['narrator']['reading_count'], 0)
        self.assertEqual(usage['edges'], [])
        self.assertEqual(script.chapters[0].segments[1].speaker.status, 'unknown')

    def test_changed_attribution_lock_or_voice_invalidates_saved_plan(self):
        self.complete()
        draft = self.controller.make_draft(bank(), 'en', client=CardsClient(), model='mock')
        for changed in [replace(self.source, entities={**self.source.entities, 'lead': replace(self.source.entities['lead'], voice_locked=True)}),
                        replace(self.source, roles={**self.source.roles, 'lead': replace(self.source.roles['lead'], provider_params={'voice':'Chloe'})}),
                        replace(self.source, chapters=(replace(self.source.chapters[0], segments=tuple(replace(s, speaker=SpeakerDecision(s.role_id, 'confirmed')) for s in self.source.chapters[0].segments)),))]:
            current = BookCasting(self.temp.name, self.parsed, 'parser', changed)
            with self.assertRaisesRegex(ValueError, '失效'):
                current.apply(bank(), draft['draft_id'])
        voice_changed = replace(self.source, roles={**self.source.roles,
            'lead':replace(self.source.roles['lead'], provider_params={'voice':'Chloe'})})
        current = BookCasting(self.temp.name,self.parsed,'parser',voice_changed,source_revision='changed on disk')
        self.assertTrue(current.progress()['full_book'])
        self.assertEqual(current.analyzed_script().roles['lead'].provider_params['voice'],'Chloe')
        changed_bank = copy.deepcopy(bank())
        changed_bank['voices']['Mia']['embeddings']['a'] = [1, .2]
        with self.assertRaisesRegex(ValueError, '声音库已改变'):
            self.controller.apply(changed_bank, draft['draft_id'])
        with self.assertRaisesRegex(ValueError, '失效'):
            self.controller.apply(bank(), 'old-id')

    def test_description_edits_and_validation(self):
        self.complete()
        draft = self.controller.make_draft(bank(), 'en', client=CardsClient(), model='mock')
        rows = draft_rows(draft)
        guest = next(row for row in rows if row[0] == 'guest')
        guest[4] = 'Low dry resonance, crisp English consonants.'
        result = self.controller.apply(bank(), draft['draft_id'], rows)
        self.assertEqual(result.roles['guest'].provider_params['voice_description'], guest[4])
        self.assertTrue(result.roles['guest'].provider_params['voice_version'])
        current = BookCasting(self.temp.name, self.parsed, 'parser', result, source_revision='applied')
        client = CardsClient()
        reused = current.make_draft(bank(), 'en', client=client, model='mock')
        self.assertEqual(client.calls, [])
        self.assertEqual(reused['cards']['guest']['voice_description'], guest[4])
        guest[4] = ''
        with self.assertRaises(ValueError):
            self.controller.apply(bank(), draft['draft_id'], rows)

    def test_gender_fit_does_not_guess_unknown_attributes(self):
        script = replace(self.full, roles={**self.full.roles, 'late': replace(self.full.roles['late'], gender='male')})
        fit = fit_matrix(script, bank(), 'en')
        self.assertTrue(all(value >= 2 for value in fit['late'].values()))
        self.assertTrue(all(value == 0 for value in fit['lead'].values()))
        manifest = hybrid_casting(script, bank(), language='en', full_book=True, attribution_policy='draft', fit_penalties=fit)
        self.assertEqual(manifest['profiles']['late']['reason'], 'no_acceptable_preset')
        self.assertEqual(manifest['profiles']['lead']['voice_mode'], 'preset')

    def test_hard_fit_matching_keeps_high_priority_and_fills_other_suitable_role(self):
        fit = {r: {'Mia':0, 'Chloe':0} for r in self.full.roles}
        fit['lead']['Chloe'] = 2
        manifest = hybrid_casting(self.full, bank(), language='en', full_book=True,
            attribution_policy='draft', fit_penalties=fit, reserve_narrator=False)
        self.assertEqual(manifest['profiles']['lead']['provider_params']['voice'], 'Mia')
        self.assertEqual(manifest['profiles']['late']['provider_params']['voice'], 'Chloe')

    def test_equal_interaction_cost_prefers_larger_overall_distance(self):
        from audiobook_generator.audio_core.casting import optimize_casting
        voices = bank()
        voices['voices']['Chloe']['embeddings'] = {'a':[1,.1], 'b':[1,.1]}
        voices['voices']['Dean'] = {'verified':True, 'embeddings':{'a':[0,1], 'b':[0,1]}}
        value = optimize_casting(['a','b'], {}, voices, unique_voices=True, spread_tiebreak=True)
        self.assertEqual(set(value['roles'].values()), {'Mia','Dean'})

    def test_draft_ranking_stays_same_when_one_line_is_split(self):
        original = role_usage(self.full, language='en', attribution_policy='draft')
        chapter = self.full.chapters[-1]
        split = tuple(s for segment in chapter.segments for s in (
            replace(segment,text=segment.text[:7]), replace(segment,text=segment.text[7:])))
        script = replace(self.full,chapters=self.full.chapters[:-1] + (replace(chapter,segments=split),))
        usage = role_usage(script,language='en',attribution_policy='draft')
        self.assertEqual(original['ranked_roles'],usage['ranked_roles'])
        self.assertEqual({r:v['reading_count'] for r,v in original['roles'].items()},
                         {r:v['reading_count'] for r,v in usage['roles'].items()})

    def test_resumable_deadline_explains_continuation(self):
        control = SplitControl(task_seconds=-1)
        control.resumable = True
        with self.assertRaisesRegex(SplitAborted, '再次点击可继续'):
            control.check()

    def test_no_narrator_text_no_reserved_slot_and_no_dormant_description(self):
        script = replace(self.full, chapters=tuple(replace(c, segments=tuple(s for s in c.segments if s.role_id != 'narrator')) for c in self.full.chapters))
        manifest = hybrid_casting(script, bank(), language='en', full_book=True, attribution_policy='draft')
        self.assertEqual(manifest['profiles']['narrator']['reason'], 'no_spoken_text')
        self.assertEqual(manifest['profiles']['lead']['voice_mode'], 'preset')
        self.assertEqual(manifest['profiles']['late']['voice_mode'], 'preset')

    def test_locked_sharing_preserved_even_outside_current_bank(self):
        roles = dict(self.full.roles)
        entities = dict(self.full.entities)
        for role in ['lead', 'guest']:
            roles[role] = replace(roles[role], provider_params={'voice':'Dean','speed':1.2})
            entities[role] = replace(entities[role], voice_locked=True)
        script = replace(self.full, roles=roles, entities=entities)
        manifest = hybrid_casting(script, bank(), language='en', full_book=True, attribution_policy='draft')
        self.assertEqual(manifest['profiles']['guest']['provider_params'], {'voice':'Dean','speed':1.2})
        self.assertEqual(manifest['profiles']['lead']['reason'], 'user_locked')

    def test_import_rejects_wrong_language_unverified_or_bad_probes(self):
        path = Path(self.temp.name) / 'bank.json'
        for value in [{**bank(), 'languages':['zh']}, {**bank(), 'voices':{}},
                      {**bank(), 'voices':{'Mia':{'verified':False}}},
                      {**bank(), 'voices':{'Mia':{'verified':True,'embeddings':{'one':[1,0]}}}}]:
            path.write_text(json.dumps(value))
            with self.assertRaises((ValueError, KeyError)):
                load_bank(path, 'en')

    def test_batches_save_success_and_only_fill_missing_without_retry(self):
        count = 19
        roles = {f'r{i}':RoleDefinition(f'Person {i}', {'voice':'Mia'}, 'male') for i in range(count)}
        roles['narrator'] = RoleDefinition('Narrator', {'voice':'Mia'})
        line = 'This is a line. '
        segments = tuple(SegmentScript(f'r{i}', line, segment_id=f's{i}', source_span=SourceSpan(1,i*len(line),(i+1)*len(line)),
                                       speaker=SpeakerDecision(f'r{i}','proposed')) for i in range(count))
        parsed = [('All', ''.join(s.text for s in segments))]
        script = RoleScriptV2(2, 'openai', 'b'*64, 200, roles, (ChapterScript(1,'All',segments),),
                              {r:CharacterEntity(r) for r in roles}, 'parser', chapter_hashes(parsed), True)
        controller = BookCasting(self.temp.name, parsed, 'parser', script)
        client = CardsClient(fail_at=2)
        with self.assertRaises(TimeoutError):
            controller.make_draft(bank(), 'en', client=client, model='mock')
        saved = controller.read_draft()
        self.assertEqual(len(saved['cards']), 8)
        self.assertEqual(len(client.calls), 2)
        previous = set(saved['cards'])
        client = CardsClient()
        draft = controller.make_draft(bank(), 'en', client=client, model='mock')
        self.assertEqual(len(draft['cards']), 19)
        self.assertEqual([len(c['roles']) for c in client.calls], [8,3])
        self.assertFalse(previous & set().union(*(set(c['roles']) for c in client.calls)))
        controller.apply(bank(), draft['draft_id'])
        client = CardsClient()
        controller.make_draft(bank(), 'en', client=client, model='mock')
        self.assertEqual(client.calls, [])


if __name__ == '__main__':
    unittest.main()
