"""构造音频只验证尾重复保护、调度及恢复，不计入真实修复成功率。"""
import io
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np
import soundfile as sf

from audiobook_generator.audio_core.models import CoreOptions, ResourceLimits, QualityIssue, QualityReport
from audiobook_generator.audio_core.pipeline import run_chapter
from audiobook_generator.audio_core.quality import QualityEvaluator
from audiobook_generator.audio_core.reading import build_reading_plan
from audiobook_generator.audio_core.store import ArtifactStore, fingerprint
from audiobook_generator.audio_core.tail_repeat import inspect_tail_repeat, repeat_evidence, render_checked_prefix
from audiobook_generator.core.audio_tags import AudioTags
from tests.audiobook_generator.audio_core.pipeline_test import plan_for

BODY = 'Please wait beside the bridge until I arrive.'
EXTRA = 'Please wait beside the bridge.'


def fixture(quiet=True):
    rate = 16000
    tone = lambda n,hz: .12*np.sin(np.arange(n)*2*np.pi*hz/rate)
    return np.concatenate((tone(rate,200),np.zeros(9600) if quiet else tone(9600,200),
                           tone(12800,400),np.zeros(6400))),rate


def transcribe(path):
    pcm,rate = sf.read(path)
    # 400Hz仅为测试中的“重复尾段”标记，不代表真实转写模型。
    start = pcm[:min(rate,len(pcm))]
    freq = np.argmax(abs(np.fft.rfft(start))) * rate / len(start)
    if freq > 300: return EXTRA
    return BODY + (' '+EXTRA if len(pcm)/rate > 2 else '')


class RepeatingProvider:
    provider_id = 'openai'
    def __init__(self): self.calls = 0
    def synthesize_observed_chunk(self,text,profile,store,run_id,*,resample=False,repair=False):
        key = fingerprint({'fixture':text})
        cached = None if resample else store.cached(key)
        if cached: return cached
        self.calls += 1
        request = store.reserve(run_id,key,len(text),repair=repair)
        pcm,rate = fixture(); data=io.BytesIO()
        sf.write(data,pcm,rate,format='WAV',subtype='PCM_16')
        path=store.save_sample(key,data.getvalue(),'wav'); store.settle(request,artifact=path)
        return path


