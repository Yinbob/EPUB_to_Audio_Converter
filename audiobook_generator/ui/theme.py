"""深色 / 浅色双主题：设计令牌、暗色覆盖、主题切换脚本。

为什么能一套 CSS 出两套皮：整站颜色基本都走 ``var(--apple-*)``，所以只要把同一批
变量在暗色下重新赋值，绝大多数组件自动跟随。暗色选择器用 ``:root .dark, :root.dark``——
前者正是 Gradio 自己的暗色钩子（``body.dark``，见 gradio 主题生成器写出的 ``:root .dark{}``），
这样我们的令牌和 Gradio 组件（下拉、滑块、勾选）会一起翻转，不会一半亮一半暗。

主题模式：``auto``（跟随系统，默认）/ ``light`` / ``dark``，存在 localStorage ``ata-theme``，
由顶栏的 ``#ata-theme-toggle`` 按钮循环切换。显式选择后即使用户改系统主题也不跟随；
auto 模式下监听 ``prefers-color-scheme`` 变化。

本模块是纯字符串常量（不 import gradio），任何解释器都能直接 import 做单测。
"""

THEME_STORAGE_KEY = "ata-theme"

# ── 令牌：浅色（默认）与暗色两套值 ──
THEME_TOKENS_CSS = """
:root {
  /* 底色与表面 */
  --apple-bg: #f5f5f7;
  --apple-surface: #ffffff;
  --apple-surface-2: #fbfbfd;
  /* 文字三档：主 / 次 / 弱，两套主题都保证在各自背景上有足够对比度 */
  --apple-text: #1d1d1f;
  --apple-text-2: #5f5f66;
  --apple-text-3: #6a6a72;
  /* 描边 */
  --apple-border: #d2d2d7;
  --apple-border-soft: #e8e8ed;
  /* 强调色 */
  --apple-blue: #0071e3;
  --apple-blue-hover: #0077ed;
  --apple-blue-soft: #e8f1fd;
  --apple-indigo: #5e5ce6;
  --apple-green: #1f7a35;
  --apple-red: #d70015;
  --apple-amber: #b25000;
  /* 毛玻璃与半透明面 */
  --ata-glass: rgba(255,255,255,0.58);          /* 卡片 */
  --ata-glass-header: rgba(251,251,253,0.62);   /* 顶栏 */
  --ata-glass-strong: rgba(255,255,255,0.62);   /* 进度条 */
  --ata-glass-soft: rgba(255,255,255,0.45);     /* 控件 / 输入框 */
  --ata-glass-soft-2: rgba(255,255,255,0.55);   /* 弹窗内输入框 */
  --ata-glass-modal: rgba(255,255,255,0.82);    /* 弹窗玻璃 */
  --ata-sheen: linear-gradient(180deg, rgba(255,255,255,0.22), rgba(255,255,255,0) 42%);
  --ata-glass-edge: rgba(255,255,255,0.70);   /* 玻璃上沿高光 */
  --ata-glass-ring: rgba(255,255,255,0.35);   /* 玻璃内描边 */
  --ata-track: rgba(0,0,0,0.06);                /* 进度轨 / 开关底 */
  --ata-hover: rgba(0,0,0,0.04);
  --ata-hover-strong: rgba(0,0,0,0.07);
  --ata-ripple: rgba(0,0,0,0.14);
  --ata-empty: rgba(255,255,255,0.35);
  --ata-terminal: rgba(255,255,255,0.42);
  --ata-book-chip: var(--apple-surface-2);
  /* 语义提示块 */
  --ata-ready-bg: linear-gradient(135deg,#f0f9ff,#f0eefe);
  --ata-ready-border: #cfe3fc;
  --ata-ready-title: #0369a1;
  --ata-ready-text: #0c4a6e;
  --ata-danger-bg: #fff0ef;
  --ata-danger-border: #ffd1ce;
  --ata-warn-bg: #fff8e1;
  --ata-scrim: rgba(0,0,0,0.08);
  /* 阴影 */
  --apple-shadow: 0 1px 2px rgba(0,0,0,0.04), 0 8px 24px rgba(0,0,0,0.04);
  --apple-shadow-lg: 0 24px 60px rgba(0,0,0,0.14);
  --apple-shadow-blue: 0 8px 20px rgba(0,113,227,0.28);
  --ata-shadow-hover: 0 1px 2px rgba(0,0,0,0.04), 0 16px 40px rgba(0,0,0,0.07);
  --radius: 20px;
  --radius-sm: 14px;
  /* 对齐 Gradio 自带变量：默认 slate-400（#94a3b8）在浅底上只有 2.48:1，
     滑块 min/max、info、占位符都吃这几个变量，必须换成本项目的文字令牌。 */
  --body-text-color: var(--apple-text);
  --body-text-color-subdued: var(--apple-text-3);
  --block-info-text-color: var(--apple-text-3);
  --block-label-text-color: var(--apple-text-2);
  --block-title-text-color: var(--apple-text-2);
  --input-placeholder-color: var(--apple-text-3);
  --checkbox-label-text-color: var(--apple-text);
  --link-text-color: var(--apple-text-2);
  --color-accent: var(--apple-blue);
  --color-accent-soft: var(--apple-blue-soft);
}

/* 暗色：与 Gradio 的 <body class="dark"> 同步（html.dark 用于首屏不闪白） */
:root .dark,
:root.dark {
  --apple-bg: #0e0e12;
  --apple-surface: #1c1c22;
  --apple-surface-2: #232329;
  --apple-text: #f5f5f7;
  --apple-text-2: #c3c3c9;
  --apple-text-3: #a5a5ad;
  --apple-border: #3a3a42;
  --apple-border-soft: #2c2c33;
  --apple-blue: #409cff;
  --apple-blue-hover: #63b0ff;
  --apple-blue-soft: rgba(64,156,255,0.18);
  --apple-indigo: #9a97ff;
  --apple-green: #4cd964;
  --apple-red: #ff8a82;
  --apple-amber: #ffb340;
  --ata-glass: rgba(30,30,37,0.62);
  --ata-glass-header: rgba(18,18,23,0.68);
  --ata-glass-strong: rgba(32,32,39,0.66);
  --ata-glass-soft: rgba(255,255,255,0.07);
  --ata-glass-soft-2: rgba(255,255,255,0.10);
  --ata-glass-modal: rgba(24,24,30,0.86);
  --ata-sheen: linear-gradient(180deg, rgba(255,255,255,0.06), rgba(255,255,255,0) 42%);
  --ata-glass-edge: rgba(255,255,255,0.12);
  --ata-glass-ring: rgba(255,255,255,0.06);
  --ata-track: rgba(255,255,255,0.16);
  --ata-hover: rgba(255,255,255,0.08);
  --ata-hover-strong: rgba(255,255,255,0.13);
  --ata-ripple: rgba(255,255,255,0.22);
  --ata-empty: rgba(255,255,255,0.05);
  --ata-terminal: rgba(10,10,14,0.55);
  --ata-book-chip: rgba(255,255,255,0.07);
  --ata-ready-bg: linear-gradient(135deg, rgba(64,156,255,0.16), rgba(154,151,255,0.14));
  --ata-ready-border: rgba(100,170,255,0.35);
  --ata-ready-title: #9ecbff;
  --ata-ready-text: #d6e7ff;
  --ata-danger-bg: rgba(255,105,97,0.16);
  --ata-danger-border: rgba(255,105,97,0.42);
  --ata-warn-bg: rgba(255,179,64,0.16);
  --ata-scrim: rgba(0,0,0,0.55);
  --apple-shadow: 0 1px 2px rgba(0,0,0,0.5), 0 8px 24px rgba(0,0,0,0.45);
  --apple-shadow-lg: 0 24px 60px rgba(0,0,0,0.6);
  --apple-shadow-blue: 0 8px 20px rgba(0,80,180,0.45);
  --ata-shadow-hover: 0 1px 2px rgba(0,0,0,0.5), 0 16px 40px rgba(0,0,0,0.5);
}

/* Gradio 的暗色变量写在 `:root .dark{}`（(0,2,0)）；这里用 :root:root 提高一级特异性，
   保证"文字/强调色必须用我们的令牌"这条在任何注入顺序下都成立。 */
:root:root .dark,
:root:root.dark {
  --body-text-color: var(--apple-text);
  --body-text-color-subdued: var(--apple-text-3);
  --block-info-text-color: var(--apple-text-3);
  --block-label-text-color: var(--apple-text-2);
  --block-title-text-color: var(--apple-text-2);
  --input-placeholder-color: var(--apple-text-3);
  --checkbox-label-text-color: var(--apple-text);
  --link-text-color: var(--apple-text-2);
  --color-accent: var(--apple-blue);
  --color-accent-soft: var(--apple-blue-soft);
}
"""

