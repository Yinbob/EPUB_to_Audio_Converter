"""人工裁决只处理精确问题；构造控制不计入真实检出效果。"""
import contextlib
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path

from audiobook_generator.audio_core.__main__ import main
from audiobook_generator.audio_core.listening import _listening_source, prepare_listening
from audiobook_generator.audio_core.quality_review import VERSION, adjudicate_quality
from audiobook_generator.audio_core.store import fingerprint
from tests.audiobook_generator.audio_core import listening_test

sha = listening_test.sha


class QualityReviewTest(unittest.TestCase):
    def asr_inputs(self, root):
        conditions, path, review_path, review = self.inputs(root)
        report = json.loads(path.read_text())
        report['boundaries'][0]['issues'] = []
        report['boundaries'][0]['dimensions']['content'] = 'passed'
        issue = {'code': 'asr_mismatch', 'dimension': 'content', 'severity': 'warning',
                 'certainty': 'suspected', 'evidence': {'fixture': 'short_phrase_asr_error'}}
        check = report['chunks'][0]['report']
        check['issues'] = [issue]
        check['dimensions'].update(content='incomplete', consistency='incomplete')
        check['status'] = 'incomplete'
        path.write_text(json.dumps(report))
        review['source_report_sha256'] = sha(path)
        review['decisions'] = [{'scope': 'chunk', 'index': 0, 'issue_sha256': fingerprint(issue),
            'resolution': 'false_positive', 'reason': 'constructed full-utterance human judgment',
            'verified_tts_text': report['chunks'][0]['chunk']['tts_text'],
            'content_complete': True, 'no_additions': True}]
        review_path.write_text(json.dumps(review))
        return conditions, path, review_path, review

    def inputs(self,root):
        conditions=listening_test.ListeningTest().conditions(root)
        path=Path(conditions[0]['report_path']);report=json.loads(path.read_text())
        issue={'code':'boundary_content_mismatch','dimension':'content','severity':'warning',
               'certainty':'suspected','evidence':{'fixture':'wrong_asr'}}
        report['boundaries'][0]['issues']=[issue]
        report['boundaries'][0]['dimensions']['content']='incomplete'
        path.write_text(json.dumps(report))
        review={'version':VERSION,'source_report_sha256':sha(path),
                'source_audio_sha256':report['final_verification']['metrics']['encoded_sha256'],
                'reviewer':'fixture-reviewer','reviewed_at':'2026-10-16T21:00:00+08:00',
                'decisions':[{'scope':'boundary','index':0,'issue_sha256':fingerprint(issue),
                              'resolution':'false_positive','reason':'constructed normal-content judgment'}]}
        review_path=root/'review.json';review_path.write_text(json.dumps(review))
        return conditions,path,review_path,review

    def save(self,path,result):path.write_text(json.dumps(result));return path

    def test_exact_review_enables_draft_and_keeps_machine_evidence_and_original(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);conditions,path,review_path,_=self.inputs(root);before=path.read_bytes()
            with self.assertRaises(ValueError):_listening_source(path)
            result=adjudicate_quality(path,review_path)
            self.assertEqual(path.read_bytes(),before)
            self.assertEqual(result['boundaries'][0]['dimensions']['content'],'passed')
            self.assertEqual(result['boundaries'][0]['issues'],[])
            self.assertEqual(len(result['boundaries'][0]['machine_evidence']['issues']),1)
            self.assertFalse(result['human_adjudication']['full_chapter_human_verified'])
            derived=self.save(root/'derived.json',result)
            self.assertEqual(len(_listening_source(derived)['review_dependencies']),2)
            conditions[0]['report_path']=str(derived)
            exported=prepare_listening(conditions,root/'pack')
            self.assertEqual(exported['trials'],8)
            key=json.loads((root/'pack/private_answer_key.json').read_text())
            self.assertEqual(len(key['sources'][0]['human_review_dependencies']),2)
            public=(root/'pack/public/trials.json').read_text()
            self.assertNotIn('fixture-reviewer',public)
            self.assertNotIn(str(review_path),public)

    def test_hash_wrong_position_duplicate_or_unsupported_dismissal_is_rejected(self):
        mutations=[lambda r:r.update(source_report_sha256='wrong'),
                   lambda r:r['decisions'][0].update(index=1),
                   lambda r:r['decisions'].append(copy.deepcopy(r['decisions'][0])),
                   lambda r:r['decisions'][0].update(resolution='acceptable_variation'),
                   lambda r:r.update(reviewer=''),lambda r:r.update(reviewed_at='2026-10-16')]
        for mutate in mutations:
            with self.subTest(mutation=mutations.index(mutate)),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);_,path,review_path,review=self.inputs(root)
                mutate(review);review_path.write_text(json.dumps(review))
                with self.assertRaises(ValueError):adjudicate_quality(path,review_path)

    def test_derived_report_and_changed_review_cannot_bypass_existing_gate(self):
        for target in ('review','derived','source_audio'):
            with self.subTest(target=target),tempfile.TemporaryDirectory() as temp:
                root=Path(temp);_,path,review_path,review=self.inputs(root)
                result=adjudicate_quality(path,review_path);derived=self.save(root/'derived.json',result)
                if target=='review':
                    review['decisions'][0]['reason']='changed';review_path.write_text(json.dumps(review))
                elif target=='derived':
                    result['chunks'][0]['chunk']['tts_text']='wrong';self.save(derived,result)
                else:
                    Path(result['output_file']).write_bytes(b'changed')
                with self.assertRaises(ValueError):_listening_source(derived)

    def test_unresolved_human_issue_still_blocks_and_cannot_be_silenced_by_content_review(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);_,path,review_path,review=self.inputs(root)
            review['additional_issues']=[{'scope':'boundary','index':0,'issue':{
                'code':'human_loudness_mismatch','dimension':'signal','severity':'warning',
                'evidence':{'reviewer_statement':'right louder'}}}]
            review_path.write_text(json.dumps(review));result=adjudicate_quality(path,review_path)
            self.assertEqual(result['boundaries'][0]['issues'][0]['code'],'human_loudness_mismatch')
            with self.assertRaises(ValueError):_listening_source(self.save(root/'derived.json',result))

    def test_cli_refuses_overwrite_and_changed_review_during_export_leaves_no_pack(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);conditions,path,review_path,review=self.inputs(root);derived=root/'derived.json'
            args=['adjudicate-quality','--manifest',str(path),'--review',str(review_path),'--output',str(derived)]
            stdout=io.StringIO();stderr=io.StringIO()
            with contextlib.redirect_stdout(stdout):self.assertEqual(main(args),0)
            before=derived.read_bytes()
            with contextlib.redirect_stderr(stderr):self.assertEqual(main(args),2)
            self.assertEqual(derived.read_bytes(),before)
            conditions[0]['report_path']=str(derived)
            from unittest.mock import patch
            from audiobook_generator.audio_core import listening
            original=listening.shutil.copyfile
            def changed(*args,**kwargs):
                value=original(*args,**kwargs)
                review_path.write_text(json.dumps({**review,'reviewer':'changed'}))
                return value
            with patch.object(listening.shutil,'copyfile',side_effect=changed):
                with self.assertRaisesRegex(ValueError,'裁决依据改变'):
                    prepare_listening(conditions,root/'pack')
            self.assertFalse((root/'pack').exists())

    def test_exact_asr_review_preserves_original_and_unverified_consistency(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, path, review_path, _ = self.asr_inputs(root)
            before = path.read_bytes()
            result = adjudicate_quality(path, review_path)
            check = result['chunks'][0]['report']
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(check['dimensions']['content'], 'passed')
            self.assertEqual(check['dimensions']['consistency'], 'incomplete')
            self.assertEqual(check['status'], 'incomplete')
            self.assertEqual(check['machine_evidence']['issues'][0]['code'], 'asr_mismatch')
            self.assertFalse(result['human_adjudication']['full_chapter_human_verified'])
            from audiobook_generator.audio_core.quality_review import validate_adjudicated_source
            from audiobook_generator.audio_core.repair_review import _read_report
            derived = self.save(root/'asr_derived.json', result)
            self.assertEqual(len(validate_adjudicated_source(_read_report(derived))), 2)

    def test_asr_review_needs_exact_spoken_reference_and_both_content_judgments(self):
        mutations = [lambda r: r['decisions'][0].update(verified_tts_text='different reading'),
                     lambda r: r['decisions'][0].pop('content_complete'),
                     lambda r: r['decisions'][0].update(content_complete=1),
                     lambda r: r['decisions'][0].pop('no_additions'),
                     lambda r: r['decisions'][0].update(no_additions=False)]
        for mutate in mutations:
            with self.subTest(mutation=mutations.index(mutate)), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                _, path, review_path, review = self.asr_inputs(root)
                mutate(review); review_path.write_text(json.dumps(review))
                with self.assertRaisesRegex(ValueError, 'ASR误报'):
                    adjudicate_quality(path, review_path)

    def test_asr_review_cannot_dismiss_boundary_severe_or_failed_content(self):
        for mutation in ('boundary', 'severe', 'failed', 'wrong_dimension'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                _, path, review_path, review = self.asr_inputs(root)
                report = json.loads(path.read_text())
                check = report['chunks'][0]['report']
                issue = check['issues'][0]
                if mutation == 'boundary':
                    report['boundaries'][0]['issues'] = [issue]
                    review['decisions'][0]['scope'] = 'boundary'
                elif mutation == 'severe': issue['severity'] = 'error'
                elif mutation == 'failed': check['dimensions']['content'] = 'failed'
                else: issue['dimension'] = 'signal'
                path.write_text(json.dumps(report)); review['source_report_sha256'] = sha(path)
                review['decisions'][0]['issue_sha256'] = fingerprint(issue)
                review_path.write_text(json.dumps(review))
                with self.assertRaises(ValueError): adjudicate_quality(path, review_path)

    def test_asr_review_keeps_unresolved_content_and_rejects_changed_dependencies(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _, path, review_path, review = self.asr_inputs(root)
            report = json.loads(path.read_text())
            report['chunks'][0]['report']['issues'].append({'code': 'another_content_warning',
                'dimension': 'content', 'severity': 'warning', 'certainty': 'suspected', 'evidence': {}})
            path.write_text(json.dumps(report)); review['source_report_sha256'] = sha(path)
            review_path.write_text(json.dumps(review))
            result = adjudicate_quality(path, review_path)
            check = result['chunks'][0]['report']
            self.assertEqual(check['dimensions']['content'], 'incomplete')
            self.assertEqual([i['code'] for i in check['issues']], ['another_content_warning'])
            from audiobook_generator.audio_core.quality_review import validate_adjudicated_source
            from audiobook_generator.audio_core.repair_review import _read_report
            derived = self.save(root/'derived.json', result)
            review['decisions'][0]['verified_tts_text'] = 'tampered'
            review_path.write_text(json.dumps(review))
            with self.assertRaises(ValueError): validate_adjudicated_source(_read_report(derived))


if __name__=='__main__':unittest.main()
