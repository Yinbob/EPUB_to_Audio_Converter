import contextlib
import csv
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import soundfile as sf

from audiobook_generator.audio_core.__main__ import main
from audiobook_generator.audio_core.models import CoreOptions
from audiobook_generator.audio_core.pipeline import run_chapter
from audiobook_generator.audio_core.dataset import augment_boundaries
from audiobook_generator.core.audio_tags import AudioTags
from tests.audiobook_generator.audio_core.pipeline_test import ObservedFake, plan_for
from tests.audiobook_generator.audio_core import boundary_model_test


class ResearchCliTest(unittest.TestCase):
    def command(self, *args, expected=0):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(list(args))
        self.assertEqual(code, expected, stderr.getvalue())
        return json.loads(stdout.getvalue()) if code == 0 else stderr.getvalue()

    def test_offline_plan_preflight_evaluation_label_and_training_workflow(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch("openai.OpenAI") as remote:
                preflight = self.command("preflight")
                remote.assert_not_called()
            self.assertEqual(preflight["requests_sent"], 0)
            text = root / "text.txt"
            text.write_text("API到了2026年10月16日，增长3.5%。")
            dictionary = root / "readings.json"
            dictionary.write_text(json.dumps({"API": "应用接口"}))
            self.command("plan", "--text", str(text), "--output", str(root / "plan.json"),
                         "--reading-dictionary", str(dictionary))
            reading = json.loads((root / "plan.json").read_text())
            self.assertIn("百分之三点五", reading["chunks"][0]["tts_text"])
            self.assertIn("应用接口", reading["chunks"][0]["tts_text"])
            self.assertEqual(reading["reading_dictionary"], {"API": "应用接口"})
            project = root / "project"
            run_chapter(plan_for(), ObservedFake(), root / "out.wav", AudioTags("章", "作者", "书", 1), project,
                        options=CoreOptions(enable_asr=False, enable_speaker=False))
            report = next(project.rglob("quality.json"))
            self.command("evaluate", "--manifest", str(report), "--output", str(root / "evaluated.json"),
                         "--no-asr", "--no-speaker")
            result = self.command("prepare-labels", "--report", str(report), "--output", str(root / "labels.jsonl"))
            self.assertEqual(result["rows"], 1)
            row = json.loads((root / "labels.jsonl").read_text())
            self.assertIsNone(row["labels"])
            self.assertEqual(row["split"], "unassigned")
            self.command("train-boundary", "--data", str(root / "labels.jsonl"), "--output", str(root / "bad.json"), expected=2)
            row.update(labels=[], split="train", reviewed_normal=True, origin="real_reviewed")
            (root / "labels.jsonl").write_text(json.dumps(row))
            self.command("augment", "--data", str(root / "labels.jsonl"), "--output", str(root / "augmented.jsonl"))
            variants = [json.loads(line) for line in (root / "augmented.jsonl").read_text().splitlines()]
            self.assertEqual(len(variants), 3)
            self.assertTrue(all(v["group_id"] == row["group_id"] and v["split"] == "train" for v in variants))
            self.assertTrue(all(v["labels"] is None and v["origin"] == "synthetic" for v in variants))
            row["split"] = "test"
            with self.assertRaisesRegex(ValueError, "测试集"):
                augment_boundaries([row], root / "forbidden")
            rows = boundary_model_test.BoundaryModelTest().rows()
            data = root / "toy.jsonl"
            data.write_text("\n".join(json.dumps(r) for r in rows))
            trained = self.command("train-boundary", "--data", str(data), "--output", str(root / "model.json"), "--steps", "30")
            self.assertEqual(trained["confidence_kind"], "uncalibrated_scores")
            model = json.loads((root / "model.json").read_text())
            self.assertEqual(model["real_validation_status"], "no_real_test_data")
            self.assertEqual(model["heldout_metrics"]["rows"], 16)
            summary = self.command("summarize", str(report), str(report))
            self.assertEqual(len(summary["resources_by_run"]), 1)

    def test_untrainable_boundary_data_cannot_publish_or_overwrite_model(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            rows = boundary_model_test.BoundaryModelTest().rows()
            for row in rows:
                row['labels'] = []
            data, output = root/'negative.jsonl', root/'model.json'
            data.write_text('\n'.join(json.dumps(r) for r in rows))
            for existing in (False, True):
                with self.subTest(existing=existing):
                    if existing:
                        output.write_bytes(b'keep previous model')
                    with patch('openai.OpenAI') as remote:
                        error = self.command('train-boundary', '--data', str(data),
                                             '--output', str(output), '--steps', '1', expected=2)
                        remote.assert_not_called()
                    self.assertIn('没有可训练类别', error)
                    if existing:
                        self.assertEqual(output.read_bytes(), b'keep previous model')
                    else:
                        self.assertFalse(output.exists())

    def test_listening_package_hides_answers_and_scores_only_collected_responses(self):
        with tempfile.TemporaryDirectory() as folder:
            root, conditions = Path(folder), []
            for condition_index, condition in enumerate(("graph_condition", "random_condition")):
                directory = root / condition
                directory.mkdir()
                chunks, spans, boundaries, pcm_parts, cursor = [], [], [], [], 0
                for i, role in enumerate(("hero_a", "hero_b", "hero_a", "hero_b")):
                    path = directory / f"{i}.wav"
                    signal = .1 * np.sin(np.arange(50000 + i * 1000) * (0.05 + i * .01 + condition_index * .02))
                    sf.write(path, signal, 16000, subtype="PCM_16")
                    pcm_parts.append(sf.read(path, dtype="int16")[0])
                    spans.append({"chunk_id": f"chunk{i}", "start_sample": cursor, "end_sample": cursor + len(signal),
                                  "render_sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
                    if i:
                        boundaries.append({"left_chunk_id": f"chunk{i-1}", "right_chunk_id": f"chunk{i}",
                                           "start_sample": cursor, "end_sample": cursor})
                    cursor += len(signal)
                    chunks.append({"chunk": {"chunk_id": f"chunk{i}", "role_id": role, "tts_text": f"测试句{i}",
                                              "source_text": f"测试句{i}"},
                                   "rendered_path": str(path), "report": {"dimensions": {"content": "passed", "signal": "passed"},
                                                                            "issues": []}})
                pcm = directory / "chapter.wav"
                sf.write(pcm, np.concatenate(pcm_parts), 16000, subtype="PCM_16")
                pcm_sha = hashlib.sha256(pcm.read_bytes()).hexdigest()
                report = directory / "quality.json"
                report.write_text(json.dumps({"schema_version": "audio-core-v1", "source_group_id": "scene",
                    "provider": "openai", "generation_status": "generated", "output_file": str(pcm),
                    "quality_status": "incomplete", "chunks": chunks,
                    "assembly": {"sample_rate": 16000, "channels": 1, "total_samples": cursor,
                                 "spans": spans, "boundaries": boundaries},
                    "boundaries": [{"dimensions": {"content": "passed", "stitching": "incomplete"}, "issues": []}
                                   for _ in boundaries],
                    "final_verification": {"dimensions": {"encoding": "passed", "content": "passed"}, "issues": [],
                                           "metrics": {"encoded_sha256": pcm_sha, "reference_pcm_sha256": pcm_sha}}}))
                conditions.append({"condition": condition, "report_path": str(report)})
            manifest = root / "conditions.json"
            manifest.write_text(json.dumps(conditions))
            output = root / "study"
            result = self.command("prepare-listening", "--conditions", str(manifest), "--output", str(output))
            self.assertEqual(result["trials"], 8)
            public = (output / "public" / "trials.json").read_text()
            self.assertNotIn("graph_condition", public)
            self.assertNotIn("hero_a", public)
            self.assertNotIn("correct_role", public)
            key = output / "private_answer_key.json"
            answers = json.loads(key.read_text())["answers"]
            responses = output / "responses.csv"
            with responses.open("w", newline="") as stream:
                writer = csv.writer(stream)
                writer.writerow(["participant_id", "trial_id", "response_role"])
                writer.writerows(["pilot_1", trial, value["correct_role"]] for trial, value in answers.items())
            scores = self.command("score-listening", "--key", str(key), "--responses", str(responses),
                                  "--output", str(root / "scores.json"))
            self.assertEqual(scores["analysis_kind"], "descriptive_pilot")
            self.assertTrue(all(s["accuracy"] == 1 for s in scores["conditions"].values()))

    def test_relocated_legacy_report_can_be_reevaluated_twice_and_exported_without_requests(self):
        from audiobook_generator.audio_core.annotations import export_review_pack
        from audiobook_generator.audio_core.store import ArtifactStore
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            provider = ObservedFake()
            project = root / "project"
            source = run_chapter(plan_for(), provider, root / "out.wav", AudioTags("章", "作者", "书", 1), project,
                options=CoreOptions(enable_asr=False, enable_speaker=False))
            original = next(project.rglob("quality.json"))
            original_bytes = original.read_bytes()
            source["final_verification"]["metrics"].pop("reference_pcm_path")
            outside = root / "outside"
            outside.mkdir()
            legacy = outside / "legacy.json"
            legacy.write_text(json.dumps(source))
            store = ArtifactStore(project)
            events = store.request_events(run_id=source["run_id"])
            for index in (1, 2):
                result = outside / f"pass_{index}" / "quality.json"
                self.command("evaluate", "--manifest", str(legacy), "--output", str(result), "--no-asr", "--no-speaker")
                payload = json.loads(result.read_text())
                self.assertEqual(payload["final_verification"]["metrics"]["reference_pcm_path"], str((original.parent / "chapter.wav").resolve()))
                self.assertEqual(payload["final_verification"]["dimensions"]["encoding"], "passed")
                legacy = result
            exported = export_review_pack([legacy], root / "pack")
            self.assertEqual(exported["boundary_count"], 1)
            self.assertEqual(len(provider.calls), 2)
            self.assertEqual(store.request_events(run_id=source["run_id"]), events)
            self.assertEqual(original.read_bytes(), original_bytes)

    def test_reports_in_same_output_directory_keep_independent_previews(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            sources = []
            for index, frequency in enumerate((200, 300)):
                project = root / f"project{index}"
                run_chapter(plan_for(), ObservedFake(frequency=frequency), root / f"out{index}.wav",
                    AudioTags("章", "作者", "书", 1), project,
                    options=CoreOptions(enable_asr=False, enable_speaker=False))
                sources.append(next(project.rglob("quality.json")))
            protected = {}
            previews = []
            for index, source in enumerate(sources):
                output = root / f"evaluated{index}.json"
                self.command("evaluate", "--manifest", str(source), "--output", str(output), "--no-asr", "--no-speaker")
                report = json.loads(output.read_text())
                preview = Path(report["boundaries"][0]["metrics"]["preview_path"])
                decoded = Path(report["final_verification"]["metrics"]["decoded_path"])
                if index == 0:
                    protected = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (preview, decoded)}
                previews.append(preview)
            self.assertNotEqual(previews[0], previews[1])
            self.assertNotEqual(hashlib.sha256(previews[0].read_bytes()).hexdigest(),
                                hashlib.sha256(previews[1].read_bytes()).hexdigest())
            self.assertEqual({p: hashlib.sha256(p.read_bytes()).hexdigest() for p in protected}, protected)

    def test_asr_cache_reloads_when_model_changes_on_same_device(self):
        from audiobook_generator.utils import voxcpm_asr
        fake = MagicMock()
        with patch.dict("sys.modules", {"funasr": fake}), patch.object(voxcpm_asr, "_asr_model", None), \
                patch.object(voxcpm_asr, "_asr_device", None), patch.object(voxcpm_asr, "_asr_model_id", None):
            voxcpm_asr._get_or_load_asr_model("local_a")
            voxcpm_asr._get_or_load_asr_model("local_a")
            voxcpm_asr._get_or_load_asr_model("local_b")
            self.assertEqual(fake.AutoModel.call_count, 2)
