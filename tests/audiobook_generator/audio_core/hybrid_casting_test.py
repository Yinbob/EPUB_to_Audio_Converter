import unittest
from dataclasses import replace
from audiobook_generator.role_script.models import RoleDefinition, RoleScriptV1, ChapterScript, SegmentScript
from audiobook_generator.audio_core.hybrid_casting import role_usage, hybrid_casting
from audiobook_generator.audio_core.casting import optimize_casting


def fixture():
    roles = {r: RoleDefinition(r, {'voice': 'Mia'}) for r in ('narrator', 'lead', 'late', 'guest')}
    chapters = tuple(ChapterScript(i, str(i), tuple(
        [SegmentScript('narrator', 'A new day. '), SegmentScript('lead', 'We must go now. ')]
        + ([SegmentScript('late', 'Please listen. ' * 20)] if i >= 10 else [])
        + ([SegmentScript('guest', 'Good morning. ')] if i in (1, 6, 12) else [])
    )) for i in range(1, 13))
    return RoleScriptV1(1, 'openai', 'a' * 64, 200, roles, chapters)


def bank():
    return {'provider': 'openai', 'languages': ['en'], 'voices': {
        'Mia': {'verified': True, 'embeddings': {'a': [1, 0], 'b': [1, 0]}},
        'Chloe': {'verified': True, 'embeddings': {'a': [0, 1], 'b': [0, 1]}}}}


def confirmed_v2_fixture():
    from audiobook_generator.role_script.models import RoleScriptV2, CharacterEntity, AliasRecord, SpeakerDecision, SourceSpan
    source = fixture()
    chapters = []
    for c in source.chapters:
        cursor = 0
        segments = []
        for index, s in enumerate(c.segments):
            segments.append(replace(s, segment_id=f'{c.chapter_index}:{index}',
                source_span=SourceSpan(c.chapter_index, cursor, cursor+len(s.text)),
                speaker=SpeakerDecision(s.role_id, 'confirmed')))
            cursor += len(s.text)
        chapters.append(replace(c, segments=tuple(segments)))
    entities = {r: CharacterEntity(r, aliases=(AliasRecord(r+' alias', 'confirmed'),),
                voice_profile_id='legacy_'+r, voice_locked=r=='lead') for r in source.roles}
    return RoleScriptV2(2, source.provider, source.book_sha256, 200, source.roles,
                        tuple(chapters), entities, 'parser-fp', {}, True)


class HybridCastingTests(unittest.TestCase):
    def test_late_talker_and_split_invariance(self):
        script = fixture()
        usage = role_usage(script, language='en', full_book=True)
        self.assertEqual(usage['ranked_roles'][0], 'late')
        self.assertEqual(usage['roles']['guest']['absent_chapter_gaps'], [4, 5])
        first = script.chapters[0]
        pieces = tuple(s for seg in first.segments for s in (
            replace(seg, text=seg.text[:3]), replace(seg, text=seg.text[3:])))
        revised = replace(script, chapters=(replace(first, segments=pieces),) + script.chapters[1:])
        other = role_usage(revised, language='en', full_book=True)
        self.assertEqual(usage['roles'], other['roles'])
        self.assertEqual(usage['ranked_roles'], other['ranked_roles'])

    def test_narrator_capacity_and_risk(self):
        value = hybrid_casting(fixture(), bank(), language='en', full_book=True)
        profiles = value['profiles']
        self.assertEqual(profiles['late']['voice_mode'], 'preset')
        self.assertNotEqual(profiles['late']['provider_params']['voice'], profiles['narrator']['provider_params']['voice'])
        self.assertEqual(profiles['lead']['risk_tier'], 'recurrent')
        self.assertEqual(profiles['guest']['risk_tier'], 'sparse')
        self.assertEqual(profiles['lead']['voice_mode'], 'design')

    def test_locks_can_explicitly_share_but_automatic_cannot(self):
        value = hybrid_casting(fixture(), bank(), language='en', full_book=True,
                               locked={'lead': 'Mia', 'guest': 'Mia'}, reserve_narrator=False)
        self.assertEqual(value['profiles']['late']['provider_params']['voice'], 'Chloe')
        self.assertEqual(value['preset_allocation']['shared_voices'], {'Mia': ['guest', 'lead']})

    def test_partial_and_wrong_language_rejected(self):
        self.assertEqual(role_usage(fixture(), language='en')['scope'], 'partial')
        with self.assertRaises(ValueError):
            hybrid_casting(fixture(), bank(), language='en')
        with self.assertRaises(ValueError):
            hybrid_casting(fixture(), bank(), language='zh', full_book=True)

    def test_zero_capacity_and_alias(self):
        value = hybrid_casting(fixture(), {**bank(), 'voices': {}}, language='en', full_book=True, reserve_narrator=False)
        self.assertTrue(all(p['voice_mode'] == 'design' for p in value['profiles'].values()))
        with self.assertRaises(ValueError):
            hybrid_casting(fixture(), {**bank(), 'voices': {'mimo_default': bank()['voices']['Mia']}}, language='en', full_book=True)

    def test_unique_optimizer_no_interaction_still_different(self):
        value = optimize_casting(['a', 'b'], {}, bank(), language='en', unique_voices=True)
        self.assertEqual(len(set(value['roles'].values())), 2)

    def test_fit_rejects_missing_and_avoids_unsuitable(self):
        fit = {r: {'Mia': 0, 'Chloe': 0} for r in fixture().roles}
        fit['late'] = {'Mia': 2, 'Chloe': 2}
        value = hybrid_casting(fixture(), bank(), language='en', full_book=True, fit_penalties=fit)
        self.assertEqual(value['profiles']['late']['reason'], 'no_acceptable_preset')
        del fit['guest']
        with self.assertRaises(ValueError):
            hybrid_casting(fixture(), bank(), language='en', full_book=True, fit_penalties=fit)

