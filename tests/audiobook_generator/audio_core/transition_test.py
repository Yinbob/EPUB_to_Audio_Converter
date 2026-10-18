"""起读方案按接缝启用、检查退化及缓存恢复的工程回归。"""
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from audiobook_generator.audio_core.models import CoreOptions, QualityIssue
from audiobook_generator.audio_core.pipeline import run_chapter
from audiobook_generator.audio_core.quality import QualityEvaluator
from audiobook_generator.audio_core.reading import build_reading_plan
from audiobook_generator.audio_core.transition import render_onset_transition
from audiobook_generator.audio_core.store import fingerprint
from audiobook_generator.core.audio_tags import AudioTags
from tests.audiobook_generator.audio_core.pipeline_test import ObservedFake, plan_for


class TransitionTest(unittest.TestCase):
    def test_stereo_preserves_source_timing_and_pcm_outside_100ms_window(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            signal = (5000 * np.sin(np.arange(8000) * .1)).astype(np.int16)
            signal[:640] = 0
            pcm = np.c_[signal, -signal]
            source, output = root / "source.wav", root / "out.wav"
            sf.write(source, pcm, 16000, subtype="PCM_16")
            original = source.read_bytes()
            operation = render_onset_transition(source, output)
            actual, rate = sf.read(output, dtype="int16", always_2d=True)
            self.assertEqual(rate, 16000)
            self.assertEqual(operation["start_sample"], 640)
            expected = pcm.copy()
            expected[640:2240] = np.rint(pcm[640:2240] * np.linspace(.5, 1., 1600)[:, None]).astype(np.int16)
            np.testing.assert_array_equal(expected, actual)
            self.assertEqual(source.read_bytes(), original)

    def test_short_or_all_quiet_audio_and_source_overwrite_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, output = root / "source.wav", root / "out.wav"
            for signal in (np.ones(800) * .1, np.zeros(8000)):
                sf.write(source, signal, 16000)
                with self.assertRaises(ValueError):
                    render_onset_transition(source, output)
                self.assertFalse(output.exists())
            with self.assertRaises(ValueError):
                render_onset_transition(source, source)

    def test_explicit_join_policy_survives_restarts_without_accumulation_and_can_be_disabled(self):
        from audiobook_generator.audio_core.annotations import export_review_pack
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan, provider = plan_for(), ObservedFake()
            chunks = build_reading_plan(plan.units)
            boundary = f"{chunks[0].chunk_id}|{chunks[1].chunk_id}"
            options = CoreOptions(enable_asr=False, enable_speaker=False, transition_boundaries=[boundary],
                                  transition_source_group=fingerprint("".join(u.text for u in plan.units)))
            def run(name, opts):
                return run_chapter(plan, provider, root / f"{name}.wav", AudioTags("章", "作者", "书", 1),
                                   root / "project", options=opts)
            first = run("one", options)
            self.assertTrue(first["output_conditioning"]["operations"][0]["selected"])
            first_output = (root / "one.wav").read_bytes()
            source_path = Path(first["chunks"][1]["selected_rendered_path"])
            source_bytes = source_path.read_bytes()
            source, _ = sf.read(source_path, dtype="int16")
            final, _ = sf.read(first["chunks"][1]["rendered_path"], dtype="int16")
            self.assertFalse(np.array_equal(source, final))
            np.testing.assert_array_equal(source[1600:], final[1600:])
            second = run("two", options)
            self.assertEqual((root / "two.wav").read_bytes(), first_output)
            self.assertEqual(len(provider.calls), 2)
            self.assertEqual(source_path.read_bytes(), source_bytes)
            self.assertEqual(second["chunks"][0]["rendered_path"], first["chunks"][0]["rendered_path"])
            plain = run("plain", CoreOptions(enable_asr=False, enable_speaker=False))
            self.assertEqual(plain["output_conditioning"]["operations"], [])
            np.testing.assert_array_equal(sf.read(plain["chunks"][1]["rendered_path"], dtype="int16")[0], source)
            self.assertEqual(len(provider.calls), 2)
            # 起读派生块必须与章节时间表一致，可继续用于人工标注导出。
            report_path = root / "project/reports" / first["run_id"] / "chapter_000001/quality.json"
            export_review_pack([report_path], root / "review")
            # 派生文件损坏后从未调整的选中来源重建，不能复用损坏文件或重复衰减。
            Path(second["chunks"][1]["rendered_path"]).write_bytes(b"corrupt")
            run("rebuilt", options)
            self.assertEqual((root / "rebuilt.wav").read_bytes(), first_output)
            self.assertEqual(len(provider.calls), 2)

    def test_new_content_error_rejects_policy_and_keeps_original(self):
        class RegressionEvaluator(QualityEvaluator):
            def evaluate_chunk(self, chunk, path, *, anchor=None):
                result = super().evaluate_chunk(chunk, path, anchor=anchor)
                if "transitions" in Path(path).parts:
                    result.issues.append(QualityIssue("new_content_error", "content", chunk.chunk_id,
                                                     "error", "confirmed"))
                    result.dimensions["content"] = "failed"
                return result
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan = plan_for()
            chunks = build_reading_plan(plan.units)
            options = CoreOptions(enable_asr=False, enable_speaker=False,
                                  transition_boundaries=[f"{chunks[0].chunk_id}|{chunks[1].chunk_id}"],
                                  transition_source_group=fingerprint("".join(u.text for u in plan.units)))
            result = run_chapter(plan, ObservedFake(), root / "out.wav", AudioTags("章", "作者", "书", 1),
                                 root / "project", options=options, evaluator=RegressionEvaluator(options))
            record = result["output_conditioning"]["operations"][0]
            self.assertFalse(record["selected"])
            self.assertEqual(record["decision_reason"], "regressed_check_keep_original")
            self.assertEqual(result["chunks"][1]["rendered_path"], result["chunks"][1]["selected_rendered_path"])

    def test_boundary_configuration_is_explicit_and_validated(self):
        for value in (None, True, "a|b", ["a"], ["a|"], ["a|b", "a|b"], [12], ["a|b|c"]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                CoreOptions(transition_boundaries=value)

    def test_source_binding_is_required_and_its_format_is_validated(self):
        with self.assertRaisesRegex(ValueError, "同时指定"):
            CoreOptions(transition_boundaries=["a|b"])
        for value in (True, 12, "short", "g" * 64, "A" * 64, [], {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                CoreOptions(transition_source_group=value)

    def test_same_boundary_ids_with_different_text_are_rejected_before_synthesis(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            approved = plan_for()
            other = plan_for(("另一本书的开场。", "这是完全不同的内容。"))
            chunks = build_reading_plan(approved.units)
            self.assertEqual([c.chunk_id for c in chunks], [c.chunk_id for c in build_reading_plan(other.units)])
            options = CoreOptions(enable_asr=False, enable_speaker=False,
                transition_boundaries=[f"{chunks[0].chunk_id}|{chunks[1].chunk_id}"],
                transition_source_group=fingerprint("".join(u.text for u in approved.units)))
            provider = ObservedFake()
            with self.assertRaisesRegex(ValueError, "原文指纹不符"):
                run_chapter(other, provider, root / "out.wav", AudioTags("章", "作者", "书", 1),
                            root / "project", options=options)
            self.assertEqual(provider.calls, [])
            self.assertFalse((root / "out.wav").exists())

    def test_unrelated_chapter_without_configured_join_keeps_original_processing(self):
        from dataclasses import replace
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            approved = plan_for()
            other = plan_for(("另一个章节。", "没有配置接缝。"))
            other = replace(other, chapter_index=2, units=tuple(
                replace(u, chapter_index=2, unit_id=u.unit_id.replace("1:", "2:", 1)) for u in other.units))
            chunks = build_reading_plan(approved.units)
            options = CoreOptions(enable_asr=False, enable_speaker=False,
                transition_boundaries=[f"{chunks[0].chunk_id}|{chunks[1].chunk_id}"],
                transition_source_group=fingerprint("".join(u.text for u in approved.units)))
            result = run_chapter(other, ObservedFake(), root / "out.wav", AudioTags("章", "作者", "书", 2),
                                 root / "project", options=options)
            self.assertEqual(result["output_conditioning"]["operations"], [])
            self.assertEqual(result["output_conditioning"]["matching_boundaries"], [])
            self.assertFalse(result["output_conditioning"]["source_group_matches"])
