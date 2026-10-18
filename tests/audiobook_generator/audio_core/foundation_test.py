import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import soundfile as sf

from audiobook_generator.audio_core.models import ResourceLimits
from audiobook_generator.audio_core.reading import build_reading_plan, comparison_text, normalize_reading_text
from audiobook_generator.audio_core.store import ArtifactStore, ResourceExhausted
from audiobook_generator.role_script.models import SynthesisUnit, VoiceProfile


class FoundationTest(unittest.TestCase):
    def test_structural_whitespace_does_not_remove_short_speech_or_punctuation(self):
        from dataclasses import replace
        from audiobook_generator.audio_core.reading import nonspoken_source_units
        profile = VoiceProfile("narrator", "旁白", {"voice": "冰糖"})
        base = SynthesisUnit("1:1", 1, "章", 1, 1, "narrator", "旁白", " ", profile)
        units = [replace(base, unit_id=str(i), text=text) for i, text in enumerate((" ", "I", "!", "\n\t", "嗯"))]
        self.assertEqual([c.tts_text for c in build_reading_plan(units)], ["I", "!", "嗯"])
        self.assertEqual([u["source_text"] for u in nonspoken_source_units(units)], [" ", "\n\t"])

    def test_reading_normalization_keeps_mapping_and_ambiguous_identifiers(self):
        text = "在2026年10月15日，增长3.5%，编号0012，版本v2.1。"
        spoken, mapping, edits = normalize_reading_text(text)
        self.assertEqual(spoken, "在二零二六年十月十五日，增长百分之三点五，编号0012，版本v2.1。")
        self.assertEqual(len(mapping), len(spoken))
        self.assertEqual(len(edits), 2)
        self.assertEqual(comparison_text("增长3.5%"), comparison_text("增长百分之三点五"))
        for edit in edits:
            self.assertEqual(text[edit["source_start"]:edit["source_end"]], edit["before"])

    def test_chunk_plan_has_exact_spoken_coverage_and_role_boundaries(self):
        source = "今天是2026年。" * 12
        profile = VoiceProfile("narrator", "旁白", {"voice": "冰糖"})
        unit = SynthesisUnit("1:1", 1, "章节", 1, 1, "narrator", "旁白", source, profile, pause_after_ms=300)
        chunks = build_reading_plan([unit], chunk_chars=30)
        self.assertGreater(len(chunks), 1)
        self.assertEqual("".join(c.tts_text for c in chunks), normalize_reading_text(source)[0])
        self.assertEqual("".join(c.source_text for c in chunks), source)
        self.assertEqual(chunks[-1].pause_after_ms, 300)
        self.assertTrue(all(c.pause_after_ms == 0 for c in chunks[:-1]))

    def test_invalid_calendar_date_is_not_rewritten(self):
        text = "日期2026年2月31日，增长3%。"
        spoken, mapping, edits = normalize_reading_text(text)
        self.assertEqual(spoken, "日期2026年2月31日，增长百分之三。")
        self.assertEqual(len(mapping), len(spoken))
        self.assertEqual([e["kind"] for e in edits], ["percentage"])

    def test_ambiguous_scientific_and_thousands_percentages_are_preserved(self):
        for text in ("误差1e-3%。", "增长1,000%。", "数值-3.5%。", "数值3.123456%。"):
            with self.subTest(text=text):
                self.assertEqual(normalize_reading_text(text)[0], text)

    def test_quantity_decimals_require_explicit_units_and_keep_source_mapping(self):
        text = "重量3.50千克，长度0.08米，温度20.5摄氏度，金额12.30元。编号3.5，版本v3.5。"
        spoken, mapping, edits = normalize_reading_text(text)
        self.assertEqual(spoken, "重量三点五零千克，长度零点零八米，温度二十点五摄氏度，金额十二点三零元。编号3.5，版本v3.5。")
        self.assertEqual(len(mapping), len(spoken))
        self.assertTrue(all(e["kind"] == "quantity_decimal" for e in edits))
        self.assertEqual([e["unit"] for e in edits], ["千克", "米", "摄氏度", "元"])
        for e in edits:
            self.assertEqual(text[e["source_start"]:e["source_end"]], e["before"])
            self.assertEqual(spoken[e["tts_start"]:e["tts_end"]], e["after"])
            self.assertTrue(all(span == (e["source_start"], e["source_end"])
                                for span in mapping[e["tts_start"]:e["tts_end"]]))
        for ambiguous in ("型号v3.5米", "数值1e3.5米", "重量1,003.5千克", "长度-3.5米",
                          "重量0003.5千克", "精度3.123456米", "重量10000.5千克", "长3.5m"):
            self.assertEqual(normalize_reading_text(ambiguous)[0], ambiguous)

    def test_explicit_dictionary_is_longest_first_nonrecursive_and_token_bounded(self):
        dictionary = {"API": "诶劈爱", "API接口": "应用接口", "GHz": "吉赫兹"}
        spoken, mapping, edits = normalize_reading_text("API接口用API，频率3.5GHz；RAPID和API2保持。", dictionary=dictionary)
        self.assertEqual(spoken, "应用接口用诶劈爱，频率3.5GHz；RAPID和API2保持。")
        self.assertEqual(len(mapping), len(spoken))
        self.assertTrue(all(e["confirmation"] == "user_configured" for e in edits))
        self.assertEqual(comparison_text("API接口用API", dictionary=dictionary),
                         comparison_text("应用接口用诶劈爱", dictionary=dictionary))

    def test_dictionary_rejects_empty_control_and_cascading_readings(self):
        from audiobook_generator.audio_core.reading import validate_reading_dictionary
        for value in ({"": "空"}, {"API": ""}, {"API": "<say-as>接口</say-as>"}, {"API": "[pause]"},
                      {"API": "接口\n正文"}, {"API": 123}, {"A": "B", "B": "C"}, {"AI": "AI 接口"}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_reading_dictionary(value)
        self.assertEqual(validate_reading_dictionary({"原样": "原样"}), {})

    def test_dictionary_chunks_cover_original_without_splitting_replacement(self):
        source = "先说明API。" * 10 + "重量3.5千克。"
        dictionary = {"API": "应用程序编程接口"}
        profile = VoiceProfile("narrator", "旁白", {"voice": "冰糖"})
        unit = SynthesisUnit("1:1", 1, "章节", 1, 1, "narrator", "旁白", source, profile)
        chunks = build_reading_plan([unit], chunk_chars=20, dictionary=dictionary)
        self.assertEqual("".join(c.source_text for c in chunks), source)
        self.assertEqual("".join(c.tts_text for c in chunks), normalize_reading_text(source, dictionary=dictionary)[0])
        self.assertEqual(sum(c.tts_text.count("应用程序编程接口") for c in chunks), 10)

    def test_dictionary_config_accepts_explicit_file_and_rejects_control_text(self):
        import json
        from audiobook_generator.audio_core.models import CoreOptions
        from audiobook_generator.config.general_config import GeneralConfig
        with tempfile.TemporaryDirectory() as root:
            dictionary = Path(root) / "readings.json"
            dictionary.write_text(json.dumps({"API": "应用接口"}))
            config = GeneralConfig(None)
            config.audio_core_reading_dictionary = str(dictionary)
            self.assertEqual(CoreOptions.from_config(config).reading_dictionary, {"API": "应用接口"})
            dictionary.write_text(json.dumps({"API": "<break/>"}))
            with self.assertRaises(ValueError):
                CoreOptions.from_config(config)

    def test_rejected_samples_do_not_replace_selected_cache(self):
        with tempfile.TemporaryDirectory() as root:
            store = ArtifactStore(root)
            original = store.save_sample("key", b"original", "wav")
            rejected = store.save_sample("key", b"rejected", "wav")
            self.assertEqual(store.cached("key"), original)
            accepted = store.save_sample("key", b"accepted", "wav")
            store.select_sample(accepted)
            store.save_sample("key", b"another rejected", "wav")
            self.assertEqual(ArtifactStore(root).cached("key"), accepted)
            Path(accepted).write_bytes(b"broken")
            self.assertEqual(store.cached("key"), original)
            self.assertNotEqual(store.cached("key"), rejected)

    def test_limits_are_transactional_and_failed_requests_still_count(self):
        with tempfile.TemporaryDirectory() as root:
            store = ArtifactStore(root)
            run = store.start_run(ResourceLimits(max_requests=2, max_repair_requests=1))
            first = store.reserve(run, "a", 5)
            store.settle(first, error=TimeoutError())
            store.reserve(run, "b", 5, repair=True)
            with self.assertRaises(ResourceExhausted):
                store.reserve(run, "c", 5)
            restored = ArtifactStore(root)
            self.assertEqual(restored.summary(run)["failed"]["requests"], 1)
            self.assertEqual(restored.summary(run)["running"]["repair_requests"], 1)

    def test_content_addressed_cache_survives_reopen_and_rejects_corruption(self):
        with tempfile.TemporaryDirectory() as root:
            store = ArtifactStore(root)
            path = store.save_sample("abc", b"original", "wav")
            self.assertEqual(ArtifactStore(root).cached("abc"), path)
            Path(path).write_bytes(b"damaged")
            self.assertIsNone(store.cached("abc"))

    def test_observed_mimo_reuses_or_resamples_without_sdk_retries(self):
        from audiobook_generator.tts_providers.openai_tts_provider import OpenAITTSProvider

        provider = object.__new__(OpenAITTSProvider)
        provider.config = SimpleNamespace(model_name="mimo-v2.5-tts", voice_name="冰糖", instructions=None,
                                          language="zh-CN", stream=False, output_format="wav")
        provider.client = MagicMock()
        audio = io.BytesIO()
        sf.write(audio, np.sin(np.arange(1600) * .1) * .1, 16000, format="WAV")
        profile = VoiceProfile("hero", "主角", {"voice": "冰糖"})
        with tempfile.TemporaryDirectory() as root, patch.object(provider, "_request_mimo_chunk", return_value=audio.getvalue()) as request:
            store = ArtifactStore(root)
            run = store.start_run(ResourceLimits(max_requests=2))
            first = provider.synthesize_observed_chunk("你好。", profile, store, run)
            self.assertEqual(first, provider.synthesize_observed_chunk("你好。", profile, store, run))
            second = provider.synthesize_observed_chunk("你好。", profile, store, run, resample=True, repair=True)
            self.assertNotEqual(first, second)
            self.assertEqual(request.call_count, 2)
            self.assertEqual(provider.client.with_options.call_args.kwargs["max_retries"], 0)
            self.assertEqual(store.summary(run)["succeeded"]["requests"], 2)


if __name__ == "__main__":
    unittest.main()
