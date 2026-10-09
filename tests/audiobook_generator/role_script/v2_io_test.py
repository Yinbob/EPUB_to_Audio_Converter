import json
import tempfile
import unittest
from pathlib import Path

from audiobook_generator.role_script.deepseek_splitter import role_script_to_dict
from audiobook_generator.role_script.loader import load_role_script
from audiobook_generator.role_script.models import (
    AliasRecord, CharacterEntity, ChapterScript, EvidenceSpan, RoleDefinition,
    RoleScriptV2, SegmentScript, SourceSpan, SpeakerDecision,
)
from audiobook_generator.role_script.validator import validate_role_script


def _script():
    source = "林黛玉说：你好。"
    return RoleScriptV2(
        schema_version=2,
        provider="openai",
        book_sha256="a" * 64,
        default_pause_after_ms=250,
        roles={
            "narrator": RoleDefinition("旁白", {"voice": "冰糖", "speed": 1.0}),
            "char_1": RoleDefinition("林黛玉", {"voice": "茉莉", "speed": 1.0}),
        },
        chapters=(ChapterScript(1, "第一章", (
            SegmentScript("narrator", source[:5], segment_id="ch1_s1",
                          source_span=SourceSpan(1, 0, 5),
                          speaker=SpeakerDecision("narrator", "confirmed")),
            SegmentScript("char_1", source[5:], segment_id="ch1_s2",
                          source_span=SourceSpan(1, 5, len(source)),
                          speaker=SpeakerDecision(
                              "char_1", "proposed", 0.82,
                              (EvidenceSpan(SourceSpan(1, 0, 5), "explicit_speech_tag", source[:5]),),
                              "deepseek-chat",
                          )),
        )),),
        entities={
            "narrator": CharacterEntity("旁白", voice_profile_id="voice_narrator"),
            "char_1": CharacterEntity("林黛玉", (AliasRecord("黛玉", "confirmed"),), "voice_1", True, "female"),
        },
    ), source


class RoleScriptV2IOTest(unittest.TestCase):
    def _load(self, payload):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "role.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            return load_role_script(path)

    def test_roundtrip_and_source_validation(self):
        script, source = _script()
        loaded, report = self._load(role_script_to_dict(script))
        self.assertTrue(report.ok, report.to_dict())
        self.assertIsInstance(loaded, RoleScriptV2)
        result = validate_role_script(loaded, chapters=[("第一章", source)])
        self.assertTrue(result.ok, result.report.to_dict())
        self.assertEqual(result.script.entities["char_1"].aliases[0].text, "黛玉")

    def test_rejects_bad_evidence_and_missing_entity(self):
        script, source = _script()
        payload = role_script_to_dict(script)
        payload["chapters"][0]["segments"][1]["speaker"]["evidence"][0]["quote"] = "错误引文"
        loaded, report = self._load(payload)
        self.assertTrue(report.ok)
        result = validate_role_script(loaded, chapters=[("第一章", source)])
        self.assertIn("evidence_span_mismatch", [item.code for item in result.report.errors])

        payload["chapters"][0]["segments"][1]["speaker"]["entity_id"] = "unknown_person"
        loaded, report = self._load(payload)
        self.assertTrue(report.ok)
        result = validate_role_script(loaded, chapters=[("第一章", source)])
        self.assertIn("unknown_entity", [item.code for item in result.report.errors])


if __name__ == "__main__":
    unittest.main()
