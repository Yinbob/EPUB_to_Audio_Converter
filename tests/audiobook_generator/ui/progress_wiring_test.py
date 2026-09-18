"""进度条接线与状态机回归测试。

背景：`gr.Timer` 只有在"有效可见"时才会被应用 active 更新并启动 tick；
一旦被包进 `visible=False` 的容器，进度条就会永远停在初始文案（所有引擎一致）。
本文件用两类断言锁死这个回归点：
1. 结构：Timer 不在任何不可见祖先里，且 tick / load 事件都已绑定；
2. 状态机：空闲 / 启动中 / 生成中 / 完成 / 中断五态下的文案与定时器开关。
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
VENV_PYTHON = os.path.join(REPO_ROOT, "venv_chatterbox", "bin", "python3")

# 直接 import audiobook_generator.ui.web_ui 会连带 import main，而 main.py 顶层在
# "解释器不是 venv + venv 存在"时会 os.execv 切换解释器（把测试进程整个换掉），
# 所以本用例只在 venv 解释器下运行，其余情况跳过。
# 注意必须用字符串精确比较：venv 的 python3 是指向系统解释器的符号链接，
# realpath 之后两边会相等，跳过判断就失效了（main.py 也是按精确路径判断的）。
RUNNABLE = os.path.exists(VENV_PYTHON) and sys.executable == VENV_PYTHON
SKIP_REASON = "需要在 venv_chatterbox 解释器下运行（main.py 会 execv 切换解释器）"


class _AliveProcess:
    def __init__(self, alive=True):
        self._alive = alive

    def is_alive(self):
        return self._alive


def _ancestor_visibilities(node, target_id, ancestors=()):
    """在 Blocks 配置的布局树里找到目标组件，返回其所有祖先的 visible 值"""
    hits = []
    for child in node.get("children", []) or []:
        if child.get("id") == target_id:
            hits.append([n.get("props", {}).get("visible", True) for n in ancestors])
        if child.get("children"):
            hits.extend(_ancestor_visibilities(child, target_id, ancestors + (child,)))
    return hits


@unittest.skipUnless(RUNNABLE, SKIP_REASON)
class TestProgressWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import gradio as gr

        from audiobook_generator.config.ui_config import UiConfig
        import audiobook_generator.ui.web_ui as web_ui

        cls.gr = gr
        cls.web_ui = web_ui
        # 只构建 UI，不真正监听端口
        cls.captured = {}
        cls._original_launch = gr.Blocks.launch
        gr.Blocks.launch = lambda self, *args, **kwargs: cls.captured.setdefault("ui", self)

        web_ui.host_ui(UiConfig(SimpleNamespace(host="127.0.0.1", port=7999)))
        cls.config = cls.captured["ui"].get_config_file()

    @classmethod
    def tearDownClass(cls):
        cls.gr.Blocks.launch = cls._original_launch

    def _find_ids(self):
        timers = [
            c for c in self.config["components"]
            if c.get("type") == "timer" and c.get("props", {}).get("value") == 2
        ]
        self.assertEqual(len(timers), 1, f"没找到唯一的进度 Timer：{timers}")
        progress_ids = [
            c["id"] for c in self.config["components"]
            if c.get("type") == "html"
            and "progress-bar-wrap" in str(c.get("props", {}).get("elem_classes"))
        ]
        self.assertEqual(len(progress_ids), 1, f"没找到唯一的进度条 HTML：{progress_ids}")
        return timers[0]["id"], progress_ids[0]

    def test_progress_timer_is_not_inside_hidden_container(self):
        timer_id, _ = self._find_ids()
        visibilities = _ancestor_visibilities(self.config["layout"], timer_id)
        self.assertTrue(visibilities, "布局树里没有找到进度 Timer")
        for chain in visibilities:
            # Gradio 前端 ct() 判定：祖先 visible 为 False / "hidden" 都不会让 Timer 真正生效
            self.assertNotIn(False, chain, f"Timer 被放进了不可见容器：{chain}")
            self.assertNotIn("hidden", chain, f"Timer 被放进了隐藏容器：{chain}")

    def test_tick_and_load_events_are_wired(self):
        timer_id, progress_id = self._find_ids()
        dependencies = self.config["dependencies"]

        tick_deps = [
            d for d in dependencies
            if any(t[0] == timer_id and t[1] == "tick" for t in d.get("targets", []))
        ]
        self.assertTrue(tick_deps, "没有绑定 Timer 的 tick 事件")
        self.assertIn(progress_id, tick_deps[0]["outputs"])
        self.assertIn(timer_id, tick_deps[0]["outputs"])

        load_deps = [
            d for d in dependencies
            if any(event == "load" for _, event in d.get("targets", []))
            and progress_id in d.get("outputs", [])
            and timer_id in d.get("outputs", [])
        ]
        self.assertTrue(load_deps, "没有为进度条绑定页面加载（load）同步事件")


@unittest.skipUnless(RUNNABLE, SKIP_REASON)
class TestProgressStateMachine(unittest.TestCase):
    BOOK_LINE = "2026-09-18 08:00:00 - 📚 [1/1] 开始转换: 测试书\n"
    COUNT_LINE = "2026-09-18 08:00:01 - audiobook_generator.py:97 - run - INFO - Chapters count: 2.\n"
    RANGE_LINE = "2026-09-18 08:00:02 - audiobook_generator.py:117 - run - INFO - Converting chapters from 1 to 2.\n"
    CHUNK_LINE = ("2026-09-18 08:00:05 - [Worker-1] - chatterbox_tts_provider.py:277 - text_to_speech"
                  " - INFO - 处理 chapter-1_第一章_chunk_2_of_4, 长度=460\n")
    DONE_LINE = "2026-09-18 08:00:09 - [Worker-1] - audiobook_generator.py:76 - INFO - ✅ Converted chapter 1: 第一章\n"
    FINISHED_LINE = "2026-09-18 08:00:30 - 🎉 全部处理完毕！共 1 本书\n"

    @classmethod
    def setUpClass(cls):
        import audiobook_generator.ui.web_ui as web_ui

        cls.web_ui = web_ui
        cls._original_running_process = web_ui.running_process

    @classmethod
    def tearDownClass(cls):
        cls.web_ui.running_process = cls._original_running_process
        cls.web_ui.webui_log_file = None

    def _state(self, content, alive=True):
        """alive=None 表示"还没有启动过任何批次"（running_process is None）"""
        tmp_dir = tempfile.mkdtemp(prefix="progress_wiring_")
        log_path = Path(tmp_dir) / "webui.log"
        if content is not None:
            log_path.write_text(content, encoding="utf-8")
        self.web_ui.webui_log_file = log_path
        self.web_ui.running_process = None if alive is None else _AliveProcess(alive)
        html, timer = self.web_ui.get_progress_info()
        return html, timer.active

    def test_idle_without_run(self):
        html, active = self._state("", alive=None)
        self.assertIn("等待开始生成", html)
        self.assertFalse(active)

    def test_starting_keeps_polling_even_without_log_file(self):
        # 批次已启动但日志还没写出标记（chatterbox 加载模型期间就是这样）
        html, active = self._state(None, alive=True)
        self.assertIn("正在启动", html)
        self.assertTrue(active, "运行中必须保持轮询，否则进度条会永久停在等待状态")

    def test_running_reports_chunk_level_progress(self):
        html, active = self._state(self.BOOK_LINE + self.COUNT_LINE + self.RANGE_LINE + self.CHUNK_LINE)
        self.assertIn("正在生成", html)
        self.assertIn("第 1 章 2/4 块", html)
        self.assertTrue(active)

    def test_finished_stops_polling(self):
        html, active = self._state(
            self.BOOK_LINE + self.COUNT_LINE + self.RANGE_LINE + self.DONE_LINE
            + self.DONE_LINE.replace("chapter 1", "chapter 2") + self.FINISHED_LINE
        )
        self.assertIn("全部完成", html)
        self.assertFalse(active)

    def test_interrupted_run_is_reported(self):
        html, active = self._state(self.BOOK_LINE + self.COUNT_LINE, alive=False)
        self.assertIn("生成已中断", html)
        self.assertFalse(active)

    def test_failed_start_is_reported(self):
        # 进程已退出且没有任何标记：应提示启动失败而不是假装等待
        html, active = self._state("2026-09-18 08:00:00 - 无关键信息的一行\n", alive=False)
        self.assertIn("启动失败", html)
        self.assertFalse(active)


if __name__ == "__main__":
    unittest.main()
