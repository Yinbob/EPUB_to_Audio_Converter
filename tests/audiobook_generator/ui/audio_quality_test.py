import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from audiobook_generator.config.general_config import GeneralConfig
from audiobook_generator.audio_core.pipeline import run_chapter
from audiobook_generator.audio_core.models import CoreOptions
from audiobook_generator.core.audio_tags import AudioTags
from audiobook_generator.ui.audio_quality import apply_quality_settings, find_quality_reports, load_quality_report, preview_quality_issue
from tests.audiobook_generator.audio_core.pipeline_test import ObservedFake, plan_for


class AudioQualityUiTest(unittest.TestCase):
    def test_tail_repeat_mode_settings_and_candidate_preview_integrity(self):
        from tests.audiobook_generator.audio_core.tail_repeat_test import RepeatingProvider, TailRepeatTest
        with tempfile.TemporaryDirectory() as root:
            settings=Path(root)/'settings.json'
            for mode in ('off','review','auto'):
                settings.write_text(json.dumps({'tail_repeat_mode':mode}))
                self.assertEqual(apply_quality_settings(GeneralConfig(None),settings).tail_repeat_mode,mode)
            for value in (True,[],{},'yes',None):
                settings.write_text(json.dumps({'tail_repeat_mode':value}))
                with self.assertRaises(ValueError): apply_quality_settings(GeneralConfig(None),settings)
            result=TailRepeatTest().generate(root,RepeatingProvider(),'review')
            report=Path(root)/'project/reports'/result['run_id']/'chapter_000001/quality.json'
            scope='tail_repeat:'+result['chunks'][0]['chunk']['chunk_id']
            _,_,previews=load_quality_report(report)
            candidate=Path(previews[scope]); candidate.write_bytes(b'changed candidate')
            self.assertNotIn(scope,load_quality_report(report)[2])

    def test_fixed_references_roundtrip_and_invalid_path_types_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "settings.json"
            reference = str(Path(root) / "references.json")
            for value in (reference, None):
                path.write_text(json.dumps({"role_references": value}))
                config = GeneralConfig(None)
                options = apply_quality_settings(config, path)
                self.assertEqual(config.audio_core_role_references, value)
                self.assertEqual(options.role_references, value)
            for value in (True, 1, {}, [], "", "  "):
                path.write_text(json.dumps({"role_references": value}))
                with self.assertRaises(ValueError):
                    apply_quality_settings(GeneralConfig(None), path)
                with self.assertRaises(ValueError):
                    CoreOptions(role_references=value)

    def test_reviewed_transition_boundaries_roundtrip_through_ui_json(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "settings.json"
            path.write_text(json.dumps({"transition_boundaries": ["a|b"], "transition_source_group": "a" * 64}))
            options = apply_quality_settings(GeneralConfig(None), path)
            self.assertEqual(options.transition_boundaries, ["a|b"])
            self.assertEqual(options.transition_source_group, "a" * 64)
            path.write_text(json.dumps({"transition_boundaries": "all"}))
            with self.assertRaises(ValueError):
                apply_quality_settings(GeneralConfig(None), path)

    def test_validated_json_settings_reject_unknown_keys_and_zero_chunks(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "settings.json"
            path.write_text(json.dumps({"chunk_chars": 100, "max_requests": 5, "no_asr": True}))
            config = GeneralConfig(None)
            options = apply_quality_settings(config, path)
            self.assertEqual(options.chunk_chars, 100)
            self.assertFalse(options.enable_asr)
            for value in ({"chunk_chars": 0}, {"no_asr": "false"}, {"api_key": "do not accept"}):
                path.write_text(json.dumps(value))
                with self.assertRaises(ValueError):
                    apply_quality_settings(GeneralConfig(None), path)

    def test_reports_are_found_and_audio_previews_stay_within_project(self):
        with tempfile.TemporaryDirectory() as root:
            project = Path(root) / ".audio_projects" / "book"
            run_chapter(plan_for(), ObservedFake(), Path(root) / "out.wav", AudioTags("章", "作者", "书", 1),
                        project, options=CoreOptions(enable_asr=False, enable_speaker=False))
            paths = find_quality_reports(root)
            self.assertEqual(len(paths), 1)
            value, rows, previews = load_quality_report(paths[0])
            self.assertTrue(rows)
            self.assertEqual(len(previews), 4)
            self.assertEqual(value["final_verification"]["metrics"]["content_method"], "exact_pcm_equivalence")
            scope = value["boundaries"][0]["scope_id"]
            self.assertTrue(Path(preview_quality_issue(paths[0], scope)).is_file())
            value["chunks"][0]["rendered_path"] = str(Path(root) / "out.wav")
            Path(paths[0]).write_text(json.dumps(value))
            _, _, previews = load_quality_report(paths[0])
            self.assertNotIn(value["chunks"][0]["chunk"]["chunk_id"], previews)

    def test_explicit_reading_dictionary_is_validated_in_ui_settings(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "settings.json"
            path.write_text(json.dumps({"reading_dictionary": {"API": "应用接口"}}))
            options = apply_quality_settings(GeneralConfig(None), path)
            self.assertEqual(options.reading_dictionary, {"API": "应用接口"})
            for value in ("a.json", {"API": "<break/>"}, {"A": "B", "B": "C"}):
                path.write_text(json.dumps({"reading_dictionary": value}))
                with self.assertRaises(ValueError):
                    apply_quality_settings(GeneralConfig(None), path)
