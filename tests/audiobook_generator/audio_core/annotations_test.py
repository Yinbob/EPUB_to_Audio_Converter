import contextlib
import csv
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from audiobook_generator.audio_core.__main__ import main
from audiobook_generator.audio_core.annotations import MANUAL_FIELDS, export_review_pack, read_review_pack
from audiobook_generator.audio_core.boundary_model import FEATURES


class AnnotationImportTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.audio = self.root / "audio.wav"
        self.audio.write_bytes(b"fixed-test-artifact")
        self.rows = []
        for sid, kind in (("C01", "chunk"), ("B01", "boundary")):
            row = {key: "" for key in sorted(MANUAL_FIELDS)}
            row.update(sample_id=sid, sample_type=kind, source_text="测试原文。",
                       audio_path="audio.wav", review_status="pending")
            self.rows.append(row)
        source = {"sample_id": "B01", "group_id": "source_scene", "split": "unassigned", "labels": None,
                  "origin": "real_unlabelled", "reviewed_normal": False, "boundary_id": "left|right",
                  "features": {key: 0. for key in FEATURES},
                  **{key: str(self.audio) for key in ("left_path", "right_path", "preview_path", "full_context_path")}}
        data = self.root / "pending_boundaries.jsonl"
        data.write_text(json.dumps(source) + "\n")
        self.manifest = {"schema": "audio-quality-human-review-v1",
                         "review_records": [{k: v for k, v in row.items() if k not in MANUAL_FIELDS}
                                            for row in self.rows],
                         "audio_files": [{"path": "audio.wav", "sha256": hashlib.sha256(self.audio.read_bytes()).hexdigest()}],
                         "boundary_data_sha256": hashlib.sha256(data.read_bytes()).hexdigest()}
        (self.root / "manifest.json").write_text(json.dumps(self.manifest))
        self.csv = self.root / "annotation.csv"
        self.save_csv()

    def save_csv(self):
        with self.csv.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(self.rows[0]))
            writer.writeheader()
            writer.writerows(self.rows)

    def reviewed(self):
        self.rows[1].update(review_status="reviewed", reviewer="test-fixture-only",
                            reviewed_at="2026-10-16T12:00:00+08:00", labels_json="[]",
                            cutoff="no", gap="no", click="no", overlap="no")
        self.save_csv()

    def test_pending_is_not_normal_and_only_explicit_splits_are_applied(self):
        result = read_review_pack(self.root, self.csv)
        self.assertEqual(result["reviewed_boundaries"], 0)
        self.assertEqual(len(result["skipped"]), 2)
        self.reviewed()
        result = read_review_pack(self.root, self.csv)
        self.assertTrue(result["split_required"])
        self.assertEqual(result["boundaries"][0]["labels"], [])
        self.assertEqual(result["boundaries"][0]["split"], "unassigned")
        self.assertTrue(result["boundaries"][0]["reviewed_normal"])
        result = read_review_pack(self.root, self.csv, splits={"source_scene": "dev"})
        self.assertEqual(result["boundaries"][0]["split"], "dev")
        self.assertEqual(result["training_sufficiency"], "not_assessed")

    def test_abstention_and_conflicting_labels_never_become_training_truth(self):
        self.reviewed()
        self.rows[1]["cutoff"] = "uncertain"
        self.save_csv()
        with self.assertRaisesRegex(ValueError, "未完成或仍不确定"):
            read_review_pack(self.root, self.csv)
        self.rows[1]["review_status"] = "needs_review"
        self.save_csv()
        self.assertEqual(read_review_pack(self.root, self.csv)["reviewed_boundaries"], 0)
        self.reviewed()
        self.rows[1]["labels_json"] = '["cutoff_suspected"]'
        self.save_csv()
        with self.assertRaisesRegex(ValueError, "矛盾"):
            read_review_pack(self.root, self.csv)
        self.rows[1]["cutoff"] = "yes"
        self.save_csv()
        result = read_review_pack(self.root, self.csv)
        self.assertFalse(result["boundaries"][0]["reviewed_normal"])

    def test_identity_metadata_audio_and_original_data_are_verified(self):
        self.rows[1]["source_text"] = "改错了原文。"
        self.save_csv()
        with self.assertRaisesRegex(ValueError, "受保护字段"):
            read_review_pack(self.root, self.csv)
        self.rows[1]["source_text"] = "测试原文。"
        self.rows.append(dict(self.rows[1]))
        self.save_csv()
        with self.assertRaisesRegex(ValueError, "重复或未知"):
            read_review_pack(self.root, self.csv)
        self.rows.pop()
        self.save_csv()
        self.audio.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "音频缺失或内容改变"):
            read_review_pack(self.root, self.csv)
        self.audio.write_bytes(b"fixed-test-artifact")
        (self.root / "pending_boundaries.jsonl").write_text("{}")
        with self.assertRaisesRegex(ValueError, "原始边界数据已改变"):
            read_review_pack(self.root, self.csv)

    def test_review_requires_identity_time_and_known_group_splits(self):
        self.reviewed()
        for key, value in (("reviewer", ""), ("reviewed_at", "2026-10-16"), ("reviewed_at", "invalid")):
            with self.subTest(key=key, value=value):
                self.reviewed()
                self.rows[1][key] = value
                self.save_csv()
                with self.assertRaises(ValueError):
                    read_review_pack(self.root, self.csv)
        self.reviewed()
        with self.assertRaisesRegex(ValueError, "划分文件"):
            read_review_pack(self.root, self.csv, splits={"wrong_scene": "test"})

    def test_cli_check_only_does_not_write_and_import_refuses_overwrite(self):
        self.reviewed()
        output = self.root / "reviewed.jsonl"
        args = ["import-review", "--pack", str(self.root), "--reviews", str(self.csv), "--output", str(output)]
        with contextlib.redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(main(args + ["--check-only"]), 0)
        self.assertEqual(json.loads(stdout.getvalue())["reviewed_boundaries"], 1)
        self.assertFalse(output.exists())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(args), 0)
        row = json.loads(output.read_text())
        self.assertEqual(row["origin"], "real_reviewed")
        self.assertTrue(output.with_name(output.name + ".review.json").is_file())
        before = output.read_bytes()
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(args), 2)
        self.assertEqual(output.read_bytes(), before)

    def test_export_preserves_real_join_and_rejects_changed_audio_or_overwrite(self):
        import numpy as np
        import soundfile as sf
        source = self.root / "source"
        source.mkdir()
        chunks, spans = [], []
        for i in range(2):
            path = source / f"chunk{i}.wav"
            sf.write(path, np.full((16000, 1), .1 * (i + 1)), 16000, subtype="PCM_16")
            chunks.append({"chunk": {"chunk_id": f"chunk{i}", "role_id": "narrator",
                                     "source_text": f"第{i}段。", "tts_text": f"第{i}段。"},
                           "rendered_path": str(path)})
            spans.append({"chunk_id": f"chunk{i}", "start_sample": 16000 * i, "end_sample": 16000 * (i + 1),
                          "render_sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        assembled = np.concatenate([sf.read(c["rendered_path"], always_2d=True)[0] for c in chunks])
        sf.write(source / "chapter.wav", assembled, 16000, subtype="PCM_16")
        report = {"schema_version": "audio-core-v1", "provider": "openai", "generation_status": "generated",
                  "chapter_index": 1, "source_group_id": "source_scene", "chunks": chunks,
                  "assembly": {"sample_rate": 16000, "channels": 1, "total_samples": 32000, "spans": spans,
                               "boundaries": [{"boundary_id": "chunk0|chunk1", "left_chunk_id": "chunk0",
                                               "right_chunk_id": "chunk1", "start_sample": 16000,
                                               "end_sample": 16000, "same_speaker": True}]},
                  "boundaries": [{"scope_id": "chunk0|chunk1", "metrics": {"features": {key: 0. for key in FEATURES}}}]}
        report_path = source / "quality.json"
        report_path.write_text(json.dumps(report))
        output = self.root / "new_pack"
        result = export_review_pack([report_path], output)
        self.assertEqual(result["sample_count"], 3)
        self.assertEqual(result["audio_files"], 4)
        self.assertEqual(read_review_pack(output, output / "annotation.csv")["reviewed_boundaries"], 0)
        pending = json.loads((output / "pending_boundaries.jsonl").read_text())
        self.assertEqual(pending["boundary_at_preview_seconds"], 1)
        self.assertIsNone(pending["labels"])
        actual, _ = sf.read(pending["preview_path"], dtype="int16", always_2d=True)
        original, _ = sf.read(source / "chapter.wav", dtype="int16", always_2d=True)
        np.testing.assert_array_equal(actual, original)
        with self.assertRaisesRegex(ValueError, "目录已存在"):
            export_review_pack([report_path], output)
        Path(chunks[0]["rendered_path"]).write_bytes(b"damaged")
        with self.assertRaisesRegex(ValueError, "校验值不一致"):
            export_review_pack([report_path], self.root / "failed_pack")
        self.assertFalse((self.root / "failed_pack").exists())


class InternalBoundaryExportTest(unittest.TestCase):
    def setUp(self):
        from audiobook_generator.audio_core.audio import boundary_features
        from audiobook_generator.audio_core.models import CoreOptions
        from audiobook_generator.audio_core.pipeline import run_chapter
        from audiobook_generator.core.audio_tags import AudioTags
        from tests.audiobook_generator.audio_core.content_repair_test import ContentFake, ContentOracle, LONG_TEXT
        from tests.audiobook_generator.audio_core.pipeline_test import plan_for

        class FeatureOracle(ContentOracle):
            # 判定仍为构造夹具；特征来自实际构造 WAV，不计入真实人工样本。
            def evaluate_boundary(self, left, right, left_path, right_path, **kwargs):
                report = super().evaluate_boundary(left, right, left_path, right_path, **kwargs)
                report.metrics["features"] = boundary_features(left_path, right_path,
                    same_speaker=left.role_id == right.role_id, planned_pause_ms=left.pause_after_ms)
                return report

        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.provider = ContentFake()
        self.result = run_chapter(plan_for(("开场。", LONG_TEXT)), self.provider, self.root / "out.wav",
            AudioTags("章", "作者", "书", 1), self.root / "project", options=CoreOptions(auto_repair=True),
            evaluator=FeatureOracle())
        self.report = next((self.root / "project" / "reports").glob("*/chapter_*/quality.json"))

    def test_export_internal_join_has_actual_chapter_offset_and_same_source_group(self):
        import numpy as np
        import soundfile as sf
        output = self.root / "pack"
        result = export_review_pack([self.report], output)
        self.assertEqual(result["sample_count"], 6)  # 两个父块、两个子块、原接缝和新增内部接缝。
        self.assertEqual(result["boundary_count"], 2)
        self.assertEqual(result["requests_sent"], 0)
        pending = [json.loads(line) for line in (output / "pending_boundaries.jsonl").read_text().splitlines()]
        self.assertEqual({r["group_id"] for r in pending}, {self.result["source_group_id"]})
        inner = next(r for r in pending if r["scope_kind"] == "internal_resegment")
        parent = self.result["chunks"][1]
        position = (self.result["assembly"]["spans"][1]["start_sample"]
                    + parent["composition"]["base_assembly"]["boundaries"][0]["start_sample"])
        self.assertEqual(inner["boundary_at_chapter_sample"], position)
        self.assertEqual(inner["parent_chunk_id"], parent["chunk"]["chunk_id"])
        actual, rate = sf.read(inner["preview_path"], dtype="int16", always_2d=True)
        full, _ = sf.read(self.report.parent / "chapter.wav", dtype="int16", always_2d=True)
        start = max(0, position - 2 * rate)
        np.testing.assert_array_equal(actual, full[start:min(len(full), position + 2 * rate)])
        self.assertTrue(all(r["labels"] is None for r in pending))
        self.assertEqual(read_review_pack(output, output / "annotation.csv")["reviewed_boundaries"], 0)
        with (output / "annotation.csv").open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        for row in rows:
            if row["sample_id"] == inner["sample_id"]:
                row.update(review_status="reviewed", reviewer="constructed-fixture-only",
                    reviewed_at="2026-10-16T12:00:00+08:00", labels_json="[]",
                    cutoff="no", gap="no", click="no", overlap="no")
        with (output / "annotation.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        accepted = read_review_pack(output, output / "annotation.csv")
        self.assertEqual(accepted["reviewed_boundaries"], 1)
        self.assertEqual(accepted["boundaries"][0]["group_id"], self.result["source_group_id"])
        self.assertEqual(accepted["boundaries"][0]["split"], "unassigned")

    def test_report_copy_outside_project_exports_the_bound_chapter(self):
        import soundfile as sf
        relocated = self.root / "unrelated" / "reevaluated.json"
        relocated.parent.mkdir()
        relocated.write_bytes(self.report.read_bytes())
        output = self.root / "relocated_pack"
        exported = export_review_pack([relocated], output)
        self.assertEqual(exported["boundary_count"], 2)
        actual, _ = sf.read(output / "audio/chapter_000001_full.wav", dtype="int16")
        expected, _ = sf.read(self.report.parent / "chapter.wav", dtype="int16")
        self.assertTrue((actual == expected).all())
        self.assertEqual(read_review_pack(output, output / "annotation.csv")["reviewed_boundaries"], 0)

    def test_export_rejects_stale_composition_coordinates_or_changed_child(self):
        original = json.loads(self.report.read_text())
        stale = json.loads(self.report.read_text())
        stale["chunks"][1]["composition"]["coordinate_scope"] = "before_parent_local_operations"
        self.report.write_text(json.dumps(stale))
        with self.assertRaisesRegex(ValueError, "内部组合"):
            export_review_pack([self.report], self.root / "stale")
        self.assertFalse((self.root / "stale").exists())
        self.report.write_text(json.dumps(original))
        child = Path(original["chunks"][1]["synthesis_parts"][1]["rendered_path"])
        child.write_bytes(b"corrupted")
        with self.assertRaisesRegex(ValueError, "校验值不一致"):
            export_review_pack([self.report], self.root / "damaged")
        self.assertFalse((self.root / "damaged").exists())

    def test_export_rejects_same_length_wrong_chapter_audio_or_nonzero_planned_pause(self):
        import soundfile as sf
        pcm = self.report.parent / "chapter.wav"
        original = pcm.read_bytes()
        samples, rate = sf.read(pcm, dtype="int16", always_2d=True)
        samples[100] = 12345
        sf.write(pcm, samples, rate, subtype="PCM_16")
        with self.assertRaisesRegex(ValueError, "来源校验"):
            export_review_pack([self.report], self.root / "wrong_content")
        pcm.write_bytes(original)
        samples, rate = sf.read(pcm, dtype="int16", always_2d=True)
        gap = self.result["assembly"]["boundaries"][0]
        self.assertGreater(gap["end_sample"], gap["start_sample"])
        samples[gap["start_sample"]] = 23456
        sf.write(pcm, samples, rate, subtype="PCM_16")
        with self.assertRaisesRegex(ValueError, "来源校验"):
            export_review_pack([self.report], self.root / "wrong_gap")
        self.assertFalse((self.root / "wrong_content").exists())
        self.assertFalse((self.root / "wrong_gap").exists())
