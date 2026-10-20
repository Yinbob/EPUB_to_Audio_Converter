"""真引文不能给虚构姓名或跨章人物提供身份担保。"""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from dataclasses import replace
from audiobook_generator.role_script.models import CharacterEntity, ChapterScript, RoleDefinition, RoleScriptV1, RoleScriptV2, SegmentScript, AliasRecord, SpeakerDecision, SourceSpan, EvidenceSpan
from audiobook_generator.role_script.narration import request_narration_context, name_in_source, grounded_entities
from audiobook_generator.role_script.v2_generation import upgrade_generated_script, generate_v2_for_book
from audiobook_generator.role_script.project_store import chapter_hashes
from tests.audiobook_generator.role_script.narration_test import response, narrator


class NarratorGroundingTest(unittest.TestCase):
    def test_true_quote_does_not_validate_invented_or_other_chapter_name(self):
        source = 'Bryce, listen. I waited by the door.'
        known = [{'role_id': 'caleb', 'display_name': 'Caleb Hughes', 'aliases': []}]
        for people in ([], known):
            client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(
                return_value=response(narrator('caleb', 'Caleb Hughes', 'I waited by the door.'))))))
            self.assertEqual(request_narration_context(client, 'test', 1, 'One', source, people)['narrators'], [])

    def test_confirmed_local_alias_supports_known_canonical_name(self):
        source = 'Bryce, listen. I waited.'
        known = [{'role_id': 'bryce', 'display_name': 'Bryce Loski', 'aliases': ['Bryce']}]
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(
            return_value=response(narrator('bryce', 'Bryce Loski', 'Bryce, listen.'))))))
        self.assertEqual(request_narration_context(client, 'test', 1, 'One', source, known)['narrators'][0]['role_id'], 'bryce')
        self.assertFalse(name_in_source('Al', 'walked'))
        self.assertTrue(name_in_source('Bryce', 'BRYCE, listen.'))
        self.assertTrue(name_in_source('小明', '小明说。'))

    def test_upgrade_blocks_unsupported_role_including_dialogue_and_unknown(self):
        for kind in ('narration', 'dialogue', 'unknown'):
            source = 'I waited.'
            generated = RoleScriptV1(1, 'openai', 'a'*64, 250,
                {'narrator': RoleDefinition('Narrator', {'voice': 'Milo'}), 'fake': RoleDefinition('Invented Name', {'voice': 'Dean'})},
                (ChapterScript(1, 'One', (SegmentScript('fake', source, text_kind=kind,
                 evidence_candidates=((source, 'narrator_identity'),)),)),))
            script = upgrade_generated_script(generated, [('One', source)],
                {'narrator': CharacterEntity('Narrator')}, parser_fingerprint='p', model='test')
            segment = script.chapters[0].segments[0]
            self.assertEqual((segment.role_id, segment.speaker.status), ('narrator', 'needs_review'))
            self.assertNotIn('Invented Name', [e.canonical_name for e in script.entities.values()])
            self.assertEqual(segment.text, source)

    def test_known_elsewhere_cannot_be_chapter_narrator_with_generic_quote(self):
        source = 'I waited. Bryce, come here.'
        chapters = [('One', source), ('Two', 'Caleb Hughes went next.')]
        for kind in ('narration', 'unknown'):
            generated = RoleScriptV1(1, 'openai', 'a'*64, 250,
                {'narrator': RoleDefinition('Narrator', {'voice': 'Milo'}), 'caleb': RoleDefinition('Caleb Hughes', {'voice': 'Dean'})},
                (ChapterScript(1, 'One', (SegmentScript('caleb', source, text_kind=kind,
                 evidence_candidates=(('I waited.', 'narrator_identity'),)),)),))
            script = upgrade_generated_script(generated, chapters,
                {'narrator': CharacterEntity('Narrator'), 'caleb': CharacterEntity('Caleb Hughes')},
                parser_fingerprint='p', model='test')
            self.assertEqual(script.chapters[0].segments[0].role_id, 'narrator')
            self.assertEqual(script.chapters[0].segments[0].speaker.status, 'needs_review')

    def test_old_registry_is_not_proof_and_alias_must_be_confirmed(self):
        entities = {'fake': CharacterEntity('Invented Name'),
                    'a': CharacterEntity('Full Name', (AliasRecord('Bryce', 'proposed'),)),
                    'b': CharacterEntity('Other Name', (AliasRecord('Bryce', 'confirmed'),))}
        self.assertEqual(set(grounded_entities(entities, [('One', 'Bryce waited.')])), {'b'})

    def test_resplit_also_revalidates_retained_chapter_and_inherited_dialogue(self):
        texts = ['Bryce, listen. I waited. ', '“Hello.”', ' I left.']
        source = ''.join(texts)
        chapters = [('One', source), ('Two', 'Caleb Hughes went next.')]
        roles = {'narrator': RoleDefinition('Narrator', {'voice': 'Milo'}),
                 'caleb': RoleDefinition('Caleb Hughes', {'voice': 'Dean'})}
        entities = {'narrator': CharacterEntity('Narrator'), 'caleb': CharacterEntity('Caleb Hughes')}
        quote = 'I waited.'
        evidence = EvidenceSpan(SourceSpan(1, source.index(quote), source.index(quote) + len(quote)), 'narrator_identity', quote)
        segments = []
        start = 0
        for index, text in enumerate(texts):
            speaker = SpeakerDecision('caleb', 'confirmed' if index == 2 else 'proposed', .8,
                                      (evidence,) if index == 0 else (), 'old', 'human' if index == 2 else 'uncalibrated')
            segments.append(SegmentScript('caleb', text, segment_id=f'old{index}',
                source_span=SourceSpan(1, start, start + len(text)), speaker=speaker,
                text_kind='narration' if index == 0 else 'dialogue'))
            start += len(text)
        previous = RoleScriptV2(2, 'openai', 'a'*64, 250, roles,
            (ChapterScript(1, 'One', tuple(segments)),), entities, 'p', chapter_hashes(chapters), True)
        generated = RoleScriptV1(1, 'openai', 'a'*64, 250, roles,
            (ChapterScript(2, 'Two', (SegmentScript('caleb', chapters[1][1], text_kind='dialogue'),)),))
        result = upgrade_generated_script(generated, chapters, dict(entities), parser_fingerprint='p', model='test', previous=previous)
        self.assertEqual([(s.role_id, s.speaker.status) for s in result.chapters[0].segments[:2]],
                         [('narrator', 'needs_review'), ('narrator', 'needs_review')])
        self.assertEqual(result.chapters[0].segments[2], segments[2])
        self.assertEqual(result.chapters[1].segments[0].role_id, 'caleb')
        self.assertEqual(result.roles['caleb'], roles['caleb'])
        self.assertEqual(''.join(s.text for s in result.chapters[0].segments), source)

    def test_new_cross_chapter_narrator_cannot_keep_its_dialogue(self):
        source = 'Bryce, listen. I waited. “Hello.”'
        roles = {'narrator': RoleDefinition('Narrator', {'voice': 'Milo'}),
                 'caleb': RoleDefinition('Caleb Hughes', {'voice': 'Dean'})}
        generated = RoleScriptV1(1, 'openai', 'a'*64, 250, roles, (ChapterScript(1, 'One', (
            SegmentScript('caleb', 'Bryce, listen. I waited. ', text_kind='narration', evidence_candidates=(('I waited.', 'narrator_identity'),)),
            SegmentScript('caleb', '“Hello.”', text_kind='dialogue'),)),))
        result = upgrade_generated_script(generated, [('One', source), ('Two', 'Caleb Hughes went next.')],
            {'narrator': CharacterEntity('Narrator'), 'caleb': CharacterEntity('Caleb Hughes')}, parser_fingerprint='p', model='test')
        self.assertTrue(all(s.role_id == 'narrator' and s.speaker.status == 'needs_review' for s in result.chapters[0].segments))


if __name__ == '__main__': unittest.main()
