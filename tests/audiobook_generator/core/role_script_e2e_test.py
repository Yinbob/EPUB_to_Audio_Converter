"""角色模式端到端 mock 验收。

测试用真实 WAV + 真实 ffmpeg 音频管线跑通 ``AudiobookGenerator.run()``；
进程池替换为同进程串行池，但每个任务仍经过 pickle round-trip，以覆盖跨进程边界。
"""
import hashlib
import os
import pickle
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from audiobook_generator.config.general_config import GeneralConfig
from audiobook_generator.core.audiobook_generator import AudiobookGenerator
from audiobook_generator.role_script.models import (
    ChapterScript,
    RoleDefinition,
    RoleScriptV1,
    SegmentScript,
)
from audiobook_generator.role_script.audio_pipeline import build_audio_artifact


class _SerialPool:
    """兼容 Pool 上下文协议的同进程测试池。"""

    def __init__(self, processes=None, initializer=None, initargs=()):
        if initializer is not None:
            initializer(*initargs)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def imap_unordered(self, func, tasks):
        for task in tasks:
            # spawn 会 pickle 任务；这里做同样检查后再执行。
            yield func(pickle.loads(pickle.dumps(task)))


class _SerialContext:
    def Pool(self, processes=None, initializer=None, initargs=()):
        return _SerialPool(processes, initializer, initargs)


class _FakeBookParser:
    def __init__(self, chapters):
        self._chapters = chapters

    def get_chapters(self, break_string):
        return list(self._chapters)

    def get_book_author(self):
        return "测试作者"

    def get_book_title(self):
        return "测试书名"


