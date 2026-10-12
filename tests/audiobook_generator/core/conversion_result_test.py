"""转换结果必须反映音频产物，并区分预解析和真实合成。"""
import ast
import logging
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from audiobook_generator.config.general_config import GeneralConfig
from audiobook_generator.core.audiobook_generator import AudiobookGenerator
from audiobook_generator.ui.progress_parser import parse_progress, decide_progress_state

MODULE = "audiobook_generator.core.audiobook_generator"
ROOT = Path(__file__).resolve().parents[3]


class ConversionResultTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = GeneralConfig(None)
        self.config.output_folder = self.tmp.name
        self.config.output_text = False
        self.config.preview = False
        self.config.chapter_start = 1
        self.config.chapter_end = -1
        self.config.no_prompt = True
        self.config.worker_count = 1
        self.parser = MagicMock()
        self.parser.get_chapters.return_value = [("第一章", "测试正文")]
        self.provider = MagicMock()
        self.provider.get_output_file_extension.return_value = "wav"
        self.provider.estimate_cost.return_value = 0.0

    def run_conversion(self):
        pool = MagicMock()
        pool.__enter__.return_value = pool
        pool.imap_unordered.side_effect = lambda func, tasks: map(func, tasks)
        with patch(f"{MODULE}.get_book_parser", return_value=self.parser), patch(
            f"{MODULE}.get_tts_provider", return_value=self.provider
        ), patch(f"{MODULE}.multiprocessing.get_context") as context:
            context.return_value.Pool.return_value = pool
            return AudiobookGenerator(self.config).run()

    def test_missing_or_empty_audio_fails(self):
        for empty in (False, True):
            with self.subTest(empty=empty):
                self.provider.text_to_speech.side_effect = (
                    (lambda text, path, tags: Path(path).write_bytes(b"")) if empty else None
                )
                self.assertIs(self.run_conversion(), False)

    def test_written_audio_succeeds(self):
        self.provider.text_to_speech.side_effect = lambda text, path, tags: Path(path).write_bytes(b"audio")
        self.assertIs(self.run_conversion(), True)

    def test_preview_skips_synthesis_and_is_explicit(self):
        self.config.preview = True
        self.assertIs(self.run_conversion(), True)
        self.provider.text_to_speech.assert_not_called()
        state = parse_progress("📚 [1/1] 开始转换: 测试\nChapters count: 1\n"
                               "预解析完成（未生成音频）\n🎉 全部处理完毕")
        self.assertIn("未生成音频", decide_progress_state(state, False)["status"])

    def test_parser_error_returns_failure(self):
        self.parser.get_chapters.side_effect = ValueError("解析失败")
        self.assertIs(self.run_conversion(), False)

    def test_batch_does_not_mark_failed_book_successful(self):
        # 提取实际 worker，避免导入 Gradio 和可选 API 依赖或调用 setsid。
        source = ast.parse((ROOT / "audiobook_generator/ui/web_ui.py").read_text())
        worker = next(node for node in source.body if isinstance(node, ast.FunctionDef)
                      and node.name == "_batch_worker")
        namespace = {"os": MagicMock(), "Path": Path,
                     "_get_batch_logger": lambda path: logging.getLogger("test.batch"),
                     "main": lambda *args: False}
        exec(compile(ast.Module(body=[worker], type_ignores=[]), "web_ui.py", "exec"), namespace)
        with self.assertLogs("test.batch", level="INFO") as logs:
            namespace["_batch_worker"]([SimpleNamespace(input_file="book.epub", preview=False)], "unused")
        content = "\n".join(logs.output)
        self.assertNotIn("全部处理完毕", content)
        self.assertNotIn("✅", content)
        state = parse_progress(content)
        self.assertEqual(decide_progress_state(state, False)["mode"], "failed")

    def test_old_failure_does_not_contaminate_new_batch(self):
        content = ("📚 [1/1] 开始转换: 旧书\n批次处理失败\n"
                   "📚 [1/1] 开始转换: 新书\nChapters count: 1\n"
                   "✅ Converted chapter 1\n🎉 全部处理完毕")
        self.assertEqual(decide_progress_state(parse_progress(content), False)["mode"], "finished")
