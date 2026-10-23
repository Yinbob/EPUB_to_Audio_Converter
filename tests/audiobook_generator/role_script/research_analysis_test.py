import copy
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from audiobook_generator.role_script.research_analysis import analyze, validate_proposal
from audiobook_generator.role_script.context_budget import checkpoint_scope
from audiobook_generator.role_script.research_io import input_digest
from tests.audiobook_generator.role_script.research_test import state


class FakeClient:
    def __init__(self, entity='char_1', transform=None):
        self.calls = 0
        self.base_url = 'offline://research'
        self.entity, self.transform = entity, transform
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls += 1
        request = json.loads(kwargs['messages'][1]['content'])
        raw = {'decisions': [{'segment_id': request['segment_id'], 'entity_id': self.entity,
            'candidates': [self.entity], 'evidence': [], 'against': [], 'depends_on': []}],
            'mentions': [], 'claims': [], 'conflicts': []}
        if self.transform:
            self.transform(raw, request)
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',
            message=SimpleNamespace(content=json.dumps(raw, ensure_ascii=False)))])


class ResearchAnalysisTest(unittest.TestCase):
    def test_valid_proposal_has_no_side_effect_and_cache_is_bound(self):
        s = state(); before = copy.deepcopy(s)
        chapters = [('第一章', s['sources']['1'])]
        client = FakeClient()
        with tempfile.TemporaryDirectory() as root, checkpoint_scope(root):
            p = analyze(s, chapters, client=client, model='offline', target_ids=['ch1_s2'])
            analyze(s, chapters, client=client, model='offline', target_ids=['ch1_s2'])
            self.assertEqual(client.calls, 1)
            changed = copy.deepcopy(s)
            changed['decisions']['ch1_s1']['status'] = 'human'
            analyze(changed, chapters, client=client, model='offline', target_ids=['ch1_s2'])
            self.assertEqual(client.calls, 2)
        self.assertEqual(s, before)
        self.assertEqual(p['input_digest'], input_digest(s))

    def test_fabricated_quote_unknown_claim_and_missing_coverage_rejected(self):
        def quote(raw, request):
            raw['decisions'][0]['evidence'] = [{'span': {'chapter_index': 1, 'start': 0, 'end': 1}, 'quote': '假', 'kind': 'explicit'}]
        def claim(raw, request):
            raw['decisions'][0]['depends_on'] = ['unknown']
        def missing(raw, request):
            raw['decisions'] = []
        for transform in (quote, claim, missing):
            with self.subTest(transform=transform), self.assertRaises(ValueError):
                s = state()
                analyze(s, [('第一章', s['sources']['1'])], client=FakeClient(transform=transform), target_ids=['ch1_s2'])

    def test_different_source_rejected_before_request(self):
        client = FakeClient()
        with self.assertRaisesRegex(ValueError, '原书正文'):
            analyze(state(), [('第一章', '不同正文')], client=client)
        self.assertEqual(client.calls, 0)

    def test_stable_mention_ids_and_local_conflict_reference_validation(self):
        def mention(raw, request):
            span = {'chapter_index': 1, 'start': 0, 'end': 3}
            raw['mentions'] = [{'id': 'model-local', 'span': span, 'text': '林黛玉', 'block_id': 'ignored'}]
            raw['claims'] = [{'id': 'model-claim', 'kind': 'mention_entity', 'subject': 'model-local',
                'entity_id': 'char_1', 'scope': {'chapter_index': 1, 'start': 0, 'end': 8}, 'evidence': []}]
            raw['decisions'][0]['depends_on'] = ['model-claim']
            raw['conflicts'] = [{'kind': 'candidate', 'refs': ['model-local', 'model-claim'], 'evidence': []}]
        s = state()
        a = analyze(s, [('第一章', s['sources']['1'])], client=FakeClient(transform=mention), target_ids=['ch1_s2'])
        b = analyze(s, [('第一章', s['sources']['1'])], client=FakeClient(transform=mention), target_ids=['ch1_s2'])
        self.assertEqual(a['mentions'][0]['id'], b['mentions'][0]['id'])
        self.assertEqual(set(a['conflicts'][0]['refs']), {a['mentions'][0]['id'], a['claims'][0]['id']})
        def invalid(raw, request):
            raw['conflicts'] = [{'kind': 'candidate', 'refs': ['not-in-input'], 'evidence': []}]
        with self.assertRaisesRegex(ValueError, '冲突引用'):
            analyze(s, [('第一章', s['sources']['1'])], client=FakeClient(transform=invalid), target_ids=['ch1_s2'])

    def test_long_segment_splits_without_changing_segment(self):
        s = state()
        text = '这是很长的原文。' * 150
        s['script']['chapters'][0]['segments'] = [copy.deepcopy(s['script']['chapters'][0]['segments'][1])]
        row = s['script']['chapters'][0]['segments'][0]
        row.update(text=text, source_span={'chapter_index': 1, 'start': 0, 'end': len(text)})
        s['sources'] = {'1': text}
        s['decisions'].pop('ch1_s1')
        s['decisions']['ch1_s2']['evidence'] = []
        client = FakeClient()
        with patch.dict('os.environ', {'ROLE_LLM_CONTEXT_TOKENS': '4096'}):
            p = analyze(s, [('第一章', text)], client=client)
        self.assertGreater(client.calls, 1)
        self.assertEqual(len(p['changes']), 1)
        self.assertEqual(row['text'], text)
