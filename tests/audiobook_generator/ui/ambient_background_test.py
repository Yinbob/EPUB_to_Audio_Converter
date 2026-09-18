"""氛围背景层（光晕 + 鼠标交互 + 生成态切换）的结构回归测试。

这些断言锁住三件事：
1. 背景层按契约挂载（#ata-bg / #ata-bg-base / #ata-bg-canvas），并复用现有进度条契约
   （#progress_container 的类名）判断"生成中"，不引入新的 Gradio 组件；
2. 降级路径存在：prefers-reduced-motion、document.hidden、触屏、窄屏、DPR 上限；
3. 毛玻璃只能画在伪元素上——绝不能在 .app-card / .gradio-container 自身上使用
   transform / filter / backdrop-filter / contain（会让 Gradio Dropdown 的 portal
   面板把容器当作 containing block，选项跑到很远的顶部），也不能给 .app-card 加
   overflow: hidden（日志页 xterm 会被裁掉）。

本文件只做字符串/常量断言，不 import gradio，任何解释器都能跑。
"""

import json
import re
import unittest

from audiobook_generator.ui.ambient_background import (
    AMBIENT_CSS,
    AMBIENT_ENABLED,
    AMBIENT_HUE_PALETTE,
    AMBIENT_IDLE_COUNT,
    AMBIENT_IDLE_SPREAD,
    AMBIENT_LAYER_HTML,
)

FORBIDDEN_ON_CONTAINERS = ("transform", "filter", "backdrop-filter", "contain", "will-change")
# 这些取值是"关掉该属性"，不会建立包含块 / 不会裁剪内容
NEUTRAL_VALUES = ("none", "initial", "unset", "revert", "revert-layer", "auto", "visible")


def _css_rules(css):
    """极简 CSS 规则拆分：返回 [(selector, body), ...]，@media 前缀会拼在选择器前。"""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)   # 去掉注释，避免污染选择器
    rules = []
    prefixes = []
    selector = None
    body = None
    buf = ""
    for ch in css:
        if ch == "{":
            if body is None:
                text = buf.strip()
                buf = ""
                if text.startswith("@"):
                    prefixes.append(text)
                else:
                    selector = " ".join(prefixes + [text]).strip()
                    body = ""
                continue
            buf += ch
            continue
        if ch == "}":
            if body is not None:
                rules.append((selector, body))
                selector = None
                body = None
                buf = ""
                continue
            if prefixes:
                prefixes.pop()
            buf = ""
            continue
        if body is None:
            buf += ch
        else:
            body += ch
    return rules


def _declares(body, prop):
    """判断声明块里是否**生效地**声明了某属性。

    1. 按声明位置匹配，避免把 transition 值里的 transform 词算进去；
    2. 取值为 none/auto/... 之类等于关闭该属性（例如 `.app-card { backdrop-filter: none }`
       这种显式重置），不算生效。
    """
    match = re.search(r"(?:^|;)\s*" + re.escape(prop) + r"\s*:\s*([^;]+)", body)
    if not match:
        return False
    value = match.group(1).replace("!important", "").strip().lower()
    return value not in NEUTRAL_VALUES


def _bare_selectors(selector):
    """拆出选择器列表，并剥掉 @media 前缀，便于按 .app-card / .gradio-container 精确匹配"""
    parts = []
    for part in selector.split(","):
        parts.append(re.sub(r"^@[^)]*\)\s*", "", part).strip())
    return parts


