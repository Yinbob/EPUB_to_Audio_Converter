"""氛围背景层：固定全屏 canvas 光晕 + 鼠标交互 + 生成态切换。

设计目标（参考 travel-agent 的 ambient glow，按本项目的浅色苹果风重做）：
- 空闲态：屏幕中上部一团柔和彩光，随鼠标收束（粒子向光标聚拢、范围收小、
  亮度上升），鼠标离开后缓慢漂移回位；
- 生成态：点「开始生成」后光晕在约 1 秒内散向视口四周边框，边缘光晕缓慢呼吸，
  生成中鼠标只保留约 15% 的参与度（轻微牵引 + 提亮）；
- 结束态：完成 / 失败 / 停止后约 1.5 秒平滑回落到空闲态。

实现要点：
- 背景层挂在 ``document.body`` 首个子节点上（``position: fixed``），
  页面脚本仍注入在 ``head``，不新增任何 Gradio 组件，页面重渲染不受影响；
- 触发源复用现有契约 ``#progress_container`` 的类名（idle/active/starting/running/
  done/warn/collapsed）与 ``#progress_state`` 载荷，后端逻辑一行不改；
- 光晕用**预渲染 sprite**（24 个色相 × 2 种衰减曲线）逐帧 ``drawImage`` 绘制，
  避免每帧为每个粒子新建 ``createRadialGradient``（travel-agent 的做法，粒子多时偏重）；
- 降级：``prefers-reduced-motion`` 只画静态帧、``document.hidden`` 暂停渲染循环、
  触屏（``pointer: coarse``）关闭收束改为缓慢自动漂移、DPR 上限 2、窄屏粒子减半。

本模块是纯字符串常量（不 import gradio / 第三方库），任何解释器都能直接 import 做单测。
"""

import json

# 一键关闭动画层（置 False 时 head 里不再注入脚本，静态渐变兜底仍在）
AMBIENT_ENABLED = True

# ── 视觉参数（JS 侧通过 window.__ATA_AMBIENT_CONFIG 读取，Python 侧便于单测断言） ──
AMBIENT_HUE_PALETTE = (212, 250, 196, 288)   # 浅色苹果风的蓝 / 靛 / 青 / 紫
AMBIENT_HUE_SEGMENT_MS = 10000               # 每段色相停留时长（整轮 = 段数-1 倍）
AMBIENT_HUE_COUNT = 24                       # 预渲染 sprite 的色相数量
AMBIENT_SPRITE_SIZE = 160                    # 单张 sprite 的边长（px）
AMBIENT_IDLE_COUNT = 42                      # 空闲态粒子数
AMBIENT_IDLE_CORE_COUNT = 8                  # 其中贴近核心的粒子数
AMBIENT_IDLE_SPREAD = 380                    # 空闲态粒子扩散半径（px）
AMBIENT_EDGE_PER_SIDE = 12                   # 生成态每条边的边缘粒子数
AMBIENT_ARM_TIMEOUT_MS = 6000                # 点「开始生成」后等不到真实状态的兜底回退时长

_CONFIG = {
    "enabled": AMBIENT_ENABLED,
    "huePalette": list(AMBIENT_HUE_PALETTE),
    "hueSegmentMs": AMBIENT_HUE_SEGMENT_MS,
    "hueCount": AMBIENT_HUE_COUNT,
    "spriteSize": AMBIENT_SPRITE_SIZE,
    "idleCount": AMBIENT_IDLE_COUNT,
    "idleCoreCount": AMBIENT_IDLE_CORE_COUNT,
    "idleSpread": AMBIENT_IDLE_SPREAD,
    "edgePerSide": AMBIENT_EDGE_PER_SIDE,
    "armTimeoutMs": AMBIENT_ARM_TIMEOUT_MS,
    # 深色主题：光晕用更亮更饱和的 sprite、整体强度抬高（深底会把浅色雾吃没）
    "spriteSatLight": 78, "spriteLightLight": 76,
    "spriteSatDark": 82, "spriteLightDark": 70,
    "alphaScaleLight": 1.0, "alphaScaleDark": 1.05,
}