# ── 需要单独照顾的组件（令牌覆盖不到的部分） ──
THEME_CSS = """
/* 暗色下环境光渐变要更"发光"一点，否则深底上几乎看不见 */
:root .dark #ata-bg-base,
:root.dark #ata-bg-base {
  background:
    radial-gradient(58% 38% at 10% 0%, rgba(64,156,255,0.16), transparent 72%),
    radial-gradient(48% 34% at 92% 4%, rgba(154,151,255,0.15), transparent 72%),
    radial-gradient(46% 32% at 50% 100%, rgba(76,217,100,0.10), transparent 72%);
}
:root .dark #ata-bg-base::after,
:root.dark #ata-bg-base::after {
  background:
    radial-gradient(58% 38% at 10% 0%, rgba(64,156,255,0.13), transparent 72%),
    radial-gradient(48% 34% at 92% 4%, rgba(154,151,255,0.12), transparent 72%),
    radial-gradient(46% 32% at 50% 100%, rgba(76,217,100,0.08), transparent 72%);
}
:root .dark body,
:root.dark body {
  background-color: var(--apple-bg) !important;
  background-image:
    radial-gradient(58% 38% at 10% 0%, rgba(64,156,255,0.09), transparent 72%),
    radial-gradient(48% 34% at 92% 4%, rgba(154,151,255,0.08), transparent 72%),
    radial-gradient(46% 32% at 50% 100%, rgba(76,217,100,0.05), transparent 72%) !important;
}

/* 日志终端：xterm 用 canvas 画字、主题色写死在组件里（浅底深字），
   暗色下把"文字画布"整体反相得到深底浅字；hue-rotate 近似保留日志级别配色。
   ⚠️ 只反相 .xterm-screen（画字那一层）：如果连 .xterm 一起反，会把我们给
   .xterm-viewport 设的暗色底又反成浅色，终端就成了一块亮板。 */
:root .dark .xterm-screen,
:root.dark .xterm-screen { filter: invert(1) hue-rotate(180deg); }
:root .dark .app-card .xterm-viewport,
:root.dark .app-card .xterm-viewport { background: var(--ata-terminal) !important; }

/* 进度条激活态：浅色下 5% 的蓝色叠加已经够看，深色下几乎不可见，单独加深 */
:root .dark .progress-container.active,
:root.dark .progress-container.active {
  background: linear-gradient(135deg, rgba(64,156,255,0.16), rgba(154,151,255,0.14)) !important;
  border-color: rgba(64,156,255,0.34) !important;
  box-shadow: 0 10px 30px rgba(0,0,0,0.45) !important;
}

/* 顶栏主题切换按钮 */
.ata-theme-toggle {
  display: inline-flex; align-items: center; gap: 6px;
  height: 34px; padding: 0 12px; margin-left: auto;
  border-radius: 980px; cursor: pointer;
  border: 1px solid var(--apple-border-soft);
  background: var(--ata-glass-soft); color: var(--apple-text);
  font-size: 0.8rem; font-weight: 500; line-height: 1;
  transition: background 0.2s ease, border-color 0.2s ease, transform 0.2s ease;
}
.ata-theme-toggle:hover { background: var(--ata-hover-strong); border-color: var(--apple-border); }
.ata-theme-toggle:active { transform: scale(0.97); }
.ata-theme-toggle .ata-theme-icon { font-size: 0.95rem; }

/* 暗色下输入类控件的文字/占位符要有足够对比度 */
:root .dark input::placeholder,
:root .dark textarea::placeholder,
:root.dark input::placeholder,
:root.dark textarea::placeholder { color: var(--apple-text-3) !important; }

/* ── 标签页悬停：Gradio 默认给的是实心填充（浅色下 rgb(248,250,252)，像贴了一块白框），
   改成毛玻璃高亮 —— 半透明底 + 轻微模糊 + 一圈内描边，和卡片玻璃同一套观感。
   `.visually-hidden` 的那个是 Gradio 的隐形导航，跳过它。 ── */
.tab-container:not(.visually-hidden) button:hover,
.tab-container:not(.visually-hidden) button.selected:hover {
  background: var(--ata-glass-soft) !important;
  -webkit-backdrop-filter: saturate(180%) blur(14px);
  backdrop-filter: saturate(180%) blur(14px);
  color: var(--apple-text) !important;
  border-radius: 10px !important;
  box-shadow: inset 0 0 0 1px var(--ata-glass-ring) !important;
}
"""


