import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from audiobook_generator.role_script.audio_quality import (
    AudioQualityReport, QualityPolicy, choose_quality_attempt,
    evaluate_segment_audio, recommended_mimo_speed,
)


class AudioQualityTest(unittest.TestCase):
    def _wav(self, folder, seconds, *, amplitude=0.15, padding=0):
        rate = 16000
        active = amplitude * np.sin(2 * np.pi * 220 * np.arange(int(seconds * rate)) / rate)
        signal = np.concatenate([np.zeros(int(padding * rate)), active,
                                 np.zeros(int(padding * rate))]).astype("float32")
        path = Path(folder) / "sample.wav"
        sf.write(path, signal, rate)
        return path

    def test_chinese_speed_uses_active_span_and_recommends_slower_playback(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self._wav(folder, 1, padding=0.3)
            report = evaluate_segment_audio("一二三四五六七八九十", path, QualityPolicy(),
                                            transcribe=lambda _: "一二三四五六七八九十")
        self.assertEqual(report.status, "failed")
        self.assertIn("too_fast", report.issues)
        self.assertGreater(report.speech_rate, 9)
        self.assertLess(recommended_mimo_speed(1.0, report, QualityPolicy()), 1.0)

    def test_asr_mismatch_and_unavailable_are_distinct(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self._wav(folder, 4)
            mismatch = evaluate_segment_audio("一二三四五六七八九十", path, QualityPolicy(),
                                              transcribe=lambda _: "完全不同文字")
            unavailable = evaluate_segment_audio("一二三四五六七八九十", path, QualityPolicy(),
                                                 transcribe=lambda _: (_ for _ in ()).throw(ImportError("无模型")))
        self.assertIn("asr_mismatch", mismatch.issues)
        self.assertEqual(mismatch.status, "failed")
        self.assertEqual(unavailable.status, "incomplete")
        self.assertIn("asr_unavailable", unavailable.issues)

    def test_signal_clipping_and_best_attempt(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self._wav(folder, 3, amplitude=1.5)
            bad = evaluate_segment_audio("一二三四五六七八九十", path, QualityPolicy(),
                                         transcribe=lambda _: "一二三四五六七八九十")
        self.assertIn("clipping", bad.issues)
        good = AudioQualityReport("passed", (), 3, 3.3, 0.0, 0.0, 0.0, -10, "一二三四五六七八九十")
        self.assertEqual(choose_quality_attempt(bad, good), 2)


if __name__ == "__main__":
    unittest.main()