AMBIENT_CSS = """
/* ════════════════════════════════════════════════════════════════
   氛围背景层（#ata-bg）——静态渐变 + canvas 光晕
   层级：body 兜底渐变 → #ata-bg（z-index:0）→ .gradio-container（z-index:1）内容
   ════════════════════════════════════════════════════════════════ */
#ata-bg {
  position: fixed; inset: 0; z-index: 0; pointer-events: none;
  overflow: hidden;
  transition: opacity 0.35s ease;
}
/* 静态环境光渐变（原 CUSTOM_CSS 里那份，挪到独立层上，生成态可以整体加强） */
#ata-bg-base {
  position: absolute; inset: 0;
  background:
    radial-gradient(58% 38% at 10% 0%, rgba(0,113,227,0.07), transparent 72%),
    radial-gradient(48% 34% at 92% 4%, rgba(94,92,230,0.07), transparent 72%),
    radial-gradient(46% 32% at 50% 100%, rgba(52,199,89,0.05), transparent 72%);
}
/* 生成态：再叠一层同款渐变，等效把整体强度抬到约 1.6 倍（0.07 → 0.13） */
#ata-bg-base::after {
  content: ""; position: absolute; inset: 0; opacity: 0;
  transition: opacity 0.9s cubic-bezier(0.22, 1, 0.36, 1);
  background:
    radial-gradient(58% 38% at 10% 0%, rgba(0,113,227,0.06), transparent 72%),
    radial-gradient(48% 34% at 92% 4%, rgba(94,92,230,0.06), transparent 72%),
    radial-gradient(46% 32% at 50% 100%, rgba(52,199,89,0.04), transparent 72%);
}
#ata-bg.generating #ata-bg-base::after { opacity: 1; }
#ata-bg-canvas {
  position: absolute; inset: 0; width: 100%; height: 100%; display: block;
}
/* 高级设置弹窗打开时让背景退后，别和遮罩层抢注意力 */
body.modal-open #ata-bg { opacity: 0.45; }

/* 背景透明：让固定的氛围层透上来（内容容器提升到 z-index:1 盖在光晕之上）。
   注意：这里只改 position/z-index/background，不能加 transform / filter /
   backdrop-filter / contain —— 那会让 Gradio Dropdown 的 portal 面板（position:fixed）
   把容器当作 containing block，选项面板会跑到很远的顶部。 */
.gradio-container {
  position: relative; z-index: 1;
  background: transparent !important;
}
#root, .main, footer, .gradio-container > .main { background: transparent !important; }

/* ── 毛玻璃调强：让光晕真的透得过玻璃 ──
   卡片必须画在伪元素上：backdrop-filter 会为 position:fixed 的后代建立包含块，
   直接加在 .app-card 上会让卡片内 Dropdown 的选项面板定位错乱（实测偏移 242px）。 */
.app-card::before {
  background:
    var(--ata-sheen),
    var(--ata-glass);
  backdrop-filter: saturate(200%) blur(26px);
  -webkit-backdrop-filter: saturate(200%) blur(26px);
  box-shadow:
    inset 0 1px 0 var(--ata-glass-edge),
    inset 0 0 0 1px var(--ata-glass-ring);
}
.app-header {
  background: var(--ata-glass-header) !important;
  backdrop-filter: saturate(190%) blur(24px);
  -webkit-backdrop-filter: saturate(190%) blur(24px);
}
.progress-container {
  background: var(--ata-glass-strong) !important;
  backdrop-filter: saturate(190%) blur(22px);
  -webkit-backdrop-filter: saturate(190%) blur(22px);
}

/* ── 板块内部不能残留不透明白框 ──
   Gradio 的布局包装层（.block / .wrap / .form / .panel / …）默认是白底，
   会整块盖住卡片毛玻璃，看起来像"卡片里又套了白框"。
   ⚠️ 必须排除下拉选项面板（ul.options，fixed 定位），它要保持不透明才读得清。 */
.app-card .block,
.app-card .form,
.app-card .panel,
.app-card .contain,
.app-card .styler,
.app-card .gr-group,
.app-card .gr-box,
.app-card .gr-form,
.app-card .wrap {
  background: transparent !important;
  box-shadow: none !important;
}
/* 卡片内的交互面：改成半透明白，既保留"可点"的层次感，又不挡毛玻璃 */
.app-card .book-file-upload button.center,
.app-card .book-file-upload button.center.boundedheight.flex,
.app-card button.center.boundedheight,
.app-card .block.toggle,
.app-card .btn-ghost,
.app-card .btn-danger,
.app-card .btn-mini,
.app-card input,
.app-card textarea,
.app-card select,
.app-card .engine-tabs > .tab-nav {
  background: var(--ata-glass-soft) !important;
}
/* 日志终端：底色放在 viewport 层（暗色下不会被反相），文字层保持透明，
   这样深色主题里"反相文字层"得到的是深底浅字，而不是把底色一起反成亮板。 */
.app-card .xterm-viewport { background: var(--ata-terminal) !important; }
.app-card .xterm-screen { background: transparent !important; }
/* 资源库空态占位框：别让它变成又一块灰白板 */
.app-card .lib-empty { background: var(--ata-empty) !important; }
/* Gradio 内置文件预览表格：行默认是白/灰底，上传文件后会盖住毛玻璃 */
.app-card .file-preview tbody > tr,
.app-card .file-preview thead > tr { background: transparent !important; }
/* 组件"有值"时贴在上边框的浮动标签：默认白底小方块，改成半透明 */
.app-card label.float,
.app-card .float { background: var(--ata-glass-soft) !important; }
/* 文件类组件（已选文件/已上传）自带的标题标签与右上角悬浮图标按钮同样是白底 */
.app-card .book-file-upload label,
.app-card .book-file-upload .icon-button-wrapper,
.app-card .book-file-upload .icon-button,
.app-card .book-file-upload .top-panel,
#advanced_modal .rules-file-upload label,
#advanced_modal label.float { background: var(--ata-glass-soft) !important; }

/* ── 高级设置弹窗也走毛玻璃 ──
   玻璃同样画在伪元素上：backdrop-filter 若直接加在 .modal-box 上，会为内部
   position:fixed 的下拉选项面板建立包含块，面板坐标会跑到很远的顶部。 */
#advanced_modal .modal-box { background: transparent !important; position: relative; }
#advanced_modal .modal-box::before {
  content: ""; position: absolute; inset: 0; border-radius: inherit; z-index: 0;
  background: var(--ata-glass-modal);
  backdrop-filter: saturate(180%) blur(30px);
  -webkit-backdrop-filter: saturate(180%) blur(30px);
  box-shadow: inset 0 0 0 1px rgba(255,255,255,0.55);
  pointer-events: none;
}
#advanced_modal .modal-box > * { position: relative; z-index: 1; }
#advanced_modal input, #advanced_modal textarea, #advanced_modal select {
  background: var(--ata-glass-soft-2) !important;
}
/* 弹窗右上角圆形关闭按钮：与其它控件统一成半透明白 */
#advanced_modal .modal-close-btn { background: var(--ata-glass-soft) !important; }

/* 小屏：模糊半径和粒子数一起降，保住帧率 */
@media (max-width: 720px) {
  .app-card::before {
    backdrop-filter: saturate(180%) blur(18px);
    -webkit-backdrop-filter: saturate(180%) blur(18px);
  }
  .app-header {
    backdrop-filter: saturate(180%) blur(18px);
    -webkit-backdrop-filter: saturate(180%) blur(18px);
  }
  .progress-container {
    backdrop-filter: saturate(180%) blur(18px);
    -webkit-backdrop-filter: saturate(180%) blur(18px);
  }
}

/* 无障碍：减少动态效果时不播放过渡（画布由脚本只画静态帧） */
@media (prefers-reduced-motion: reduce) {
  #ata-bg, #ata-bg-base::after { transition: none !important; }
}
"""


