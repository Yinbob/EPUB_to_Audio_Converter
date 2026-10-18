"""合并范围但不消除证据；构造警告不当成真实音频缺陷。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from audiobook_generator.audio_core.review_queue import build_review_queue
from audiobook_generator.audio_core.quality_review import VERSION, adjudicate_quality
from audiobook_generator.audio_core.store import fingerprint
from tests.audiobook_generator.audio_core import listening_test as fixtures


def issue(code='asr_mismatch',dimension='content',kind='replace',**extra):
    return {'code':code,'dimension':dimension,'certainty':'suspected','severity':'warning',
        'scope_id':'test-scope','evidence':{'operations':[{'kind':kind,'reference':'word','hypothesis':'other'}]},**extra}


class ReviewQueueTest(unittest.TestCase):
    def source(self,root):
        return Path(fixtures.ListeningTest().conditions(root)[0]['report_path'])

    def update(self,path,edit):
        data=json.loads(path.read_text());edit(data);path.write_text(json.dumps(data))

    def test_merges_overlaps_deduplicates_exact_issues_preserves_all_other_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);path=self.source(root)
            def edit(report):
                report['chunks'][0]['report']['issues']=[issue(),issue()]
                report['chunks'][1]['report']['issues']=[issue(kind='insert')]
                report['boundaries'][0]['issues']=[issue(code='boundary_content_mismatch')]
                report['chunks'][3]['report']['issues']=[issue(code='pitch_drift',dimension='consistency')]
            self.update(path,edit);before=path.read_bytes()
            with patch('openai.OpenAI') as remote:
                result=build_review_queue(path,max_window_seconds=10);remote.assert_not_called()
            self.assertEqual(result['summary']['machine_issue_occurrences'],5)
            self.assertEqual(result['summary']['unique_machine_issues'],4)
            self.assertEqual(result['summary']['exact_duplicate_occurrences'],1)
            self.assertEqual(len(result['windows']),2)
            self.assertEqual(result['windows'][0]['priority'],1)
            ids=[i for w in result['windows'] for i in w['issue_ids']]
            self.assertEqual(len(ids),len(set(ids)))
            self.assertEqual(set(ids),{r['issue_id'] for r in result['issues']})
            self.assertEqual(result['quality_status_unchanged'],'incomplete')
            self.assertFalse(result['human_answers_prefilled'])
            self.assertEqual(result['incomplete_check_counts']['consistency'],4)
            self.assertEqual(path.read_bytes(),before)
            passes=result['chronological_review_passes']
            self.assertTrue(all(a['end_sample'] < b['start_sample'] for a,b in zip(passes,passes[1:])))
            self.assertLessEqual(result['summary']['planned_listening_seconds'],12.8)

    def test_limit_does_not_chain_entire_chapter_or_duplicate_long_identical_contexts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);path=self.source(root)
            def edit(report):
                for i,c in enumerate(report['boundaries']):c['issues']=[issue(scope_id=str(i))]
                report['boundaries'][0]['issues'].append(issue(code='cutoff',dimension='stitching'))
            self.update(path,edit)
            result=build_review_queue(path,max_window_seconds=4)
            self.assertEqual(len(result['windows']),3)
            self.assertTrue(all(w['single_context_exceeds_limit'] for w in result['windows']))
            self.assertEqual(sorted(len(w['issue_ids']) for w in result['windows']),[1,1,2])
            self.assertTrue(all(w['duration_seconds']==6.4 for w in result['windows']))
            self.assertEqual(len(result['chronological_review_passes']),1)
            self.assertEqual(result['summary']['planned_listening_seconds'],12.8)
            self.assertAlmostEqual(result['summary']['optional_overlapping_window_seconds'],19.2)

    def test_exact_adjudication_is_respected_and_changed_dependencies_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);path=self.source(root)
            self.update(path,lambda r:r['chunks'][0]['report']['issues'].append(issue()))
            original=json.loads(path.read_text())
            review={'version':VERSION,'source_report_sha256':fixtures.sha(path),
                'source_audio_sha256':original['final_verification']['metrics']['encoded_sha256'],
                'reviewer':'synthetic','reviewed_at':'2026-10-17T12:00:00+08:00',
                'decisions':[{'scope':'chunk','index':0,'issue_sha256':fingerprint(issue()),
                    'resolution':'false_positive','reason':'构造裁决',
                    'verified_tts_text':original['chunks'][0]['chunk']['tts_text'],
                    'content_complete':True,'no_additions':True}]}
            review_path=root/'review.json';review_path.write_text(json.dumps(review))
            derived=root/'derived.json';derived.write_text(json.dumps(adjudicate_quality(path,review_path)))
            result=build_review_queue(derived)
            self.assertEqual(result['issues'],[])
            self.assertEqual(len(result['review_dependencies']),2)
            self.assertEqual(result['quality_status_unchanged'],'incomplete')
            review_path.write_text('{}')
            with self.assertRaises(ValueError):build_review_queue(derived)

    def test_invalid_limit_changed_audio_and_missing_boundaries_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);path=self.source(root)
            for limit in (True,0,-1,float('nan'),float('inf')):
                with self.subTest(limit=limit),self.assertRaises(ValueError):build_review_queue(path,max_window_seconds=limit)
            self.update(path,lambda r:r['boundaries'].pop())
            with self.assertRaises(ValueError):build_review_queue(path)
            final=path.parent/'final.wav';final.write_bytes(b'changed')
            with self.assertRaises(ValueError):build_review_queue(path)

    def test_cli_refuses_overwrite_and_preserves_final_global_issues(self):
        import contextlib
        import io
        from audiobook_generator.audio_core.__main__ import main
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);path=self.source(root)
            self.update(path,lambda r:r['final_verification']['issues'].append(
                issue(code='encoding_content_loss',severity='error',certainty='confirmed')))
            output=root/'queue.json'
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['prepare-review-queue','--report',str(path),'--output',str(output)]),0)
            result=json.loads(output.read_text())
            self.assertEqual(len(result['global_issue_ids']),1)
            self.assertEqual(result['issues'][0]['priority'],0)
            self.assertEqual(result['chronological_review_passes'][0]['duration_seconds'],12.8)
            before=output.read_bytes()
            with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                self.assertNotEqual(main(['prepare-review-queue','--report',str(path),'--output',str(output)]),0)
            self.assertEqual(output.read_bytes(),before)
