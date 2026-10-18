"""构造文件替换仅验证证据失效，不充当真实声学缺陷数据。"""
import hashlib
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from audiobook_generator.audio_core.models import CoreOptions, ReadingChunk
from audiobook_generator.audio_core.quality import QualityEvaluator


class ReferenceIntegrityTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.path = self.root / 'current.wav'
        self.reference = self.root / 'reference.wav'
        self.write(self.path, .1)
        self.write(self.reference, .1)
        text = 'The young boy opened the door and waited outside.'
        self.chunk = ReadingChunk('c', 'u', 'hero', text, text, 0, len(text), language='en')

    def write(self, path, frequency):
        sf.write(path, .1 * np.sin(np.arange(64000) * frequency), 16000)

    def sha(self, path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def evaluator(self, **kwargs):
        return QualityEvaluator(CoreOptions(language='en'),
            transcribe=kwargs.get('transcribe', lambda _: self.chunk.tts_text),
            speaker=kwargs.get('speaker', lambda _: np.array([1., 0.])))

    def test_clone_input_is_bound_but_not_content_or_rate_verified(self):
        from audiobook_generator.audio_core.role_references import clone_conditioning_reference
        profile = {'voice_mode': 'clone', 'reference_audio_path': str(self.reference),
                   'reference_audio_sha256': self.sha(self.reference)}
        anchor = clone_conditioning_reference(profile)
        self.assertNotIn('content_alignment', anchor[1])
        self.assertNotIn('human_review', anchor[1])
        report = self.evaluator().evaluate_chunk(self.chunk, self.path, anchor=anchor)
        evidence = report.metrics['consistency_reference']
        self.assertEqual(evidence['kind'], 'clone_conditioning_reference')
        self.assertEqual(evidence['source_binding'], 'matched_recorded_sha256')
        self.assertAlmostEqual(report.metrics['speaker_distance'], 0)
        self.assertEqual(report.metrics['rate_reference_unavailable'], 'reference_rate_unreliable')
        self.assertEqual(report.dimensions['consistency'], 'incomplete')

    def test_bad_clone_inputs_cannot_be_used_as_consistency_anchors(self):
        from audiobook_generator.audio_core.role_references import clone_conditioning_reference
        profile = {'voice_mode': 'clone', 'reference_audio_path': str(self.reference),
                   'reference_audio_sha256': '0' * 64}
        with self.assertRaisesRegex(ValueError, '指纹'):
            clone_conditioning_reference(profile)
        for level in (0, 1):
            sf.write(self.reference, np.full(64000, level, dtype=float), 16000, subtype='PCM_16')
            profile['reference_audio_sha256'] = self.sha(self.reference)
            self.assertIsNone(clone_conditioning_reference(profile))
        self.assertIsNone(clone_conditioning_reference({'voice_mode': 'design'}))

    def test_unverified_reference_is_not_reported_as_content_checked(self):
        evaluator = self.evaluator()
        report = evaluator.evaluate_chunk(self.chunk, self.path, anchor=(self.reference, {
            'content_alignment': {'operations': [{'kind': 'replace'}]}, 'peak': .1, 'clipped_fraction': 0}))
        evidence = report.metrics['consistency_reference']
        self.assertEqual(evidence['kind'], 'external_reference_unverified')
        self.assertEqual(evidence['sha256'], self.sha(self.reference))
        self.assertEqual(report.dimensions['consistency'], 'incomplete')

    def test_checked_bootstrap_binds_the_exact_evaluated_audio(self):
        evaluator = self.evaluator()
        first = evaluator.evaluate_chunk(self.chunk, self.reference)
        self.assertEqual(first.metrics['audio_sha256'], self.sha(self.reference))
        second = evaluator.evaluate_chunk(self.chunk, self.path, anchor=(self.reference, first.metrics))
        evidence = second.metrics['consistency_reference']
        self.assertEqual(evidence['kind'], 'bootstrap_signal_and_content_checked')
        self.assertEqual(evidence['sha256'], first.metrics['audio_sha256'])

    def test_changed_fixed_reference_is_rejected_before_embedding(self):
        calls = []
        evaluator = self.evaluator(speaker=lambda path: calls.append(path) or np.array([1., 0.]))
        metrics = {'fixed_reference_kind': 'human_confirmed_fixed_reference',
            'fixed_reference_sha256': self.sha(self.reference)}
        self.write(self.reference, .2)
        with self.assertRaisesRegex(ValueError, '参考音频'):
            evaluator.evaluate_chunk(self.chunk, self.path, anchor=(self.reference, metrics))
        self.assertEqual(calls, [])

    def test_reference_changed_during_comparison_does_not_return_a_report(self):
        def speaker(path):
            if path == str(self.path):
                self.write(self.reference, .2)
            return np.array([1., 0.])
        evaluator = self.evaluator(speaker=speaker)
        with self.assertRaisesRegex(RuntimeError, '参考音频'):
            evaluator.evaluate_chunk(self.chunk, self.path,
                anchor=(self.reference, {'fixed_reference_sha256': self.sha(self.reference)}))

    def test_transcript_for_mutated_audio_is_not_cached(self):
        def transcribe(path):
            self.write(Path(path), .2)
            return self.chunk.tts_text
        evaluator = self.evaluator(transcribe=transcribe)
        with self.assertRaisesRegex(RuntimeError, '音频'):
            evaluator.transcript(self.path)
        self.assertFalse(evaluator.transcripts)

    def test_embedding_for_mutated_audio_is_not_cached(self):
        def speaker(path):
            self.write(Path(path), .2)
            return np.array([1., 0.])
        evaluator = self.evaluator(speaker=speaker)
        with self.assertRaisesRegex(RuntimeError, '音频'):
            evaluator.embedding(self.path)
        self.assertFalse(evaluator.embeddings)

    def test_current_audio_changed_during_asr_cannot_return_mixed_evidence(self):
        def transcribe(path):
            self.write(Path(path), .2)
            return self.chunk.tts_text
        evaluator = self.evaluator(transcribe=transcribe)
        with self.assertRaisesRegex(RuntimeError, '质量评估期间音频变化'):
            evaluator.evaluate_chunk(self.chunk, self.path)
        self.assertFalse(evaluator.transcripts)


if __name__ == '__main__':
    unittest.main()
