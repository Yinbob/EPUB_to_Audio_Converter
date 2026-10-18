import io
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from audiobook_generator.audio_core.models import CoreOptions, QualityIssue, QualityReport, ResourceLimits
from audiobook_generator.audio_core.pipeline import run_chapter
from audiobook_generator.audio_core.quality import QualityEvaluator
from audiobook_generator.audio_core.store import ArtifactStore, fingerprint
from audiobook_generator.core.audio_tags import AudioTags
from audiobook_generator.role_script.models import ChapterSynthesisPlan, SynthesisUnit, VoiceProfile


class ObservedFake:
    provider_id = "openai"
    def __init__(self, clipped_first=False, frequency=200):
        self.calls = []
        self.clipped_first = clipped_first
        self.frequency = frequency

    def synthesize_observed_chunk(self, text, profile, store, run_id, *, resample=False, repair=False):
        key = fingerprint({"text": text, "voice": profile.provider_params["voice"]})
        cached = None if resample else store.cached(key)
        if cached:
            return cached
        request = store.reserve(run_id, key, len(text), repair=repair)
        self.calls.append((text, profile.provider_params.copy(), repair))
        signal = .12 * np.sin(np.arange(48000) * 2 * np.pi * self.frequency / 16000)
        if self.clipped_first and not repair:
            signal[:5000] = 1.0
        buffer = io.BytesIO()
        sf.write(buffer, signal, 16000, format="WAV")
        path = store.save_sample(key, buffer.getvalue(), "wav")
        store.settle(request, artifact=path)
        return path


def plan_for(texts=("开场。", "你好。")):
    units = tuple(SynthesisUnit(f"1:{i}", 1, "第一章", i, len(texts), "narrator", "旁白", text,
                                VoiceProfile("narrator", "旁白", {"voice": "冰糖", "speed": 1.0}),
                                pause_after_ms=200 if i < len(texts) else 0)
                  for i, text in enumerate(texts, 1))
    return ChapterSynthesisPlan(1, "第一章", units, "wav", "openai")


