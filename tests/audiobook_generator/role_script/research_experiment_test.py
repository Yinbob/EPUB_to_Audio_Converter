import json
import tempfile
import unittest
from pathlib import Path
from audiobook_generator.role_script.research_experiment import run, RecordedClient


class ResearchExperimentTest(unittest.TestCase):
    def test_replay_is_reproducible_and_has_four_arms(self):
        fixture = Path(__file__).resolve().parents[3] / 'examples/research_review'
        with tempfile.TemporaryDirectory() as root:
            a = run(fixture / 'input.json', fixture / 'gold.json', fixture / 'recordings.json', root, budgets=(60,))
            b = run(fixture / 'input.json', fixture / 'gold.json', fixture / 'recordings.json', root, budgets=(60,))
            self.assertEqual(a, b)
            self.assertEqual({r['arm'] for r in a['results']}, set('ABCD'))
            self.assertTrue(Path(root, 'results.csv').is_file())
            self.assertTrue(all(r.get('verified_source_rejection') for r in a['results'] if r['case'] == 'source_changed'))

    def test_missing_recording_never_falls_back_to_gold(self):
        client = RecordedClient({})
        with self.assertRaisesRegex(ValueError, '缺少录制响应'):
            client.create(messages=[{}, {'content': json.dumps({'segment_id': 'a', 'text': '正文', 'claims': []})}])

    def test_deterministic_analyzer_does_not_need_recordings(self):
        fixture = Path(__file__).resolve().parents[3] / 'examples/research_review'
        with tempfile.TemporaryDirectory() as root:
            result = run(fixture / 'input.json', fixture / 'gold.json', '/missing/recordings.json', root,
                budgets=(60,), analyzer='deterministic')
            self.assertIsNone(result['recordings_sha256'])
            self.assertTrue(any(r['model_requests'] > 0 for r in result['results']))
