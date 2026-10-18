"""可控音频与判定器只验证调度、限额及恢复，不计入真实修复效果。"""
import io
import contextlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import soundfile as sf

from audiobook_generator.audio_core.models import CoreOptions, QualityIssue, QualityReport, ResourceLimits
from audiobook_generator.audio_core.pipeline import run_chapter
from audiobook_generator.audio_core.reading import build_reading_plan
from audiobook_generator.audio_core.repair import CONTENT_PROMPT, content_repair_profile, split_repair_chunk
from audiobook_generator.audio_core.store import ArtifactStore, fingerprint
from audiobook_generator.core.audio_tags import AudioTags
from audiobook_generator.ui.audio_quality import load_quality_report
from tests.audiobook_generator.audio_core.pipeline_test import plan_for


LONG_TEXT = "第一段需要完整朗读，保持原文所有字词，不增加解释。第二段也应完整朗读，尤其不能省略结尾，声音保持自然。"


class ContentFake:
    provider_id = "openai"

    def __init__(self, *, fail_second=False):
        self.config = SimpleNamespace(instructions="原有角色指令", model_name="fixture", language="zh-CN",
                                      stream=False, output_format="wav")
        self.calls = []
        self.fail_second = fail_second

    def synthesize_observed_chunk(self, text, profile, store, run_id, *, resample=False, repair=False):
        key = fingerprint({"text": text, "profile": profile.provider_params})
        cached = None if resample else store.cached(key)
        if cached:
            return cached
        request = store.reserve(run_id, key, len(text), repair=repair)
        self.calls.append((text, profile, repair))
        if repair and self.fail_second and sum(call[2] for call in self.calls) == 2:
            error = TimeoutError("constructed transport failure")
            store.settle(request, error=error)
            raise error
        signal = .1 * np.sin(np.arange(32000) * 2 * np.pi * (300 if repair else 200) / 16000)
        data = io.BytesIO()
        sf.write(data, signal, 16000, format="WAV", subtype="PCM_16")
        path = store.save_sample(key, data.getvalue(), "wav")
        store.settle(request, artifact=path)
        return path


class ContentOracle:
    def __init__(self, bad_join=False, missing_child=False):
        self.bad_join = bad_join
        self.missing_child = missing_child

    def evaluate_chunk(self, chunk, path, *, anchor=None):
        signal, rate = sf.read(path)
        frequency = np.argmax(np.abs(np.fft.rfft(signal[:16000]))) * rate / min(16000, len(signal))
        bad = frequency < 250
        issues = [QualityIssue("asr_mismatch", "content", chunk.chunk_id)] if bad else []
        missing = self.missing_child and ":repair_part:" in chunk.chunk_id
        return QualityReport(chunk.chunk_id, {"signal": "passed", "content": "incomplete" if bad or missing else "passed",
                             "consistency": "incomplete"},
                             metrics={"content_alignment": {"error_rate": .1 if bad else 0},
                                      "reference": anchor[0] if anchor else None}, issues=issues)

    def evaluate_boundary(self, left, right, *paths, **kwargs):
        bad = self.bad_join and ":repair_part:" in left.chunk_id
        return QualityReport(left.chunk_id + "|" + right.chunk_id, {"content": "passed", "stitching": "incomplete"},
                             issues=[QualityIssue("cutoff_suspected", "stitching", left.chunk_id)] if bad else [])


