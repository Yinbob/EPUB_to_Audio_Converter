"""VoxCPM WebUI 接线回归测试。

锁住三条容易回归的点：
1. 「🔊 VoxCPM」标签页存在且引擎标签为 6 列布局；
2. 「开始生成」的 process_form 输入里接入了全部 18 个 VoxCPM 参数组件
   （顺序与 process_form 签名一致，尾部 18 个）；
3. 「试听当前预设音色」按钮接线到 voxcpm_preview_voice 且输出到试听 Audio。

与 progress_wiring_test 一样，需要 venv_chatterbox 解释器运行
（import web_ui 会连带 import main，main.py 顶层会 execv 切换解释器）。
"""

import os
import sys
import unittest
from types import SimpleNamespace

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
VENV_PYTHON = os.path.join(REPO_ROOT, "venv_chatterbox", "bin", "python3")

RUNNABLE = os.path.exists(VENV_PYTHON) and sys.executable == VENV_PYTHON
SKIP_REASON = "需要在 venv_chatterbox 解释器下运行（main.py 会 execv 切换解释器）"

# process_form 签名里 VoxCPM 参数的展示标签（按接入顺序；重复标签允许多处命中）
VOXCPM_LABELS = [
    "模型",
    "合成模式",
    "音色",
    "音色库目录",
    "重新生成预设音色",
    "声音描述（design / clone 模式可选）",
    "参考音频（clone / hifi 模式，可选）",
    "参考音频转写文本（hifi 模式）",
    "自动转写参考音频",
    "运行设备",
    "降噪参考音频",
    "文本规范化",
    "CFG 引导",
    "推理步数",
    "语速",
    "分块字数",
    "启用 torch.compile 优化",
    "输出格式",
]


def _label_matches(props: dict, label: str) -> bool:
    actual = str(props.get("label") or "")
    return actual == label or actual.startswith(label)


@unittest.skipUnless(RUNNABLE, SKIP_REASON)
class TestVoxCPMUiWiring(unittest.TestCase):
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
        return self.config["components"]

    def test_voxcpm_tab_exists(self):
        tabs = [c for c in self._components()
                if c.get("props", {}).get("id") == "VoxCPM"]
        self.assertTrue(tabs, "找不到 id=VoxCPM 的标签页")
        self.assertIn("🔊 VoxCPM", str(tabs[0].get("props", {}).get("label", "")))

    def test_engine_tabs_css_has_six_columns(self):
        css = self.web_ui.CUSTOM_CSS
        self.assertIn("repeat(6, 1fr) !important", css, "引擎标签应改为 6 列（6 个引擎）")

    def test_process_form_wires_all_voxcpm_components(self):
        deps = [d for d in self.config["dependencies"]
                if d.get("api_name") == "process_form"]
        self.assertTrue(deps, "没找到「开始生成」事件")
        inputs = deps[0].get("inputs") or []
        self.assertGreaterEqual(len(inputs), len(VOXCPM_LABELS),
                                "process_form 输入数量不足")
        # VoxCPM 的 18 个参数按签名顺序排在输入尾部
        voxcpm_ids = set(inputs[-len(VOXCPM_LABELS):])
        comps = self._components()
        for label in VOXCPM_LABELS:
            matches = [c for c in comps if _label_matches(c.get("props", {}) or {}, label)]
            self.assertTrue(matches, f"UI 里找不到组件：{label}")
            self.assertTrue(
                any(c["id"] in voxcpm_ids for c in matches),
                f"组件 {label} 没有接入 process_form 的 VoxCPM 参数段",
            )

    def test_preview_button_wired_to_preset_audio(self):
        deps = [d for d in self.config["dependencies"]
                if d.get("api_name") == "voxcpm_preview_voice"]
        self.assertTrue(deps, "没找到试听按钮事件")
        dep = deps[0]
        self.assertEqual(len(dep.get("inputs") or []), 7,
                         "试听事件应接收 voice/model/device/voice_dir/cfg/steps/regenerate")
        outputs = dep.get("outputs") or []
        self.assertEqual(len(outputs), 1, "试听事件应输出一个 Audio 组件")

        # 试听按钮本体（targets 里的 button）
        button_ids = [t[0] for t in dep.get("targets", [])]
        buttons = [c for c in self._components()
                   if c["id"] in button_ids and c.get("type") == "button"]
        self.assertTrue(buttons, "找不到试听按钮")
        self.assertIn("🎧 试听", str(buttons[0].get("props", {}).get("value", "")))

    def test_provider_label_and_badge_registered(self):
        self.assertEqual(self.web_ui._PROVIDER_LABEL.get("VoxCPM"), "VoxCPM")
        self.assertIn("VoxCPM", self.web_ui._PROVIDER_LABEL)


if __name__ == "__main__":
    unittest.main()