def _write_constant_wav(path, value=6000, duration_ms=120):
    sample_rate = 16000
    frame_count = max(1, sample_rate * duration_ms // 1000)
    with wave.open(path, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(value.to_bytes(2, "little", signed=True) * frame_count)


class _FakeProvider:
    provider_id = "openai"

    def __init__(self, config):
        self.config = config
        self.segment_calls = []
        self.direct_calls = []

    def get_break_string(self):
        return "   "

    def get_output_file_extension(self):
        return "wav"

    def estimate_cost(self, total_chars):
        return 0.0

    def synthesize_segment(self, text, profile, work_dir, progress=None):
        self.segment_calls.append((text, profile.role_id, dict(profile.provider_params)))
        if progress is not None:
            progress("provider_internal_chunk_1_of_1")
        os.makedirs(work_dir, exist_ok=True)
        safe_role = "".join(ch if ch.isalnum() else "_" for ch in profile.role_id)
        path = os.path.join(work_dir, f"segment_{len(self.segment_calls)}_{safe_role}.wav")
        _write_constant_wav(path, 5000 + len(self.segment_calls))
        return build_audio_artifact(path, cache_key=f"e2e-{len(self.segment_calls)}")

    def text_to_speech(self, text, output_file, audio_tags):
        self.direct_calls.append((text, output_file, audio_tags))
        _write_constant_wav(output_file)


def _role_script(book_sha256):
    return RoleScriptV1(
        schema_version=1,
        provider="openai",
        book_sha256=book_sha256,
        default_pause_after_ms=250,
        roles={
            "narrator": RoleDefinition(
                "旁白", {"voice": "冰糖", "instructions": "沉稳", "speed": 1.0}
            ),
            "hero": RoleDefinition(
                "主角", {"voice": "茉莉", "instructions": "年轻", "speed": 1.0}
            ),
        },
        chapters=(
            ChapterScript(
                chapter_index=1,
                title="第一章",
                segments=(
                    SegmentScript("narrator", "开场。", tone="平静"),
                    SegmentScript("hero", "你好。", tone="克制", pause_after_ms=0),
                ),
            ),
        ),
    )


class RoleScriptEndToEndTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from audiobook_generator.role_script.audio_pipeline import require_ffmpeg_tools

        try:
            require_ffmpeg_tools()
        except RuntimeError as exc:
            raise unittest.SkipTest(str(exc))

    def _config(self, root, *, role_mode):
        input_file = os.path.join(root, "book.epub")
        book_bytes = b"mock epub bytes"
        Path(input_file).write_bytes(book_bytes)
        config = GeneralConfig(None)
        config.input_file = input_file
        config.output_folder = os.path.join(root, "out")
        config.preview = False
        config.output_text = False
        config.log = "INFO"
        config.log_file = os.path.join(root, "e2e.log")
        config.no_prompt = True
        config.worker_count = 1
        config.use_pydub_merge = False
        config.chapter_start = 1
        config.chapter_end = -1
        config.title_mode = "auto"
        config.newline_mode = "double"
        config.remove_endnotes = False
        config.remove_reference_numbers = False
        config.search_and_replace_file = ""
        config.tts = "openai"
        config.language = "zh-CN"
        config.model_name = "mimo-v2.5-tts"
        config.voice_name = "冰糖"
        config.instructions = "全局语气"
        config.speed = 1.0
        config.stream = False
        config.output_format = "wav"
        config.role_script = (
            _role_script(hashlib.sha256(book_bytes).hexdigest()) if role_mode else None
        )
        config.allow_role_text_override = False
        config.allow_role_title_mismatch = False
        config.allow_role_fallback = False
        return config

    def test_role_mode_run_outputs_tagged_audio_progress_and_cleanup(self):
        with tempfile.TemporaryDirectory() as root:
            config = self._config(root, role_mode=True)
            parser = _FakeBookParser([("第一章", "开场。你好。")])
            provider = _FakeProvider(config)
            import audiobook_generator.core.audiobook_generator as core

            with patch.object(
                core, "get_book_parser", return_value=parser
            ), patch.object(
                core, "get_tts_provider", return_value=provider
            ), patch.object(
                core.multiprocessing, "get_context", return_value=_SerialContext()
            ), patch.object(
                core.logger, "info", wraps=core.logger.info
            ) as logged:
                AudiobookGenerator(config).run()

            outputs = list(Path(config.output_folder).glob("*.wav"))
            self.assertEqual(len(outputs), 1, outputs)
            self.assertEqual(
                [(text, role_id) for text, role_id, _ in provider.segment_calls],
                [("开场。", "narrator"), ("你好。", "hero")],
            )
            self.assertEqual(provider.direct_calls, [])
            self.assertFalse(
                os.path.exists(os.path.join(config.output_folder, ".role_tmp", "chapter_000001"))
            )

            messages = [str(call.args[0]) for call in logged.call_args_list if call.args]
            self.assertIn("role_chapter_1_segment_1_of_2", messages)
            self.assertIn("role_chapter_1_segment_2_of_2", messages)

            from mutagen.wave import WAVE

            tags = WAVE(str(outputs[0])).tags
            self.assertEqual(tags["TIT2"].text[0], "第一章")
            self.assertEqual(tags["TPE1"].text[0], "测试作者")
            self.assertEqual(tags["TALB"].text[0], "测试书名")

    def test_normal_mode_run_keeps_direct_text_to_speech_path(self):
        with tempfile.TemporaryDirectory() as root:
            config = self._config(root, role_mode=False)
            parser = _FakeBookParser([("第一章", "普通模式正文。")])
            provider = _FakeProvider(config)
            import audiobook_generator.core.audiobook_generator as core

            with patch.object(
                core, "get_book_parser", return_value=parser
            ), patch.object(
                core, "get_tts_provider", return_value=provider
            ), patch.object(
                core.multiprocessing, "get_context", return_value=_SerialContext()
            ):
                AudiobookGenerator(config).run()

            outputs = list(Path(config.output_folder).glob("*.wav"))
            self.assertEqual(len(outputs), 1, outputs)
            self.assertEqual(len(provider.direct_calls), 1)
            self.assertEqual(provider.direct_calls[0][0], "普通模式正文。")
            self.assertEqual(provider.segment_calls, [])
            self.assertFalse(os.path.exists(os.path.join(config.output_folder, ".role_tmp")))


if __name__ == "__main__":
    unittest.main()
