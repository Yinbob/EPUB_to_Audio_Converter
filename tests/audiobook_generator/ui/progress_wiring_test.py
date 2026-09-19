"""进度条接线与状态机回归测试。

历史教训（两条都要靠测试锁住）：
1. `gr.Timer` 被包进 `visible=False` 容器 → 前端不应用 active 更新、不启动 tick，
   进度条永远停在初始文案；
2. 每 2 秒整块替换进度条 HTML → CSS 动画（shimmer、宽度过渡）反复重放 → "一闪一闪"。
现在服务端只推一个隐藏的状态载荷，可见 DOM 由页面脚本就地更新，所以这里还要断言
"骨架不是任何事件的输出"（即不会被重新渲染）以及各补丁目标节点都在骨架里。

本文件只在 venv_chatterbox 解释器下运行：`import web_ui` 会连带 import main，
而 main.py 顶层在"解释器不是 venv + venv 存在"时会 os.execv 切换解释器。
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
VENV_PYTHON = os.path.join(REPO_ROOT, "venv_chatterbox", "bin", "python3")

# 必须用字符串精确比较：venv 的 python3 是系统解释器的符号链接，realpath 之后两边相等
RUNNABLE = os.path.exists(VENV_PYTHON) and sys.executable == VENV_PYTHON
SKIP_REASON = "需要在 venv_chatterbox 解释器下运行（main.py 会 execv 切换解释器）"

SCAFFOLD_IDS = ["progress_container", "progress_status", "progress_detail",
                "progress_pct", "progress_book", "progress_fill"]


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
        cls.captured = {}
        cls._original_launch = gr.Blocks.launch
        gr.Blocks.launch = lambda self, *args, **kwargs: cls.captured.setdefault("ui", self)

        web_ui.host_ui(UiConfig(SimpleNamespace(host="127.0.0.1", port=7999)))
        cls.config = cls.captured["ui"].get_config_file()

    @classmethod
    def tearDownClass(cls):
        cls.gr.Blocks.launch = cls._original_launch

    def _components(self):
        components = self.config["components"]
        timers = [c for c in components
                  if c.get("type") == "timer" and c.get("props", {}).get("value") == 2]
        self.assertEqual(len(timers), 1, f"没找到唯一的进度 Timer：{timers}")
        states = [c for c in components
                  if c.get("props", {}).get("elem_id") == "progress_state"]
        self.assertEqual(len(states), 1, f"没找到隐藏状态载荷组件：{states}")
        scaffolds = [c for c in components
                     if c.get("type") == "html"
                     and "progress-bar-wrap" in str(c.get("props", {}).get("elem_classes"))]
        self.assertEqual(len(scaffolds), 1, f"没找到唯一的进度条骨架：{scaffolds}")
        return timers[0]["id"], states[0]["id"], scaffolds[0]

    def test_progress_timer_is_not_inside_hidden_container(self):
        timer_id, _, _ = self._components()
        visibilities = _ancestor_visibilities(self.config["layout"], timer_id)
        self.assertTrue(visibilities, "布局树里没有找到进度 Timer")
        for chain in visibilities:
            # Gradio 前端 ct() 判定：祖先 visible 为 False / "hidden" 都不会让 Timer 真正生效
            self.assertNotIn(False, chain, f"Timer 被放进了不可见容器：{chain}")
            self.assertNotIn("hidden", chain, f"Timer 被放进了隐藏容器：{chain}")

    def test_scaffold_has_patch_targets_and_is_never_re_rendered(self):
        _, _, scaffold = self._components()
        html = scaffold.get("props", {}).get("value") or ""
        for element_id in SCAFFOLD_IDS:
            self.assertIn(f'id="{element_id}"', html,
                          f"骨架里缺少前端脚本要更新的节点：{element_id}")

        # 骨架若是某个事件的输出，Gradio 就会重新渲染它 → 动画重放 → 又回到"一闪一闪"
        for dependency in self.config["dependencies"]:
            self.assertNotIn(scaffold["id"], dependency.get("outputs", []),
                             "进度条骨架不应作为事件输出（否则每 2 秒重新渲染）")

    def test_tick_and_load_events_are_wired_to_hidden_state(self):
        timer_id, state_id, _ = self._components()
        dependencies = self.config["dependencies"]

        tick_deps = [d for d in dependencies
                     if any(t[0] == timer_id and t[1] == "tick" for t in d.get("targets", []))]
        self.assertTrue(tick_deps, "没有绑定 Timer 的 tick 事件")
        self.assertEqual(tick_deps[0]["outputs"], [state_id, timer_id])

        load_deps = [d for d in dependencies
                     if any(event == "load" for _, event in d.get("targets", []))
                     and d.get("outputs") == [state_id, timer_id]]
        self.assertTrue(load_deps, "没有为进度条绑定页面加载（load）同步事件")

    def test_start_button_scrolls_to_progress_bar(self):
        start_deps = [d for d in self.config["dependencies"]
                      if d.get("api_name") == "process_form"]
        self.assertTrue(start_deps, "没找到「开始生成」事件")
        # 滚动用页面脚本里的原生监听实现：Gradio 事件的 js= 会把表单输入变成空值
        # （实测点击后服务端报 Slider NoneType 比较错误），所以这里显式禁止再挂 js=。
        self.assertFalse(start_deps[0].get("js"),
                         "不要在「开始生成」事件上使用 js=（会清空表单输入），滚动请用 HEAD_HTML 的原生监听")
        self.assertIn("开始生成", self.web_ui.HEAD_HTML,
                      "页面脚本里没有「开始生成」按钮的滚动监听")
        # 点击后整页滑回最顶端（原来是滚到进度条）
        self.assertIn("window.scrollTo({ top: 0, behavior: 'smooth' })", self.web_ui.HEAD_HTML,
                      "「开始生成」点击后应平滑滚到页面最顶端")

    def test_start_and_stop_push_state_immediately(self):
        """点开始/停止要立刻推送状态：新批次必须马上把进度条重置，而不是等下一次轮询。"""
        _, state_id, _ = self._components()
        start_deps = [d for d in self.config["dependencies"] if d.get("api_name") == "process_form"]
        stop_deps = [d for d in self.config["dependencies"] if d.get("api_name") == "terminate_generator"]
        self.assertTrue(start_deps and stop_deps)
        self.assertIn(state_id, start_deps[0]["outputs"], "「开始生成」没有输出进度状态")
        self.assertIn(state_id, stop_deps[0]["outputs"], "「停止转换」没有输出进度状态")

    def test_page_head_contains_progress_enhancer(self):
        head = self.web_ui.HEAD_HTML
        for token in ("progress_container", "applyProgress", "__ataScrollToProgress", "ata-ripple",
                      "scheduleHide", "revealProgress", "HIDE_DELAY"):
            self.assertIn(token, head, f"页面脚本里缺少：{token}")
        # Blocks 配置里也应带上这段 head
        self.assertIn("progress_container", str(self.config.get("head", "")))

    def test_finished_state_collapses_instead_of_staying_on_top(self):
        """生成结束后进度条要自动收起，不能一直占着页面顶部"""
        head = self.web_ui.HEAD_HTML
        self.assertIn("collapsed", head)
        self.assertIn("finished: 6000", head)          # 完成态短暂展示后收起
        self.assertIn("interrupted: 12000", head)      # 异常/停止态留久一点再收起
        css = self.web_ui.CUSTOM_CSS
        self.assertIn(".progress-container.collapsed", css)
        self.assertIn("max-height: 0 !important", css)

    def test_log_component_reads_more_history_and_card_does_not_clip(self):
        """日志页要能看到足够历史，且卡片不能裁剪终端视图（否则显得"日志不全"）"""
        logs = [c for c in self.config["components"] if c.get("type") == "log"]
        self.assertTrue(logs, "没找到日志组件")
        props = logs[0].get("props", {})
        self.assertGreaterEqual(props.get("tail", 0), 500, f"日志起始读取行数太小：{props.get('tail')}")
        self.assertGreaterEqual(props.get("xterm_scrollback", 0), 1000)

        css = self.web_ui.CUSTOM_CSS
        self.assertNotIn(".app-card { position: relative; overflow: hidden; }", css,
                         "卡片不能裁剪内容：日志页的终端会被切掉")

    def test_ambient_background_layer_is_wired_in(self):
        """氛围背景层（光晕 + 鼠标交互）要同时挂在 head 与样式里"""
        head = str(self.config.get("head", ""))
        self.assertIn("ata-bg-canvas", head, "页面头里没有背景层脚本")
        self.assertIn("ata-bg-base", head, "页面头里没有背景层渐变")
        for token in ("#ata-bg", ".app-card::before", "body.modal-open #ata-bg"):
            self.assertIn(token, self.web_ui.CUSTOM_CSS, f"页面样式里缺少：{token}")
        # 背景层必须垫在内容之下：容器提升到 z-index:1 且背景透明
        self.assertIn("z-index: 1", self.web_ui.CUSTOM_CSS)

    def test_hero_title_uses_token_gradient_and_has_solid_fallback(self):
        """大标题的渐变文字不能再写成 background 简写（Gradio 会把带 var() 的渐变丢成空值）"""
        from tests.audiobook_generator.ui.ambient_background_test import _css_rules

        css = self.web_ui.CUSTOM_CSS
        body = None
        for selector, decl in _css_rules(css):
            if ".hero h1" in [s.strip() for s in selector.split(",")]:
                body = decl
                break
        self.assertIsNotNone(body, "找不到 .hero h1 规则")
        self.assertIn("background-image: var(--ata-title-grad)", body,
                      "渐变要走长写属性 + 纯 var() 引用（简写会被 Gradio 处理成空值）")
        self.assertNotIn("background: linear-gradient", body,
                         "不能再把渐变写进 background 简写")
        self.assertIn("-webkit-text-fill-color: transparent", body)
        self.assertIn("color: var(--apple-text)", body, "缺少纯色兜底")
        # 兜底类 + 运行期检测脚本
        self.assertIn(".hero h1.ata-title-solid", css)
        self.assertIn("-webkit-text-fill-color: var(--apple-text) !important",
                      css.split(".hero h1.ata-title-solid")[1][:200])
        head = str(self.config.get("head", ""))
        self.assertIn("ata-title-solid", head, "缺少标题可见性兜底脚本")
        self.assertIn("getComputedStyle(el).backgroundImage", head)

    def test_stale_terminal_payload_is_ignored_on_fresh_session(self):
        """新会话只认实时状态：上个批次的完成/中断/失败不能弹卡（用户反馈每次新开浏览器都闪一下）"""
        head = str(self.config.get("head", ""))
        self.assertIn("var sawActive = false;", head, "缺少'本次会话见过它在跑'的闸门")
        for token in ("mode === 'starting'", "mode === 'running'", "mode === 'book_done'"):
            self.assertIn(token, head)
        for token in ("mode === 'finished'", "mode === 'interrupted'", "mode === 'failed'"):
            self.assertIn(token, head)
        self.assertIn("if (!sawActive) return;", head)
        # 闸门必须在改类名之前返回：否则旧终态仍会把进度卡标成 active（并触发背景跑马灯）
        self.assertLess(head.index("if (!sawActive) return;"),
                        head.index("box.classList.remove('idle', 'active'"),
                        "旧终态必须在改 classList 之前就被丢弃")

    def test_header_is_a_rounded_glass_bar_spanning_the_card_band(self):
        """顶栏是圆角玻璃条，且要和卡片同宽（gr.HTML 包装层会把它挤窄、logo 贴边）"""
        from tests.audiobook_generator.ui.ambient_background_test import _css_rules

        rules = _css_rules(self.web_ui.CUSTOM_CSS)
        body = None
        for selector, decl in rules:
            if ".app-header" in [s.strip() for s in selector.split(",")]:
                body = decl
                break
        self.assertIsNotNone(body, "找不到 .app-header 规则")
        self.assertIn("border-radius: var(--radius)", body, "顶栏必须是圆角（原来是直角）")
        self.assertIn("border: 1px solid var(--apple-border-soft)", body, "顶栏要和卡片同款描边")
        self.assertIn("box-shadow: var(--apple-shadow)", body, "顶栏要和卡片同款投影")
        # 负外边距抵消 .html-container 的 12px 内边距，让玻璃条铺满卡片带
        self.assertIn("margin: 0 -12px", body, "顶栏要横向撑满卡片带")
        # logo 不能贴边：左右内边距要够（>=16px）
        pad = re.search(r"padding:\s*([^;]+);", body)
        self.assertIsNotNone(pad, "顶栏缺少内边距")
        nums = [float(v) for v in re.findall(r"([\d.]+)px", pad.group(1))]
        self.assertTrue(nums and max(nums) >= 16, f"顶栏左右内边距太小：{pad.group(1)}")

    def test_card_mouse_follow_highlight_is_removed(self):
        """卡片内部跟随鼠标的高光动效已按要求移除（只留背景层的光晕）"""
        self.assertNotIn(".app-card::after", self.web_ui.CUSTOM_CSS,
                         "卡片跟随鼠标的高光（.app-card::after）应已移除")
        self.assertNotIn("--mx", self.web_ui.HEAD_HTML,
                         "写 --mx/--my 的 mousemove 监听应已移除")
        self.assertNotIn("--my", self.web_ui.CUSTOM_CSS)

    def test_content_containers_keep_no_containing_block_properties(self):
        """页面样式整体也要守住 Dropdown 定位约束（不只是 ambient 模块自己的样式）"""
        from tests.audiobook_generator.ui.ambient_background_test import (
            FORBIDDEN_ON_CONTAINERS,
            _bare_selectors,
            _css_rules,
            _declares,
        )

        for selector, body in _css_rules(self.web_ui.CUSTOM_CSS):
            for token in _bare_selectors(selector):
                if token not in (".app-card", ".gradio-container"):
                    continue
                for prop in FORBIDDEN_ON_CONTAINERS:
                    self.assertFalse(
                        _declares(body, prop),
                        f"{token} 上不能声明 {prop}（Gradio Dropdown 的选项面板会定位错乱）")
                self.assertFalse(_declares(body, "overflow"),
                                 f"{token} 上不能声明 overflow（日志页终端会被裁剪）")


@unittest.skipUnless(RUNNABLE, SKIP_REASON)
class TestStopKillsWholeProcessGroup(unittest.TestCase):
    """「停止转换」必须终止批处理进程**及其孙子进程**（章节 worker），否则会继续合成。"""

    GRANDCHILD_CODE = (
        "import sys, time, pathlib\n"
        "hb = pathlib.Path(sys.argv[1])\n"
        "while True:\n"
        "    with hb.open('a') as fh:\n"
        "        fh.write('x')\n"
        "    time.sleep(0.2)\n"
    )

    @staticmethod
    def _child_main(pids_path, heartbeat_path):
        os.setsid()                      # 与 _batch_worker 的做法一致
        grand = subprocess.Popen([sys.executable, "-c", TestStopKillsWholeProcessGroup.GRANDCHILD_CODE,
                                  heartbeat_path])
        Path(pids_path).write_text(f"{os.getpid()} {grand.pid}\n")
        time.sleep(120)

    @classmethod
    def setUpClass(cls):
        import audiobook_generator.ui.web_ui as web_ui

        cls.web_ui = web_ui
        cls._original_running_process = web_ui.running_process
        cls._original_manual_stopped = web_ui.manual_stopped

    @classmethod
    def tearDownClass(cls):
        cls.web_ui.running_process = cls._original_running_process
        cls.web_ui.manual_stopped = cls._original_manual_stopped

    def test_terminate_kills_child_and_grandchild(self):
        import multiprocessing

        tmp_dir = Path(tempfile.mkdtemp(prefix="stop_group_"))
        pids_path = tmp_dir / "pids.txt"
        heartbeat = tmp_dir / "heartbeat.txt"

        ctx = multiprocessing.get_context("spawn")
        proc = ctx.Process(target=self._child_main, args=(str(pids_path), str(heartbeat)))
        proc.start()

        deadline = time.time() + 20
        while time.time() < deadline and not pids_path.exists():
            time.sleep(0.1)
        self.assertTrue(pids_path.exists(), "批处理子进程没起来")
        while time.time() < deadline and not heartbeat.exists():
            time.sleep(0.1)
        self.assertTrue(heartbeat.exists(), "孙进程（模拟章节 worker）没起来")

        self.web_ui.running_process = proc
        self.web_ui.manual_stopped = False
        stopped = self.web_ui._terminate_running_batch(timeout=3.0)
        self.assertTrue(stopped, "停止函数没有报告已停止")
        self.assertTrue(self.web_ui.manual_stopped)
        self.assertFalse(proc.is_alive(), "批处理子进程仍在运行")

        # 孙进程是否真的死了：看它的心跳文件是否停止增长（僵尸进程不会写心跳）
        size_after_stop = heartbeat.stat().st_size
        time.sleep(1.2)
        self.assertEqual(heartbeat.stat().st_size, size_after_stop,
                         "章节 worker（孙进程）仍在运行——停止没有覆盖整组进程")


@unittest.skipUnless(RUNNABLE, SKIP_REASON)
class TestProgressStateMachine(unittest.TestCase):
    """五态：空闲 / 启动中 / 生成中（含块级细节）/ 完成 / 中断 与定时器开关"""

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

    def _payload(self, content, alive=True):
        """alive=None 表示"从未启动过批次"（running_process is None）"""
        tmp_dir = tempfile.mkdtemp(prefix="progress_wiring_")
        log_path = Path(tmp_dir) / "webui.log"
        if content is not None:
            log_path.write_text(content, encoding="utf-8")
        self.web_ui.webui_log_file = log_path
        self.web_ui.running_process = None if alive is None else _AliveProcess(alive)
        raw, timer = self.web_ui.get_progress_info()
        return json.loads(raw), timer.active

    def test_idle_without_run(self):
        payload, active = self._payload("", alive=None)
        self.assertEqual(payload["mode"], "idle")
        self.assertEqual(payload["status"], "等待开始生成...")
        self.assertFalse(active)

    def test_starting_keeps_polling_even_without_log_file(self):
        payload, active = self._payload(None, alive=True)
        self.assertEqual(payload["mode"], "starting")
        self.assertEqual(payload["status"], "正在启动...")
        self.assertTrue(active, "运行中必须保持轮询，否则进度条会永久停在等待状态")

    def test_running_reports_chunk_level_progress(self):
        payload, active = self._payload(self.BOOK_LINE + self.COUNT_LINE + self.RANGE_LINE + self.CHUNK_LINE)
        self.assertEqual(payload["mode"], "running")
        self.assertEqual(payload["detail"], "章节 0/2 · 第 1 章 2/4 块")
        self.assertEqual(payload["pct"], 12)
        self.assertTrue(active)

    def test_finished_stops_polling(self):
        payload, active = self._payload(
            self.BOOK_LINE + self.COUNT_LINE + self.RANGE_LINE + self.DONE_LINE
            + self.DONE_LINE.replace("chapter 1", "chapter 2") + self.FINISHED_LINE,
            alive=False,   # 真实流程里批次写完结束标记后进程随即退出
        )
        self.assertEqual(payload["mode"], "finished")
        self.assertEqual(payload["pct"], 100)
        self.assertFalse(active)

    def test_interrupted_and_failed_start(self):
        interrupted, active = self._payload(self.BOOK_LINE + self.COUNT_LINE, alive=False)
        self.assertEqual(interrupted["mode"], "interrupted")
        self.assertFalse(active)

        failed, active = self._payload("2026-09-18 08:00:00 - 无关键信息的一行\n", alive=False)
        self.assertEqual(failed["mode"], "failed")
        self.assertFalse(active)

    def test_second_run_resets_progress(self):
        """第一次生成完成后，第二次点开始：日志里还留着上一批的结束标记，进度条必须重置。"""
        finished_text = (self.BOOK_LINE + self.COUNT_LINE + self.RANGE_LINE + self.DONE_LINE
                         + self.DONE_LINE.replace("chapter 1", "chapter 2") + self.FINISHED_LINE)

        done, active = self._payload(finished_text, alive=False)
        self.assertEqual(done["mode"], "finished")
        self.assertFalse(active)

        # 新批次启动（进程存活、日志尚未更新）
        restarted, active = self._payload(finished_text, alive=True)
        self.assertEqual(restarted["mode"], "starting")
        self.assertEqual(restarted["pct"], 0)
        self.assertTrue(active, "重置后仍要继续轮询")


if __name__ == "__main__":
    unittest.main()
