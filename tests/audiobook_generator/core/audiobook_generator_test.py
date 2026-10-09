import hashlib
import os
import pickle
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from audiobook_generator.config.general_config import GeneralConfig
from audiobook_generator.core.audiobook_generator import AudiobookGenerator
from audiobook_generator.role_script.models import (
    ChapterScript,
    ChapterSynthesisPlan,
    RoleDefinition,
    RoleScriptV1,
    SegmentScript,
    SynthesisUnit,
    VoiceProfile,
)
from audiobook_generator.role_script.planner import build_synthesis_plans


def _script(book_sha256):
    return RoleScriptV1(
        schema_version=1,
        provider="openai",
        book_sha256=book_sha256,
        default_pause_after_ms=250,
        roles={
            "narrator": RoleDefinition(
                "旁白", {"voice": "冰糖", "speed": 1.0}
            )
        },
        chapters=(
            ChapterScript(
                1,
                "第一章",
                (
                    SegmentScript("narrator", "第一段"),
                    SegmentScript("narrator", "第二段"),
                ),
            ),
        ),
    )


class _FakeBookParser:
    def get_chapters(self, break_string):
        return [("第一章", "第一段第二段")]

    def get_book_author(self):
        return "作者"

    def get_book_title(self):
        return "书名"


class _FakeProvider:
    provider_id = "openai"

    def __init__(self, fail=False):
        self.fail = fail
        self.progress = []

    def get_output_file_extension(self):
        return "wav"

    def synthesize_segment(self, text, profile, work_dir, progress):
        progress(f"role_segment_chunk_1_of_1")
        if self.fail:
            raise RuntimeError("boom")
        path = os.path.join(work_dir, f"{profile.role_id}-{len(text)}.wav")
        Path(path).write_bytes(b"fake")
        from audiobook_generator.role_script.models import AudioArtifact

        return AudioArtifact(path, "wav", 24000, 1, 100, "sha", "cache")


