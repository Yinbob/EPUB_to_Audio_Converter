import unittest
from dataclasses import replace

from audiobook_generator.role_script.models import (
    CharacterEntity, RoleDefinition, SpeakerDecision,
)
from audiobook_generator.role_script.review import (
    assign_chapter_narrator, confirm_segment_speaker, lock_entity_voice, merge_entities, pending_segments,
)
from tests.audiobook_generator.role_script.v2_io_test import _script


class ReviewTest(unittest.TestCase):
    def test_chapter_narrator_changes_only_identified_narration_and_can_be_reassigned(self):
        script, _ = _script()
        chapter = script.chapters[0]
        first = replace(chapter, segments=(replace(chapter.segments[0], text_kind='narration'),
                                         replace(chapter.segments[1], text_kind='dialogue')))
        other = replace(first, chapter_index=2)
        script = replace(script, chapters=(first, other))
        updated, count = assign_chapter_narrator(script, 1, 'char_1')
        self.assertEqual(count, 1)
        self.assertEqual(updated.chapters[0].segments[0].role_id, 'char_1')
        self.assertEqual(updated.chapters[0].segments[0].speaker.confidence_kind, 'human')
        self.assertEqual(updated.chapters[0].segments[1], first.segments[1])
        self.assertEqual(updated.chapters[1], other)
        self.assertEqual(updated.roles, script.roles)
        self.assertEqual([(s.text, s.source_span, s.segment_id) for s in updated.chapters[0].segments],
                         [(s.text, s.source_span, s.segment_id) for s in first.segments])
        reassigned, _ = assign_chapter_narrator(updated, 1, 'narrator')
        self.assertEqual(reassigned.chapters[0].segments[0].role_id, 'narrator')
        self.assertEqual(script.chapters[0], first)

    def test_narrator_assignment_rejects_legacy_chapters_and_invalid_targets(self):
        script, _ = _script()
        for chapter, entity in [(1, 'char_1'), (2, 'char_1'), (True, 'char_1'), (1, 'missing')]:
            with self.assertRaises(ValueError):
                assign_chapter_narrator(script, chapter, entity)

    def test_confirm_segment_and_voice_lock(self):
        script, _ = _script()
        self.assertEqual(len(pending_segments(script)), 1)
        updated = confirm_segment_speaker(script, "ch1_s2", "char_1")
        speaker = updated.chapters[0].segments[1].speaker
        self.assertEqual(speaker.status, "confirmed")
        self.assertEqual(speaker.confidence_kind, "human")
        self.assertIsNone(speaker.confidence)
        self.assertEqual(len(pending_segments(updated)), 0)
        self.assertTrue(lock_entity_voice(updated, "char_1").entities["char_1"].voice_locked)
        with self.assertRaisesRegex(ValueError, "找不到"):
            confirm_segment_speaker(script, "missing", "char_1")

    def test_merge_alias_updates_segments_without_changing_target_voice(self):
        script, _ = _script()
        source = replace(script.entities["char_1"], voice_locked=False)
        entities = dict(script.entities)
        entities["char_1"] = source
        entities["char_2"] = CharacterEntity("黛玉", voice_profile_id="voice_2")
        roles = dict(script.roles)
        roles["char_2"] = RoleDefinition("黛玉", {"voice": "冰糖", "speed": 1.0})
        chapter = script.chapters[0]
        segments = list(chapter.segments)
        segments[1] = replace(segments[1], role_id="char_2",
                              speaker=SpeakerDecision("char_2", "proposed", 0.5))
        modified = replace(script, entities=entities, roles=roles,
                           chapters=(replace(chapter, segments=tuple(segments)),))
        merged = merge_entities(modified, "char_2", "char_1")
        self.assertNotIn("char_2", merged.entities)
        self.assertEqual(merged.chapters[0].segments[1].role_id, "char_1")
        self.assertEqual(merged.roles["char_1"].provider_params["voice"], "茉莉")


if __name__ == "__main__":
    unittest.main()