_CONFIG_SCRIPT = (
    "<script>window.__ATA_AMBIENT_CONFIG="
    + json.dumps(_CONFIG, separators=(",", ":"))
    + ";</script>"
)

_AMBIENT_JS = """
(function () {
  var CFG = window.__ATA_AMBIENT_CONFIG || {};
  if (CFG.enabled === false) return;
  if (window.__ataAmbient) return;            // 脚本被重复注入时不再挂第二层

  var TAU = Math.PI * 2;
  var mq = function (q) { return !!(window.matchMedia && window.matchMedia(q).matches); };
  var reduce = mq("(prefers-reduced-motion: reduce)");
  var coarse = mq("(pointer: coarse)");

  var layer = null, base = null, canvas = null, ctx = null;
  var sprites = { core: [], wash: [] };
  var vw = 0, vh = 0, homeX = 0, homeY = 0;
  var idleParts = [], edgeParts = [];
  var state = "idle";
  var themeDark = false, themeAlpha = 1;   // 主题相关的 sprite 亮度与整体强度
  var blend = 0;              // 生成态过渡：0 = 空闲，1 = 生成中
  var gather = 0;             // 鼠标收束程度
  var focusX = 0, focusY = 0, mouseX = 0, mouseY = 0;
  var driftX = 0, driftY = 0, driftTargetX = 0, driftTargetY = 0;
  var pointerActive = false;
  var wanderAt = 0;
  var t0 = (window.performance && performance.now()) || Date.now();
  var raf = null, looping = false;
  var armTimer = null;
  var boxObserver = null, payloadObserver = null, observedBox = null, observedPayload = null;
  var bootInterval = null;

  function rand(a, b) { return a + Math.random() * (b - a); }
  function gauss() { return (Math.random() + Math.random() + Math.random() - 1.5) / 1.5; }
  function now() { return (window.performance && performance.now()) || Date.now(); }

  // ── sprite：每个色相两条衰减曲线，绘制时只做缩放 + globalAlpha ──
  function makeSprite(hue, profile) {
    var size = CFG.spriteSize || 160;
    var c = document.createElement("canvas");
    c.width = c.height = size;
    var g = c.getContext("2d");
    var r = size / 2;
    // 浅色主题：饱和度降一档、明度抬一档（"浅"而不是"艳"）；
    // 深色主题反过来用更亮更饱和的色，否则深底上几乎看不见。
    var sat = themeDark ? (CFG.spriteSatDark || 84) : (CFG.spriteSatLight || 78);
    var light = themeDark ? (CFG.spriteLightDark || 66) : (CFG.spriteLightLight || 76);
    function stop(p, a) {
      return "hsla(" + hue.toFixed(1) + ", " + sat + "%, " + light + "%, " + a + ")";
    }
    var grad = g.createRadialGradient(r, r, 0, r, r, r);
    if (profile === "wash") {
      grad.addColorStop(0, stop(0, 1));
      grad.addColorStop(0.5, stop(0, 0.74));
      grad.addColorStop(1, stop(0, 0));
    } else {
      grad.addColorStop(0, stop(0, 1));
      grad.addColorStop(0.35, stop(0, 0.72));
      grad.addColorStop(0.7, stop(0, 0.26));
      grad.addColorStop(1, stop(0, 0));
    }
    g.fillStyle = grad;
    g.beginPath();
    g.arc(r, r, r, 0, TAU);
    g.fill();
    return c;
  }

  function isDarkTheme() {
    if (document.documentElement && document.documentElement.classList.contains("dark")) return true;
    return !!(document.body && document.body.classList.contains("dark"));
  }

  function buildSprites() {
    var n = CFG.hueCount || 24;
    sprites = { core: [], wash: [] };
    for (var i = 0; i < n; i++) {
      var hue = (i / n) * 360;
      sprites.core.push(makeSprite(hue, "core"));
      sprites.wash.push(makeSprite(hue, "wash"));
    }
  }

  function spriteFor(hue, profile) {
    var n = sprites.core.length || 1;
    var h = ((hue % 360) + 360) % 360;
    var idx = Math.round((h / 360) * n) % n;
    return sprites[profile][idx];
  }

  // 主题切换：换一套 sprite 亮度和整体强度（同一帧内只重建一次）
  function refreshTheme(force) {
    var dark = isDarkTheme();
    if (!force && dark === themeDark && sprites.core.length) return;
    themeDark = dark;
    themeAlpha = dark ? (CFG.alphaScaleDark || 1.7) : (CFG.alphaScaleLight || 1);
    sprites = { core: [], wash: [] };
    buildSprites();
    if (reduce) draw(now());
  }

  // ── 尺寸 / 粒子 ──
  function measure() {
    vw = Math.max(window.innerWidth || 0, 320);
    vh = Math.max(window.innerHeight || 0, 320);
    homeX = vw * 0.5;
    homeY = vh * 0.32;
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(vw * dpr);
    canvas.height = Math.round(vh * dpr);
    canvas.style.width = vw + "px";
    canvas.style.height = vh + "px";
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function assignEdgeTargets() {
    for (var i = 0; i < idleParts.length; i++) {
      var p = idleParts[i];
      var angle = Math.atan2(p.offY, p.offX);
      var cosA = Math.cos(angle), sinA = Math.sin(angle);
      var t = Infinity, tt;
      if (sinA < 0) { tt = -homeY / sinA; if (tt > 0 && tt < t) t = tt; }
      if (sinA > 0) { tt = (vh - homeY) / sinA; if (tt > 0 && tt < t) t = tt; }
      if (cosA < 0) { tt = -homeX / cosA; if (tt > 0 && tt < t) t = tt; }
      if (cosA > 0) { tt = (vw - homeX) / cosA; if (tt > 0 && tt < t) t = tt; }
      if (!isFinite(t) || t <= 0) t = 0;
      var margin = 20;
      p.edgeX = homeX + cosA * Math.max(t - margin, 0);
      p.edgeY = homeY + sinA * Math.max(t - margin, 0);
      p.edgeSize = rand(80, 150);
      p.edgeAlpha = rand(0.022, 0.040);
    }
  }

  function rebuildParticles() {
    var small = vw < 720;
    var scale = small ? 0.6 : 1;
    var core = CFG.idleCoreCount || 8;
    var count = Math.max(10, Math.round((CFG.idleCount || 42) * scale));
    var spread = (CFG.idleSpread || 380) * (small ? 0.72 : 1);

    idleParts = [];
    for (var i = 0; i < count; i++) {
      var angle = Math.random() * TAU;
      var radius = (i < core) ? Math.random() * 60 : Math.sqrt(Math.random()) * spread;
      idleParts.push({
        offX: Math.cos(angle) * radius,
        offY: Math.sin(angle) * radius,
        jx: rand(-1, 1), jy: rand(-1, 1),
        x: homeX + Math.cos(angle) * radius,
        y: homeY + Math.sin(angle) * radius,
        idleSize: rand(140, 240), gatherSize: rand(55, 95),
        idleAlpha: (i < core) ? rand(0.025, 0.045) : rand(0.012, 0.025),
        gatherAlpha: rand(0.030, 0.050),
        hueOff: rand(-18, 18),
        edgeX: 0, edgeY: 0, edgeSize: 0, edgeAlpha: 0
      });
    }
    assignEdgeTargets();

    edgeParts = [];
    var perSide = Math.max(6, Math.round((CFG.edgePerSide || 12) * scale));
    for (var s = 0; s < 4; s++) {
      for (var k = 0; k < perSide; k++) {
        var pos = (k + Math.random() * 0.7) / perSide;
        var d = Math.abs(gauss()) * 25 + 10;
        var ex, ey;
        if (s === 0) { ex = pos * vw; ey = d; }
        else if (s === 1) { ex = vw - d; ey = pos * vh; }
        else if (s === 2) { ex = pos * vw; ey = vh - d; }
        else { ex = d; ey = pos * vh; }
        edgeParts.push({ x: ex, y: ey, size: rand(140, 220), alpha: rand(0.030, 0.050),
                         hueOff: rand(-18, 18) });
      }
    }
    // 四角：每个角两颗大粒子（主角落压住角本身，副角落覆盖角内侧）
    var corners = [[0, 0], [vw, 0], [vw, vh], [0, vh]];
    for (var c = 0; c < 4; c++) {
      var cx = corners[c][0], cy = corners[c][1];
      var a2 = Math.atan2(cy - vh / 2, cx - vw / 2);
      edgeParts.push({ x: cx + Math.cos(a2) * 8, y: cy + Math.sin(a2) * 8,
                       size: rand(320, 420), alpha: rand(0.050, 0.080), hueOff: rand(-10, 10) });
      edgeParts.push({ x: cx + Math.cos(a2) * 26, y: cy + Math.sin(a2) * 26,
                       size: rand(240, 320), alpha: rand(0.035, 0.060), hueOff: rand(-14, 14) });
    }
    // 顶边：4 颗大粒子横跨顶部
    for (var t = 0; t < 4; t++) {
      edgeParts.push({ x: vw * (t + 0.5) / 4, y: 0,
                       size: rand(300, 400), alpha: rand(0.040, 0.070), hueOff: rand(-10, 10) });
    }
  }

  // ── 色相缓慢流动 ──
  function slowHue(ts) {
    var pal = CFG.huePalette || [212, 250, 196, 288];
    if (pal.length < 2) return pal[0] || 212;
    var span = (CFG.hueSegmentMs || 10000) * (pal.length - 1);
    var elapsed = Math.max(0, ts - t0);
    var pos = ((elapsed % span) / span) * (pal.length - 1);
    var i = Math.min(pal.length - 2, Math.floor(pos));
    var f = pos - i;
    var e = f * f * (3 - 2 * f);
    return pal[i] + (pal[i + 1] - pal[i]) * e;
  }

  // ── 绘制 ──
  function draw(ts) {
    if (!ctx) return;
    var hue = slowHue(ts);
    var cx = homeX + driftX;
    var cy = homeY + driftY;
    // 生成中鼠标只保留 15% 的参与度
    var mouseWeight = 0.15 + 0.85 * (1 - Math.min(1, blend));
    var g = gather * mouseWeight;
    var ease = reduce ? 1 : 0.07;
    var edgeEase = Math.min(1, blend * 1.5);
    var centerAlpha = Math.max(0, 1 - blend * 1.2);

    ctx.clearRect(0, 0, vw, vh);
    ctx.globalCompositeOperation = "lighter";

    // 中心弥散光（生成态淡出）
    if (centerAlpha > 0.002) {
      var washR = (CFG.idleSpread || 380) + 60;
      ctx.globalAlpha = Math.min(1, 0.028 * centerAlpha * themeAlpha);
      ctx.drawImage(spriteFor(hue, "wash"), cx - washR, cy - washR, washR * 2, washR * 2);
      ctx.globalAlpha = Math.min(1, 0.090 * centerAlpha * themeAlpha);
      var coreR = 300;
      ctx.drawImage(spriteFor(hue, "core"), cx - coreR, cy - coreR, coreR * 2, coreR * 2);
    }

    // 中心粒子（生成态飞向视口边缘）
    for (var i = 0; i < idleParts.length; i++) {
      var p = idleParts[i];
      var bx = cx + p.offX, by = cy + p.offY;
      var hx = bx, hy = by, size, alpha;
      if (blend > 0.01) {
        hx = bx + (p.edgeX - bx) * edgeEase;
        hy = by + (p.edgeY - by) * edgeEase;
      }
      var tx = hx + (focusX + p.jx * 50 - hx) * g;
      var ty = hy + (focusY + p.jy * 50 - hy) * g;
      p.x += (tx - p.x) * ease;
      p.y += (ty - p.y) * ease;

      var span = p.idleSize + (p.gatherSize - p.idleSize) * g;
      var baseA = p.idleAlpha + (p.gatherAlpha - p.idleAlpha) * g;
      if (blend > 0.01) {
        size = span + (p.edgeSize - span) * edgeEase;
        alpha = (baseA + (p.edgeAlpha - baseA) * edgeEase) *
                Math.max(0, 1 - blend * 0.5);
      } else {
        size = span;
        alpha = baseA;
      }
      if (alpha <= 0.002 || size <= 1) continue;
      ctx.globalAlpha = Math.min(1, alpha * themeAlpha);
      ctx.drawImage(spriteFor(hue + p.hueOff, "core"),
                    p.x - size, p.y - size, size * 2, size * 2);
    }

    // 边缘粒子（生成态）
    if (blend > 0.002) {
      var breathe = 0.85 + 0.15 * Math.sin(ts * 0.0008 + t0 * 0.001);
      for (var j = 0; j < edgeParts.length; j++) {
        var ep = edgeParts[j];
        var dx = focusX - ep.x, dy = focusY - ep.y;
        var dist = Math.sqrt(dx * dx + dy * dy) || 1;
        var near = Math.max(0, 1 - dist / 520);      // 离光标越近的边缘粒子越亮
        var pull = 14 * g;                            // 被光标轻微牵引
        var ex2 = ep.x + (dx / dist) * pull;
        var ey2 = ep.y + (dy / dist) * pull;
        var ea = ep.alpha * blend * breathe * (1 + 0.5 * near * g);
        if (ea <= 0.002) continue;
        ctx.globalAlpha = Math.min(1, ea * themeAlpha);
        ctx.drawImage(spriteFor(hue + ep.hueOff, "wash"),
                      ex2 - ep.size, ey2 - ep.size, ep.size * 2, ep.size * 2);
      }
    }

    ctx.globalAlpha = 1;
    ctx.globalCompositeOperation = "source-over";
  }

  // ── 状态机：idle → arming → generating → settling → idle ──
  function paintClass() {
    if (!layer) return;
    var on = (state === "generating" || state === "arming");
    if (on) layer.classList.add("generating");
    else layer.classList.remove("generating");
  }

  function setState(next) {
    if (reduce && next === "settling") next = "idle";
    if (next === state) return;
    state = next;
    if (armTimer && next !== "arming") { clearTimeout(armTimer); armTimer = null; }
    paintClass();
    if (reduce) draw(now());
  }

  function signalStart() {
    setState("arming");
    if (armTimer) clearTimeout(armTimer);
    armTimer = setTimeout(function () {
      armTimer = null;
      if (state === "arming") setState("idle");     // 表单校验没过：安静地退回去
    }, CFG.armTimeoutMs || 6000);
  }

  function signalSettle() { setState("settling"); }

  function progressBox() { return document.getElementById("progress_container"); }

  function modeFromDom() {
    var box = progressBox();
    if (!box || !box.classList) return null;
    var cl = box.classList;
    if (cl.contains("collapsed")) return "idle";
    if (cl.contains("done") || cl.contains("warn")) return "settle";
    if (cl.contains("active")) return "generating";
    return "idle";
  }

  function syncFromProgress() {
    var mode = modeFromDom();
    if (mode === "generating") { setState("generating"); return; }
    if (mode === "settle") { setState("settling"); return; }
    // idle：arming 等后端确认、settling 让回落动画自己跑完，都不被旧状态打断
    if (state === "arming" || state === "settling") return;
    setState("idle");
  }

  function bindObservers() {
    var box = progressBox();
    if (box && box !== observedBox) {
      if (boxObserver) boxObserver.disconnect();
      boxObserver = new MutationObserver(syncFromProgress);
      boxObserver.observe(box, { attributes: true, attributeFilter: ["class"] });
      observedBox = box;
    }
    var payload = document.getElementById("progress_state");
    if (payload && payload !== observedPayload) {
      if (payloadObserver) payloadObserver.disconnect();
      payloadObserver = new MutationObserver(syncFromProgress);
      payloadObserver.observe(payload, { childList: true, subtree: true, characterData: true });
      observedPayload = payload;
    }
  }

  // ── 交互 ──
  function onMouseMove(e) {
    pointerActive = true;
    mouseX = e.clientX;
    mouseY = e.clientY;
  }

  function onMouseLeave() {
    pointerActive = false;
    var dx = mouseX - homeX, dy = mouseY - homeY;
    var len = Math.sqrt(dx * dx + dy * dy) || 1;
    var d = 140 + Math.random() * 100;
    driftTargetX = (dx / len) * d;
    driftTargetY = (dy / len) * d;
  }

  // 指针离开窗口时 mouseleave 不一定触发，用 mouseout + relatedTarget 空值兜底
  function onMouseOut(e) {
    if (!e.relatedTarget && !e.toElement) onMouseLeave();
  }

  function onClick(e) {
    var target = e.target;
    if (!target || !target.closest) return;
    var btn = target.closest(".btn-primary, .btn-ghost, .btn-danger");
    if (!btn || btn.disabled) return;
    var text = btn.textContent || "";
    if (btn.classList.contains("btn-primary") && text.indexOf("开始生成") >= 0) {
      signalStart();
    } else if (text.indexOf("停止转换") >= 0) {
      signalSettle();
    }
  }

  function onResize() {
    measure();
    rebuildParticles();
    if (reduce) draw(now());
  }

  function onVisibility() {
    if (document.hidden) stopLoop();
    else startLoop();
  }

  function onThemeChange() { refreshTheme(false); }

  // ── 渲染循环 ──
  function step(ts) {
    if (!layer || !layer.isConnected) { cleanup(); return; }

    if (state === "generating") blend += (1 - blend) * 0.03;
    else if (state === "arming") blend += (0.35 - blend) * 0.03;
    else blend += (0 - blend) * (state === "settling" ? 0.045 : 0.05);
    if (blend < 0.001) blend = 0;
    if (blend > 0.999) blend = 1;

    // 触屏没有 hover：关闭收束，改成缓慢自动漂移
    var wantGather = pointerActive && !coarse ? 1 : 0;
    gather += (wantGather - gather) * 0.05;
    if (gather < 0.001) gather = 0;

    if (pointerActive && !coarse) {
      focusX += (mouseX - focusX) * 0.05;           // 光标跟随带一点惯性
      focusY += (mouseY - focusY) * 0.05;
      driftX += (0 - driftX) * 0.01;
      driftY += (0 - driftY) * 0.01;
    } else {
      if (coarse && ts > wanderAt) {
        wanderAt = ts + 7000;                        // 每 7 秒换一个漂移目标
        driftTargetX = rand(-90, 90);
        driftTargetY = rand(-60, 60);
      }
      driftX += (driftTargetX - driftX) * 0.006;
      driftY += (driftTargetY - driftY) * 0.006;
      var fx = homeX + driftX, fy = homeY + driftY;
      focusX += (fx - focusX) * 0.02;
      focusY += (fy - focusY) * 0.02;
    }

    if (state === "settling" && blend <= 0.001) setState("idle");
    draw(ts);
    raf = requestAnimationFrame(step);
  }

  function startLoop() {
    if (reduce || looping) return;
    looping = true;
    raf = requestAnimationFrame(step);
  }

  function stopLoop() {
    looping = false;
    if (raf) cancelAnimationFrame(raf);
    raf = null;
  }

  // ── 挂载 ──
  function ensureLayer() {
    if (layer && layer.isConnected) return true;
    if (!document.body) return false;
    layer = document.getElementById("ata-bg");
    if (!layer) {
      layer = document.createElement("div");
      layer.id = "ata-bg";
      layer.setAttribute("aria-hidden", "true");
      base = document.createElement("div");
      base.id = "ata-bg-base";
      layer.appendChild(base);
      canvas = document.createElement("canvas");
      canvas.id = "ata-bg-canvas";
      layer.appendChild(canvas);
      document.body.insertBefore(layer, document.body.firstChild);
    }
    canvas = document.getElementById("ata-bg-canvas");
    if (!canvas) return false;
    ctx = canvas.getContext("2d");
    return !!ctx;
  }

  function boot() {
    if (!ensureLayer()) return;
    refreshTheme(false);                       // 主题变了就换一套 sprite
    if (!sprites.core.length) buildSprites();
    if (!idleParts.length) {
      measure();
      focusX = homeX; focusY = homeY;
      rebuildParticles();
    }
    paintClass();
    bindObservers();
    syncFromProgress();
    if (reduce) draw(now());
    else startLoop();
  }

  function cleanup() {
    stopLoop();
    if (armTimer) { clearTimeout(armTimer); armTimer = null; }
    if (boxObserver) { boxObserver.disconnect(); boxObserver = null; }
    if (payloadObserver) { payloadObserver.disconnect(); payloadObserver = null; }
    if (bootInterval) { clearInterval(bootInterval); bootInterval = null; }
    window.removeEventListener("resize", onResize);
    document.removeEventListener("visibilitychange", onVisibility);
    document.removeEventListener("ata-theme-change", onThemeChange);
    document.removeEventListener("mousemove", onMouseMove);
    document.removeEventListener("mouseleave", onMouseLeave);
    document.removeEventListener("mouseout", onMouseOut);
    document.removeEventListener("click", onClick, true);
  }

  window.__ataAmbient = {
    setState: setState,
    signalStart: signalStart,
    signalSettle: signalSettle,
    getState: function () { return state; },
    getBlend: function () { return blend; },
    draw: draw,
    rebuild: function () { measure(); rebuildParticles(); draw(now()); },
    cleanup: cleanup,
    reduceMotion: reduce,
    coarsePointer: coarse
  };

  function init() {
    if (!ensureLayer()) {
      // body 还没挂上（脚本在 head 里）：等 DOM 就绪
      if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init, { once: true });
      }
      return;
    }
    boot();
    window.addEventListener("resize", onResize);
    document.addEventListener("visibilitychange", onVisibility);
    document.addEventListener("mousemove", onMouseMove, { passive: true });
    document.addEventListener("mouseleave", onMouseLeave);
    document.addEventListener("mouseout", onMouseOut, { passive: true });
    document.addEventListener("click", onClick, true);
    document.addEventListener("ata-theme-change", onThemeChange);
    if (document.hidden) stopLoop();

    // Gradio 是渐进渲染的：组件可能稍后才挂载，轻量重试避免漏绑（与进度条脚本一致）
    window.setTimeout(boot, 600);
    window.setTimeout(boot, 2000);
    bootInterval = window.setInterval(boot, 3000);
  }

  init();
})();
"""

AMBIENT_LAYER_HTML = (_CONFIG_SCRIPT + "<script>" + _AMBIENT_JS + "</script>") if AMBIENT_ENABLED else ""
