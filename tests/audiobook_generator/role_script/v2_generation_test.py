import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from audiobook_generator.role_script.models import (
    ChapterScript, RoleDefinition, RoleScriptV1, SegmentScript, RegistryWarning,
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

    def test_selected_chapters_only_keep_absolute_evidence_and_saved_voice(self):
        chapters = [("一", "不应发送的第一章"), ("二", "张三说：你好。"), ("三", "张三说：再见。")]
        with patch("audiobook_generator.role_script.v2_generation.splitter._create_client", return_value=object()), \
             patch("audiobook_generator.role_script.v2_generation._request_character_chunk",
                   return_value=[{"name": "张三", "aliases": [], "evidence_quote": "张三"}]) as registry, \
             patch("audiobook_generator.role_script.v2_generation.splitter.split_chapters_with_deepseek",
                   side_effect=[self._generated(2, chapters), self._generated(3, chapters)]):
            first = generate_v2_for_book(
                chapters, 2, 2, "openai", "a" * 64, "key", "https://example.test", "deepseek-chat",
                parser_fingerprint="parser-v1", index_full_book=False,
            )
            self.assertEqual([(call.args[2], call.args[3]) for call in registry.call_args_list], [(2, chapters[1][1])])
            self.assertFalse(first.registry_complete)
            entity_id = first.chapters[0].segments[0].role_id
            first = replace(first, roles={**first.roles, entity_id: RoleDefinition("张三", {"voice": "茉莉", "speed": 1.0})})
            with tempfile.TemporaryDirectory() as folder:
                path = save_project(first, project_path(folder, "a" * 64))
                previous = load_project(path, book_sha256="a" * 64)
                self.assertFalse(previous.registry_complete)
                second = generate_v2_for_book(
                    chapters, 3, 3, "openai", "a" * 64, "key", "https://example.test", "deepseek-chat",
                    parser_fingerprint="parser-v1", previous=previous, index_full_book=False,
                )
            self.assertFalse(second.registry_complete)
            self.assertEqual([chapter.chapter_index for chapter in second.chapters], [2, 3])
            self.assertEqual(second.chapters[1].segments[0].role_id, entity_id)
            self.assertEqual(second.chapters[1].segments[0].speaker.evidence[0].span.chapter_index, 3)
            self.assertEqual(second.roles[entity_id].provider_params['voice'], '茉莉')
            self.assertEqual([call.args[2] for call in registry.call_args_list], [2, 3])

    def test_invalid_scope_fails_before_any_request(self):
        with patch("audiobook_generator.role_script.v2_generation.splitter._create_client") as client:
            for start, end, full in [(0, 1, False), (1, 3, True), (2, 1, False), (1, 1, "false")]:
                with self.assertRaises(ValueError):
                    generate_v2_for_book(
                        [("一", "张三说：你好。")], start, end, "openai", "a" * 64,
                        "key", "https://example.test", "deepseek-chat",
                        parser_fingerprint="parser-v1", index_full_book=full,
                    )
            client.assert_not_called()

    def test_tolerated_index_marks_automatic_assignments_for_review_and_recovers(self):
        chapters = [("一", "张三说：你好。")]

        def registry(*args, **kwargs):
            kwargs['warnings'].append(RegistryWarning(1, 0, 1, 2, '第 1 章有一个无法定位的人物'))
            return [{"name": "张三", "aliases": [], "evidence_quote": "张三"}]

        with patch("audiobook_generator.role_script.v2_generation.splitter._create_client", return_value=object()), \
             patch("audiobook_generator.role_script.v2_generation._request_character_chunk", side_effect=registry) as index, \
             patch("audiobook_generator.role_script.v2_generation.splitter.split_chapters_with_deepseek",
                   side_effect=[self._generated(1, chapters)] * 2):
            first = generate_v2_for_book(
                chapters, 1, 1, "openai", "a" * 64, "key", "https://example.test", "deepseek-chat",
                parser_fingerprint="parser-v1",
            )
            self.assertFalse(first.registry_complete)
            self.assertEqual(len(first.registry_warnings), 1)
            segment = first.chapters[0].segments[0]
            self.assertEqual(segment.text, chapters[0][1])
            self.assertEqual(segment.speaker.status, 'needs_review')
            human = replace(first, chapters=(replace(first.chapters[0], segments=(
                replace(segment, speaker=replace(segment.speaker, status='confirmed', confidence_kind='human')),
            )),))
            index.side_effect = None
            index.return_value = [{"name": "张三", "aliases": [], "evidence_quote": "张三"}]
            recovered = generate_v2_for_book(
                chapters, 1, 1, "openai", "a" * 64, "key", "https://example.test", "deepseek-chat",
                parser_fingerprint="parser-v1", previous=human,
            )
            self.assertEqual(index.call_count, 2)
            self.assertTrue(recovered.registry_complete)
            self.assertEqual(recovered.registry_warnings, ())
            self.assertEqual(recovered.chapters[0].segments[0].speaker, human.chapters[0].segments[0].speaker)

    def test_partial_retry_retains_other_chapter_warnings_and_human_confirmations(self):
        chapters = [("一", "张三说：你好。"), ("二", "张三说：再见。")]
        from audiobook_generator.role_script.v2_generation import upgrade_generated_script
        from audiobook_generator.role_script.models import CharacterEntity
        warning = RegistryWarning(1, 0, 1, 2, '第 1 章人物需复核')
        first = upgrade_generated_script(
            self._generated(1, chapters), chapters, {'char_1': CharacterEntity('张三')},
            parser_fingerprint='parser-v1', model='test', registry_complete=False,
            registry_warnings=(warning,),
        )
        segment = first.chapters[0].segments[0]
        first = replace(first, chapters=(replace(first.chapters[0], segments=(
            replace(segment, speaker=replace(segment.speaker, status='confirmed', confidence_kind='human')),
        )),))
        repeated = upgrade_generated_script(
            self._generated(1, chapters), chapters, dict(first.entities), previous=first,
            parser_fingerprint='parser-v1', model='test', registry_complete=False,
            registry_warnings=(warning,),
        )
        self.assertEqual(repeated.chapters[0].segments[0].speaker.status, 'confirmed')
        with patch("audiobook_generator.role_script.v2_generation.splitter._create_client", return_value=object()), \
             patch("audiobook_generator.role_script.v2_generation._request_character_chunk",
                   return_value=[{"name": "张三", "aliases": [], "evidence_quote": "张三"}]), \
             patch("audiobook_generator.role_script.v2_generation.splitter.split_chapters_with_deepseek",
                   return_value=self._generated(2, chapters)):
            second = generate_v2_for_book(
                chapters, 2, 2, "openai", "a" * 64, "key", "https://example.test", "deepseek-chat",
                parser_fingerprint='parser-v1', previous=first, index_full_book=False,
            )
        self.assertEqual(second.registry_warnings, (warning,))
        self.assertFalse(second.registry_complete)
        self.assertEqual(second.chapters[0], first.chapters[0])


if __name__ == "__main__":
    unittest.main()
