import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from audiobook_generator.role_script.models import (
    ChapterScript, RoleDefinition, RoleScriptV1, SegmentScript,
)
from audiobook_generator.role_script.project_store import load_project, project_path, save_project
from audiobook_generator.role_script.v2_generation import generate_v2_for_book


class V2GenerationTest(unittest.TestCase):
    def _generated(self, index, chapters):
        return RoleScriptV1(
            1, "openai", "a" * 64, 250,
            {
                "narrator": RoleDefinition("旁白", {"voice": "mimo_default", "speed": 1.0}),
                "zhang": RoleDefinition("张三", {"voice": "苏打", "speed": 1.0}),
            },
            (ChapterScript(index, chapters[index - 1][0],
                           (SegmentScript("zhang", chapters[index - 1][1],
                                          evidence_candidates=(("张三", "speaker_mention"),)),)),),
        )

    def test_fullbook_scan_and_repeat_run_reuses_entity_and_voice(self):
        chapters = [("一", "张三说：你好。"), ("二", "张三又说：再见。")]
        generated = [self._generated(1, chapters), self._generated(2, chapters)]
        with patch("audiobook_generator.role_script.v2_generation.splitter._create_client", return_value=object()), \
             patch("audiobook_generator.role_script.v2_generation._request_character_chunk",
                   return_value=[{"name": "张三", "aliases": [], "evidence_quote": "张三"}]) as registry, \
             patch("audiobook_generator.role_script.v2_generation.splitter.split_chapters_with_deepseek",
                   side_effect=generated):
            first = generate_v2_for_book(
                chapters, 1, 1, "openai", "a" * 64, "key", "https://example.test", "deepseek-chat",
                parser_fingerprint="parser-v1",
            )
            self.assertEqual(registry.call_count, 2)
            entity_id = first.chapters[0].segments[0].role_id
            self.assertEqual(first.chapters[0].segments[0].source_span.end, len(chapters[0][1]))
            self.assertEqual(first.chapters[0].segments[0].speaker.evidence[0].quote, "张三")
            locked = replace(first, entities={
                **first.entities, entity_id: replace(first.entities[entity_id], voice_locked=True)
            })
            with tempfile.TemporaryDirectory() as folder:
                path = project_path(folder, "a" * 64)
                save_project(locked, path)
                previous = load_project(path, book_sha256="a" * 64)
                second = generate_v2_for_book(
                    chapters, 2, 2, "openai", "a" * 64, "key", "https://example.test", "deepseek-chat",
                    parser_fingerprint="parser-v1", previous=previous,
                )
            self.assertEqual(registry.call_count, 2)
            self.assertEqual(len(second.chapters), 2)
            self.assertEqual(second.chapters[1].segments[0].role_id, entity_id)
            self.assertTrue(second.entities[entity_id].voice_locked)
            self.assertEqual(second.roles[entity_id].provider_params["voice"], "苏打")


if __name__ == "__main__":
    unittest.main()
