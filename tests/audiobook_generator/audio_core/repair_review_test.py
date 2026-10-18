"""只验证盲听材料与评分契约；构造人工回答不计入实验数据。"""
import contextlib
import csv
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from audiobook_generator.audio_core.__main__ import main
from audiobook_generator.audio_core.repair_review import DIMENSIONS, prepare_repair_review, score_repair_review


class RepairReviewTest(unittest.TestCase):
    def make_pair(self, root):
        paths = []
        for name, frames in (("baseline", 64000), ("candidate", 67200)):
            audio = root / f"{name}.wav"
            sf.write(audio, .1 * np.sin(np.arange(frames) * .08), 16000, subtype="PCM_16")
            chunks = [{"chunk": {"chunk_id": f"c{i}", "role_id": role, "source_text": text, "tts_text": text,
                                  "profile": {"voice": voice}}} for i, (role, voice, text) in
                      enumerate((("narrator", "冰糖", "这是第一句。"), ("hero", "苏打", "这是第二句。")), 1)]
            report = {"schema_version": "audio-core-v1", "provider": "openai", "generation_status": "generated",
                      "quality_status": "incomplete", "source_group_id": "constructed-group", "chapter_index": 1,
                      "chunks": chunks, "output_file": str(audio),
                      "final_verification": {"dimensions": {"encoding": "passed"},
                                             "metrics": {"encoded_sha256": hashlib.sha256(audio.read_bytes()).hexdigest()}},
                      "assembly": {"sample_rate": 16000, "total_samples": frames,
                                   "spans": [{"chunk_id": "c1", "start_sample": 0, "end_sample": 32000},
                                             {"chunk_id": "c2", "start_sample": 32000, "end_sample": frames}],
                                   "boundaries": [{"start_sample": 32000, "end_sample": 32000, "same_speaker": False}]}}
            path = root / f"{name}.json"
            path.write_text(json.dumps(report))
            paths.append(str(path))
        return [{"baseline_report": paths[0], "candidate_report": paths[1]}]

    def read_rows(self, path):
        with path.open(encoding="utf-8-sig", newline="") as stream:
            return list(csv.DictReader(stream))

    def write_rows(self, path, rows):
        with path.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)

    def test_export_is_blind_preserves_actual_times_and_does_not_prefill_labels(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = prepare_repair_review(self.make_pair(root), root / "pack", seed=8)
            public = root / "pack/public"
            trial = json.loads((public / "trials.json").read_text())["trials"][0]
            self.assertEqual(result["requests_sent"], 0)
            self.assertEqual(sorted(v["duration_seconds"] for v in trial["versions"].values()), [4, 4.2])
            for version in trial["versions"].values():
                self.assertFalse(version["joins"][0]["same_speaker"])
                self.assertEqual(version["joins"][0]["start_seconds"], 2)
                self.assertEqual(sf.info(public / version["audio"]).subtype, "PCM_16")
            for path in public.glob("*.*"):
                self.assertNotIn("baseline", path.read_text(encoding="utf-8-sig"))
                self.assertNotIn("candidate", path.read_text(encoding="utf-8-sig"))
                self.assertNotIn(str(root), path.read_text(encoding="utf-8-sig"))
            rows = self.read_rows(public / "responses.csv")
            self.assertEqual(rows[0]["review_status"], "pending")
            self.assertTrue(all(rows[0][dimension] == "" for dimension in DIMENSIONS))
            scored = score_repair_review(root / "pack/private_key.json", public / "responses.csv")
            self.assertEqual((scored["reviewed"], scored["skipped"], scored["participants"]), (0, 1, 0))
            self.assertEqual(scored["status"], "awaiting_human_review")

    def test_identity_and_output_guards_reject_invalid_comparison_without_partial_pack(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pair = self.make_pair(root)
            candidate = Path(pair[0]["candidate_report"])
            original = json.loads(candidate.read_text())
            for name, value in (("tts_text", "篡改正文。"), ("profile", {"voice": "其他声音"})):
                changed = json.loads(json.dumps(original))
                changed["chunks"][0]["chunk"][name] = value
                candidate.write_text(json.dumps(changed))
                with self.assertRaises(ValueError):
                    prepare_repair_review(pair, root / "pack")
                self.assertFalse((root / "pack").exists())
            candidate.write_text(json.dumps(original))
            prepare_repair_review(pair, root / "pack")
            with self.assertRaises(ValueError):
                prepare_repair_review(pair, root / "pack")
            with self.assertRaises(ValueError):
                prepare_repair_review(pair * 2, root / "duplicate")

    def test_changed_source_and_missing_encoding_check_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pair = self.make_pair(root)
            source = Path(pair[0]["candidate_report"])
            original = json.loads(source.read_text())
            changed = {**original, "final_verification": {}}
            source.write_text(json.dumps(changed))
            with self.assertRaises(ValueError):
                prepare_repair_review(pair, root / "missing")
            source.write_text(json.dumps(original))
            sf.write(original["output_file"], np.zeros(67200), 16000, subtype="PCM_16")
            with self.assertRaises(ValueError):
                prepare_repair_review(pair, root / "changed")

    def test_scoring_decodes_random_arms_and_rejects_duplicates_incomplete_and_changed_audio(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prepare_repair_review(self.make_pair(root), root / "pack")
            key_path, response_path = root / "pack/private_key.json", root / "pack/public/responses.csv"
            key = json.loads(key_path.read_text())
            rows = self.read_rows(response_path)
            row = rows[0]
            arms = key["answers"][row["trial_id"]]["arms"]
            better = next(label for label, arm in arms.items() if arm["method"] == "candidate")
            row.update(participant_id="constructed-reviewer", review_status="reviewed", reviewed_at="2026-10-16T12:00:00+08:00")
            row.update(dict(zip(DIMENSIONS, (better, "tie", "uncertain", "not_applicable"))))
            self.write_rows(response_path, rows)
            result = score_repair_review(key_path, response_path)
            self.assertEqual(result["dimension_preferences"]["stitching"]["candidate"], 1)
            self.assertEqual(result["dimension_preferences"]["content"]["uncertain"], 1)
            self.write_rows(response_path, rows * 2)
            with self.assertRaises(ValueError):
                score_repair_review(key_path, response_path)
            row["content"] = ""
            self.write_rows(response_path, rows)
            with self.assertRaises(ValueError):
                score_repair_review(key_path, response_path)
            row["content"] = "uncertain"
            self.write_rows(response_path, rows)
            (root / "pack/public" / next(name for name in key["public_sha256"] if name.endswith(".wav"))).write_bytes(b"changed")
            with self.assertRaises(ValueError):
                score_repair_review(key_path, response_path)

    def test_cli_exports_and_scores_empty_responses_without_inference(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "pairs.json").write_text(json.dumps(self.make_pair(root)))
            for argv in (["prepare-repair-review", "--pairs", str(root / "pairs.json"), "--output", str(root / "pack")],
                         ["score-repair-review", "--key", str(root / "pack/private_key.json"), "--responses", str(root / "pack/public/responses.csv"), "--output", str(root / "scores.json")]):
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(main(argv), 0)
            self.assertEqual(json.loads((root / "scores.json").read_text())["reviewed"], 0)