class PipelineCoreTest(unittest.TestCase):
    def test_whitespace_is_preserved_as_source_metadata_without_tts_request(self):
        import json
        from dataclasses import replace
        from audiobook_generator.role_script.models import SourceSpan
        class RejectBlankProvider(ObservedFake):
            def synthesize_observed_chunk(self, text, *args, **kwargs):
                if not text.strip():
                    raise AssertionError("纯空白不应提交给语音接口")
                return super().synthesize_observed_chunk(text, *args, **kwargs)

        with tempfile.TemporaryDirectory() as root:
            provider = RejectBlankProvider()
            plan = plan_for(("Hello.", " \n\t", "Yes!"))
            offset, units = 0, []
            for unit in plan.units:
                units.append(replace(unit, source_span=SourceSpan(1, offset, offset + len(unit.text))))
                offset += len(unit.text)
            plan = replace(plan, units=tuple(units))
            project = Path(root) / "project"
            result = run_chapter(plan, provider, Path(root) / "out.wav", AudioTags("章", "作者", "书", 1),
                project, options=CoreOptions(enable_asr=False, enable_speaker=False, auto_repair=False))
            self.assertEqual([call[0] for call in provider.calls], ["Hello.", "Yes!"])
            self.assertEqual(result["source_group_id"], fingerprint("Hello. \n\tYes!"))
            structural = result["nonspoken_source_units"]
            self.assertEqual(len(structural), 1)
            self.assertEqual(structural[0]["source_text"], " \n\t")
            self.assertEqual(structural[0]["source_span"], {"chapter_index": 1, "start": 6, "end": 9})
            spans = [item["chunk"]["source_span"] for item in result["chunks"]]
            self.assertEqual([(s["start"], s["end"]) for s in spans], [(0, 6), (9, 13)])
            saved = json.loads((project / "reports" / result["run_id"] / "chapter_000001/reading_plan.json").read_text())
            self.assertEqual(saved["nonspoken_source_units"], structural)

    def test_all_whitespace_fails_without_request_and_retains_source_record(self):
        import json
        with tempfile.TemporaryDirectory() as root:
            provider = ObservedFake()
            project = Path(root) / "project"
            with self.assertRaisesRegex(ValueError, "朗读计划为空"):
                run_chapter(plan_for((" \n",)), provider, Path(root) / "out.wav", AudioTags("章", "作者", "书", 1),
                            project, options=CoreOptions(enable_asr=False, enable_speaker=False))
            self.assertEqual(provider.calls, [])
            report = json.loads(next(project.glob("reports/*/chapter_000001/quality.json")).read_text())
            self.assertEqual(report["nonspoken_source_units"][0]["source_text"], " \n")

    def test_boundary_local_repairs_run_before_remote_and_keep_source_audio(self):
        class BoundaryDefectProvider(ObservedFake):
            def synthesize_observed_chunk(self, text, profile, store, run_id, *, resample=False, repair=False):
                key = fingerprint({"text": text, "voice": profile.provider_params["voice"]})
                cached = None if resample else store.cached(key)
                if cached:
                    return cached
                request = store.reserve(run_id, key, len(text), repair=repair)
                self.calls.append((text, profile.provider_params.copy(), repair))
                signal = .1 * np.sin(np.arange(32000) * .08)
                if text == "开场。":
                    if self.defect == "gap":
                        signal = np.r_[signal, np.zeros(32000)]
                    else:
                        signal = np.r_[signal, np.zeros(1000), .8]
                buffer = io.BytesIO()
                sf.write(buffer, signal, 16000, format="WAV", subtype="PCM_16")
                path = store.save_sample(key, buffer.getvalue(), "wav")
                store.settle(request, artifact=path)
                return path

        for defect, action in (("gap", "local_trim_silence"), ("click", "local_edge_fade")):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as root:
                provider = BoundaryDefectProvider()
                provider.defect = defect
                options = CoreOptions(enable_asr=False, enable_speaker=False, auto_repair=True,
                                      limits=ResourceLimits(max_requests=2, max_repair_requests=0))
                result = run_chapter(plan_for(), provider, Path(root) / "out.wav", AudioTags("章", "作者", "书", 1),
                                     Path(root) / "project", options=options)
                selected = [r for r in result["repair_attempts"] if r["selected"]]
                self.assertEqual([r["action"]["kind"] for r in selected], [action])
                self.assertEqual(selected[0]["decision_reason"], "improved_priority_without_regressions")
                self.assertIn("before_boundaries", selected[0])
                self.assertEqual(len(provider.calls), 2)
                self.assertEqual(result["boundaries"][0]["issues"], [])
                self.assertEqual(result["chunks"][0]["render_operations"][0]["kind"], action)
                self.assertNotEqual(result["chunks"][0]["raw_path"], result["chunks"][0]["rendered_path"])
                raw, _ = sf.read(result["chunks"][0]["raw_path"])
                repaired, _ = sf.read(result["chunks"][0]["rendered_path"])
                if defect == "gap":
                    np.testing.assert_array_equal(raw[:32000], repaired[:32000])
                else:
                    self.assertEqual(raw[-1], np.float64(.79998779296875))
                    self.assertEqual(repaired[-1], 0)

    def test_reading_dictionary_reaches_request_and_changed_reading_invalidates_cache(self):
        import json
        with tempfile.TemporaryDirectory() as root:
            provider = ObservedFake()
            project = Path(root) / "project"
            plan = plan_for(("API重量3.5千克。",))
            options = CoreOptions(enable_asr=False, enable_speaker=False, reading_dictionary={"API": "应用接口"})
            first = run_chapter(plan, provider, Path(root) / "one.wav", AudioTags("章", "作者", "书", 1), project,
                                options=options)
            self.assertEqual(provider.calls[0][0], "应用接口重量三点五千克。")
            self.assertEqual(first["chunks"][0]["chunk"]["source_text"], "API重量3.5千克。")
            self.assertEqual(first["reading_configuration"]["reading_dictionary"], options.reading_dictionary)
            stored = json.loads((project / "reports" / first["run_id"] / "chapter_000001" / "reading_plan.json").read_text())
            self.assertEqual(stored["reading_dictionary"], options.reading_dictionary)
            run_chapter(plan, provider, Path(root) / "two.wav", AudioTags("章", "作者", "书", 1), project,
                        options=options)
            self.assertEqual(len(provider.calls), 1)
            options.reading_dictionary = {"API": "应用程序接口"}
            second = run_chapter(plan, provider, Path(root) / "three.wav", AudioTags("章", "作者", "书", 1), project,
                                 options=options)
            self.assertEqual(len(provider.calls), 2)
            self.assertNotEqual(first["chunks"][0]["raw_path"], second["chunks"][0]["raw_path"])

    def test_local_slowdown_repeats_at_most_twice_without_resynthesis(self):
        with tempfile.TemporaryDirectory() as root:
            provider = ObservedFake()
            options = CoreOptions(enable_asr=False, enable_speaker=False, auto_repair=True,
                                  limits=ResourceLimits(max_repair_characters=0))
            text = "一二三四五六七八九十一二三四五。"
            result = run_chapter(plan_for((text,)), provider, Path(root) / "out.wav", AudioTags("章", "作者", "书", 1),
                                 Path(root) / "project", options=options)
            selected = [r for r in result["repair_attempts"] if r["selected"]]
            self.assertEqual(len(selected), 2)
            self.assertTrue(all(r["action"]["kind"] == "local_speed" for r in selected))
            self.assertEqual(len(provider.calls), 1)
            self.assertAlmostEqual(result["chunks"][0]["speed"], (1 / 1.05) ** 2)
            self.assertGreater(result["assembly"]["total_samples"] / result["assembly"]["sample_rate"], 3.2)

    def test_role_reference_is_reused_across_chapters_and_checksum_checked(self):
        from dataclasses import replace
        with tempfile.TemporaryDirectory() as root:
            options = CoreOptions()
            first_plan = plan_for(("开场。",))
            first = run_chapter(first_plan, ObservedFake(), Path(root) / "one.wav", AudioTags("章", "作者", "书", 1),
                Path(root) / "project", options=options,
                evaluator=QualityEvaluator(options, transcribe=lambda _: "开场。", speaker=lambda _: np.array([1., 0.])))
            second_plan = replace(plan_for(("你好。",)), chapter_index=2)
            second = run_chapter(second_plan, ObservedFake(frequency=300), Path(root) / "two.wav", AudioTags("章", "作者", "书", 2),
                Path(root) / "project", options=options,
                evaluator=QualityEvaluator(options, transcribe=lambda _: "你好。", speaker=lambda _: np.array([1., 0.])))
            reference = second["chunks"][0]["report"]["metrics"]["consistency_reference"]
            self.assertEqual(reference["path"], first["chunks"][0]["rendered_path"])
            self.assertEqual(second["chunks"][0]["report"]["metrics"]["speaker_distance"], 0)
            store = ArtifactStore(Path(root) / "project")
            with store.connect() as db:
                key = db.execute("SELECT anchor_key FROM role_anchors").fetchone()[0]
            Path(reference["path"]).write_bytes(b"damaged")
            self.assertIsNone(store.load_anchor(key))

    def test_boundary_repair_tries_right_chunk_and_refreshes_changed_role_anchor(self):
        class VariableProvider(ObservedFake):
            def synthesize_observed_chunk(self, text, profile, store, run_id, *, resample=False, repair=False):
                key = fingerprint({"text": text, "voice": profile.provider_params["voice"]})
                cached = None if resample else store.cached(key)
                if cached:
                    return cached
                request = store.reserve(run_id, key, len(text), repair=repair)
                self.calls.append((text, profile.provider_params.copy(), repair))
                signal = .1 * np.sin(np.arange(48000) * 2 * np.pi * (190 + len(self.calls) * 10) / 16000)
                buffer = io.BytesIO()
                sf.write(buffer, signal, 16000, format="WAV")
                path = store.save_sample(key, buffer.getvalue(), "wav")
                store.settle(request, artifact=path)
                return path

        class BoundaryOracle:
            # 可控缺陷定位器，只检验调度和依赖更新，不代表真实声学模型效果。
            def __init__(self, bad_side):
                self.initial = {}
                self.bad_side = bad_side

            def evaluate_chunk(self, chunk, path, *, anchor=None):
                self.initial.setdefault(chunk.chunk_id, path)
                return QualityReport(chunk.chunk_id, {"content": "passed", "signal": "passed", "consistency": "incomplete"},
                                     metrics={"reference": anchor[0] if anchor else None})

            def evaluate_boundary(self, left, right, left_path, right_path, **kwargs):
                target, path = (left, left_path) if self.bad_side == "left" else (right, right_path)
                issues = [QualityIssue("cutoff_suspected", "stitching", "boundary")] if path == self.initial[target.chunk_id] else []
                return QualityReport("boundary", {"stitching": "incomplete", "content": "passed"}, issues=issues)

        for side in ("left", "right"):
            with self.subTest(side=side), tempfile.TemporaryDirectory() as root:
                provider, evaluator = VariableProvider(), BoundaryOracle(side)
                result = run_chapter(plan_for(), provider, Path(root) / "out.wav", AudioTags("章", "作者", "书", 1),
                    Path(root) / "project", options=CoreOptions(auto_repair=True), evaluator=evaluator)
                self.assertEqual(result["boundaries"][0]["issues"], [])
                selected = [r for r in result["repair_attempts"] if r["selected"]]
                expected_index = 0 if side == "left" else 1
                self.assertEqual(selected[0]["chunk_id"], result["chunks"][expected_index]["chunk"]["chunk_id"])
                if side == "left":
                    self.assertEqual(result["chunks"][1]["report"]["metrics"]["reference"], result["chunks"][0]["rendered_path"])
                else:
                    self.assertFalse(result["repair_attempts"][0]["selected"])
                    self.assertTrue(result["repair_attempts"][1]["selected"])

    def test_offline_pipeline_has_audio_timeline_report_and_reusable_artifacts(self):
        with tempfile.TemporaryDirectory() as root:
            plan = plan_for()
            provider = ObservedFake()
            options = CoreOptions(enable_asr=False, enable_speaker=False)
            output = Path(root) / "out.wav"
            result = run_chapter(plan, provider, output, AudioTags("第一章", "作者", "书", 1),
                                 Path(root) / "project", options=options)
            self.assertTrue(output.is_file())
            self.assertEqual(result["quality_status"], "incomplete")
            self.assertEqual(len(result["assembly"]["spans"]), 2)
            self.assertEqual(len(result["boundaries"]), 1)
            self.assertTrue(all(Path(c["raw_path"]).is_file() for c in result["chunks"]))
            run_chapter(plan, provider, output, AudioTags("第一章", "作者", "书", 1),
                        Path(root) / "project", options=options)
            self.assertEqual(len(provider.calls), 2)

    def test_resample_repairs_confirmed_clipping_without_changing_voice(self):
        with tempfile.TemporaryDirectory() as root:
            options = CoreOptions(enable_asr=False, enable_speaker=False, auto_repair=True)
            provider = ObservedFake(clipped_first=True)
            result = run_chapter(plan_for(("开场。",)), provider, Path(root) / "out.wav",
                                 AudioTags("章", "作者", "书", 1), Path(root) / "project", options=options)
            self.assertEqual(len(provider.calls), 2)
            self.assertTrue(result["repair_attempts"][0]["selected"])
            self.assertEqual(provider.calls[0][1]["voice"], provider.calls[1][1]["voice"])
            self.assertFalse(any(i["code"] == "clipping" for i in result["chunks"][0]["report"]["issues"]))
            rerun = run_chapter(plan_for(("开场。",)), provider, Path(root) / "again.wav",
                                AudioTags("章", "作者", "书", 1), Path(root) / "project", options=options)
            self.assertEqual(len(provider.calls), 2)
            self.assertEqual(result["chunks"][0]["raw_path"], rerun["chunks"][0]["raw_path"])

    def test_render_corruption_is_rebuilt_from_verified_raw(self):
        with tempfile.TemporaryDirectory() as root:
            provider = ObservedFake()
            options = CoreOptions(enable_asr=False, enable_speaker=False)
            args = (plan_for(("开场。",)), provider, Path(root) / "out.wav",
                    AudioTags("章", "作者", "书", 1), Path(root) / "project")
            first = run_chapter(*args, options=options)
            rendered = Path(first["chunks"][0]["rendered_path"])
            expected = rendered.read_bytes()
            rendered.write_bytes(b"corrupted")
            run_chapter(*args, options=options)
            self.assertEqual(rendered.read_bytes(), expected)
            self.assertEqual(len(provider.calls), 1)

    def test_pair_preview_corruption_is_rebuilt_before_quality_reuse(self):
        with tempfile.TemporaryDirectory() as root:
            provider = ObservedFake()
            options = CoreOptions(enable_asr=False, enable_speaker=False)
            args = (plan_for(), provider, Path(root) / "out.wav", AudioTags("章", "作者", "书", 1),
                    Path(root) / "project")
            first = run_chapter(*args, options=options)
            pair = Path(first["boundaries"][0]["metrics"]["preview_path"])
            expected = pair.read_bytes()
            pair.write_bytes(b"corrupted")
            second = run_chapter(*args, options=options)
            self.assertEqual(pair.read_bytes(), expected)
            self.assertEqual(len(provider.calls), 2)
            self.assertEqual(first["boundaries"][0]["issues"], second["boundaries"][0]["issues"])

    def test_repair_limit_exports_unresolved_candidate_and_reports_stop(self):
        with tempfile.TemporaryDirectory() as root:
            options = CoreOptions(enable_asr=False, enable_speaker=False, auto_repair=True,
                                  limits=ResourceLimits(max_requests=1, max_repair_requests=0))
            result = run_chapter(plan_for(("开场。",)), ObservedFake(clipped_first=True),
                                 Path(root) / "out.wav", AudioTags("章", "作者", "书", 1),
                                 Path(root) / "project", options=options)
            self.assertEqual(result["quality_status"], "failed")
            self.assertTrue(result["limits_reached"])
            self.assertEqual(result["resource_summary"]["succeeded"]["requests"], 1)


if __name__ == "__main__":
    unittest.main()
