"""深浅双主题的结构与对比度回归测试。

两条硬要求：
1. 浅色 / 暗色两套令牌都必须存在，且暗色选择器要和 Gradio 的暗色钩子一致
   （``:root .dark`` = ``body.dark``），否则会出现"我们的样式变暗、Gradio 组件还是亮的"；
2. 文字与背景的对比度要达标（WCAG AA：正文 ≥ 4.5:1，次要文字 ≥ 3:1），
   这条直接在单元测试里算，避免以后改配色把可读性改坏。

只做字符串/常量断言，不 import gradio。
"""

import re
import unittest

from audiobook_generator.ui.theme import (
    THEME_CSS,
    THEME_HEAD_HTML,
    THEME_STORAGE_KEY,
    THEME_TOKENS_CSS,
)

LIGHT_SELECTOR = ":root {\n"
DARK_SELECTOR = ":root .dark,"


def _block(css, selector):
    idx = css.index(selector)
    start = css.index("{", idx) + 1
    end = css.index("}", start)
    return css[start:end]


def _token(css, selector, name):
    body = _block(css, selector)
    match = re.search(r"--" + re.escape(name) + r"\s*:\s*([^;]+);", body)
    return match.group(1).strip() if match else None


def _rgb(value):
    value = value.strip()
    if value.startswith("#"):
        h = value.lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    nums = [float(n) for n in re.findall(r"[\d.]+", value)]
    return tuple(int(n) for n in nums[:3])


def _rgba(value):
    nums = [float(n) for n in re.findall(r"[\d.]+", value)]
    r, g, b = (int(n) for n in nums[:3])
    a = nums[3] if len(nums) > 3 else 1.0
    return r, g, b, a


def _over(fg_rgba, bg_rgb):
    r, g, b, a = fg_rgba
    return tuple(round(f * a + bg * (1 - a)) for f, bg in zip((r, g, b), bg_rgb))


