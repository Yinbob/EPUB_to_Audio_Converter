import json
import tempfile
import unittest
from pathlib import Path

from audiobook_generator.role_script.loader import load_role_script


BOOK_HASH = "a" * 64


def minimal_script():
    return {
        "schema_version": 1,
        "provider": "openai",
        "book_sha256": BOOK_HASH,
        "default_pause_after_ms": 250,
        "roles": {
            "narrator": {
                "display_name": "旁白",
                "provider_params": {"voice": "冰糖", "speed": 1.0},
            }
        },
        "chapters": [
            {
                "chapter_index": 1,
                "title": "第一章",
                "segments": [{"role_id": "narrator", "text": "正文"}],
            }
        ],
    }


class RoleScriptLoaderTest(unittest.TestCase):
    def write(self, content):
        temporary = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", encoding="utf-8", delete=False
        )
        with temporary:
            temporary.write(content)
        self.addCleanup(Path(temporary.name).unlink, missing_ok=True)
        return temporary.name

    def test_loads_minimal_script(self):
        path = self.write(json.dumps(minimal_script(), ensure_ascii=False))
        script, report = load_role_script(path)
        self.assertIsNotNone(script)
        self.assertTrue(report.ok)
        self.assertEqual(script.chapters[0].segments[0].text, "正文")

    def test_loads_and_normalizes_optional_gender(self):
        payload = minimal_script()
        payload["roles"]["narrator"]["gender"] = "unknown"
        payload["roles"]["lin"] = {
            "display_name": "林黛玉",
            "gender": "女",
            "provider_params": {"voice": "茉莉", "speed": 1.0},
        }
        path = self.write(json.dumps(payload, ensure_ascii=False))

        script, report = load_role_script(path)

        self.assertTrue(report.ok, report.to_dict())
        self.assertIsNone(script.roles["narrator"].gender)
        self.assertEqual(script.roles["lin"].gender, "female")

    def test_rejects_invalid_gender_with_structured_error(self):
        payload = minimal_script()
        payload["roles"]["narrator"]["gender"] = "robot"
        path = self.write(json.dumps(payload, ensure_ascii=False))

        script, report = load_role_script(path)

        self.assertIsNone(script)
        self.assertEqual(report.errors[0].code, "invalid_role_gender")
        self.assertEqual(report.errors[0].path, "$.roles.narrator.gender")

    def test_duplicate_nested_key_has_precise_path(self):
        path = self.write(
            json.dumps(minimal_script(), ensure_ascii=False).replace(
                '"text": "正文"', '"text": "正文", "text": "重复"'
            )
        )
        script, report = load_role_script(path)
        self.assertIsNone(script)
        self.assertEqual(report.errors[0].code, "duplicate_key")
        self.assertEqual(report.errors[0].path, "$.chapters[0].segments[0].text")

    def test_invalid_json_is_structured(self):
        script, report = load_role_script(self.write("{not json"))
        self.assertIsNone(script)
        self.assertEqual(report.errors[0].code, "invalid_json")
        self.assertIn("line", report.errors[0].context)


if __name__ == "__main__":
    unittest.main()