class TailRepeatTest(unittest.TestCase):
    def test_text_requires_complete_body_before_extra_not_internal_repetition(self):
        self.assertTrue(repeat_evidence(BODY,BODY+' '+EXTRA,language='en')['auto_eligible_text'])
        for reference,hyp in ((BODY,BODY),(BODY,'Please wait beside the bridge. Please wait beside the bridge.'),
                              (BODY,BODY+' Some completely unrelated extra words.'),
                              ('Go on. Go on. Please wait beside the bridge.',
                               'Go on. Go on. Please wait beside the bridge.')):
            self.assertIsNone(repeat_evidence(reference,hyp,language='en'))

    def test_chinese_and_original_repeated_words_are_preserved(self):
        body='请在桥边等待我到达之后一起回家。'
        self.assertTrue(repeat_evidence(body,body+'请在桥边等待我。',language='zh')['auto_eligible_text'])
        self.assertIsNone(repeat_evidence('不，不，不！','不，不，不！',language='zh'))
        r=repeat_evidence('No, no, no!','No no no no no',language='en')
        self.assertFalse(r['auto_eligible_text']); self.assertTrue(r['short_or_low_diversity_text'])

    def test_fuzzy_full_reading_is_candidate_only_never_auto(self):
        body="I'm still trying to pull free but the girl's got me in a death grip. My mom's grinning looking at our hands and my fiery red face."
        hyp=body.replace("I'm",'I am').replace("girl's",'girls')+" My mom's grinning looking at our hands and my fiery red face."
        r=repeat_evidence(body,hyp,language='en')
        self.assertIsNotNone(r); self.assertFalse(r['auto_eligible_text'])

    def setup_audio(self,root,quiet=True):
        path=Path(root)/'source.wav'; pcm,rate=fixture(quiet)
        sf.write(path,pcm,rate,subtype='PCM_16')
        c=build_reading_plan(plan_for((BODY,)).units,language='en')[0]
        q=QualityEvaluator(CoreOptions(language='en',enable_speaker=False),transcribe=transcribe)
        report=q.evaluate_chunk(c,path)
        return path,c,q,report

    def test_safe_cut_preserves_exact_pcm_and_independent_prefix_suffix_transcripts(self):
        with tempfile.TemporaryDirectory() as root:
            path,c,q,report=self.setup_audio(root)
            r=inspect_tail_repeat(c,path,report,q,Path(root)/'probes')
            self.assertEqual(r['status'],'candidate_pending_review'); self.assertTrue(r['auto_eligible'])
            self.assertGreater(r['evaluation_seconds'],0)
            a,_=sf.read(path,dtype='int16'); b,_=sf.read(r['candidate_path'],dtype='int16')
            np.testing.assert_array_equal(a[:len(b)],b)
            self.assertEqual(r['candidate_prefix_alignment']['operations'],[])
            self.assertEqual(r['probes'][0]['suffix_tokens'],['please','wait','beside','the','bridge'])

    def test_no_silence_and_deadline_keep_original(self):
        with tempfile.TemporaryDirectory() as root:
            path,c,q,report=self.setup_audio(root,False)
            r=inspect_tail_repeat(c,path,report,q,Path(root)/'probes')
            self.assertEqual(r['status'],'suspected_no_safe_cut'); self.assertNotIn('candidate_path',r)
        with tempfile.TemporaryDirectory() as root:
            path,c,q,report=self.setup_audio(root)
            r=inspect_tail_repeat(c,path,report,q,Path(root)/'probes',deadline=time.perf_counter()-1)
            self.assertEqual(r['status'],'evaluation_time_limit'); self.assertFalse(r['probes'])

    def test_crop_rejects_changed_source_unsafe_point_and_existing_wrong_candidate(self):
        import hashlib
        with tempfile.TemporaryDirectory() as root:
            path,c,q,report=self.setup_audio(root); digest=hashlib.sha256(path.read_bytes()).hexdigest()
            target=Path(root)/'cut.wav'
            with self.assertRaises(ValueError): render_checked_prefix(path,target,end_sample=8000,expected_sha256=digest)
            with self.assertRaises(ValueError): render_checked_prefix(path,path,end_sample=20000,expected_sha256=digest)
            sf.write(target,np.zeros(10),16000,subtype='PCM_16')
            with self.assertRaises(ValueError): render_checked_prefix(path,target,end_sample=20000,expected_sha256=digest)
            sf.write(path,np.zeros(32000),16000,subtype='PCM_16')
            with self.assertRaises(ValueError): render_checked_prefix(path,Path(root)/'new.wav',end_sample=20000,expected_sha256=digest)

    def generate(self,root,provider,mode='auto'):
        options=CoreOptions(language='en',enable_speaker=False,auto_repair=True,tail_repeat_mode=mode,
            max_english_wpm=1000.,
            limits=ResourceLimits(max_requests=1,max_repair_requests=0))
        evaluator=QualityEvaluator(options,transcribe=transcribe)
        return run_chapter(plan_for((BODY,)),provider,Path(root)/'out.wav',AudioTags('章','作者','书',1),
            Path(root)/'project',options=options,evaluator=evaluator)

    def test_auto_local_crop_uses_no_repair_request_and_recovers_deleted_render(self):
        with tempfile.TemporaryDirectory() as root:
            provider=RepeatingProvider(); r=self.generate(root,provider)
            self.assertEqual(provider.calls,1)
            self.assertTrue(r['tail_repeat_checks'][0]['selected'])
            self.assertEqual(r['repair_attempts'][0]['action']['kind'],'local_tail_repeat')
            self.assertTrue(r['repair_attempts'][0]['selected'])
            self.assertEqual(r['chunks'][0]['report']['metrics']['content_alignment']['error_rate'],0)
            self.assertLess(sf.info(r['chunks'][0]['rendered_path']).duration,2)
            Path(r['chunks'][0]['rendered_path']).unlink()
            again=self.generate(root,provider)
            self.assertEqual(provider.calls,1)
            self.assertEqual(again['chunks'][0]['report']['metrics']['content_alignment']['error_rate'],0)
            self.assertEqual(again['resource_summary'],{})
            off=self.generate(root,provider,'off')
            self.assertGreater(sf.info(off['chunks'][0]['rendered_path']).duration,2)
            self.assertFalse(off['tail_repeat_checks'])

    def test_review_mode_exports_candidate_without_selecting_or_regenerating(self):
        with tempfile.TemporaryDirectory() as root:
            provider=RepeatingProvider(); r=self.generate(root,provider,'review')
            self.assertEqual(provider.calls,1)
            self.assertGreater(sf.info(r['chunks'][0]['rendered_path']).duration,2)
            self.assertEqual(r['tail_repeat_checks'][0]['status'],'candidate_pending_review')
            self.assertFalse(r['repair_attempts'])

    def test_new_rate_warning_rejects_cut_instead_of_relaxing_existing_checks(self):
        with tempfile.TemporaryDirectory() as root:
            options=CoreOptions(language='en',enable_speaker=False,auto_repair=True,tail_repeat_mode='auto',
                limits=ResourceLimits(max_requests=1,max_repair_requests=0))
            r=run_chapter(plan_for((BODY,)),RepeatingProvider(),Path(root)/'out.wav',AudioTags('章','作者','书',1),
                Path(root)/'project',options=options,evaluator=QualityEvaluator(options,transcribe=transcribe))
            self.assertFalse(r['tail_repeat_checks'][0]['selected'])
            self.assertEqual(r['repair_attempts'][0]['decision_reason'],'no_priority_gain')
            self.assertGreater(sf.info(r['chunks'][0]['rendered_path']).duration,2)

    def test_invalid_mode_is_rejected(self):
        for value in ('enabled',True,[],None):
            with self.assertRaises(ValueError): CoreOptions(tail_repeat_mode=value)

    def test_pending_repeat_does_not_regenerate_innocent_neighbor(self):
        class NeighborOracle(QualityEvaluator):
            def evaluate_chunk(self,chunk,path,*,anchor=None):
                if chunk.tts_text == 'This is the next sentence.':
                    return QualityReport(chunk.chunk_id,{'content':'passed','signal':'passed'})
                return super().evaluate_chunk(chunk,path,anchor=anchor)
            def evaluate_boundary(self,left,right,*paths,**kwargs):
                return QualityReport(left.chunk_id+'|'+right.chunk_id,{'content':'incomplete'},
                    issues=[QualityIssue('boundary_content_mismatch','content',left.chunk_id)])
        with tempfile.TemporaryDirectory() as root:
            provider=RepeatingProvider()
            options=CoreOptions(language='en',enable_speaker=False,auto_repair=True,tail_repeat_mode='review',
                limits=ResourceLimits(max_requests=4,max_repair_requests=2))
            r=run_chapter(plan_for((BODY,'This is the next sentence.')),provider,Path(root)/'out.wav',
                AudioTags('章','作者','书',1),Path(root)/'project',options=options,
                evaluator=NeighborOracle(options,transcribe=transcribe))
            self.assertEqual(provider.calls,2)
            self.assertFalse(r['repair_attempts'])


if __name__=='__main__': unittest.main()
