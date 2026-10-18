"""接缝试听只验证受控变换和证据状态；不将构造转写作为效果结果。"""
import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from audiobook_generator.audio_core.__main__ import main
from audiobook_generator.audio_core.transition_preview import prepare_transition_preview


class FakeEvaluator:
    def __init__(self, transform=None):
        self.transform = transform

    def backend_identity(self, kind):
        return {"kind": "constructed", "fingerprint": "fixture-only"}

    def transcript(self, path):
        return self.transform(path) if self.transform else "甲乙"


class TransitionPreviewTest(unittest.TestCase):
    def source(self, root):
        signal = .1 * np.sin(np.arange(32000) * .1)
        left, right = signal.copy(), signal.copy()
        left[-1600:], right[:1600] = 0, 0
        audio = root / "source.wav"
        sf.write(audio, np.r_[left, right], 16000, subtype="PCM_16")
        report = {"schema_version": "audio-core-v1", "provider": "openai", "generation_status": "generated",
            "source_group_id": "constructed", "output_file": str(audio),
            "final_verification": {"dimensions": {"encoding": "passed"}, "metrics": {"encoded_sha256": hashlib.sha256(audio.read_bytes()).hexdigest()}},
            "chunks": [{"chunk": {"chunk_id": name, "tts_text": text}} for name, text in (("a", "甲"), ("b", "乙"))],
            "assembly": {"sample_rate": 16000, "total_samples": 64000,
                "spans": [{"chunk_id": "a", "start_sample": 0, "end_sample": 32000}, {"chunk_id": "b", "start_sample": 32000, "end_sample": 64000}],
                "boundaries": [{"boundary_id": "a|b", "left_chunk_id": "a", "right_chunk_id": "b", "start_sample": 32000, "end_sample": 32000}]}}
        path = root / "report.json"
        path.write_text(json.dumps(report))
        return path

    def test_pause_inserts_only_exact_zeros_and_preserves_all_source_samples(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.source(root)
            old = (root / "source.wav").read_bytes()
            prepare_transition_preview(source, "a|b", root / "pack")
            original, _ = sf.read(root / "pack/audio/original.wav", dtype="int16")
            candidate, _ = sf.read(root / "pack/audio/pause_plus_150ms.wav", dtype="int16")
            np.testing.assert_array_equal(original[:32000], candidate[:32000])
            np.testing.assert_array_equal(original[32000:], candidate[34400:])
            self.assertFalse(np.any(candidate[32000:34400]))
            self.assertEqual(len(candidate), len(original) + 2400)
            self.assertEqual((root / "source.wav").read_bytes(), old)

    def test_gain_is_bounded_nonzero_and_only_changes_declared_samples(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prepare_transition_preview(self.source(root), "a|b", root / "pack")
            report = json.loads((root / "pack/manifest.json").read_text())
            original, _ = sf.read(root / "pack/audio/original.wav", dtype="int16")
            self.assertAlmostEqual(report["low_energy_estimate_seconds"]["right_head"], .1)
            for entry in report["candidates"][2:]:
                operation = entry["operation"]
                candidate, _ = sf.read(root / "pack" / entry["full_audio"], dtype="int16")
                start, end = operation["start_sample"], operation["end_sample"]
                expected = original.copy()
                expected[start:end] = np.rint(original[start:end] * np.linspace(.8, 1., end - start)).astype(np.int16)
                np.testing.assert_array_equal(expected, candidate)
                self.assertEqual(len(candidate), len(original))
                self.assertGreater(operation["initial_gain"], 0)
            self.assertFalse(report["automatically_applied"])
            self.assertIsNone(report["human_preference"])

    def test_content_checks_preserve_uncertainty_and_detect_differences(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def transcript(path):
                if path.stem == "onset_gain_200ms":
                    raise RuntimeError("fixture failure")
                return "甲" if path.stem == "onset_gain_400ms" else "甲乙"

            result = prepare_transition_preview(self.source(root), "a|b", root / "pack", evaluator=FakeEvaluator(transcript))
            self.assertEqual(result["content_checks"], {"original": "no_asr_difference", "pause_plus_150ms": "no_asr_difference", "onset_gain_200ms": "incomplete", "onset_gain_400ms": "asr_difference"})
            self.assertFalse(result["automatically_applied"])

    def test_requested_gain40_400ms_cli_preserves_timing_and_documents_actual_gain(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.source(root)
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = main(["preview-transition", "--report", str(source), "--boundary", "a|b",
                             "--output", str(root / "pack"), "--onset-gain", "0.4", "--ramp-ms", "400"])
            self.assertEqual(code, 0)
            manifest = json.loads((root / "pack/manifest.json").read_text())
            self.assertEqual(len(manifest["candidates"]), 3)
            entry = manifest["candidates"][-1]
            operation = entry["operation"]
            start, end = operation["start_sample"], operation["end_sample"]
            self.assertEqual(end - start, 6400)
            self.assertEqual(operation["initial_gain"], .4)
            self.assertEqual(operation["final_gain"], 1.)
            original, _ = sf.read(root / "pack/audio/original.wav", dtype="int16")
            candidate, _ = sf.read(root / "pack" / entry["full_audio"], dtype="int16")
            expected = original.copy()
            expected[start:end] = np.rint(original[start:end] * np.linspace(.4, 1., 6400)).astype(np.int16)
            np.testing.assert_array_equal(expected, candidate)
            self.assertEqual(len(candidate), len(original))
            readme = (root / "pack/README.md").read_text()
            self.assertIn("40% 恢复到 100%", readme)
            self.assertNotIn("80%", readme)
            self.assertFalse(manifest["automatically_applied"])

    def test_source_changes_during_evaluation_abort_and_remove_partial_outputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.source(root)

            def change_source(path):
                (root / "source.wav").write_bytes(b"changed")
                return "甲乙"

            with self.assertRaisesRegex(ValueError, "来源文件发生改变"):
                prepare_transition_preview(source, "a|b", root / "pack", evaluator=FakeEvaluator(change_source))
            self.assertFalse((root / "pack").exists())

    def test_invalid_boundary_parameters_and_overwrite_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.source(root)
            for kwargs in ({"onset_gain": 0}, {"onset_gain": .39}, {"extra_pause_ms": True}, {"ramp_ms": (200, 200)}, {"ramp_ms": (True,)}):
                with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                    prepare_transition_preview(source, "a|b", root / "pack", **kwargs)
            with self.assertRaisesRegex(ValueError, "唯一存在"):
                prepare_transition_preview(source, "unknown", root / "pack")
            prepare_transition_preview(source, "a|b", root / "pack")
            with self.assertRaisesRegex(ValueError, "拒绝覆盖"):
                prepare_transition_preview(source, "a|b", root / "pack")

    def test_cli_without_asr_marks_content_unassessed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()):
                code = main(["preview-transition", "--report", str(self.source(root)), "--boundary", "a|b", "--output", str(root / "pack")])
            self.assertEqual(code, 0)
            result = json.loads(output.getvalue())
            self.assertTrue(all(status == "not_assessed" for status in result["content_checks"].values()))
            self.assertEqual(result["additional_tts_requests"], 0)
