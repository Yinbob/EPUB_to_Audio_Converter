import unittest

from audiobook_generator.ui.progress_parser import (
    MODE_BOOK_DONE,
    MODE_FAILED,
    MODE_FINISHED,
    MODE_IDLE,
    MODE_INTERRUPTED,
    MODE_RUNNING,
    MODE_STARTING,
    decide_progress_state,
    parse_progress,
)


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
        self.assertFalse(state["has_markers"])

    def test_has_markers_turns_true_once_book_or_chapters_known(self):
        # 只有书名标记
        self.assertTrue(parse_progress(BOOK_START)["has_markers"])
        # 只有章节数标记
        self.assertTrue(parse_progress(CHAPTERS_COUNT)["has_markers"])
        # 无关日志行不算已开始
        self.assertFalse(parse_progress("2026-09-18 08:00:00 - 加载 Chatterbox TTS 模型\n")["has_markers"])

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

    def test_finished_marker_is_scoped_to_current_book(self):
        """上一批的结束标记不能让新一批一开始就显示"已完成"。"""
        first_run = BOOK_START + CHAPTERS_COUNT + CONVERTED_1 + FINISHED
        second_run = (
            "2026-09-18 09:20:00 - 📚 [1/1] 开始转换: 第二本书\n"
            "2026-09-18 09:20:01 - audiobook_generator.py:99 - run - INFO - Chapters count: 3.\n"
        )
        state = parse_progress(first_run + second_run)
        self.assertEqual(state["book"], "第二本书")
        self.assertEqual(state["total"], 3)
        self.assertEqual(state["done"], 0)
        self.assertFalse(state["finished"], "结束标记属于上一批，不应影响新批次")
        self.assertTrue(state["has_markers"])

    def test_worker_prefixed_lines_are_parsed(self):
        # 真实日志里 worker 行形如：时间 - [Worker-x] - 文件:行 - 函数 - INFO - 内容
        state = parse_progress(BOOK_START + CHAPTERS_COUNT + CHUNK_2_OF_4)
        self.assertEqual(state["total"], 3)
        self.assertEqual(state["extra"], "第 2 章 2/4 块")


class TestDecideProgressState(unittest.TestCase):
    """展示状态机：解析结果 + 批次是否在跑 → 进度条展示模式 / 文案 / 是否继续轮询"""

    def test_idle_when_never_started(self):
        decision = decide_progress_state(parse_progress(""), run_alive=False)
        self.assertEqual(decision["mode"], MODE_IDLE)
        self.assertEqual(decision["status"], "等待开始生成...")
        self.assertFalse(decision["active"])

    def test_starting_while_run_alive_without_markers(self):
        decision = decide_progress_state(parse_progress(""), run_alive=True)
        self.assertEqual(decision["mode"], MODE_STARTING)
        self.assertEqual(decision["status"], "正在启动...")
        self.assertTrue(decision["active"], "运行中必须保持轮询")

    def test_running_reports_chunk_detail(self):
        state = parse_progress(BOOK_START + CHAPTERS_COUNT + CHAPTER_RANGE + CHUNK_2_OF_4)
        decision = decide_progress_state(state, run_alive=True)
        self.assertEqual(decision["mode"], MODE_RUNNING)
        self.assertEqual(decision["status"], "正在生成...")
        self.assertEqual(decision["detail"], "章节 0/3 · 第 2 章 2/4 块")
        self.assertEqual(decision["pct"], 8)
        self.assertEqual(decision["book"], "新建 DOCX 文档")
        self.assertTrue(decision["active"])

    def test_book_done_still_polls_for_next_book(self):
        log = (BOOK_START + CHAPTERS_COUNT + CHAPTER_RANGE
               + CONVERTED_1 + CONVERTED_1.replace("chapter 2", "chapter 3")
               + CONVERTED_1.replace("chapter 2", "chapter 4"))
        decision = decide_progress_state(parse_progress(log), run_alive=True)
        self.assertEqual(decision["mode"], MODE_BOOK_DONE)
        self.assertEqual(decision["detail"], "章节 3/3")
        self.assertTrue(decision["active"], "批次里可能还有下一本书，需要继续轮询")

    def test_finished_stops_polling(self):
        log = BOOK_START + CHAPTERS_COUNT + CONVERTED_1 + FINISHED
        decision = decide_progress_state(parse_progress(log), run_alive=False)
        self.assertEqual(decision["mode"], MODE_FINISHED)
        self.assertEqual(decision["pct"], 100)
        self.assertFalse(decision["active"])

    def test_interrupted_and_failed(self):
        interrupted = decide_progress_state(parse_progress(BOOK_START + CHAPTERS_COUNT),
                                            run_alive=False, batch_started=True)
        self.assertEqual(interrupted["mode"], MODE_INTERRUPTED)
        self.assertFalse(interrupted["active"])
        self.assertIn("中断", interrupted["status"])

        # 用户主动点「停止转换」：文案要区分于异常中断
        stopped = decide_progress_state(parse_progress(BOOK_START + CHAPTERS_COUNT),
                                        run_alive=False, batch_started=True, manually_stopped=True)
        self.assertEqual(stopped["mode"], MODE_INTERRUPTED)
        self.assertIn("已停止", stopped["status"])
        self.assertFalse(stopped["active"])

        failed = decide_progress_state(parse_progress("2026-09-18 08:00:00 - 无关日志\n"),
                                       run_alive=False, batch_started=True)
        self.assertEqual(failed["mode"], MODE_FAILED)
        self.assertFalse(failed["active"])

        # 单纯刷新页面（从未启动过批次）仍应显示空闲，而不是"启动失败"
        idle = decide_progress_state(parse_progress("2026-09-18 08:00:00 - 无关日志\n"),
                                     run_alive=False, batch_started=False)
        self.assertEqual(idle["mode"], MODE_IDLE)

    def test_new_batch_resets_after_previous_finished(self):
        """上一批已完成，用户再次点开始：进度条要重置为启动态（0%），而不是停在 100%。"""
        finished_log = BOOK_START + CHAPTERS_COUNT + CONVERTED_1 + FINISHED

        # 已完成、批次已退出 → 显示完成
        done = decide_progress_state(parse_progress(finished_log), run_alive=False, batch_started=True)
        self.assertEqual(done["mode"], MODE_FINISHED)
        self.assertEqual(done["pct"], 100)

        # 新批次刚启动（进程存活、日志还没写新标记）→ 必须重置
        restarted = decide_progress_state(parse_progress(finished_log), run_alive=True, batch_started=True)
        self.assertEqual(restarted["mode"], MODE_STARTING)
        self.assertEqual(restarted["pct"], 0)
        self.assertEqual(restarted["book"], "")
        self.assertTrue(restarted["active"])

        # 新批次写出自己的标记后 → 按新批次的数据从 0 开始
        new_run = finished_log + ("2026-09-18 09:20:00 - 📚 [1/1] 开始转换: 第二本书\n"
                                  "2026-09-18 09:20:01 - audiobook_generator.py:99 - run - INFO - Chapters count: 3.\n")
        running = decide_progress_state(parse_progress(new_run), run_alive=True, batch_started=True)
        self.assertEqual(running["mode"], MODE_RUNNING)
        self.assertEqual(running["book"], "第二本书")
        self.assertEqual(running["pct"], 0)


if __name__ == "__main__":
    unittest.main()
