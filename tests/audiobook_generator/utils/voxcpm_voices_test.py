"""VoxCPM 音色库（预设 + 参考音频缓存）单元测试。"""

import json
import os
import tempfile
import unittest

import numpy as np

from audiobook_generator.utils.voxcpm_voices import (
    VOXCPM_DEFAULT_VOICE_KEY,
    VOXCPM_DEFAULT_VOICE_VALUE,
    VOXCPM_FINGERPRINT_FIELDS,
    VOXCPM_VOICE_PRESETS,
    build_preset_fingerprint,
    cached_preset_audio_path,
    ensure_preset_audio,
    fingerprint_matches,
    get_voxcpm_voice_choices,
    list_user_voice_files,
    read_preset_fingerprint,
    resolve_voxcpm_voice,
    write_preset_audio,
)


class TestVoicePresets(unittest.TestCase):
    def test_six_chinese_presets_exist(self):
        self.assertEqual(len(VOXCPM_VOICE_PRESETS), 6)
        for name in ("沉稳男声", "温柔女声", "青年男声", "知性女声", "新闻播报", "亲切老者"):
            preset = VOXCPM_VOICE_PRESETS[name]
            self.assertTrue(preset["description"])
            self.assertIsInstance(preset["seed"], int)
            self.assertTrue(preset["audition_text"])

    def test_default_voice_is_calm_male_preset(self):
        self.assertEqual(VOXCPM_DEFAULT_VOICE_KEY, "沉稳男声")
        self.assertTrue(VOXCPM_DEFAULT_VOICE_VALUE.startswith("preset:"))


class TestResolveVoice(unittest.TestCase):
    def test_preset_value(self):
        ctx = resolve_voxcpm_voice("preset:沉稳男声")
        self.assertEqual(ctx["kind"], "preset")
        self.assertEqual(ctx["key"], "沉稳男声")
        self.assertEqual(ctx["seed"], VOXCPM_VOICE_PRESETS["沉稳男声"]["seed"])
        self.assertTrue(ctx["description"])
        self.assertTrue(ctx["audition_text"])

    def test_plain_preset_name_also_works(self):
        ctx = resolve_voxcpm_voice("温柔女声")
        self.assertEqual(ctx["kind"], "preset")
        self.assertEqual(ctx["key"], "温柔女声")

    def test_existing_file_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            wav = os.path.join(tmp, "my_voice.wav")
            with open(wav, "w") as f:
                f.write("dummy")
            ctx = resolve_voxcpm_voice(wav, tmp)
            self.assertEqual(ctx["kind"], "file")
            self.assertEqual(ctx["wav_path"], wav)

    def test_voice_dir_file_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            wav = os.path.join(tmp, "朋友.wav")
            with open(wav, "w") as f:
                f.write("dummy")
            ctx = resolve_voxcpm_voice("file:朋友.wav", tmp)
            self.assertEqual(ctx["kind"], "file")
            self.assertEqual(ctx["wav_path"], wav)

    def test_missing_voice_raises(self):
        with self.assertRaises(ValueError):
            resolve_voxcpm_voice("不存在的音色")

    def test_empty_value(self):
        ctx = resolve_voxcpm_voice("")
        self.assertEqual(ctx["kind"], "none")


class TestVoiceChoices(unittest.TestCase):
    def test_choices_include_presets_and_user_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "a.wav"), "w").write("x")
            open(os.path.join(tmp, "b.mp3"), "w").write("x")
            open(os.path.join(tmp, "ignore.txt"), "w").write("x")
            choices = get_voxcpm_voice_choices(tmp)
            values = [v for _, v in choices]
            self.assertIn("preset:沉稳男声", values)
            self.assertIn("file:a.wav", values)
            self.assertIn("file:b.mp3", values)
            self.assertNotIn("file:ignore.txt", values)

    def test_list_user_voice_files_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(list_user_voice_files(tmp), [])


class TestFingerprintAndCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.voice_dir = self.tmp.name
        self.model_id = "openbmb/VoxCPM2"
        self.cfg = 2.0
        self.steps = 10

    def test_build_and_read_fingerprint_roundtrip(self):
        fp = build_preset_fingerprint("沉稳男声", self.model_id, self.cfg, self.steps)
        self.assertEqual(set(VOXCPM_FINGERPRINT_FIELDS), set(fp.keys()))
        path = os.path.join(self.voice_dir, "preset_沉稳男声.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(fp, f, ensure_ascii=False)
        self.assertEqual(read_preset_fingerprint("沉稳男声", self.voice_dir), fp)
        self.assertTrue(
            fingerprint_matches("沉稳男声", self.model_id, self.cfg, self.steps, self.voice_dir)
        )

    def test_fingerprint_mismatch_when_parameters_change(self):
        fp = build_preset_fingerprint("沉稳男声", self.model_id, self.cfg, self.steps)
        path = os.path.join(self.voice_dir, "preset_沉稳男声.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(fp, f, ensure_ascii=False)
        self.assertFalse(
            fingerprint_matches("沉稳男声", "other/model", self.cfg, self.steps, self.voice_dir)
        )
        self.assertFalse(
            fingerprint_matches("沉稳男声", self.model_id, 3.0, self.steps, self.voice_dir)
        )

    def _write_cache(self, preset_key="沉稳男声"):
        wav = np.zeros(48000, dtype="float32")  # 1 秒静音
        fp = build_preset_fingerprint(preset_key, self.model_id, self.cfg, self.steps)
        return write_preset_audio(preset_key, self.voice_dir, wav, 48000, fp)

    def test_write_preset_audio_atomic_and_readable(self):
        wav_path = self._write_cache()
        self.assertTrue(os.path.exists(wav_path))
        self.assertTrue(os.path.exists(os.path.join(self.voice_dir, "preset_沉稳男声.json")))
        self.assertEqual(cached_preset_audio_path("沉稳男声", self.voice_dir), wav_path)

    def test_ensure_preset_audio_generates_once_and_reuses_cache(self):
        calls = []

        def generator(text, seed):
            calls.append((text, seed))
            return np.zeros(48000, dtype="float32"), 48000

        path1 = ensure_preset_audio(
            "沉稳男声", self.voice_dir, self.model_id, self.cfg, self.steps, generator
        )
        self.assertEqual(len(calls), 1)
        self.assertIn(VOXCPM_VOICE_PRESETS["沉稳男声"]["audition_text"], calls[0][0])
        self.assertEqual(calls[0][1], VOXCPM_VOICE_PRESETS["沉稳男声"]["seed"])

        # 第二次：指纹匹配，不再调用 generator
        path2 = ensure_preset_audio(
            "沉稳男声", self.voice_dir, self.model_id, self.cfg, self.steps, generator
        )
        self.assertEqual(path1, path2)
        self.assertEqual(len(calls), 1)

    def test_ensure_preset_audio_regenerates_when_requested(self):
        calls = []

        def generator(text, seed):
            calls.append(seed)
            return np.zeros(48000, dtype="float32"), 48000

        ensure_preset_audio(
            "温柔女声", self.voice_dir, self.model_id, self.cfg, self.steps, generator
        )
        ensure_preset_audio(
            "温柔女声", self.voice_dir, self.model_id, self.cfg, self.steps,
            generator, regenerate=True
        )
        self.assertEqual(len(calls), 2)

    def test_ensure_preset_audio_regenerates_on_fingerprint_drift(self):
        calls = []

        def generator(text, seed):
            calls.append(seed)
            return np.zeros(48000, dtype="float32"), 48000

        ensure_preset_audio(
            "知性女声", self.voice_dir, self.model_id, self.cfg, self.steps, generator
        )
        # 换模型名 → 指纹不匹配 → 重新生成
        ensure_preset_audio(
            "知性女声", self.voice_dir, "local/model", self.cfg, self.steps, generator
        )
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