class VoiceCardTests(unittest.TestCase):
    def test_apply_roundtrip_source_and_no_legacy_reassignment(self):
        from audiobook_generator.audio_core.hybrid_casting import apply_hybrid
        from audiobook_generator.role_script.deepseek_splitter import differentiate_role_voices, role_script_to_dict
        from audiobook_generator.role_script.loader import parse_role_script
        from audiobook_generator.role_script.errors import ValidationReport
        script = fixture()
        manifest = hybrid_casting(script, bank(), language='en', full_book=True)
        cards = {r: {'voice_description': 'Mid-low resonant voice, clear English articulation.'}
                 for r, p in manifest['profiles'].items() if p['voice_mode'] == 'design'}
        applied = apply_hybrid(script, manifest, cards)
        self.assertEqual(applied.chapters, script.chapters)
        self.assertNotIn('voice', applied.roles['guest'].provider_params)
        self.assertEqual(differentiate_role_voices(applied)[0], applied)
        import json
        report = ValidationReport()
        loaded = parse_role_script(role_script_to_dict(applied), report)
        self.assertTrue(report.ok, report.to_dict())
        self.assertEqual(applied, loaded)
        with self.assertRaises(ValueError):
            apply_hybrid(replace(script, book_sha256='b' * 64), manifest, cards)
        with self.assertRaises(ValueError):
            apply_hybrid(script, manifest, {})

    def test_schema_rejects_invalid_design(self):
        from audiobook_generator.role_script.validator import validate_role_script
        script = fixture()
        for params in ({'voice_mode': 'unknown', 'voice': 'Mia'}, {'voice_mode': 'design'},
                       {'voice_mode': 'preset', 'voice': 'Mia', 'voice_description': 'low'}):
            invalid = replace(script, roles={**script.roles, 'guest': RoleDefinition('guest', params)})
            self.assertFalse(validate_role_script(invalid).ok)

    def test_chinese_counts_and_voice_card_prompt_preserves_unknown_facts(self):
        from audiobook_generator.audio_core.hybrid_casting import generate_voice_cards
        from unittest.mock import MagicMock
        from types import SimpleNamespace
        script = RoleScriptV1(1, 'openai', 'c' * 64, 200,
            {'guest': RoleDefinition('访客', {'voice': '冰糖'})},
            (ChapterScript(1, '一', (SegmentScript('guest', '请在桥边等我。'),)),))
        usage = role_usage(script, language='zh', full_book=True)
        self.assertEqual(usage['roles']['guest']['reading_count'], 6)
        self.assertEqual(usage['roles']['guest']['estimated_seconds'], 1.5)
        casting = hybrid_casting(script, {'provider': 'openai', 'languages': ['zh'], 'voices': {}},
                                 language='zh', full_book=True, reserve_narrator=False)
        fake = MagicMock()
        fake.with_options.return_value.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"guest":{"voice_description":"中低声区，胸腔共鸣，清晰普通话，质感略干。"}}'))])
        cards, receipt = generate_voice_cards(script, casting, client=fake, model='test')
        self.assertIsNone(receipt['input']['roles']['guest']['known_gender'])
        self.assertEqual(receipt['requests'], 1)
        self.assertIn('voice_description', cards['guest'])
        self.assertEqual(fake.with_options.call_args.kwargs['max_retries'], 0)

    def test_mixed_or_wrong_language_never_silently_counts_zero(self):
        script = fixture()
        chapter = ChapterScript(1, 'mixed', (SegmentScript('guest', '请在 bridge 等我。'),))
        with self.assertRaises(ValueError):
            role_usage(replace(script, chapters=(chapter,)), language='en', full_book=True)
        with self.assertRaises(ValueError):
            role_usage(fixture(), language='zh', full_book=True)

    def test_hard_fit_capacity_conflict_preserves_scores(self):
        fit = {r: {'Mia': 0, 'Chloe': 2} for r in fixture().roles}
        value = hybrid_casting(fixture(), bank(), language='en', full_book=True, fit_penalties=fit)
        self.assertEqual(value['profiles']['narrator']['provider_params']['voice'], 'Mia')
        self.assertEqual(value['profiles']['late']['voice_mode'], 'design')
        self.assertEqual(fit['late'], {'Mia': 0, 'Chloe': 2})

    def test_v2_locks_aliases_and_source_spans_survive_hybrid(self):
        from audiobook_generator.audio_core.hybrid_casting import apply_hybrid
        script = confirmed_v2_fixture()
        manifest = hybrid_casting(script, bank(), language='en', full_book=True)
        cards = {r:{'voice_description':'Low resonant voice, clear neutral English.'}
                 for r,p in manifest['profiles'].items() if p['voice_mode']=='design' and not p['locked']}
        result = apply_hybrid(script, manifest, cards)
        self.assertEqual(result.entities, script.entities)
        self.assertEqual(result.chapters, script.chapters)
        self.assertEqual(result.parser_fingerprint, script.parser_fingerprint)
        self.assertEqual(result.roles['lead'].provider_params['voice'], 'Mia')
        self.assertEqual(manifest['profiles']['lead']['reason'], 'user_locked')

    def test_apply_rechecks_script_locks_after_manifest_edits(self):
        import copy
        from audiobook_generator.audio_core.hybrid_casting import apply_hybrid
        script = confirmed_v2_fixture()
        roles = dict(script.roles)
        roles['lead'] = replace(roles['lead'], provider_params={
            'voice': 'Mia', 'speed': 1.2, 'instructions': 'A calm reading.', 'voice_language': 'en'})
        script = replace(script, roles=roles)
        original = hybrid_casting(script, bank(), language='en', full_book=True)
        cards = {r: {'voice_description': 'Low resonant voice with clear neutral English.'}
                 for r,p in original['profiles'].items() if p['voice_mode']=='design' and not p['locked']}
        for field, value in (('locked', False), ('locked', 'false'), ('voice', 'Chloe'), ('speed', .9),
                             ('instructions', 'An excited reading.'), ('language', 'zh')):
            with self.subTest(field=field):
                manifest = copy.deepcopy(original)
                if field == 'locked':
                    manifest['profiles']['lead']['locked'] = value
                elif field == 'language':
                    manifest['language'] = value
                else:
                    manifest['profiles']['lead']['provider_params'][field] = value
                with self.assertRaises(ValueError):
                    apply_hybrid(script, manifest, cards)
        self.assertEqual(script.roles['lead'].provider_params, roles['lead'].provider_params)

    def test_locked_design_identity_and_version_cannot_be_replaced(self):
        import copy
        from audiobook_generator.audio_core.hybrid_casting import apply_hybrid
        from tests.audiobook_generator.audio_core.mimo_design_test import card
        script = confirmed_v2_fixture()
        roles = {**script.roles, 'lead': replace(script.roles['lead'], provider_params=card())}
        script = replace(script, roles=roles)
        manifest = hybrid_casting(script, bank(), language='en', full_book=True)
        cards = {r: {'voice_description': 'Warm bright neutral English voice.'}
                 for r,p in manifest['profiles'].items() if p['voice_mode']=='design' and not p['locked']}
        result = apply_hybrid(script, manifest, cards)
        self.assertEqual(result.roles['lead'].provider_params, card())
        for field, value in (('voice_description', 'A different voice.'), ('voice_version', 'v2'),
                             ('voice_profile_id', 'replacement')):
            edited = copy.deepcopy(manifest)
            edited['profiles']['lead']['provider_params'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                apply_hybrid(script, edited, cards)