THEME_HEAD_HTML = """
<script>
(function () {
  var KEY = "__ATA_THEME_KEY__";
  var mq = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  var mode = "auto";
  try { var saved = window.localStorage.getItem(KEY); if (saved) mode = saved; } catch (e) {}
  // 尽力尊重 Gradio 的 ?__theme=dark|light（与它前端的行为保持一致）：
  // 注意 Gradio 前端可能在注入本脚本前就把参数从 URL 里去掉了，读不到时退回本地记忆/系统偏好
  try {
    var fromUrl = /[?&]__theme=(dark|light)\b/.exec(window.location.search);
    if (fromUrl) { mode = fromUrl[1]; }
  } catch (e) {}
  if (mode !== "light" && mode !== "dark") mode = "auto";

  function systemDark() { return !!(mq && mq.matches); }
  function isDark() { return mode === "dark" || (mode === "auto" && systemDark()); }

  function apply() {
    var dark = isDark();
    var root = document.documentElement;
    if (dark) root.classList.add("dark"); else root.classList.remove("dark");
    root.setAttribute("data-ata-theme", mode);
    if (document.body) {
      if (dark) document.body.classList.add("dark"); else document.body.classList.remove("dark");
    }
    var label = document.getElementById("ata-theme-label");
    var icon = document.getElementById("ata-theme-icon");
    if (label) label.textContent = mode === "auto" ? "跟随系统" : (mode === "dark" ? "深色" : "浅色");
    if (icon) icon.textContent = dark ? "🌙" : "☀️";
    var btn = document.getElementById("ata-theme-toggle");
    if (btn) btn.setAttribute("title", "当前：" + (mode === "auto" ? "跟随系统" : mode === "dark" ? "深色" : "浅色") + "（点击切换 自动 → 浅色 → 深色）");
    try {
      document.dispatchEvent(new CustomEvent("ata-theme-change", { detail: { dark: dark, mode: mode } }));
    } catch (e) {}
  }

  function set(next) {
    mode = (next === "light" || next === "dark") ? next : "auto";
    try { window.localStorage.setItem(KEY, mode); } catch (e) {}
    apply();
  }

  function cycle() { set(mode === "auto" ? "light" : mode === "light" ? "dark" : "auto"); }

  window.__ataTheme = { get: function () { return mode; }, isDark: isDark, set: set, cycle: cycle, apply: apply };

  // 顶栏按钮是后渲染的，用事件委托更稳
  document.addEventListener("click", function (e) {
    var t = e.target;
    if (!t || !t.closest) return;
    if (t.closest("#ata-theme-toggle")) { cycle(); }
  }, true);

  if (mq && mq.addEventListener) {
    mq.addEventListener("change", function () { if (mode === "auto") apply(); });
  }

  // Gradio 挂载时会按系统偏好自己加/去 body.dark；用户显式选过就把它纠回来
  var observer = null;
  function watch() {
    if (observer || !document.body) return;
    observer = new MutationObserver(function () {
      if (mode === "auto") return;
      var want = isDark();
      if (document.body.classList.contains("dark") !== want) apply();
    });
    observer.observe(document.body, { attributes: true, attributeFilter: ["class"] });
  }

  apply();
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { apply(); watch(); });
  } else {
    watch();
  }
  window.setTimeout(function () { apply(); watch(); }, 400);
  window.setTimeout(function () { apply(); watch(); }, 1600);
  window.setTimeout(function () { apply(); watch(); }, 3200);
})();
</script>
""".replace("__ATA_THEME_KEY__", THEME_STORAGE_KEY)