class ContentRepairTest(unittest.TestCase):
    def generate(self, root, provider, text=LONG_TEXT, **kwargs):
        return run_chapter(plan_for((text,)), provider, Path(root) / "out.wav", AudioTags("章", "作者", "书", 1),
                           Path(root) / "project", options=kwargs.pop("options", CoreOptions(auto_repair=True)),
                           evaluator=kwargs.pop("evaluator", ContentOracle()), **kwargs)

    def test_split_preserves_source_spans_normalized_tokens_voice_and_tone(self):
        plan = plan_for(("API重量3.50千克，" + LONG_TEXT,))
        dictionary = {"API": "应用程序接口"}
        chunk = build_reading_plan(plan.units, dictionary=dictionary)[0]
        chunk = replace(chunk, source_span={"start": 100, "end": 100 + len(chunk.source_text)}, tone="平静")
        children = split_repair_chunk(chunk, dictionary=dictionary)
        self.assertEqual(len(children), 2)
        self.assertEqual("".join(c.tts_text for c in children), chunk.tts_text)
        self.assertEqual("".join(c.source_text for c in children), chunk.source_text)
        self.assertEqual(children[0].source_end, children[1].source_start)
        self.assertEqual(children[0].source_span["end"], children[1].source_span["start"])
        self.assertEqual(children[-1].source_span["end"], chunk.source_span["end"])
        self.assertTrue(all(c.profile == chunk.profile and c.tone == chunk.tone for c in children))
        self.assertIn("三点五零千克", children[0].tts_text)
        profile = content_repair_profile(chunk, "全局指令")
        self.assertEqual(profile.provider_params["instructions"], "全局指令\n" + CONTENT_PROMPT)
        self.assertEqual(profile.provider_params["voice"], chunk.profile["voice"])
        self.assertEqual(profile.tone, "平静")
        self.assertFalse(split_repair_chunk(replace(chunk, source_text="长" * 60, tts_text="长" * 60)))
        explicit = replace(chunk, profile={**chunk.profile, "instructions": "本角色"})
        self.assertTrue(content_repair_profile(explicit, "全局").provider_params["instructions"].startswith("本角色\n"))

    def test_short_content_error_uses_fixed_prompt_and_establishes_repaired_anchor(self):
        with tempfile.TemporaryDirectory() as root:
            provider = ContentFake()
            result = self.generate(root, provider, "开场。")
            self.assertEqual(len(provider.calls), 2)
            first, second = provider.calls
            self.assertEqual(first[0], second[0])
            self.assertEqual(first[1].provider_params["voice"], second[1].provider_params["voice"])
            self.assertIn(CONTENT_PROMPT, second[1].provider_params["instructions"])
            self.assertTrue(result["repair_attempts"][0]["selected"])
            self.assertEqual(result["chunks"][0]["synthesis_parts"][0]["strategy"], "content_prompt")
            store = ArtifactStore(Path(root) / "project")
            with store.connect() as db:
                anchor = db.execute("SELECT path FROM role_anchors").fetchone()
            self.assertEqual(anchor[0], result["chunks"][0]["rendered_path"])

    def test_two_part_repair_checks_internal_join_and_restores_without_requests(self):
        with tempfile.TemporaryDirectory() as root:
            provider = ContentFake()
            first = self.generate(root, provider)
            self.assertEqual(len(provider.calls), 3)
            chunk = first["chunks"][0]
            self.assertEqual(len(chunk["synthesis_parts"]), 2)
            self.assertEqual("".join(part["chunk"]["tts_text"] for part in chunk["synthesis_parts"]), LONG_TEXT)
            self.assertEqual(len(chunk["composition"]["internal_reports"]), 3)
            self.assertTrue(first["repair_attempts"][0]["selected"])
            report_path = next((Path(root) / "project" / "reports" / first["run_id"]).glob("chapter_*/quality.json"))
            _, _, previews = load_quality_report(report_path)
            self.assertTrue(all(r["scope_id"] in previews for r in chunk["composition"]["internal_reports"]))
            expected, target = Path(chunk["rendered_path"]).read_bytes(), Path(chunk["rendered_path"])
            target.write_bytes(b"corrupt derived combination")
            Path(chunk["synthesis_parts"][1]["rendered_path"]).write_bytes(b"corrupt child PCM")
            second = self.generate(root, provider, options=CoreOptions(limits=ResourceLimits(max_requests=0, max_repair_requests=0)))
            self.assertEqual(len(provider.calls), 3)
            self.assertEqual(second["resource_summary"], {})
            self.assertEqual(Path(second["chunks"][0]["rendered_path"]).read_bytes(), expected)
            self.assertEqual(second["chunks"][0]["report"]["metrics"]["content_alignment"]["error_rate"], 0)

    def test_offline_reevaluation_rechecks_internal_join_instead_of_reusing_previous_verdict(self):
        from audiobook_generator.audio_core.__main__ import main
        with tempfile.TemporaryDirectory() as root:
            result = self.generate(root, ContentFake())
            report = next((Path(root) / "project" / "reports" / result["run_id"]).glob("chapter_*/quality.json"))
            output = Path(root) / "reevaluated.json"
            with patch("audiobook_generator.audio_core.quality.QualityEvaluator", return_value=ContentOracle(bad_join=True)), \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = main(["evaluate", "--manifest", str(report), "--output", str(output), "--no-speaker"])
            self.assertEqual(code, 0)
            refreshed = json.loads(output.read_text())
            self.assertTrue(any(issue["code"] == "cutoff_suspected"
                                for issue in refreshed["chunks"][0]["report"]["issues"]))
            self.assertEqual(refreshed["reevaluation"]["requests_sent"], 0)

    def test_one_remaining_request_uses_one_prompt_instead_of_two_parts(self):
        with tempfile.TemporaryDirectory() as root:
            provider = ContentFake()
            result = self.generate(root, provider, options=CoreOptions(auto_repair=True,
                limits=ResourceLimits(max_requests=2, max_repair_requests=1)))
            self.assertEqual(len(provider.calls), 2)
            self.assertIsNone(result["chunks"][0]["composition"])
            self.assertEqual(provider.calls[1][0], LONG_TEXT)
            self.assertEqual(result["resource_summary"]["succeeded"]["repair_requests"], 1)

    def test_bad_internal_join_or_unknown_child_content_cannot_replace_original(self):
        for evaluator in (ContentOracle(bad_join=True), ContentOracle(missing_child=True)):
            with self.subTest(evaluator=evaluator), tempfile.TemporaryDirectory() as root:
                provider = ContentFake()
                result = self.generate(root, provider, evaluator=evaluator)
                self.assertEqual(len(provider.calls), 3)
                self.assertFalse(any(r["selected"] for r in result["repair_attempts"]))
                self.assertEqual(result["chunks"][0]["synthesis_parts"][0]["strategy"], "initial")
                with ArtifactStore(Path(root) / "project").connect() as db:
                    self.assertIsNone(db.execute("SELECT path FROM role_anchors").fetchone())

    def test_second_child_failure_is_counted_and_original_remains_selected(self):
        with tempfile.TemporaryDirectory() as root:
            provider = ContentFake(fail_second=True)
            result = self.generate(root, provider)
            self.assertEqual(len(provider.calls), 3)
            self.assertEqual(result["resource_summary"]["failed"]["repair_requests"], 1)
            self.assertEqual(result["resource_summary"]["succeeded"]["requests"], 2)
            self.assertEqual(result["chunks"][0]["synthesis_parts"][0]["strategy"], "initial")
            self.assertEqual(result["repair_attempts"][0]["error_type"], "TimeoutError")
            self.assertTrue(list((Path(root) / "project" / "reports").glob("*/chapter_*/repair_plan_*.json")))

    def test_store_selection_does_not_accept_unregistered_or_damaged_raw(self):
        with tempfile.TemporaryDirectory() as root:
            store = ArtifactStore(root)
            raw = store.save_sample("sample", b"raw sample", "wav")
            rendered = Path(root) / "rendered.wav"
            rendered.write_bytes(b"derived render")
            payload = {"parts": [{"raw_path": raw}], "rendered_path": str(rendered)}
            store.save_render_selection("key", payload)
            rendered.write_bytes(b"broken render")
            self.assertFalse(ArtifactStore(root).load_render_selection("key")["render_valid"])
            with self.assertRaises(ValueError):
                store.save_render_selection("invalid", {**payload, "parts": [{"raw_path": str(rendered)}]})
            Path(raw).write_bytes(b"broken raw")
            self.assertIsNone(store.load_render_selection("key"))
