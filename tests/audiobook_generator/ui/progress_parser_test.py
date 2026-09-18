import unittest

from audiobook_generator.ui.progress_parser import parse_progress


BOOK_START = "2026-09-17 14:29:00,000 - 📚 [1/1] 开始转换: 新建 DOCX 文档\n"
CHAPTERS_COUNT = "2026-09-17 14:29:01,000 - audiobook_generator.py:97 - run - INFO - Chapters count: 3.\n"
CHAPTER_RANGE = "2026-09-17 14:29:02,000 - audiobook_generator.py:110 - run - INFO - Converting chapters from 2 to 4.\n"
CONVERTED_1 = "2026-09-17 14:29:30,000 - [Worker-1] - audiobook_generator.py:76 - INFO - ✅ Converted chapter 2: 第二章, output file: out.mp3\n"
CHUNK_2_OF_4 = ("2026-09-17 14:29:40,000 - [Worker-1] - chatterbox_tts_provider.py:277 - text_to_speech"
                " - INFO - 处理 chapter-2_第二章_chunk_2_of_4, 长度=460\n")
FINISHED = "2026-09-17 14:35:00,000 - 🎉 全部处理完毕！共 1 本书\n"


class TestParseProgress(unittest.TestCase):
    def test_empty_log_is_idle(self):
        state = parse_progress("")
        self.assertEqual(state["book"], "")
        self.assertEqual(state["total"], 0)
        self.assertEqual(state["pct"], 0)
        self.assertFalse(state["finished"])

    def test_log_without_book_marker_reports_counts_only(self):
        state = parse_progress(CHAPTERS_COUNT + CONVERTED_1)
        self.assertEqual(state["book"], "")
        self.assertEqual(state["total"], 3)
        self.assertEqual(state["done"], 1)
        self.assertEqual(state["pct"], 33)

    def test_chapter_range_wins_over_total_count(self):
        state = parse_progress(BOOK_START + CHAPTERS_COUNT + CHAPTER_RANGE + CONVERTED_1)
        self.assertEqual(state["book"], "新建 DOCX 文档")
        self.assertEqual(state["total"], 3)  # 2~4 章
        self.assertEqual(state["done"], 1)
        self.assertEqual(state["pct"], 33)

    def test_chunk_level_progress_moves_inside_long_chapter(self):
        state = parse_progress(BOOK_START + CHAPTERS_COUNT + CHAPTER_RANGE + CHUNK_2_OF_4)
        self.assertEqual(state["done"], 0)
        self.assertEqual(state["extra"], "第 2 章 2/4 块")
        self.assertEqual(state["pct"], 8)  # (0 + 1/4) / 3

        # 块继续推进，百分比相应提高
        state_later = parse_progress(
            BOOK_START + CHAPTERS_COUNT + CHAPTER_RANGE
            + CHUNK_2_OF_4.replace("chunk_2_of_4", "chunk_4_of_4")
        )
        self.assertEqual(state_later["pct"], 25)  # (0 + 3/4) / 3
        self.assertGreater(state_later["pct"], state["pct"])

    def test_chunk_progress_is_ignored_after_chapter_done(self):
        state = parse_progress(BOOK_START + CHAPTERS_COUNT + CHAPTER_RANGE + CONVERTED_1 + CHUNK_2_OF_4)
        # 第 2 章已完成，块级插值不再重复计入
        self.assertEqual(state["done"], 1)
        self.assertEqual(state["extra"], "")
        self.assertEqual(state["pct"], 33)

    def test_batch_scope_is_limited_to_current_book(self):
        log = (
            "2026-09-17 14:00:00,000 - 📚 [1/2] 开始转换: 第一本书\n"
            + CHAPTERS_COUNT
            + CONVERTED_1
            + CONVERTED_1
            + CONVERTED_1
            + "2026-09-17 14:10:00,000 - 📚 [2/2] 开始转换: 第二本书\n"
            + "2026-09-17 14:10:01,000 - audiobook_generator.py:97 - run - INFO - Chapters count: 2.\n"
        )
        state = parse_progress(log)
        self.assertEqual(state["book"], "第二本书")
        self.assertEqual(state["total"], 2)
        self.assertEqual(state["done"], 0)
        self.assertEqual(state["pct"], 0)

    def test_finished_marker(self):
        state = parse_progress(BOOK_START + CHAPTERS_COUNT + CONVERTED_1 + FINISHED)
        self.assertTrue(state["finished"])

    def test_worker_prefixed_lines_are_parsed(self):
        # 真实日志里 worker 行形如：时间 - [Worker-x] - 文件:行 - 函数 - INFO - 内容
        state = parse_progress(BOOK_START + CHAPTERS_COUNT + CHUNK_2_OF_4)
        self.assertEqual(state["total"], 3)
        self.assertEqual(state["extra"], "第 2 章 2/4 块")


if __name__ == "__main__":
    unittest.main()
