import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path

from audiobook_generator.audio_core.models import CoreOptions
from audiobook_generator.audio_core.pipeline import run_chapter
from audiobook_generator.audio_core.reading import build_reading_plan, pronunciation_review
from audiobook_generator.core.audio_tags import AudioTags
from audiobook_generator.ui.audio_quality import load_quality_report
from tests.audiobook_generator.audio_core.pipeline_test import ObservedFake, plan_for


class PronunciationReviewTest(unittest.TestCase):
    def test_hints_preserve_body_and_keep_dictionary_override_unverified(self):
        chunks = build_reading_plan(plan_for(("银行重量3.5千克。",)).units, dictionary={"银行": "银航"})
        chunk = replace(chunks[0], source_span={"chapter_index": 1, "start": 50, "end": 62}, source_scope="chapter")
        before = asdict(chunk)
        result = pronunciation_review([chunk])
        self.assertEqual(asdict(chunk), before)
        self.assertEqual([hint["character"] for hint in result["hints"]], ["行", "重"])
        self.assertTrue(result["hints"][0]["reading_override_declared"])
        self.assertEqual(result["hints"][0]["source_span"]["start"], 51)
        self.assertEqual(result["hints"][0]["declared_readings"], [{"before": "银行", "after": "银航"}])
        self.assertFalse(result["audio_pronunciation_verified"])
        self.assertEqual(result["status"], "needs_review")

    def test_no_rule_hit_does_not_claim_pronunciation_verified_and_offsets_cover_chunks(self):
        plain = pronunciation_review(build_reading_plan(plan_for(("你好。",)).units))
        self.assertEqual(plain["status"], "not_flagged_by_rules")
        self.assertFalse(plain["audio_pronunciation_verified"])
        source = "行走在小路上。" * 10
        chunks = build_reading_plan(plan_for((source,)).units, chunk_chars=20)
        result = pronunciation_review(chunks)
        self.assertEqual([hint["unit_start"] for hint in result["hints"]], list(range(0, len(source), 7)))
        self.assertTrue(all(hint["source_span"] is None for hint in result["hints"]))

    def test_ui_shows_advisory_after_quality_checks_without_triggering_resynthesis(self):
        with tempfile.TemporaryDirectory() as root:
            provider = ObservedFake()
            result = run_chapter(plan_for(("银行。",)), provider, Path(root) / "out.wav",
                AudioTags("章", "作者", "书", 1), Path(root) / "project",
                options=CoreOptions(enable_asr=False, enable_speaker=False, auto_repair=True))
            self.assertEqual(len(provider.calls), 1)
            self.assertEqual(result["repair_attempts"], [])
            report = next((Path(root) / "project" / "reports").glob("*/chapter_*/quality.json"))
            _, rows, previews = load_quality_report(report)
            self.assertEqual(rows[-1][1], "读音复核")
            self.assertEqual(rows[-1][3], "pending")
            self.assertIn(result["pronunciation_review"]["hints"][0]["chunk_id"], previews)
