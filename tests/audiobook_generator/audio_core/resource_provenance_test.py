"""只使用构造 Provider，验证缓存、失败和跨报告统计的资源口径。"""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from audiobook_generator.audio_core.__main__ import main
from audiobook_generator.audio_core.models import CoreOptions, ResourceLimits
from audiobook_generator.audio_core.pipeline import run_chapter
from audiobook_generator.audio_core.store import ArtifactStore
from audiobook_generator.core.audio_tags import AudioTags
from audiobook_generator.ui.audio_quality import resource_summary_text
from tests.audiobook_generator.audio_core.content_repair_test import ContentFake, ContentOracle, LONG_TEXT
from tests.audiobook_generator.audio_core.pipeline_test import ObservedFake, plan_for


class ResourceProvenanceTest(unittest.TestCase):
    def run_pipeline(self, root, provider, *, options=None, evaluator=None, text="开场。"):
        return run_chapter(plan_for((text,)), provider, Path(root) / "out.wav", AudioTags("章", "作者", "书", 1),
            Path(root) / "project", options=options or CoreOptions(enable_asr=False, enable_speaker=False),
            evaluator=evaluator)

    def test_cache_recovery_has_zero_current_requests_but_keeps_origin_event(self):
        with tempfile.TemporaryDirectory() as root:
            provider = ObservedFake()
            first = self.run_pipeline(root, provider)
            second = self.run_pipeline(root, provider,
                options=CoreOptions(enable_asr=False, enable_speaker=False,
                                    limits=ResourceLimits(max_requests=0, max_repair_requests=0)))
            self.assertEqual(len(provider.calls), 1)
            self.assertEqual(second["resource_summary"], {})
            provenance = second["resource_provenance"]
            self.assertEqual(provenance["actual_run"]["request_events"], [])
            generation = provenance["recorded_generation"]
            self.assertEqual(generation["summary"]["succeeded"]["requests"], 1)
            self.assertEqual(generation["request_events"][0]["run_id"], first["run_id"])
            self.assertFalse(generation["history_incomplete"])
            self.assertIn("本次运行累计 0 次", resource_summary_text(second))
            self.assertIn("历史已记录 1 次", resource_summary_text(second))
            reports = sorted((Path(root) / "project" / "reports").glob("*/chapter_*/quality.json"))
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(["summarize", *map(str, reports), str(reports[0])]), 0)
            summary = json.loads(output.getvalue())
            self.assertEqual(summary["recorded_generation"]["request_count"], 1)
            self.assertEqual(len(summary["resources_by_run"]), 2)

    def test_partial_child_failure_and_rejected_candidate_history_survive_zero_request_restart(self):
        with tempfile.TemporaryDirectory() as root:
            provider = ContentFake(fail_second=True)
            first = self.run_pipeline(root, provider, text=LONG_TEXT, evaluator=ContentOracle(),
                                      options=CoreOptions(auto_repair=True))
            old_lineage = first["resource_provenance"]["recorded_generation"]
            self.assertEqual(old_lineage["summary"]["succeeded"]["requests"], 2)
            self.assertEqual(old_lineage["summary"]["failed"]["requests"], 1)
            self.assertEqual(len(old_lineage["request_events"]), 3)
            second = self.run_pipeline(root, provider, text=LONG_TEXT, evaluator=ContentOracle(),
                options=CoreOptions(limits=ResourceLimits(max_requests=0, max_repair_requests=0)))
            self.assertEqual(len(provider.calls), 3)
            self.assertEqual(second["resource_summary"], {})
            self.assertEqual(second["resource_provenance"]["recorded_generation"]["summary"], old_lineage["summary"])
            failed = next(e for e in old_lineage["request_events"] if e["status"] == "failed")
            self.assertEqual(failed["error_type"], "TimeoutError")
            self.assertIsNone(failed["artifact"])

    def test_untracked_raw_and_missing_old_events_remain_unknown_not_free(self):
        with tempfile.TemporaryDirectory() as root:
            store = ArtifactStore(root)
            run = store.start_run(ResourceLimits())
            raw = store.save_sample("historical", b"registered but no original request", "wav")
            provenance = store.resource_provenance(run, [raw, raw],
                [{"chunk_id": "old", "request_ids": ["missing-event"], "history_incomplete": False}])
            self.assertEqual(len(provenance["selected_sources"]), 1)
            self.assertEqual(provenance["selected_sources"][0]["origin_status"], "unknown")
            lineage = provenance["recorded_generation"]
            self.assertTrue(lineage["history_incomplete"])
            self.assertEqual(lineage["missing_request_ids"], ["missing-event"])
            self.assertEqual(lineage["unknown_source_paths"], [raw])
            self.assertIn("未知部分未计作零", resource_summary_text({"resource_summary": {}, "resource_provenance": provenance}))
            Path(raw).write_bytes(b"damaged")
            with self.assertRaisesRegex(ValueError, "校验失败"):
                store.sample_provenance(raw)

    def test_legacy_selected_render_without_lineage_is_explicitly_incomplete(self):
        with tempfile.TemporaryDirectory() as root:
            provider = ObservedFake()
            self.run_pipeline(root, provider)
            store = ArtifactStore(Path(root) / "project")
            with store.connect() as db:
                key, raw = db.execute("SELECT selection_key,payload FROM selected_renders").fetchone()
                payload = json.loads(raw)
                payload.pop("generation_request_ids")
                payload.pop("generation_history_incomplete")
                db.execute("UPDATE selected_renders SET payload=? WHERE selection_key=?", (json.dumps(payload), key))
            result = self.run_pipeline(root, provider)
            lineage = result["resource_provenance"]["recorded_generation"]
            self.assertTrue(lineage["history_incomplete"])
            self.assertEqual(lineage["summary"]["succeeded"]["requests"], 1)
            self.assertEqual(result["resource_summary"], {})

    def test_running_requests_count_in_observed_history_and_event_lookup_is_explicit(self):
        with tempfile.TemporaryDirectory() as root:
            store = ArtifactStore(root)
            run = store.start_run(ResourceLimits())
            request = store.reserve(run, "unknown transport outcome", 10, repair=True)
            result = store.resource_provenance(run, [],
                [{"chunk_id": "chunk", "request_ids": [request], "history_incomplete": False}])
            self.assertEqual(result["recorded_generation"]["summary"]["running"]["requests"], 1)
            self.assertEqual(result["actual_run"]["summary"]["running"]["repair_requests"], 1)
            self.assertIsNone(result["actual_run"]["request_events"][0]["finished"])
            for kwargs in ({}, {"run_id": run, "request_ids": [request]}):
                with self.assertRaises(ValueError):
                    store.request_events(**kwargs)
