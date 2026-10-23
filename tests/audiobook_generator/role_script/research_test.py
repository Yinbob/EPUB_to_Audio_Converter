"""研究关系、投影、依赖与排序的行为回归。"""
import copy
import unittest
from audiobook_generator.services.projects import encode
from audiobook_generator.role_script.research_io import create_state, validate_state
from audiobook_generator.role_script.research_review import apply_decision, project
from audiobook_generator.role_script.dependency_index import affected
from audiobook_generator.role_script.review_policy import review_queue, recommendation
from tests.audiobook_generator.role_script.v2_io_test import _script


def state():
    script = encode(_script()[0])
    script['entities']['char_2'] = {**copy.deepcopy(script['entities']['char_1']), 'canonical_name': '贾宝玉', 'voice_locked': False}
    script['roles']['char_2'] = {**copy.deepcopy(script['roles']['char_1']), 'display_name': '贾宝玉'}
    return create_state('a' * 32, 1, script)


class ResearchTest(unittest.TestCase):
    def test_merge_revoke_and_human_pin(self):
        s = state()
        merged = apply_decision(s, 'merge', {'source_id': 'char_1', 'target_id': 'char_2'}, 'merge1')
        row = merged['script']['chapters'][0]['segments'][1]
        self.assertEqual(row['role_id'], 'char_2')
        self.assertNotEqual(row['speaker']['confidence_kind'], 'human')
        self.assertIn('char_1', merged['script']['entities'])
        claim = next(iter(merged['claims']))
        pinned = apply_decision(merged, 'segment', {'segment_id': 'ch1_s2', 'entity_id': 'char_2'}, 'pin')
        revoked = apply_decision(pinned, 'revoke', {'claim_id': claim}, 'revoke')
        self.assertEqual(revoked['script']['chapters'][0]['segments'][1]['role_id'], 'char_2')
        self.assertEqual(revoked['decisions']['ch1_s2']['status'], 'human')
        unpinned = apply_decision(merged, 'revoke', {'claim_id': claim}, 'undo')
        self.assertEqual(unpinned['script']['chapters'][0]['segments'][1]['role_id'], 'char_1')
        self.assertEqual(unpinned['decisions']['ch1_s2']['status'], 'stale')

    def test_transitive_dedup_context_and_cycle(self):
        s = state()
        s['dependencies'] = [
            {'decision_id': 'ch1_s2', 'upstream_id': 'ch1_s1', 'kind': 'depends_on'},
            {'decision_id': 'ch1_s2', 'upstream_id': 'ch1_s1', 'kind': 'context_refs'}]
        weights, explicit = affected(s, ['ch1_s1'])
        self.assertEqual(weights, {'ch1_s2': 1})
        self.assertEqual(explicit, {'ch1_s2'})
        s['dependencies'].append({'decision_id': 'ch1_s1', 'upstream_id': 'ch1_s2', 'kind': 'depends_on'})
        with self.assertRaisesRegex(ValueError, '循环'):
            validate_state(s)

    def test_queue_and_audit_reproducible(self):
        s = state()
        q = review_queue(s)
        self.assertTrue(q)
        session = {'strategy': 'impact', 'seed': 'fixed', 'audit_every': 10, 'answers': ['x'] * 9}
        self.assertEqual(recommendation(s, session), recommendation(s, session))
        self.assertTrue(recommendation(s, session)['audit'])

    def test_source_evidence_rejected(self):
        s = state()
        s['decisions']['ch1_s2']['evidence'][0]['quote'] = '假的证据'
        with self.assertRaisesRegex(ValueError, '引文'):
            validate_state(s)

    def test_scoped_identity_does_not_change_other_ranges_or_aliases(self):
        s = apply_decision(state(), 'merge', {'source_id': 'char_1', 'target_id': 'char_2'}, 'scope-merge')
        claim = next(iter(s['claims'].values()))
        claim['scope'] = {'chapter_index': 1, 'start': 0, 'end': 5}
        project(s)
        self.assertEqual(s['script']['chapters'][0]['segments'][1]['role_id'], 'char_1')
        self.assertEqual(s['script']['entities']['char_1']['aliases'], state()['script']['entities']['char_1']['aliases'])
        self.assertNotEqual(s['decisions']['ch1_s2']['status'], 'human')

    def test_context_exposure_requests_check_without_making_decision_stale(self):
        s = apply_decision(state(), 'merge', {'source_id': 'char_1', 'target_id': 'char_2'}, 'context-merge')
        claim = next(iter(s['claims']))
        s['dependencies'] = [{'decision_id': 'ch1_s1', 'upstream_id': claim, 'kind': 'context_refs'}]
        s = apply_decision(s, 'revoke', {'claim_id': claim}, 'context-revoke')
        self.assertNotEqual(s['decisions']['ch1_s1']['status'], 'stale')
        self.assertIn('ch1_s1', s['context_checks'])
        row = next(q for q in review_queue(s) if q['id'] == 'ch1_s1')
        self.assertEqual(row['weighted_impact'], .25)

    def test_transitive_identity_conflict_and_disjoint_scopes(self):
        from audiobook_generator.role_script.research_conflicts import detect_conflicts
        s = state()
        c = {'id': 'ab', 'kind': 'same_entity', 'subject': 'char_1', 'entity_id': 'char_2',
            'scope': {'kind': 'book'}, 'status': 'accepted', 'evidence': [], 'source': 'human',
            'created_revision': 2, 'revoked_revision': None}
        s['claims'] = {'ab': c, 'bn': {**c, 'id': 'bn', 'subject': 'char_2', 'entity_id': 'narrator'},
            'an': {**c, 'id': 'an', 'kind': 'distinct_entity', 'entity_id': 'narrator'}}
        conflicts = detect_conflicts(s)
        self.assertEqual(set(conflicts[0]['refs']), {'ab', 'bn', 'an'})
        s['claims']['ab']['scope'] = {'chapter_index': 1, 'start': 0, 'end': 5}
        s['claims']['bn']['scope'] = {'chapter_index': 1, 'start': 5, 'end': 8}
        self.assertEqual(detect_conflicts(s), [])

    def test_shared_root_queue_deduplicates_and_removes_human_benefit(self):
        s = state()
        claim = {'id': 'uncertain', 'kind': 'same_entity', 'subject': 'char_1', 'entity_id': 'char_2',
            'scope': {'kind': 'book'}, 'status': 'proposed', 'evidence': [], 'source': 'model',
            'created_revision': 2, 'revoked_revision': None}
        s['claims']['uncertain'] = claim
        s['dependencies'] = [{'decision_id': sid, 'upstream_id': 'uncertain', 'kind': 'depends_on'} for sid in s['decisions']]
        s['dependencies'].append({'decision_id': 'ch1_s2', 'upstream_id': 'ch1_s1', 'kind': 'depends_on'})
        q = review_queue(s)
        self.assertEqual(q[0]['id'], 'uncertain')
        self.assertEqual(q[0]['weighted_impact'], 2)
        s = apply_decision(s, 'segment', {'segment_id': 'ch1_s2', 'entity_id': 'char_1'}, 'solve-one')
        self.assertEqual(review_queue(s)[0]['segment_ids'], ['ch1_s1'])

    def test_identical_kinship_words_bind_different_entities(self):
        import json
        from pathlib import Path
        fixture = Path(__file__).resolve().parents[3] / 'examples/research_review/input.json'
        s = next(c['state'] for c in json.loads(fixture.read_text())['cases'] if c['id'] == 'kinship')
        self.assertEqual({m['text'] for m in s['mentions'].values()}, {'父亲'})
        self.assertEqual({s['claims'][key]['entity_id'] for key in ('truth_father_0', 'truth_father_1')}, {'person_b', 'person_c'})
        self.assertFalse(any(c['kind'] == 'mention_conflict' for c in s['conflicts']))
