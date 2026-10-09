import unittest

from audiobook_generator.role_script.models import (
    ChapterScript,
    RoleDefinition,
    RoleScriptV1,
    SegmentScript,
)
from audiobook_generator.role_script.planner import build_synthesis_plans
from audiobook_generator.role_script.validator import validate_role_script


BOOK_HASH = "a" * 64


def script(*, chapters=None, roles=None, provider="openai", pause=250):
    return RoleScriptV1(
        schema_version=1,
        provider=provider,
        book_sha256=BOOK_HASH,
        default_pause_after_ms=pause,
        roles=roles
        or {"narrator": RoleDefinition("旁白", {"voice": "冰糖", "speed": 1.0})},
        chapters=chapters
        or (
            ChapterScript(
                1,
                "第一章",
                (SegmentScript("narrator", "正文"),),
            ),
        ),
    )


class RoleScriptValidatorTest(unittest.TestCase):
    def test_valid_script(self):
        result = validate_role_script(
            script(), expected_book_sha256=BOOK_HASH, chapters=[("第一章", "正文")]
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.script.chapters[0].segments[0].text, "正文")

    def test_array_path_uses_position_not_chapter_index(self):
        result = validate_role_script(
            script(
                chapters=(
                    ChapterScript(3, "第三章", (SegmentScript("narrator", "正文"),)),
                )
            ),
            expected_book_sha256=BOOK_HASH,
            chapters=[("第一章", "正文"), ("第二章", "正文"), ("错误标题", "正文")],
        )
        self.assertFalse(result.ok)
        errors = {item.code: item.path for item in result.report.errors}
        self.assertIn("missing_chapter", errors)
        self.assertEqual(errors["title_mismatch"], "$.chapters[0].title")

    def test_provider_param_whitelist_and_ranges(self):
        bad_roles = {
            "narrator": RoleDefinition(
                "旁白", {"voice": "冰糖", "speed": 4.5, "pitch": 1}
            )
        }
        result = validate_role_script(script(roles=bad_roles))
        codes = [item.code for item in result.report.errors]
        self.assertIn("unknown_provider_param", codes)
        self.assertIn("provider_param_out_of_range", codes)

    def test_gender_is_normalized_and_invalid_value_is_reported(self):
        roles = {
            "narrator": RoleDefinition(
                "旁白",
                {"voice": "冰糖", "speed": 1.0},
                gender="男",
            )
        }
        result = validate_role_script(script(roles=roles))
        self.assertTrue(result.ok, result.report.to_dict())
        self.assertEqual(result.script.roles["narrator"].gender, "male")

        invalid = validate_role_script(
            script(
                roles={
                    "narrator": RoleDefinition(
                        "旁白",
                        {"voice": "冰糖", "speed": 1.0},
                        gender="robot",
                    )
                }
            )
        )
        self.assertFalse(invalid.ok)
        self.assertEqual(invalid.report.errors[0].code, "invalid_role_gender")
        self.assertEqual(invalid.report.errors[0].path, "$.roles.narrator.gender")

    def test_missing_role_and_fallback(self):
        chapters = (
            ChapterScript(1, "第一章", (SegmentScript("guest", "正文"),)),
        )
        missing = validate_role_script(
            script(chapters=chapters), chapters=[("第一章", "正文")]
        )
        self.assertIn("missing_role", [item.code for item in missing.report.errors])

        fallback = validate_role_script(
            script(chapters=chapters),
            chapters=[("第一章", "正文")],
            allow_fallback=True,
            fallback_profile={"voice": "冰糖", "speed": 1.0},
        )
        self.assertTrue(fallback.ok)
        self.assertIn("role_fallback", [item.code for item in fallback.report.warnings])

    def test_title_and_coverage_overrides(self):
        chapters = (ChapterScript(1, "标题错误", (SegmentScript("narrator", "错文"),)),)
        result = validate_role_script(
            script(chapters=chapters),
            chapters=[("正确标题", "正文")],
            allow_title_mismatch=True,
            allow_text_override=True,
        )
        self.assertTrue(result.ok)
        warning_codes = {item.code for item in result.report.warnings}
        self.assertIn("title_mismatch_override", warning_codes)
        self.assertIn("text_override", warning_codes)

    def test_missing_role_falls_back_to_narrator_first(self):
        chapters = (
            ChapterScript(1, "第一章", (SegmentScript("guest", "正文"),)),
        )
        result = build_synthesis_plans(
            script(chapters=chapters),
            [("第一章", "正文")],
            expected_book_sha256=BOOK_HASH,
            provider="openai",
            chapter_start=1,
            chapter_end=1,
            output_format="mp3",
            allow_fallback=True,
            fallback_profile={"voice": "全局音色", "speed": 1.0},
        )
        self.assertTrue(result.ok, result.report.to_dict())
        profile = result.plans[0].units[0].profile
        self.assertEqual(profile.role_id, "guest")
        self.assertEqual(profile.display_name, "旁白")
        self.assertEqual(profile.provider_params["voice"], "冰糖")

    def test_missing_narrator_falls_back_to_global_profile(self):
        chapters = (
            ChapterScript(1, "第一章", (SegmentScript("guest", "正文"),)),
        )
        roles = {"other": RoleDefinition("其他", {"voice": "苏打", "speed": 1.0})}
        result = build_synthesis_plans(
            script(chapters=chapters, roles=roles),
            [("第一章", "正文")],
            expected_book_sha256=BOOK_HASH,
            provider="openai",
            chapter_start=1,
            chapter_end=1,
            output_format="mp3",
            allow_fallback=True,
            fallback_profile={"voice": "全局音色", "speed": 1.0},
        )
        self.assertTrue(result.ok, result.report.to_dict())
        profile = result.plans[0].units[0].profile
        self.assertEqual(profile.role_id, "guest")
        self.assertEqual(profile.display_name, "全局默认音色")
        self.assertEqual(profile.provider_params["voice"], "全局音色")


if __name__ == "__main__":
    unittest.main()
