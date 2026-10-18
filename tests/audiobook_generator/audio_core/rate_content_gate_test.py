"""参考词数不能代表错读音频中的实际朗读量；夹具不用于声学效果结论。"""
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from audiobook_generator.audio_core.models import CoreOptions, ReadingChunk, ResourceLimits
from audiobook_generator.audio_core.pipeline import run_chapter
from audiobook_generator.audio_core.quality import QualityEvaluator
from audiobook_generator.audio_core.repair import propose_actions
from audiobook_generator.core.audio_tags import AudioTags
from tests.audiobook_generator.audio_core.pipeline_test import ObservedFake, plan_for


class RateContentGateTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / 'sound.wav'
        sf.write(self.path, .1 * np.sin(np.arange(64000) * .1), 16000)
        self.text = 'One two three four five six seven eight nine ten eleven twelve.'
        self.chunk = ReadingChunk('en', 'u', 'narrator', self.text, self.text, 0, len(self.text), language='en')
        self.anchor = (self.path, {'articulation_rate': .2, 'articulation_rate_unit': 'words_per_second'})

    def evaluator(self, transcript, **kwargs):
        return QualityEvaluator(CoreOptions(language='en', max_english_wpm=120, enable_speaker=False, **kwargs),
                                transcribe=lambda _: transcript)

    def test_known_repetition_omission_and_substitution_do_not_trigger_rate_repairs(self):
        for transcript in (self.text + ' One two three.', 'One two three four five.',
                           self.text.replace('twelve', 'thirteen')):
            with self.subTest(transcript=transcript):
                report = self.evaluator(transcript).evaluate_chunk(self.chunk, self.path, anchor=self.anchor)
                codes = {i.code for i in report.issues}
                self.assertIn('asr_mismatch', codes)
                self.assertFalse(codes & {'too_fast', 'rate_drift'})
                self.assertEqual(report.metrics['rate_estimate_status'], 'unreliable_content_mismatch')
                self.assertEqual(report.metrics['rate_reference_unavailable'], 'current_content_mismatch')
                self.assertGreater(report.metrics['words_per_minute'], 120)
                self.assertEqual([a.kind for a in propose_actions(report)], ['content_repair'])

    def test_aligned_content_still_checks_rate_and_drift(self):
        report = self.evaluator(self.text).evaluate_chunk(self.chunk, self.path, anchor=self.anchor)
        self.assertTrue({'too_fast', 'rate_drift'} <= {i.code for i in report.issues})
        self.assertEqual(report.metrics['rate_estimate_status'], 'reference_estimate_content_aligned')
        self.assertTrue(report.metrics['rate_estimate_usable_for_heuristics'])

    def test_bad_reference_cannot_create_rate_drift_for_good_current_text(self):
        bad_anchor = {**self.anchor[1], 'content_alignment': {'operations': [{'kind': 'insert'}]}}
        report = self.evaluator(self.text).evaluate_chunk(self.chunk, self.path, anchor=(self.path, bad_anchor))
        self.assertIn('too_fast', {i.code for i in report.issues})
        self.assertNotIn('rate_drift', {i.code for i in report.issues})
        self.assertEqual(report.metrics['rate_reference_unavailable'], 'reference_rate_unreliable')

    def test_disabled_asr_keeps_explicit_unverified_heuristic_behavior(self):
        report = self.evaluator(self.text, enable_asr=False).evaluate_chunk(self.chunk, self.path)
        self.assertIn('too_fast', {i.code for i in report.issues})
        self.assertEqual(report.dimensions['content'], 'incomplete')
        self.assertEqual(report.metrics['rate_estimate_status'], 'reference_estimate_content_unverified')

    def test_pipeline_spends_repair_on_content_without_slowing_mismatched_audio(self):
        provider = ObservedFake()
        options = CoreOptions(language='en', max_english_wpm=1, enable_speaker=False, auto_repair=True,
                              limits=ResourceLimits(max_requests=2, max_repair_requests=1, per_chunk_repairs=1))
        evaluator = QualityEvaluator(options, transcribe=lambda _: self.text + ' One two three.')
        result = run_chapter(plan_for((self.text,)), provider, self.root / 'out.wav',
            AudioTags('章', '作者', '书', 1), self.root / 'project', options=options, evaluator=evaluator)
        self.assertEqual(len(provider.calls), 2)
        self.assertEqual([r['action']['kind'] for r in result['repair_attempts']], ['content_repair'])
        self.assertEqual(result['chunks'][0]['render_operations'], [])
        self.assertEqual(result['chunks'][0]['speed'], 1.)
        self.assertTrue(any(i['code'] == 'asr_mismatch' for i in result['chunks'][0]['report']['issues']))
