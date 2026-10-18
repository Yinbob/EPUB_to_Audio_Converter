"""修复字符限额的离线检验；构造音频不作为研究效果证据。"""
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from audiobook_generator.audio_core.models import CoreOptions, ResourceLimits
from audiobook_generator.audio_core.pipeline import run_chapter
from audiobook_generator.audio_core.store import ArtifactStore, ResourceExhausted
from audiobook_generator.config.general_config import GeneralConfig
from audiobook_generator.core.audio_tags import AudioTags
from audiobook_generator.ui.audio_quality import apply_quality_settings
from tests.audiobook_generator.audio_core.content_repair_test import ContentFake, ContentOracle, LONG_TEXT
from tests.audiobook_generator.audio_core.pipeline_test import plan_for


class CharacterBudgetTest(unittest.TestCase):
    def generate(self, root, provider, *, options):
        return run_chapter(plan_for((LONG_TEXT,)), provider, Path(root) / "out.wav", AudioTags("章", "作者", "书", 1),
                           Path(root) / "project", options=options, evaluator=ContentOracle())

    def test_failed_running_and_succeeded_repairs_all_consume_characters(self):
        with tempfile.TemporaryDirectory() as root:
            store = ArtifactStore(root)
            run = store.start_run(ResourceLimits(max_repair_characters=7))
            store.reserve(run, "initial", 1000)
            failed = store.reserve(run, "failed", 3, repair=True)
            store.settle(failed, error=TimeoutError())
            store.reserve(run, "running", 2, repair=True)
            succeeded = store.reserve(run, "succeeded", 2, repair=True)
            store.settle(succeeded)
            self.assertEqual(store.remaining_repair_characters(run), 0)
            with self.assertRaises(ResourceExhausted):
                store.reserve(run, "over", 1, repair=True)
            self.assertEqual(len(store.request_events(run_id=run)), 4)

    def test_concurrent_reservations_cannot_exceed_cap(self):
        with tempfile.TemporaryDirectory() as root:
            store = ArtifactStore(root)
            run = store.start_run(ResourceLimits(max_repair_characters=7))

            def reserve(index):
                try:
                    store.reserve(run, str(index), 2, repair=True)
                    return True
                except ResourceExhausted:
                    return False

            with ThreadPoolExecutor(max_workers=8) as pool:
                self.assertEqual(sum(pool.map(reserve, range(8))), 3)
            self.assertEqual(store.remaining_repair_characters(run), 1)

    def test_old_run_limits_remain_uncapped_and_new_limits_survive_reopen(self):
        with tempfile.TemporaryDirectory() as root:
            store = ArtifactStore(root)
            old = store.start_run(ResourceLimits())
            with store.connect() as db:
                limits = json.loads(db.execute("SELECT limits FROM runs WHERE id=?", (old,)).fetchone()[0])
                del limits["max_repair_characters"]
                db.execute("UPDATE runs SET limits=? WHERE id=?", (json.dumps(limits), old))
            new = store.start_run(ResourceLimits(max_repair_characters=0))
            restored = ArtifactStore(root)
            self.assertIsNone(restored.remaining_repair_characters(old))
            restored.reserve(old, "old-repair", 500, repair=True)
            with self.assertRaises(ResourceExhausted):
                restored.reserve(new, "new-repair", 1, repair=True)

    def test_characters_and_optional_limit_require_nonnegative_integers(self):
        for value in (-1, True, 1.5, "3"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                ResourceLimits(max_repair_characters=value)
        with tempfile.TemporaryDirectory() as root:
            store = ArtifactStore(root)
            run = store.start_run(ResourceLimits())
            for value in (-1, True, 1.5, "3", None):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    store.reserve(run, "invalid", value, repair=True)
            self.assertEqual(store.request_events(run_id=run), [])

    def test_compound_repair_with_insufficient_total_cap_sends_no_first_child(self):
        with tempfile.TemporaryDirectory() as root:
            provider = ContentFake()
            result = self.generate(root, provider, options=CoreOptions(auto_repair=True,
                limits=ResourceLimits(max_repair_characters=len(LONG_TEXT) - 1)))
            self.assertEqual(len(provider.calls), 1)
            self.assertIsNone(result["chunks"][0]["composition"])
            self.assertFalse(any(item["selected"] for item in result["repair_attempts"]))
            self.assertTrue(result["limits_reached"])
            self.assertTrue(all(item["decision_reason"] == "resource_limit" for item in result["repair_attempts"]))

    def test_compound_repair_exact_fit_counts_body_once_across_two_children(self):
        with tempfile.TemporaryDirectory() as root:
            provider = ContentFake()
            result = self.generate(root, provider, options=CoreOptions(auto_repair=True,
                limits=ResourceLimits(max_repair_characters=len(LONG_TEXT))))
            self.assertEqual(len(provider.calls), 3)
            self.assertIsNotNone(result["chunks"][0]["composition"])
            self.assertEqual("".join(text for text, _, repair in provider.calls if repair), LONG_TEXT)
            self.assertEqual(result["resource_limits"]["max_repair_characters"], len(LONG_TEXT))
            self.assertEqual(ArtifactStore(Path(root) / "project").remaining_repair_characters(result["run_id"]), 0)

    def test_quality_settings_accept_null_and_zero_but_reject_invalid_limits(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "settings.json"
            for value in (None, 0, 100):
                path.write_text(json.dumps({"max_repair_characters": value}))
                options = apply_quality_settings(GeneralConfig(None), path)
                self.assertEqual(options.limits.max_repair_characters, value)
            for value in (-1, True, 1.5, "3"):
                path.write_text(json.dumps({"max_repair_characters": value}))
                with self.subTest(value=value), self.assertRaises(ValueError):
                    apply_quality_settings(GeneralConfig(None), path)
