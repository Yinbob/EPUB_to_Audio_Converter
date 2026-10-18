import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import soundfile as sf

from audiobook_generator.audio_core.audio import assemble_pcm
from audiobook_generator.audio_core.encoding import verify_encoded_audio
from audiobook_generator.audio_core.models import ReadingChunk
from audiobook_generator.role_script.audio_pipeline import require_ffmpeg_tools


class EncodingVerificationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.chunks = [ReadingChunk("a", "u", "narrator", "甲", "甲", 0, 1),
                       ReadingChunk("b", "v", "narrator", "乙", "乙", 0, 1)]
        paths = []
        for i in range(2):
            path = self.root / f"source{i}.wav"
            sf.write(path, .1 * np.sin(np.arange(32000) * (.08 + i * .05)), 16000, subtype="PCM_16")
            paths.append(path)
        self.reference = self.root / "reference.wav"
        self.mapping = assemble_pcm(self.chunks, paths, self.reference)

    def verify(self, final, transcribe=None, *, asr=True):
        def unexpected(_):
            self.fail("PCM 相同时不应调用转写")
        evaluator = SimpleNamespace(transcript=transcribe or unexpected, evaluation_seconds=0.)
        return verify_encoded_audio(final, self.reference, self.chunks, self.mapping,
                                    self.root / "checks", evaluator, enable_asr=asr)

    def test_lossless_pcm_equality_proves_encoding_preservation_without_asr(self):
        final = self.root / "final.wav"
        shutil.copyfile(self.reference, final)
        result = self.verify(final)
        self.assertEqual(result.status, "passed")
        self.assertTrue(result.metrics["pcm_equal"])
        self.assertEqual(result.metrics["content_method"], "exact_pcm_equivalence")
        self.assertEqual(result.metrics["checks"], [])
        self.assertEqual(result.metrics["reference_pcm_path"], str(self.reference.resolve()))

    def test_same_duration_repetition_is_caught_by_post_encoding_alignment(self):
        a, rate = sf.read(self.root / "source0.wav")
        final = self.root / "repeated.wav"
        sf.write(final, np.concatenate([a, a]), rate, subtype="PCM_16")
        # 构造的转写夹具只验证编码后检查能发现等长重复，不代表真实 ASR 检出率。
        def transcript(path):
            return "甲甲" if path.name.startswith("boundary") else "甲"
        result = self.verify(final, transcript)
        self.assertEqual(result.metrics["sample_count_delta"], 0)
        self.assertFalse(result.metrics["pcm_equal"])
        self.assertEqual(result.status, "incomplete")
        self.assertEqual(len(result.metrics["checks"]), 3)
        self.assertTrue(any(i.code == "encoded_asr_mismatch" and i.scope_id == "encoded:b" for i in result.issues))
        self.assertTrue(all(i.certainty == "suspected" for i in result.issues))

    def test_truncation_and_silence_are_confirmed_but_missing_asr_is_unknown(self):
        samples, rate = sf.read(self.reference)
        final = self.root / "bad.wav"
        sf.write(final, samples[:-rate], rate)
        self.assertEqual(self.verify(final).status, "failed")
        sf.write(final, samples * .9, rate)
        result = self.verify(final, asr=False)
        self.assertEqual(result.dimensions["content"], "incomplete")
        self.assertEqual(result.metrics["asr_unavailable"], "disabled")
        sf.write(final, np.zeros_like(samples), rate)
        result = self.verify(final, lambda _: "甲乙")
        self.assertEqual(result.status, "failed")
        self.assertTrue(any(i.code == "encoded_too_quiet" for i in result.issues))

    def test_real_mp3_decode_uses_recorded_chunk_and_pair_ranges(self):
        ffmpeg, _ = require_ffmpeg_tools()
        final = self.root / "final.mp3"
        subprocess.run([ffmpeg, "-v", "error", "-y", "-i", str(self.reference), "-c:a", "libmp3lame", str(final)],
                       check=True, capture_output=True)
        def transcript(path):
            return "甲乙" if path.name.startswith("boundary") else ("甲" if "000001" in path.name else "乙")
        result = self.verify(final, transcript)
        self.assertEqual(result.dimensions["encoding"], "passed")
        self.assertEqual(result.dimensions["content"], "passed")
        self.assertFalse(result.metrics["pcm_equal"])
        self.assertEqual([c["start_seconds"] for c in result.metrics["checks"]], [0, 2, 0])
        self.assertTrue(all(Path(c["path"]).is_file() for c in result.metrics["checks"]))