class TestAmbientLayerContract(unittest.TestCase):
    def test_layer_html_is_injected_when_enabled(self):
        self.assertTrue(AMBIENT_ENABLED, "默认应启用氛围背景层")
        self.assertIn("__ATA_AMBIENT_CONFIG", AMBIENT_LAYER_HTML)
        self.assertIn("__ataAmbient", AMBIENT_LAYER_HTML)

    def test_layer_mounts_expected_dom(self):
        for token in ('"ata-bg"', '"ata-bg-base"', '"ata-bg-canvas"',
                      "insertBefore", 'setAttribute("aria-hidden", "true")'):
            self.assertIn(token, AMBIENT_LAYER_HTML, "背景层脚本缺少：" + token)

    def test_state_machine_reuses_progress_contract(self):
        for token in ("progress_container", "collapsed", "generating", "arming", "settling",
                      "开始生成", "停止转换", "signalStart", "signalSettle"):
            self.assertIn(token, AMBIENT_LAYER_HTML, "状态机缺少：" + token)
        self.assertIn("MutationObserver", AMBIENT_LAYER_HTML)
        self.assertNotIn("fetch(", AMBIENT_LAYER_HTML)

    def test_click_spread_starts_from_pointer_and_is_angularly_even(self):
        """点「开始生成」时光晕要从鼠标位置、按黄金角均匀散向四周"""
        for token in ("spreadAnchorX", "spreadAnchorY", "angleJitter", "edgeAngle"):
            self.assertIn(token, AMBIENT_LAYER_HTML, "扩散动效缺少：" + token)
        self.assertIn("2.39996323", AMBIENT_LAYER_HTML, "缺少黄金角（保证各方向都有粒子）")
        # 起点必须取自当前鼠标位置
        self.assertIn("spreadAnchorX = mouseX", AMBIENT_LAYER_HTML)
        self.assertIn("spreadAnchorY = mouseY", AMBIENT_LAYER_HTML)
        # 点击后要先重算边缘目标再进入 arming
        start = AMBIENT_LAYER_HTML.index("function signalStart()")
        body = AMBIENT_LAYER_HTML[start:start + 600]
        self.assertIn("assignEdgeTargets()", body)
        self.assertIn('setState("arming")', body)

    def test_banding_mitigations_are_in_place(self):
        """色彩断层的三道防线：色相交叉淡入 + 更密的色相档 + 抖动噪声层"""
        from audiobook_generator.ui.ambient_background import (
            AMBIENT_HUE_COUNT,
            AMBIENT_SPRITE_SIZE,
        )
        self.assertGreaterEqual(AMBIENT_HUE_COUNT, 32, "色相档位太少会出现跳色")
        self.assertGreaterEqual(AMBIENT_SPRITE_SIZE, 224, "sprite 太小放大后会有条带")
        # 相邻两张 sprite 交叉淡入（f 与 1-f 两次绘制）
        self.assertIn("function drawGlowSprite", AMBIENT_LAYER_HTML)
        self.assertIn("a * (1 - f)", AMBIENT_LAYER_HTML)
        self.assertIn("a * f", AMBIENT_LAYER_HTML)
        # 抖动噪声层：预烘焙瓦片 + pattern 平铺
        self.assertIn("function bakeDither", AMBIENT_LAYER_HTML)
        self.assertIn("createPattern", AMBIENT_LAYER_HTML)
        self.assertIn("drawDither", AMBIENT_LAYER_HTML)
        self.assertIn("data[i * 4 + 3] = 6", AMBIENT_LAYER_HTML, "噪声强度应为 ±3/255 级别")

    def test_renders_without_per_frame_gradients(self):
        self.assertIn("drawImage", AMBIENT_LAYER_HTML)
        self.assertIn('globalCompositeOperation = "lighter"', AMBIENT_LAYER_HTML)
        self.assertEqual(AMBIENT_LAYER_HTML.count("createRadialGradient"), 1,
                         "createRadialGradient 只应在预渲染 sprite 时出现一次")

    def test_degradation_paths(self):
        for token in ("prefers-reduced-motion",
                      "visibilitychange", "document.hidden",
                      "devicePixelRatio || 1, 2",
                      '"(pointer: coarse)"',
                      "vw < 720",
                      "cleanup"):
            self.assertIn(token, AMBIENT_LAYER_HTML, "降级路径缺少：" + token)

    def test_config_is_valid_json_and_centralized(self):
        match = re.search(r"window\.__ATA_AMBIENT_CONFIG=(\{.*?\});</script>",
                          AMBIENT_LAYER_HTML, re.DOTALL)
        self.assertIsNotNone(match, "没有找到注入的配置块")
        cfg = json.loads(match.group(1))
        self.assertEqual(cfg["huePalette"], list(AMBIENT_HUE_PALETTE))
        self.assertEqual(cfg["idleCount"], AMBIENT_IDLE_COUNT)
        self.assertEqual(cfg["idleSpread"], AMBIENT_IDLE_SPREAD)
        self.assertTrue(cfg["enabled"])
        for key in ("hueSegmentMs", "hueCount", "spriteSize", "edgePerSide", "armTimeoutMs"):
            self.assertIn(key, cfg)


