"""人工上传 TTS 官网音色说明的目录层测试。"""

import os
import tempfile
import unittest
from unittest.mock import patch

from audiobook_generator.tts_providers import voice_catalog


class VoiceCatalogTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env_patch = patch.dict(
            os.environ,
            {"TTS_VOICE_CATALOG_PATH": os.path.join(self.temp_dir.name, "voices.json")},
        )
        self.env_patch.start()

    def tearDown(self):
        self.env_patch.stop()
        self.temp_dir.cleanup()

    def test_builtin_catalog_contains_english_mimo_voices(self):
        entries = voice_catalog.load_voice_catalog()
        ids = {entry.voice_id for entry in entries}
        self.assertTrue({"Chloe", "Mia", "Dean", "Milo"}.issubset(ids))
        self.assertEqual(voice_catalog.normalize_voice_language("English"), "en")
        self.assertEqual(voice_catalog.normalize_catalog_gender("female"), "female")

    def test_parse_json_csv_markdown_and_pipe_text(self):
        documents = (
            (
                "json",
                '[{"voice_id": "JsonEn", "display_name": "Json English", "language": "en", "gender": "male"}]',
            ),
            (
                "csv",
                "voice_id,display_name,language,gender,description\nCsvEn,Csv Male,English,male,clear",
            ),
            (
                "markdown",
                "| voice_id | display_name | language | gender |\n| --- | --- | --- | --- |\n| MdEn | Md Female | English | female |",
            ),
            (
                "pipe",
                "PipeEn | Pipe Voice | English | female | clear narration",
            ),
        )
        for name, text in documents:
            with self.subTest(name=name):
                result = voice_catalog.import_voice_catalog_document(
                    text=text,
                    provider="openai",
                )
                self.assertTrue(result.ok, result.to_dict())
                self.assertEqual(result.entries[0].language, "en")
                self.assertIn(result.entries[0].gender, {"male", "female"})
                self.assertEqual(result.entries[0].provider, "openai")

    def test_duplicate_voice_keeps_last_definition_and_warns(self):
        result = voice_catalog.import_voice_catalog_document(
            text=(
                "voice_id | display_name | language | gender\n"
                "DupEn | First | English | female\n"
                "DupEn | Second | English | male"
            ),
            provider="openai",
        )
        self.assertTrue(result.ok, result.to_dict())
        self.assertEqual(len(result.entries), 1)
        self.assertEqual(result.entries[0].display_name, "Second")
        self.assertTrue(any("重复音色" in warning for warning in result.warnings))

    def test_invalid_provider_is_reported(self):
        result = voice_catalog.import_voice_catalog_document(
            text="voice_id,language\nVoiceA,English",
            provider="unknown-provider",
        )
        self.assertFalse(result.ok)
        self.assertTrue(any("不支持的 provider" in error for error in result.errors))

    def test_saved_user_entry_overrides_builtin_and_leads_english_pool(self):
        custom = voice_catalog.VoiceCatalogEntry(
            provider="openai",
            voice_id="Dean",
            display_name="User Dean",
            language="en",
            gender="male",
            recommended=True,
            tags=("narrator",),
        )
        voice_catalog.save_user_voice_entries((custom,))
        loaded = voice_catalog.get_voice_entry("openai", "Dean")
        self.assertEqual(loaded.display_name, "User Dean")
        self.assertEqual(loaded.source, "uploaded")

        pools = voice_catalog.get_role_voice_pools("openai", "en")
        self.assertEqual(pools["narrator"], "Dean")
        self.assertEqual(pools["male"][0], "Dean")

    def test_english_role_pool_contains_user_voice_first(self):
        result = voice_catalog.import_voice_catalog_document(
            text=(
                "voice_id | display_name | language | gender | description\n"
                "UserEnglish | User English | English | female | recommended narrator"
            ),
            provider="openai",
        )
        voice_catalog.save_user_voice_entries(result.entries)
        pools = voice_catalog.get_role_voice_pools("openai", "en")
        self.assertEqual(pools["narrator"], "UserEnglish")
        self.assertEqual(pools["female"][0], "UserEnglish")
        self.assertIn("Mia", pools["female"])


if __name__ == "__main__":
    unittest.main()