def _contrast(fg, bg):
    def lum(c):
        def f(v):
            v /= 255.0
            return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
        r, g, b = c
        return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
    a, b = lum(fg), lum(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


class TestThemeTokens(unittest.TestCase):
    def test_dark_selector_follows_gradio_hook(self):
        # Gradio 自己的暗色变量写在 `:root .dark{}`，即 body.dark；我们必须挂同一个钩子
        self.assertIn(DARK_SELECTOR, THEME_TOKENS_CSS)
        self.assertIn(":root.dark", THEME_TOKENS_CSS, "html.dark 用于首屏不闪白")

    def test_both_palettes_define_the_same_keys(self):
        light = set(re.findall(r"--([\w-]+)\s*:", _block(THEME_TOKENS_CSS, LIGHT_SELECTOR)))
        # 暗色分两块：调色板 + 需要更高特异性的 Gradio 变量重映射
        dark = set()
        for sel in (DARK_SELECTOR, ":root:root .dark,"):
            dark |= set(re.findall(r"--([\w-]+)\s*:", _block(THEME_TOKENS_CSS, sel)))
        self.assertTrue(light)
        # 纯几何令牌（圆角等）与主题无关，不要求暗色重复声明
        geometry_only = {"radius", "radius-sm"}
        missing = light - dark - geometry_only
        self.assertFalse(missing, f"暗色缺少这些令牌：{sorted(missing)}")

    def _ratios(self, selector):
        bg = _rgb(_token(THEME_TOKENS_CSS, selector, "apple-bg"))
        glass = _over(_rgba(_token(THEME_TOKENS_CSS, selector, "ata-glass")), bg)
        out = {}
        for key in ("apple-text", "apple-text-2", "apple-text-3"):
            fg = _rgb(_token(THEME_TOKENS_CSS, selector, key))
            out[key] = (_contrast(fg, bg), _contrast(fg, glass))
        return out

    def test_light_theme_contrast(self):
        ratios = self._ratios(LIGHT_SELECTOR)
        self.assertGreaterEqual(ratios["apple-text"][0], 4.5)
        self.assertGreaterEqual(ratios["apple-text-2"][0], 4.5, "次要文字也要 ≥4.5:1")
        self.assertGreaterEqual(ratios["apple-text-3"][0], 4.5, "弱化文字同样按正文标准 ≥4.5:1")
        # 玻璃面板上的文字：卡片玻璃是半透明，压过底色后仍要够对比
        self.assertGreaterEqual(ratios["apple-text"][1], 4.5)
        self.assertGreaterEqual(ratios["apple-text-3"][1], 4.5)

    def test_dark_theme_contrast(self):
        ratios = self._ratios(DARK_SELECTOR)
        self.assertGreaterEqual(ratios["apple-text"][0], 4.5)
        self.assertGreaterEqual(ratios["apple-text-2"][0], 4.5, "暗色次要文字也要 ≥4.5:1")
        self.assertGreaterEqual(ratios["apple-text-3"][0], 4.5, "暗色弱化文字同样 ≥4.5:1")
        self.assertGreaterEqual(ratios["apple-text"][1], 4.5, "暗色玻璃面板上文字要够对比")
        self.assertGreaterEqual(ratios["apple-text-3"][1], 4.5)

    def test_gradio_text_variables_follow_our_tokens(self):
        for selector in (LIGHT_SELECTOR, ":root:root .dark,"):
            body = _block(THEME_TOKENS_CSS, selector)
            for gradio_var, token in (("body-text-color-subdued", "--apple-text-3"),
                                      ("block-info-text-color", "--apple-text-3"),
                                      ("input-placeholder-color", "--apple-text-3"),
                                      ("block-label-text-color", "--apple-text-2"),
                                      ("body-text-color", "--apple-text")):
                self.assertIn(f"--{gradio_var}: var({token})", body,
                              f"{selector} 里没有把 --{gradio_var} 接到 {token}")

    def test_status_colors_are_readable_on_glass(self):
        """状态色也当文字用（进度百分比、失败/完成文案），必须和玻璃底拉开对比度"""
        for selector, name in ((LIGHT_SELECTOR, "浅色"), (DARK_SELECTOR, "深色")):
            bg = _rgb(_token(THEME_TOKENS_CSS, selector, "apple-bg"))
            glass = _over(_rgba(_token(THEME_TOKENS_CSS, selector, "ata-glass")), bg)
            for token_name in ("apple-blue", "apple-green", "apple-red", "apple-text-2"):
                fg = _rgb(_token(THEME_TOKENS_CSS, selector, token_name))
                ratio = _contrast(fg, glass)
                self.assertGreaterEqual(
                    ratio, 4.5, f"{name}主题 {token_name} 在玻璃底上只有 {ratio:.2f}:1")

    def test_dark_theme_covers_hardcoded_pieces(self):
        # xterm 终端是浅底深字且主题写死在组件里，暗色下要反相；环境光渐变要单独给暗色值
        self.assertIn("invert(1) hue-rotate(180deg)", THEME_CSS)
        self.assertIn("#ata-bg-base", THEME_CSS)

    def test_tab_hover_uses_glass_instead_of_solid_fill(self):
        """Gradio 默认给标签页 hover 实心填充（浅色下像一块白框），必须换成毛玻璃"""
        self.assertIn(".tab-container:not(.visually-hidden) button:hover", THEME_CSS)
        idx = THEME_CSS.index(".tab-container:not(.visually-hidden) button:hover")
        rule = THEME_CSS[idx:idx + 400]
        self.assertIn("var(--ata-glass-soft)", rule)
        self.assertIn("backdrop-filter", rule)
        self.assertIn("var(--ata-glass-ring)", rule)


class TestThemeToggle(unittest.TestCase):
    def test_toggle_script_contract(self):
        self.assertIn(THEME_STORAGE_KEY, THEME_HEAD_HTML)
        self.assertIn("ata-theme-toggle", THEME_HEAD_HTML)
        self.assertIn("ata-theme-change", THEME_HEAD_HTML)
        self.assertIn("prefers-color-scheme", THEME_HEAD_HTML)
        # 自动 → 浅色 → 深色 循环，并且要同步 body.dark 让 Gradio 组件一起翻转
        self.assertIn('mode === "auto" ? "light" : mode === "light" ? "dark" : "auto"', THEME_HEAD_HTML)
        self.assertIn('document.body.classList.add("dark")', THEME_HEAD_HTML)
        self.assertIn('document.body.classList.remove("dark")', THEME_HEAD_HTML)
        self.assertIn("__ataTheme", THEME_HEAD_HTML)
        # Gradio 自己的 ?__theme=dark 参数要被尊重，不能被我们的记忆值覆盖
        self.assertIn("__theme=", THEME_HEAD_HTML)


if __name__ == "__main__":
    unittest.main()
