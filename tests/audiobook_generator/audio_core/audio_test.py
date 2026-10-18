import tempfile
import unittest
from dataclasses import replace
import hashlib
from pathlib import Path

import numpy as np
import soundfile as sf

from audiobook_generator.audio_core.audio import assemble_pcm, boundary_features, render_safe_boundary, signal_features
from audiobook_generator.audio_core.models import ReadingChunk


class AudioCoreAudioTest(unittest.TestCase):
    def test_safe_silence_trim_removes_only_digital_zero_and_preserves_quiet_speech(self):
        with tempfile.TemporaryDirectory() as root:
            source, output = Path(root) / "source.wav", Path(root) / "trimmed.wav"
            speech = np.r_[np.ones(800) * .001, np.sin(np.arange(3200) * .1) * .1]
            sf.write(source, np.r_[np.zeros(16000), speech], 16000, subtype="PCM_16")
            before, _ = sf.read(source, dtype="int16")
            operation = render_safe_boundary(source, output, kind="local_trim_silence", edge="head", keep_silence_ms=100)
            after, _ = sf.read(output, dtype="int16")
            self.assertEqual(operation["removed_samples"], 14400)
            np.testing.assert_array_equal(after, before[14400:])
            # 不能把小声发音误当静音继续裁切。
            with self.assertRaisesRegex(ValueError, "没有可安全"):
                render_safe_boundary(output, source.with_name("unsafe.wav"), kind="local_trim_silence", edge="head", keep_silence_ms=100)

    def test_edge_fade_requires_isolated_impulse_and_never_fades_speech(self):
        with tempfile.TemporaryDirectory() as root:
            source, output = Path(root) / "source.wav", Path(root) / "faded.wav"
            samples = np.r_[.1 * np.sin(np.arange(3200) * .1), np.zeros(1000), .8]
            sf.write(source, samples, 16000, subtype="PCM_16")
            before, _ = sf.read(source, dtype="int16")
            op = render_safe_boundary(source, output, kind="local_edge_fade", edge="tail")
            after, _ = sf.read(output, dtype="int16")
            np.testing.assert_array_equal(after[:-1], before[:-1])
            self.assertEqual(after[-1], 0)
            self.assertEqual(op["isolated_impulse_samples"], 1)
            sf.write(source, np.r_[np.ones(2000) * .1, .8], 16000)
            with self.assertRaisesRegex(ValueError, "不能安全淡化"):
                render_safe_boundary(source, output, kind="local_edge_fade", edge="tail")

    def test_assembly_preserves_tail_and_adds_only_missing_silence(self):
        with tempfile.TemporaryDirectory() as root:
            a, b, target = [Path(root) / p for p in ("a.wav", "b.wav", "joined.wav")]
            sr = 16000
            sound = np.sin(np.arange(sr) * .1) * .2
            sf.write(a, np.r_[sound, np.zeros(1600)], sr)
            sf.write(b, np.r_[np.zeros(1600), sound], sr)
            chunks = [ReadingChunk("a", "u", "r", "甲", "甲", 0, 1, pause_after_ms=300),
                      ReadingChunk("b", "v", "r", "乙", "乙", 0, 1)]
            mapping = assemble_pcm(chunks, [a, b], target)
            self.assertEqual(mapping["boundaries"][0]["added_silence_samples"], 1600)
            rendered, _ = sf.read(target)
            original, _ = sf.read(a)
            np.testing.assert_array_equal(rendered[:len(original)], original)
            self.assertEqual(len(rendered), 36800)
            self.assertEqual(mapping["spans"][1]["start_sample"], 19200)

    def test_missing_or_duplicate_chunks_are_rejected(self):
        chunk = ReadingChunk("a", "u", "r", "甲", "甲", 0, 1)
        with self.assertRaises(ValueError):
            assemble_pcm([chunk], [], "unused.wav")
        with self.assertRaises(ValueError):
            assemble_pcm([chunk, chunk], ["a.wav", "a.wav"], "unused.wav")

    def test_features_keep_speaker_switch_as_explicit_input(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "a.wav"
            sf.write(path, .1 * np.sin(np.arange(16000) * 2 * np.pi * 200 / 16000), 16000)
            features = signal_features(path)
            self.assertAlmostEqual(features["pitch"]["median_hz"], 200, delta=10)
            self.assertEqual(boundary_features(path, path, same_speaker=False)["same_speaker"], 0)

    def test_shuffled_plan_or_artifact_mapping_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            a, b = Path(root) / "a.wav", Path(root) / "b.wav"
            sf.write(a, np.ones(1000) * .1, 16000)
            sf.write(b, np.ones(1000) * .2, 16000)
            first = ReadingChunk("a", "u", "r", "甲", "甲", 0, 1, sequence_index=1)
            second = replace(first, chunk_id="b", sequence_index=2)
            with self.assertRaisesRegex(ValueError, "顺序"):
                assemble_pcm([second, first], [b, a], Path(root) / "wrong.wav")
            expected = {"a": hashlib.sha256(a.read_bytes()).hexdigest(), "b": hashlib.sha256(b.read_bytes()).hexdigest()}
            with self.assertRaisesRegex(ValueError, "不匹配"):
                assemble_pcm([first, second], [b, a], Path(root) / "wrong.wav", expected_artifacts=expected)


if __name__ == "__main__":
    unittest.main()
