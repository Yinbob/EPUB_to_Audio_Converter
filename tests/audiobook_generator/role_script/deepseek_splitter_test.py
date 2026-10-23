import os
import tempfile
import unittest
from unittest.mock import patch

from audiobook_generator.role_script import deepseek_splitter
from audiobook_generator.role_script.errors import ValidationReport
from audiobook_generator.role_script.normalization import normalize_coverage_text
from audiobook_generator.tts_providers import voice_catalog


BOOK_HASH = "b" * 64


def _payload(*segments):
    return {
        "roles": {
            "narrator": {"display_name": "旁白"},
            "lin": {"display_name": "林黛玉"},
        },
        "segments": list(segments),
    }


class DeepSeekSplitterTest(unittest.TestCase):
    def test_reconcile_preserves_exact_source_when_whitespace_and_nfkc_expand(self):
        source = "甲。\n\u3000乙。"
        roles = {"narrator": {"display_name": "旁白"}}
        segments = deepseek_splitter._reconcile_segments(
            source,
            [
                {"role_id": "narrator", "text": "甲。"},
                {"role_id": "narrator", "text": "乙。"},
            ],
            roles,
        )
        self.assertEqual("".join(segment.text for segment in segments), source)
        self.assertEqual(segments[0].text, "甲。\n\u3000")

    def test_reconcile_skips_blank_placeholder_segments(self):
        source = "甲。\u3000乙。"
        roles = {"narrator": {"display_name": "旁白"}}
        segments = deepseek_splitter._reconcile_segments(
            source,
            [
                {"role_id": "narrator", "text": "甲。"},
                {"role_id": "narrator", "text": "\u3000\n  "},
                {"role_id": "narrator", "text": "乙。"},
            ],
            roles,
        )
        self.assertEqual("".join(segment.text for segment in segments), source)
        self.assertEqual(len(segments), 2)

    def test_reconcile_skips_invisible_format_character_placeholders(self):
        source = "甲。乙。"
        roles = {"narrator": {"display_name": "旁白"}}
        segments = deepseek_splitter._reconcile_segments(
            source,
            [
                {"role_id": "narrator", "text": "甲。"},
                {"role_id": "narrator", "text": "\u200b\ufeff\u00ad\u3000\n"},
                {"role_id": "narrator", "text": "乙。"},
            ],
            roles,
        )
        self.assertEqual("".join(segment.text for segment in segments), source)
        self.assertEqual(len(segments), 2)

    def test_has_visible_text_ignores_unicode_format_characters(self):
        self.assertFalse(deepseek_splitter._has_visible_text("\u200b\ufeff\u00ad\u3000\n"))

    def test_role_voices_are_differentiated_by_gender_and_name(self):
        payload = {
            "roles": {
                "narrator": {"display_name": "旁白", "gender": "unknown"},
                "lin_daiyu": {"display_name": "林黛玉", "gender": "female"},
                "xiao_ming": {"display_name": "小明", "gender": "male"},
            },
            "segments": [{"role_id": "narrator", "text": "正文"}],
        }
        definitions = deepseek_splitter._build_role_definitions(
            "openai",
            {
                role_id: {
                    "display_name": meta["display_name"],
                    "gender": meta.get("gender", ""),
                }
                for role_id, meta in payload["roles"].items()
            },
        )
        self.assertEqual(definitions["narrator"].provider_params["voice"], "mimo_default")
        self.assertEqual(definitions["lin_daiyu"].provider_params["voice"], "茉莉")
        self.assertEqual(definitions["xiao_ming"].provider_params["voice"], "苏打")
        self.assertNotEqual(
            definitions["lin_daiyu"].provider_params["voice"],
            definitions["xiao_ming"].provider_params["voice"],
        )
        self.assertEqual(definitions["lin_daiyu"].gender, "female")
        self.assertEqual(definitions["xiao_ming"].gender, "male")
        self.assertIsNone(definitions["narrator"].gender)
        for definition in definitions.values():
            self.assertNotIn("gender", definition.provider_params)

    def test_gender_inference_ignores_given_name_characters(self):
        # “贾宝玉 / 林黛玉”都含“玉”，旧实现会把两人都判成 female。
        self.assertIsNone(deepseek_splitter._infer_gender("jia_baoyu", "贾宝玉"))
        self.assertIsNone(deepseek_splitter._infer_gender("lin_daiyu", "林黛玉"))
        self.assertIsNone(deepseek_splitter._infer_gender("jia_zheng", "贾政"))
        # 强称谓仍然有效。
        self.assertEqual(deepseek_splitter._infer_gender("wang_furen", "王夫人"), "female")
        self.assertEqual(deepseek_splitter._infer_gender("jia_gongzi", "贾公子"), "male")

    def test_role_voices_follow_model_gender_and_stay_distinct(self):
        for provider, female_prefix, male_prefix, narrator_voice in (
            ("openai", ("茉莉", "冰糖", "Chloe", "Mia"), ("苏打", "白桦", "Dean", "Milo"), "mimo_default"),
            (
                "minimax",
                ("female-yujie", "female-chengshu", "female-shaonv", "female-tianmei"),
                ("male-qn-badao", "male-qn-qingse", "male-qn-daxuesheng", "male-qn-jingying"),
                "male-qn-jingying",
            ),
        ):
            definitions = deepseek_splitter._build_role_definitions(
                provider,
                {
                    "narrator": {"display_name": "旁白", "gender": ""},
                    "jia_baoyu": {"display_name": "贾宝玉", "gender": "male"},
                    "lin_daiyu": {"display_name": "林黛玉", "gender": "female"},
                    "xue_baochai": {"display_name": "薛宝钗", "gender": "female"},
                    "jia_zheng": {"display_name": "贾政", "gender": "male"},
                },
            )
            field = "voice" if provider == "openai" else "voice_id"
            self.assertEqual(definitions["narrator"].provider_params[field], narrator_voice)
            self.assertEqual(definitions["jia_baoyu"].gender, "male")
            self.assertEqual(definitions["lin_daiyu"].gender, "female")
            self.assertIn(definitions["jia_baoyu"].provider_params[field], male_prefix)
            self.assertIn(definitions["jia_zheng"].provider_params[field], male_prefix)
            self.assertIn(definitions["lin_daiyu"].provider_params[field], female_prefix)
            self.assertIn(definitions["xue_baochai"].provider_params[field], female_prefix)
            character_voices = [
                role.provider_params[field]
                for role_id, role in definitions.items()
                if role_id != "narrator"
            ]
            self.assertEqual(len(character_voices), len(set(character_voices)))
            self.assertNotIn(narrator_voice, character_voices)

    def test_unique_but_gender_mismatched_voice_is_repaired(self):
        script = deepseek_splitter.RoleScriptV1(
            schema_version=1,
            provider="openai",
            book_sha256=BOOK_HASH,
            default_pause_after_ms=250,
            roles={
                "narrator": deepseek_splitter.RoleDefinition(
                    display_name="旁白",
                    provider_params={"voice": "mimo_default"},
                ),
                "jia_baoyu": deepseek_splitter.RoleDefinition(
                    display_name="贾宝玉",
                    gender="male",
                    provider_params={"voice": "茉莉"},
                ),
                "wang_furen": deepseek_splitter.RoleDefinition(
                    display_name="王夫人",
                    gender="female",
                    provider_params={"voice": "白桦"},
                ),
            },
            chapters=(),
        )

        upgraded, changed = deepseek_splitter.differentiate_role_voices(script)

        self.assertTrue(changed)
        self.assertIn(
            upgraded.roles["jia_baoyu"].provider_params["voice"],
            ("苏打", "白桦", "Dean", "Milo"),
        )
        self.assertIn(
            upgraded.roles["wang_furen"].provider_params["voice"],
            ("茉莉", "冰糖", "Chloe", "Mia"),
        )
        self.assertNotEqual(
            upgraded.roles["jia_baoyu"].provider_params["voice"],
            upgraded.roles["wang_furen"].provider_params["voice"],
        )

    @patch.object(deepseek_splitter, "_create_client", return_value=object())
    @patch.object(deepseek_splitter, "_request_chunk")
    def test_gender_survives_across_chunks(self, request, _client):
        def fake_request(client, model, chapter_index, title, text, provider, language, narration_context=None):
            if "前半" in text:
                roles = {
                    "narrator": {"display_name": "旁白", "gender": "unknown"},
                    "baoyu": {"display_name": "贾宝玉", "gender": "male"},
                }
            else:
                # 后续 chunk 没有可靠性别时，不能把前面已拿到的 male 覆盖掉。
                roles = {
                    "narrator": {"display_name": "旁白", "gender": "unknown"},
                    "baoyu": {"display_name": "贾宝玉"},
                }
            return {
                "roles": roles,
                "segments": [{"role_id": "narrator", "text": text}],
            }

        request.side_effect = fake_request
        script = deepseek_splitter.split_chapters_with_deepseek(
            [("第一章", "前半" * 150 + "后半" * 150)],
            1,
            1,
            "openai",
            BOOK_HASH,
            "sk-test",
            "https://api.deepseek.com",
            "deepseek-chat",
            chunk_chars=200,
        )

        self.assertGreaterEqual(request.call_count, 2)
        self.assertEqual(script.roles["baoyu"].gender, "male")
        self.assertIn(script.roles["baoyu"].provider_params["voice"], ("苏打", "白桦", "Dean", "Milo"))

    def test_explicit_gender_overrides_name_inference_when_repairing_voices(self):
        script = deepseek_splitter.RoleScriptV1(
            schema_version=1,
            provider="openai",
            book_sha256=BOOK_HASH,
            default_pause_after_ms=250,
            roles={
                "narrator": deepseek_splitter.RoleDefinition(
                    display_name="旁白",
                    provider_params={"voice": "mimo_default"},
                ),
                "female_named_warrior": deepseek_splitter.RoleDefinition(
                    display_name="女将军",
                    gender="male",
                    provider_params={"voice": "mimo_default"},
                ),
            },
            chapters=(),
        )

        upgraded, changed = deepseek_splitter.differentiate_role_voices(script)

        self.assertTrue(changed)
        self.assertEqual(upgraded.roles["female_named_warrior"].gender, "male")
        self.assertEqual(
            upgraded.roles["female_named_warrior"].provider_params["voice"],
            "苏打",
        )

    def test_old_script_with_identical_role_voices_is_upgraded(self):
        script = deepseek_splitter.RoleScriptV1(
            schema_version=1,
            provider="openai",
            book_sha256=BOOK_HASH,
            default_pause_after_ms=250,
            roles={
                "narrator": deepseek_splitter.RoleDefinition(
                    display_name="旁白",
                    provider_params={"voice": "mimo_default"},
                ),
                "lin_daiyu": deepseek_splitter.RoleDefinition(
                    display_name="林黛玉",
                    provider_params={"voice": "mimo_default"},
                ),
                "xiao_ming": deepseek_splitter.RoleDefinition(
                    display_name="小明",
                    provider_params={"voice": "mimo_default"},
                ),
            },
            chapters=(),
        )
        upgraded, changed = deepseek_splitter.differentiate_role_voices(script)
        self.assertTrue(changed)
        self.assertEqual(upgraded.roles["narrator"].provider_params["voice"], "mimo_default")
        self.assertEqual(upgraded.roles["lin_daiyu"].provider_params["voice"], "茉莉")
        self.assertEqual(upgraded.roles["xiao_ming"].provider_params["voice"], "苏打")

    def test_old_script_keeps_existing_distinct_role_voices(self):
        script = deepseek_splitter.RoleScriptV1(
            schema_version=1,
            provider="minimax",
            book_sha256=BOOK_HASH,
            default_pause_after_ms=250,
            roles={
                "narrator": deepseek_splitter.RoleDefinition(
                    display_name="旁白",
                    provider_params={"voice_id": "male-qn-jingying"},
                ),
                "lin_daiyu": deepseek_splitter.RoleDefinition(
                    display_name="林黛玉",
                    provider_params={"voice_id": "female-yujie"},
                ),
                "xiao_ming": deepseek_splitter.RoleDefinition(
                    display_name="小明",
                    provider_params={"voice_id": "male-qn-badao"},
                ),
            },
            chapters=(),
        )
        unchanged, changed = deepseek_splitter.differentiate_role_voices(script)
        self.assertFalse(changed)
        self.assertIs(unchanged, script)

    def test_voice_diversity_repairs_narrator_collision_and_gender_duplicates(self):
        script = deepseek_splitter.RoleScriptV1(
            schema_version=1,
            provider="minimax",
            book_sha256=BOOK_HASH,
            default_pause_after_ms=250,
            roles={
                "narrator": deepseek_splitter.RoleDefinition(
                    display_name="旁白",
                    provider_params={"voice_id": "male-qn-jingying"},
                ),
                "lin_daiyu": deepseek_splitter.RoleDefinition(
                    display_name="林黛玉",
                    provider_params={"voice_id": "female-yujie"},
                ),
                "wang_furen": deepseek_splitter.RoleDefinition(
                    display_name="王夫人",
                    provider_params={"voice_id": "female-yujie"},
                ),
                "chen_ming": deepseek_splitter.RoleDefinition(
                    display_name="陈明",
                    provider_params={"voice_id": "male-qn-jingying"},
                ),
            },
            chapters=(),
        )

        upgraded, changed = deepseek_splitter.differentiate_role_voices(script)

        self.assertTrue(changed)
        self.assertEqual(
            upgraded.roles["narrator"].provider_params["voice_id"],
            "male-qn-jingying",
        )
        character_voices = [
            role.provider_params["voice_id"]
            for role_id, role in upgraded.roles.items()
            if role_id != "narrator"
        ]
        self.assertNotIn("male-qn-jingying", character_voices)
        self.assertEqual(len(character_voices), len(set(character_voices)))
        self.assertTrue(upgraded.roles["lin_daiyu"].provider_params["voice_id"].startswith("female-"))
        self.assertTrue(upgraded.roles["wang_furen"].provider_params["voice_id"].startswith("female-"))
        self.assertTrue(upgraded.roles["chen_ming"].provider_params["voice_id"].startswith("male-"))

    @patch.object(deepseek_splitter, "_create_client", return_value=object())
    @patch.object(deepseek_splitter, "_request_chunk")
    def test_split_returns_validated_role_script_with_exact_coverage(self, request, _client):
        request.return_value = _payload(
            {"role_id": "narrator", "text": "花园里，"},
            {"role_id": "lin", "text": "“你也来了。”"},
        )
        report = ValidationReport(schema_version=1)
        script = deepseek_splitter.split_chapters_with_deepseek(
            [("第一回", "花园里，“你也来了。”")],
            1,
            1,
            "openai",
            BOOK_HASH,
            "sk-test",
            "https://api.deepseek.com",
            "deepseek-chat",
            report=report,
        )

        self.assertEqual(script.book_sha256, BOOK_HASH)
        self.assertEqual(script.chapters[0].title, "第一回")
        self.assertEqual(
            "".join(segment.text for segment in script.chapters[0].segments),
            "花园里，“你也来了。”",
        )
        self.assertIn("lin", script.roles)
        self.assertEqual(script.roles["lin"].display_name, "林黛玉")
        self.assertIn("voice", script.roles["lin"].provider_params)
        self.assertTrue(report.ok, report.to_dict())

    @patch.object(deepseek_splitter, "_create_client", return_value=object())
    @patch.object(deepseek_splitter, "_request_chunk")
    def test_split_skips_semantically_empty_chunks_before_request(self, request, _client):
        request.return_value = _payload({"role_id": "narrator", "text": "正文"})
        report = ValidationReport(schema_version=1)
        script = deepseek_splitter.split_chapters_with_deepseek(
            [("第一章", " " * 250 + "正文")],
            1,
            1,
            "openai",
            BOOK_HASH,
            "sk-test",
            "https://api.deepseek.com",
            "deepseek-chat",
            report=report,
            chunk_chars=200,
        )
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.args[4], "正文")
        self.assertEqual(script.chapters[0].segments[0].text, "正文")
        self.assertTrue(report.ok, report.to_dict())
        self.assertNotIn("deepseek_chunk_fallback", {item.code for item in report.warnings})

    @patch.object(deepseek_splitter, "_create_client", return_value=object())
    @patch.object(deepseek_splitter, "_request_chunk")
    def test_split_skips_invisible_format_only_chunks_before_request(self, request, _client):
        request.return_value = _payload({"role_id": "narrator", "text": "正文"})
        report = ValidationReport(schema_version=1)
        deepseek_splitter.split_chapters_with_deepseek(
            [("第一章", "\u200b\ufeff\u00ad" * 90 + "正文")],
            1,
            1,
            "openai",
            BOOK_HASH,
            "sk-test",
            "https://api.deepseek.com",
            "deepseek-chat",
            report=report,
            chunk_chars=200,
        )
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.args[4], "正文")
        self.assertNotIn("deepseek_chunk_fallback", {item.code for item in report.warnings})

    def test_role_script_to_dict_exports_gender_without_provider_params(self):
        script = deepseek_splitter.RoleScriptV1(
            schema_version=1,
            provider="openai",
            book_sha256=BOOK_HASH,
            default_pause_after_ms=250,
            roles={
                "lin": deepseek_splitter.RoleDefinition(
                    display_name="林黛玉",
                    gender="female",
                    provider_params={"voice": "茉莉", "speed": 1.0},
                )
            },
            chapters=(),
        )
        payload = deepseek_splitter.role_script_to_dict(script)
        self.assertEqual(payload["roles"]["lin"]["gender"], "female")
        self.assertNotIn("gender", payload["roles"]["lin"]["provider_params"])

    @patch.object(deepseek_splitter, "_create_client", return_value=object())
    @patch.object(deepseek_splitter, "_request_chunk")
    def test_split_rejects_invisible_only_chapter_without_request(self, request, _client):
        with self.assertRaises(deepseek_splitter.DeepSeekSplitError):
            deepseek_splitter.split_chapters_with_deepseek(
                [("第一章", "\u3000\n\t")],
                1,
                1,
                "openai",
                BOOK_HASH,
                "sk-test",
                "https://api.deepseek.com",
                "deepseek-chat",
            )
        request.assert_not_called()

    @patch.object(deepseek_splitter, "_create_client", return_value=object())
    @patch.object(deepseek_splitter, "_request_chunk")
    def test_split_retries_once_before_accepting_exact_result(self, request, _client):
        request.side_effect = [
            _payload({"role_id": "narrator", "text": "错文"}),
            _payload({"role_id": "narrator", "text": "正文"}),
        ]
        report = ValidationReport(schema_version=1)
        script = deepseek_splitter.split_chapters_with_deepseek(
            [("第一章", "正文")],
            1,
            1,
            "minimax",
            BOOK_HASH,
            "sk-test",
            "https://api.deepseek.com",
            "deepseek-chat",
            report=report,
        )
        self.assertEqual(request.call_count, 2)
        self.assertEqual(script.chapters[0].segments[0].text, "正文")
        self.assertNotIn("deepseek_chunk_fallback", {item.code for item in report.warnings})

    @patch.object(deepseek_splitter, "_create_client", return_value=object())
    @patch.object(deepseek_splitter, "_request_chunk")
    def test_split_falls_back_to_narrator_after_two_bad_attempts(self, request, _client):
        request.return_value = _payload({"role_id": "lin", "text": "错文"})
        report = ValidationReport(schema_version=1)
        script = deepseek_splitter.split_chapters_with_deepseek(
            [("第一章", "正文")],
            1,
            1,
            "openai",
            BOOK_HASH,
            "sk-test",
            "https://api.deepseek.com",
            "deepseek-chat",
            report=report,
        )
        self.assertEqual(request.call_count, deepseek_splitter.MAX_ATTEMPTS_PER_CHUNK)
        self.assertEqual(script.chapters[0].segments[0].role_id, "narrator")
        self.assertEqual(script.chapters[0].segments[0].text, "正文")
        self.assertIn("deepseek_chunk_fallback", {item.code for item in report.warnings})

    @patch.object(deepseek_splitter, "_create_client", return_value=object())
    @patch.object(deepseek_splitter, "_request_chunk")
    def test_all_blank_model_segments_do_not_raise_normalized_empty_error(self, request, _client):
        request.return_value = _payload(
            {"role_id": "narrator", "text": " \u3000\n"},
            {"role_id": "lin", "text": "\t\n"},
        )
        report = ValidationReport(schema_version=1)

        script = deepseek_splitter.split_chapters_with_deepseek(
            [("第一章", "正文")],
            1,
            1,
            "openai",
            BOOK_HASH,
            "sk-test",
            "https://api.deepseek.com",
            "deepseek-chat",
            report=report,
        )

        self.assertEqual(script.chapters[0].segments[0].role_id, "narrator")
        self.assertEqual(script.chapters[0].segments[0].text, "正文")
        warning_codes = {item.code for item in report.warnings}
        self.assertIn("deepseek_chunk_fallback", warning_codes)
        self.assertNotIn("规范化后为空", " ".join(item.message for item in report.warnings))

    @patch.object(deepseek_splitter, "_create_client", return_value=object())
    @patch.object(deepseek_splitter, "_request_chunk")
    def test_lenient_salvage_keeps_coverage_and_emits_partial_warning(self, request, _client):
        source = "甲说：你好。乙说：再见。"
        bad_payload = _payload(
            {"role_id": "lin", "text": "甲说：你好。"},
            {"role_id": "xiao", "text": "乙说：错字。"},
        )
        request.side_effect = [bad_payload, bad_payload]
        report = ValidationReport(schema_version=1)

        script = deepseek_splitter.split_chapters_with_deepseek(
            [("第一章", source)],
            1,
            1,
            "openai",
            BOOK_HASH,
            "sk-test",
            "https://api.deepseek.com",
            "deepseek-chat",
            report=report,
        )

        self.assertEqual(
            "".join(segment.text for segment in script.chapters[0].segments),
            source,
        )
        warning_codes = {item.code for item in report.warnings}
        self.assertIn("deepseek_chunk_partial", warning_codes)
        self.assertNotIn("deepseek_chunk_fallback", warning_codes)

    @patch.object(deepseek_splitter, "_create_client", return_value=object())
    @patch.object(deepseek_splitter, "_request_chunk")
    def test_chunk_fallback_never_emits_semantically_empty_segment(self, request, _client):
        """回归用户反馈：`$.chapters[1].chunk_1` 回退 narrator 后不能再报“规范化后为空”。

        构造同时含 BOM、零宽字符、软连字符、全角空格、CRLF 与 NFKC 展开字符的多块章节，
        让第 1 块连续两次无法对齐（整块回退 narrator），验证最终剧本仍逐字覆盖原文，
        且不存在任何“规范化后为空”的 segment，也不会抛出空段错误。
        """
        source = (
            "甲说：“你好。”\u3000\u200b\ufeff\u00ad乙说：“再见。”\r\n"
            "㈱①丙。"
        ) + "正文" * 130 + "\n丁说：“走了。”戊。"
        parts = deepseek_splitter._split_text_chunks(source, 200)
        self.assertGreaterEqual(len(parts), 2, "测试数据应至少切成两块")
        # 第 1 块必须确实带着这些不可见/展开字符，否则这条回归没有意义。
        self.assertIn("\u200b", parts[0])
        self.assertIn("㈱", parts[0])

        calls = {"count": 0}

        def _fake_request(_client, _model, _chapter_index, _title, text, _provider, _language, narration_context=None):
            # 第 1 块（两次尝试）返回完全对不上的文本：严格对齐 + 宽松抢救都会失败，
            # 只能整块回退 narrator。后续块原样返回，走精确对齐路径。
            calls["count"] += 1
            if calls["count"] <= deepseek_splitter.MAX_ATTEMPTS_PER_CHUNK:
                return {
                    "roles": {"narrator": {"display_name": "旁白"}},
                    "segments": [{"role_id": "narrator", "text": "ZZZZZZZZZZZZ"}],
                }
            return {
                "roles": {"narrator": {"display_name": "旁白"}},
                "segments": [{"role_id": "narrator", "text": text}],
            }

        request.side_effect = _fake_request
        report = ValidationReport(schema_version=1)
        script = deepseek_splitter.split_chapters_with_deepseek(
            [("第一章", source)],
            1,
            1,
            "openai",
            BOOK_HASH,
            "sk-test",
            "https://api.deepseek.com",
            "deepseek-chat",
            report=report,
            chunk_chars=200,
        )

        fallback = [item for item in report.warnings if item.code == "deepseek_chunk_fallback"]
        self.assertEqual(len(fallback), 1)
        self.assertEqual(fallback[0].path, "$.chapters[1].chunk_1")

        segments = list(script.chapters[0].segments)
        self.assertTrue(segments)
        for segment in segments:
            self.assertTrue(
                normalize_coverage_text(segment.text),
                f"出现了规范化后为空的 segment：{segment!r}",
            )
        joined = "".join(segment.text for segment in segments)
        self.assertEqual(
            normalize_coverage_text(joined),
            normalize_coverage_text(source),
            "回退后剧本必须仍然逐字覆盖章节正文",
        )
        self.assertTrue(report.ok, report.to_dict())
        self.assertNotIn(
            "规范化后为空",
            " ".join(item.message for item in report.warnings),
        )


    def test_detects_english_and_uses_english_mimo_voices(self):
        source = (
            "Once upon a time, the little prince lived on a small planet. "
            "He met a fox and they talked for a while."
        )
        self.assertEqual(deepseek_splitter.detect_text_language(source), "en")

        definitions = deepseek_splitter._build_role_definitions(
            "openai",
            {
                "narrator": {"display_name": "Narrator", "gender": "unknown"},
                "fox": {"display_name": "Fox", "gender": "female"},
                "little_prince": {"display_name": "The Little Prince", "gender": "male"},
            },
            language="en",
        )

        self.assertEqual(definitions["narrator"].provider_params["voice"], "Milo")
        self.assertEqual(definitions["fox"].provider_params["voice"], "Chloe")
        self.assertEqual(definitions["little_prince"].provider_params["voice"], "Dean")
        for definition in definitions.values():
            instructions = definition.provider_params["instructions"]
            self.assertFalse(deepseek_splitter._CJK_PATTERN.search(instructions))

    def test_old_chinese_voices_are_migrated_for_english_script(self):
        source = (
            "Once upon a time, the little prince lived on a small planet. "
            "He met a fox and they talked for a while."
        )
        script = deepseek_splitter.RoleScriptV1(
            schema_version=1,
            provider="openai",
            book_sha256=BOOK_HASH,
            default_pause_after_ms=250,
            roles={
                "narrator": deepseek_splitter.RoleDefinition(
                    display_name="旁白",
                    provider_params={
                        "voice": "mimo_default",
                        "instructions": "用清晰、平稳、有起伏的中文有声书旁白语气朗读，不要表演化。",
                        "speed": 1.0,
                    },
                ),
                "fox": deepseek_splitter.RoleDefinition(
                    display_name="狐狸",
                    gender="female",
                    provider_params={
                        "voice": "茉莉",
                        "instructions": "以狐狸的身份自然演绎角色对白，保留原作语气。",
                        "speed": 1.0,
                    },
                ),
                "little_prince": deepseek_splitter.RoleDefinition(
                    display_name="小王子",
                    gender="male",
                    provider_params={
                        "voice": "苏打",
                        "instructions": "以小王子的身份自然演绎角色对白，保留原作语气。",
                        "speed": 1.0,
                    },
                ),
            },
            chapters=(
                deepseek_splitter.ChapterScript(
                    chapter_index=1,
                    title="Chapter 1",
                    segments=(
                        deepseek_splitter.SegmentScript(
                            role_id="narrator",
                            text=source,
                        ),
                    ),
                ),
            ),
        )

        upgraded, changed = deepseek_splitter.differentiate_role_voices(script)

        self.assertTrue(changed)
        self.assertEqual(upgraded.roles["narrator"].provider_params["voice"], "Milo")
        self.assertEqual(upgraded.roles["fox"].provider_params["voice"], "Chloe")
        self.assertEqual(
            upgraded.roles["little_prince"].provider_params["voice"], "Dean"
        )
        for role in upgraded.roles.values():
            instructions = role.provider_params["instructions"]
            self.assertFalse(deepseek_splitter._CJK_PATTERN.search(instructions))

    @patch.object(deepseek_splitter, "_create_client", return_value=object())
    @patch.object(deepseek_splitter, "_request_chunk")
    def test_split_detects_english_and_requests_english_voices(self, request, _client):
        source = (
            "Once upon a time, the little prince lived on a small planet. "
            "He met a fox and they talked for a while."
        )
        request.return_value = {
            "roles": {
                "narrator": {"display_name": "Narrator", "gender": "unknown"},
                "fox": {"display_name": "Fox", "gender": "female"},
                "little_prince": {
                    "display_name": "The Little Prince",
                    "gender": "male",
                },
            },
            "segments": [{"role_id": "narrator", "text": source}],
        }
        report = ValidationReport(schema_version=1)

        script = deepseek_splitter.split_chapters_with_deepseek(
            [("Chapter 1", source)],
            1,
            1,
            "openai",
            BOOK_HASH,
            "sk-test",
            "https://api.deepseek.com",
            "deepseek-chat",
            report=report,
        )

        self.assertEqual(request.call_args.args[6], "en")
        self.assertEqual(script.roles["narrator"].provider_params["voice"], "Milo")
        self.assertEqual(script.roles["fox"].provider_params["voice"], "Chloe")
        self.assertEqual(script.roles["little_prince"].provider_params["voice"], "Dean")
        self.assertTrue(report.ok, report.to_dict())

    def test_uploaded_english_catalog_voice_is_preferred_for_english_roles(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(
            os.environ,
            {"TTS_VOICE_CATALOG_PATH": os.path.join(temp_dir, "voices.json")},
        ):
            voice_catalog.save_user_voice_entries(
                (
                    voice_catalog.VoiceCatalogEntry(
                        provider="openai",
                        voice_id="UserNarrator",
                        display_name="User Narrator",
                        language="en",
                        gender="male",
                        recommended=True,
                        tags=("narrator",),
                    ),
                    voice_catalog.VoiceCatalogEntry(
                        provider="openai",
                        voice_id="UserFemale",
                        display_name="User Female",
                        language="en",
                        gender="female",
                    ),
                )
            )

            definitions = deepseek_splitter._build_role_definitions(
                "openai",
                {
                    "narrator": {"display_name": "Narrator", "gender": "unknown"},
                    "fox": {"display_name": "Fox", "gender": "female"},
                },
                language="en",
            )

        self.assertEqual(
            definitions["narrator"].provider_params["voice"], "UserNarrator"
        )
        self.assertEqual(definitions["fox"].provider_params["voice"], "UserFemale")


if __name__ == "__main__":
    unittest.main()
