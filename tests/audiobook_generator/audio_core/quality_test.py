import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from audiobook_generator.audio_core.models import CoreOptions, ReadingChunk
from audiobook_generator.audio_core.quality import QualityEvaluator, align_text


class QualityCoreTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.path = Path(self.root.name) / "sound.wav"
        sf.write(self.path, .1 * np.sin(np.arange(64000) * .1), 16000)
        self.chunk = ReadingChunk("a", "u", "hero", "今天增长3.5%。", "今天增长百分之三点五。", 0, 9)

    def test_alignment_retains_deletion_and_insertion_evidence(self):
        self.assertEqual(align_text("今天增长3.5%", "今天增长百分之三点五")["error_rate"], 0)
        self.assertEqual(align_text("你好世界", "你好")["deletions"], 2)
        self.assertEqual(align_text("你好", "你好你好")["insertions"], 2)

    def test_explicit_readings_and_quantity_equivalence_apply_to_asr(self):
        dictionary = {"API": "诶劈爱"}
        self.assertEqual(align_text("诶劈爱重三点五千克", "API重3.5千克", dictionary=dictionary)["error_rate"], 0)
        chunk = ReadingChunk("a", "u", "hero", "API重3.5千克。", "诶劈爱重三点五千克。", 0, 11)
        evaluator = QualityEvaluator(CoreOptions(reading_dictionary=dictionary), transcribe=lambda _: "API重3.5千克。")
        report = evaluator.evaluate_chunk(chunk, self.path)
        self.assertEqual(report.dimensions["content"], "passed")
        self.assertFalse(any(i.code == "asr_mismatch" for i in report.issues))

    def test_missing_models_do_not_appear_as_passed(self):
        evaluator = QualityEvaluator(CoreOptions())
        report = evaluator.evaluate_chunk(self.chunk, self.path)
        self.assertEqual(report.status, "incomplete")
        self.assertEqual(report.dimensions["content"], "incomplete")
        self.assertIn("asr_unavailable", report.metrics)

    def test_transcript_cached_and_asr_error_is_only_suspected(self):
        calls = []
        def transcribe(path):
            calls.append(path)
            return "今天增长"
        evaluator = QualityEvaluator(CoreOptions(), transcribe=transcribe)
        report = evaluator.evaluate_chunk(self.chunk, self.path)
        evaluator.evaluate_chunk(self.chunk, self.path)
        self.assertEqual(len(calls), 1)
        self.assertTrue(any(i.code == "asr_mismatch" and i.certainty == "suspected" for i in report.issues))
        self.assertNotEqual(report.status, "failed")

    def test_speaker_evidence_is_computed_but_not_falsely_calibrated(self):
        evaluator = QualityEvaluator(CoreOptions(), transcribe=lambda _: self.chunk.tts_text,
                                     speaker=lambda _: np.array([1., 0.]))
        first = evaluator.evaluate_chunk(self.chunk, self.path)
        second = evaluator.evaluate_chunk(self.chunk, self.path, anchor=(self.path, first.metrics))
        self.assertAlmostEqual(second.metrics["speaker_distance"], 0)
        self.assertEqual(second.dimensions["consistency"], "incomplete")

    def test_boundary_checks_actual_combination_and_marks_role_switch(self):
        right = ReadingChunk("b", "v", "other", "你好。", "你好。", 0, 3)
        evaluator = QualityEvaluator(CoreOptions(), transcribe=lambda _: "今天增长百分之三点五你好你好")
        report = evaluator.evaluate_boundary(self.chunk, right, self.path, self.path, assembled_window=self.path)
        self.assertEqual(report.metrics["features"]["same_speaker"], 0)
        self.assertTrue(any(i.code == "boundary_content_mismatch" for i in report.issues))

    def test_large_speaker_and_pitch_changes_are_suspected_not_confirmed(self):
        other = Path(self.root.name) / "other.wav"
        sf.write(other, .1 * np.sin(np.arange(64000) * .2), 16000)
        evaluator = QualityEvaluator(CoreOptions(), transcribe=lambda _: self.chunk.tts_text,
            speaker=lambda path: np.array([1., 0.]) if path == str(self.path) else np.array([0., 1.]))
        first = evaluator.evaluate_chunk(self.chunk, self.path)
        second = evaluator.evaluate_chunk(self.chunk, other, anchor=(self.path, first.metrics))
        codes = {i.code for i in second.issues}
        self.assertTrue({"speaker_drift", "pitch_drift"} <= codes)
        self.assertTrue(all(i.certainty == "suspected" for i in second.issues))

    def test_local_slowdown_factor_reduces_atempo_instead_of_increasing_it(self):
        from audiobook_generator.audio_core.repair import propose_actions
        from audiobook_generator.audio_core.models import QualityIssue, QualityReport
        report = QualityReport("x", metrics={"articulation_rate": 5.0},
                               issues=[QualityIssue("too_fast", "consistency", "x")])
        action = propose_actions(report)[0]
        self.assertEqual(action.kind, "local_speed")
        self.assertLess(action.speed_factor, 1)
        self.assertGreaterEqual(action.speed_factor, 1 / 1.05)


if __name__ == "__main__":
    unittest.main()