class TestRoleScriptCoreOrchestration(unittest.TestCase):
    def _config(self, root, *, preview=True, tts="openai"):
        input_path = os.path.join(root, "book.epub")
        Path(input_path).write_bytes(b"book bytes")
        content_hash = hashlib.sha256(b"book bytes").hexdigest()
        config = GeneralConfig(None)
        config.input_file = input_path
        config.output_folder = os.path.join(root, "out")
        config.preview = preview
        config.output_text = False
        config.tts = tts
        config.output_format = "wav"
        config.role_script = _script(content_hash)
        config.allow_role_text_override = False
        config.allow_role_title_mismatch = False
        config.allow_role_fallback = False
        config.use_pydub_merge = False
        config.worker_count = 1
        config.chapter_start = 1
        config.chapter_end = -1
        config.no_prompt = True
        config.log = "INFO"
        config.log_file = os.path.join(root, "test.log")
        return config

    def test_plan_is_pickle_safe_for_spawn(self):
        content_hash = hashlib.sha256(b"book bytes").hexdigest()
        result = build_synthesis_plans(
            _script(content_hash),
            [("第一章", "第一段第二段")],
            expected_book_sha256=content_hash,
            provider="openai",
            chapter_start=1,
            chapter_end=1,
            output_format="wav",
        )
        self.assertTrue(result.ok, result.report.to_dict())
        restored = pickle.loads(pickle.dumps(result.plans[0]))
        self.assertIsInstance(restored, ChapterSynthesisPlan)
        self.assertEqual(restored.segment_count, 2)
        self.assertEqual(restored.units[0].text, "第一段")

    def test_role_preview_does_not_create_provider(self):
        with tempfile.TemporaryDirectory() as root:
            config = self._config(root, preview=True)
            with patch(
                "audiobook_generator.core.audiobook_generator.get_book_parser",
                return_value=_FakeBookParser(),
            ), patch(
                "audiobook_generator.core.audiobook_generator.get_tts_provider",
                side_effect=AssertionError("preview 不应创建 Provider"),
            ), patch(
                "audiobook_generator.core.audiobook_generator.logger.exception"
            ) as logged_exception:
                AudiobookGenerator(config).run()
        logged_exception.assert_not_called()

    def test_provider_mismatch_is_structured(self):
        with tempfile.TemporaryDirectory() as root:
            config = self._config(root, preview=True, tts="edge")
            generator = AudiobookGenerator(config)
            with self.assertRaisesRegex(ValueError, "只支持 MiMo"):
                generator._validate_role_plans(
                    [("第一章", "第一段第二段")],
                    chapter_start=1,
                    chapter_end=1,
                )

    def test_process_role_chapter_calls_segments_in_order_and_cleans_up(self):
        with tempfile.TemporaryDirectory() as root:
            config = self._config(root, preview=False)
            generator = AudiobookGenerator(config)
            content_hash = hashlib.sha256(b"book bytes").hexdigest()
            plan = build_synthesis_plans(
                _script(content_hash),
                [("第一章", "第一段第二段")],
                expected_book_sha256=content_hash,
                provider="openai",
                chapter_start=1,
                chapter_end=1,
                output_format="wav",
            ).plans[0]
            provider = _FakeProvider()
            with patch(
                "audiobook_generator.core.audiobook_generator.get_tts_provider",
                return_value=provider,
            ), patch(
                "audiobook_generator.role_script.audio_pipeline.assemble_chapter_audio"
            ) as assemble:
                index, ok = generator.process_role_chapter(plan, "作者", "书名")
            self.assertTrue(ok)
            self.assertEqual(index, 1)
            self.assertIs(assemble.call_args.args[0], plan)
            self.assertEqual(len(assemble.call_args.args[1]), 2)
            work_dir = assemble.call_args.args[4]
            self.assertFalse(os.path.exists(work_dir))

    def test_process_role_chapter_cleans_up_on_failure(self):
        with tempfile.TemporaryDirectory() as root:
            config = self._config(root, preview=False)
            generator = AudiobookGenerator(config)
            unit = SynthesisUnit(
                unit_id="1:1:narrator",
                chapter_index=1,
                chapter_title="第一章",
                segment_index=1,
                segment_count=1,
                role_id="narrator",
                display_name="旁白",
                text="文本",
                profile=VoiceProfile("narrator", "旁白", {"voice": "冰糖"}),
                pause_after_ms=0,
            )
            plan = ChapterSynthesisPlan(1, "第一章", (unit,), "wav", "openai")
            with patch(
                "audiobook_generator.core.audiobook_generator.get_tts_provider",
                return_value=_FakeProvider(fail=True),
            ):
                index, ok = generator.process_role_chapter(plan, "作者", "书名")
            self.assertFalse(ok)
            self.assertEqual(index, 1)
            self.assertFalse(
                os.path.exists(os.path.join(config.output_folder, ".role_tmp", "chapter_000001"))
            )


    def test_english_script_localizes_old_chinese_voices_in_plans(self):
        source = (
            "Once upon a time, the little prince lived on a small planet. "
            "He met a fox and they talked for a while."
        )
        content_hash = hashlib.sha256(b"book bytes").hexdigest()
        script = RoleScriptV1(
            schema_version=1,
            provider="openai",
            book_sha256=content_hash,
            default_pause_after_ms=250,
            roles={
                "narrator": RoleDefinition(
                    "旁白",
                    {
                        "voice": "mimo_default",
                        "instructions": "用清晰、平稳的中文有声书旁白语气朗读。",
                        "speed": 1.0,
                    },
                ),
                "fox": RoleDefinition(
                    "狐狸",
                    {
                        "voice": "茉莉",
                        "instructions": "以狐狸的身份自然演绎角色对白。",
                        "speed": 1.0,
                    },
                    gender="female",
                ),
                "little_prince": RoleDefinition(
                    "小王子",
                    {
                        "voice": "苏打",
                        "instructions": "以小王子身份自然演绎角色对白。",
                        "speed": 1.0,
                    },
                    gender="male",
                ),
            },
            chapters=(
                ChapterScript(
                    1,
                    "Chapter 1",
                    (
                        SegmentScript("narrator", source),
                        SegmentScript("fox", "Hello."),
                        SegmentScript("little_prince", "Hello."),
                    ),
                ),
            ),
        )

        result = build_synthesis_plans(
            script,
            [("Chapter 1", source + "Hello.Hello.")],
            expected_book_sha256=content_hash,
            provider="openai",
            chapter_start=1,
            chapter_end=1,
            output_format="wav",
            allow_text_override=True,
        )

        self.assertTrue(result.ok, result.report.to_dict())
        voices = {
            unit.role_id: unit.profile.provider_params["voice"]
            for unit in result.plans[0].units
        }
        self.assertEqual(voices["narrator"], "Milo")
        self.assertEqual(voices["fox"], "Chloe")
        self.assertEqual(voices["little_prince"], "Dean")
        self.assertIn(
            "role_voice_localized",
            {warning.code for warning in result.report.warnings},
        )


if __name__ == "__main__":
    unittest.main()
