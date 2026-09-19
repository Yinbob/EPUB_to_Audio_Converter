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

    def test_light_field_diagnostics_are_exposed(self):
        """调参要靠光场快照，不能靠截图：dataset.field + __ataAmbient.profile 都得在"""
        self.assertIn("profileAt(focusX, focusY)", AMBIENT_LAYER_HTML)
        self.assertIn('layer.dataset.field =', AMBIENT_LAYER_HTML)
        # 快照字段顺序：峰值|峰值x|峰值y|gather|blend|聚集度|重心x|重心y|rms|focusX|focusY|同心环
        for token in ("(prof.peak * 1000 | 0)", "(massCx | 0)", "(massRms | 0)",
                      "prof.rings.map"):
            self.assertIn(token, AMBIENT_LAYER_HTML, "光场快照缺少：" + token)
        self.assertIn("profile: function (px, py)", AMBIENT_LAYER_HTML)
        self.assertIn("RING_EDGES", AMBIENT_LAYER_HTML)

    def test_state_machine_reuses_progress_contract(self):
        for token in ("progress_container", "collapsed", "generating", "arming", "settling",
                      "开始生成", "停止转换", "signalStart", "signalSettle"):
            self.assertIn(token, AMBIENT_LAYER_HTML, "状态机缺少：" + token)
        self.assertIn("MutationObserver", AMBIENT_LAYER_HTML)
        self.assertNotIn("fetch(", AMBIENT_LAYER_HTML)

    def test_hue_cycle_is_closed_loop_and_smooth(self):
        """色相循环必须首尾相接 + Catmull-Rom 插值，否则回到起点时会瞬间跳色"""
        for token in ("(i - 1 + n) % n", "(i + 1) % n", "(i + 2) % n",
                      "(-p0 + p2) * f", "(2 * p0 - 5 * p1 + 4 * p2 - p3) * f2",
                      "(-p0 + 3 * p1 - 3 * p2 + p3) * f3",
                      "(CFG.hueSegmentMs || 10000) * n"):
            self.assertIn(token, AMBIENT_LAYER_HTML, "色相循环缺少：" + token)
        # 旧的"线性扫过 + 直接回绕"写法必须消失（它会在 288 → 212 处跳 ~76°）
        self.assertNotIn("pal[i] + (pal[i + 1] - pal[i])", AMBIENT_LAYER_HTML)
        self.assertNotIn("f * f * (3 - 2 * f)", AMBIENT_LAYER_HTML)

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
        """断层的防线：浮点光场（只量化一次）+ 细色相表 + 抖动噪声层"""
        from audiobook_generator.ui.ambient_background import (
            AMBIENT_HUE_COUNT,
            AMBIENT_SPRITE_SIZE,
        )
        self.assertTrue(AMBIENT_HUE_COUNT >= 32)
        self.assertTrue(AMBIENT_SPRITE_SIZE >= 128)
        # 光场：浮点累加 + 只在最后量化一次 + 色相查表线性插值
        self.assertIn("new Float32Array", AMBIENT_LAYER_HTML, "缺少浮点光场缓冲")
        self.assertIn("fieldR[idx] += cr * k", AMBIENT_LAYER_HTML)
        self.assertIn("putImageData", AMBIENT_LAYER_HTML, "光场应只在这里量化一次")
        self.assertIn("hueLUT[j0]", AMBIENT_LAYER_HTML, "色相应查表 + 线性插值")
        # 抖动噪声层：预烘焙瓦片 + pattern 平铺（display 分辨率上叠）
        self.assertIn("function bakeDither", AMBIENT_LAYER_HTML)
        self.assertIn("createPattern", AMBIENT_LAYER_HTML)
        self.assertIn("drawDither", AMBIENT_LAYER_HTML)
        self.assertIn("data[i * 4 + 3] = 6", AMBIENT_LAYER_HTML, "噪声强度应为 ±3/255 级别")
        # 不能再回到"叠预渲染 sprite"的老路：那正是叠加边界/色带的来源
        self.assertNotIn("drawImage(sprites", AMBIENT_LAYER_HTML)
        self.assertNotIn("createRadialGradient", AMBIENT_LAYER_HTML)

    def test_soft_glow_is_kept_and_stays_smooth(self):
        """柔光光晕的观感要保留（大半径、低透明度叠加），同时必须没有色带/硬边"""
        from audiobook_generator.ui.ambient_background import (
            AMBIENT_HUE_COUNT,
            AMBIENT_IDLE_COUNT,
            AMBIENT_IDLE_SPREAD,
        )
        # 少量大半径光斑 + 中心弥散光 = 柔和光晕（不是一堆清晰小圆点）
        self.assertLessEqual(AMBIENT_IDLE_COUNT, 80, "粒子过多会变成颗粒感，不是光晕")
        self.assertGreaterEqual(AMBIENT_IDLE_SPREAD, 300)
        # 半径用区间断言（数值允许调优，但必须保持"大半径柔光"这一性质）
        m = re.search(
            r"idleSize: isCore \? rand\((\d+), (\d+)\) : rand\((\d+), (\d+)\)",
            AMBIENT_LAYER_HTML)
        self.assertIsNotNone(m, "找不到粒子半径设置")
        self.assertGreaterEqual(int(m.group(1)), 100, "核心光斑半径应保持大半径柔光")
        self.assertGreaterEqual(int(m.group(2)), 200)
        self.assertGreaterEqual(int(m.group(3)), 100, "主体光斑半径应保持大半径柔光")
        self.assertGreaterEqual(int(m.group(4)), 180)
        # 中心弥散光必须跟着鼠标走：早先画在家位置，鼠标挪开后正中会残留浅色圆
        self.assertIn("splat(baseX, baseY", AMBIENT_LAYER_HTML, "中心弥散光不能丢")
        self.assertIn("cx + (focusX - cx) * g", AMBIENT_LAYER_HTML, "中心弥散光要跟随光标")
        # 鼠标移出页面时（g→0）中心光要淡出，只留散开的粒子
        self.assertIn("centerAlpha > 0.002 && g > 0.02", AMBIENT_LAYER_HTML)
        # 光束要锚在"粒子团重心"上，不能直接跟光标：否则快速移动时粒子还在路上、
        # 光束已先到光标 → 看起来就是"鼠标上粘了一团光，其余的再挪过去"
        self.assertIn("massX += p.x * w", AMBIENT_LAYER_HTML)
        self.assertIn("massY += p.y * w", AMBIENT_LAYER_HTML)
        self.assertIn("massCx = massX / massW", AMBIENT_LAYER_HTML)
        self.assertIn("baseX = massCx", AMBIENT_LAYER_HTML)
        # 中心亮度还要乘"聚集度"：云团还没聚起来时不能先冒出一个亮核
        self.assertIn("massRms", AMBIENT_LAYER_HTML)
        self.assertIn("var beam = centerAlpha * g * conc", AMBIENT_LAYER_HTML)
        # 粒子位置必须先更新（重心才有效），再画中心光束
        self.assertLess(AMBIENT_LAYER_HTML.index("massX += p.x * w"),
                        AMBIENT_LAYER_HTML.index("splat(baseX, baseY"),
                        "必须先更新粒子位置求重心，再画中心光束")
        # 衰减曲线必须是高斯（exp(-3t)），保证叠加后仍是一整团、看不出圈边
        self.assertIn("Math.exp(-3 *", AMBIENT_LAYER_HTML)
        # 抗断层组件必须同时在位
        self.assertIn("createPattern", AMBIENT_LAYER_HTML, "缺少抖动噪声层")
        self.assertIn("new Float32Array", AMBIENT_LAYER_HTML, "缺少浮点光场")
        # 呼吸幅度收小，避免整片背景一跳一跳
        self.assertIn("0.94 + 0.06 * Math.sin", AMBIENT_LAYER_HTML)

    def test_renders_without_per_frame_gradients(self):
        """每帧只做「浮点累加 + 一次 putImageData + 一次 drawImage」，不创建任何渐变对象"""
        self.assertEqual(AMBIENT_LAYER_HTML.count("createRadialGradient"), 0,
                         "光场实现不应再创建径向渐变（那是叠加边界/色带的来源）")
        self.assertEqual(AMBIENT_LAYER_HTML.count("putImageData"), 2,
                         "只有光场量化与抖动瓦片两处会写 ImageData")
        self.assertIn("ctx.drawImage(fieldCanvas", AMBIENT_LAYER_HTML)
        # 叠加发生在浮点域（fieldR/G/B += ...），不再靠 canvas 的 lighter 合成
        self.assertNotIn('globalCompositeOperation = "lighter"', AMBIENT_LAYER_HTML)

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