class TestAmbientCss(unittest.TestCase):
    def test_background_layer_is_fixed_and_click_through(self):
        layer = next((body for sel, body in _css_rules(AMBIENT_CSS)
                      if sel.split(",")[0].strip() == "#ata-bg"), None)
        self.assertIsNotNone(layer, "缺少 #ata-bg 规则")
        self.assertIn("position: fixed", layer)
        self.assertIn("pointer-events: none", layer)
        self.assertIn("z-index: 0", layer)

    def test_content_container_sits_above_layer(self):
        container_rules = [body for sel, body in _css_rules(AMBIENT_CSS)
                           if ".gradio-container" in sel]
        self.assertTrue(container_rules, "缺少 .gradio-container 覆盖规则")
        joined = " ".join(container_rules)
        self.assertIn("z-index: 1", joined)
        self.assertIn("background: transparent !important", joined)

    def test_generating_state_and_modal_dimming(self):
        self.assertIn("#ata-bg.generating #ata-bg-base::after", AMBIENT_CSS)
        self.assertIn("body.modal-open #ata-bg", AMBIENT_CSS)
        self.assertIn("transition: opacity 0.9s", AMBIENT_CSS)

    def test_glass_is_strengthened_on_pseudo_element(self):
        rules = dict(_css_rules(AMBIENT_CSS))
        card_before = rules.get(".app-card::before")
        self.assertIsNotNone(card_before, "卡片毛玻璃必须画在 .app-card::before 上")
        self.assertIn("blur(26px)", card_before)
        # 玻璃底色走主题令牌（浅色/暗色各一套），不能再写死白色
        self.assertIn("var(--ata-glass)", card_before)
        self.assertIn("var(--ata-sheen)", card_before)
        self.assertNotIn("rgba(255,255,255", card_before, "卡片玻璃底色必须用令牌，否则暗色主题会漏白")
        self.assertIn("inset 0 1px 0", card_before)
        self.assertIn("@media (max-width: 720px)", AMBIENT_CSS)
        self.assertIn("blur(18px)", AMBIENT_CSS)

    def test_inner_blocks_do_not_cover_the_glass(self):
        """卡片内部的 Gradio 包装层不能再留白底，否则毛玻璃被整块盖住"""
        rules = _css_rules(AMBIENT_CSS)
        transparent = [sel for sel, body in rules
                       if "transparent !important" in body and ".app-card ." in sel]
        joined = " ".join(transparent)
        for sel in (".app-card .block", ".app-card .wrap", ".app-card .form",
                    ".app-card .panel", ".app-card .gr-group"):
            self.assertIn(sel, joined, f"缺少内部白底清理规则：{sel}")
        # 下拉选项面板是 fixed 定位，必须保持不透明，不能被上面这批规则误伤
        for sel, _body in rules:
            self.assertNotIn("options", sel,
                             "不能给下拉选项面板（ul.options）加背景覆盖规则")
        # 交互面改成半透明白
        self.assertIn(".app-card .btn-ghost", AMBIENT_CSS)
        self.assertIn("var(--ata-glass-soft)", AMBIENT_CSS)
        self.assertIn(".app-card .xterm-viewport", AMBIENT_CSS)

    def test_no_containing_block_properties_on_cards_or_container(self):
        for selector, body in _css_rules(AMBIENT_CSS):
            for token in _bare_selectors(selector):
                if token not in (".app-card", ".gradio-container"):
                    continue
                for prop in FORBIDDEN_ON_CONTAINERS:
                    self.assertFalse(
                        _declares(body, prop),
                        token + " 上不能声明 " + prop +
                        "（会让 fixed 后代以它为包含块，Gradio Dropdown 选项面板定位错乱）")
                self.assertFalse(_declares(body, "overflow"),
                                 token + " 上不能声明 overflow（日志页终端会被裁剪）")


if __name__ == "__main__":
    unittest.main()
