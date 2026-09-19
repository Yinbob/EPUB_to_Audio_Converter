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
# 色相档位越密，随时间流动和粒子之间的颜色过渡越平滑（24 档会看出跳色）
AMBIENT_HUE_COUNT = 32
# sprite 会被放大到 800px 上下，边长越大放大倍率越低、过渡越顺（256 起步）
AMBIENT_SPRITE_SIZE = 256
# 柔和光晕：少量大半径、低透明度的光斑叠加成一整团过渡顺滑的光晕
AMBIENT_IDLE_COUNT = 46                      # 空闲态粒子数
AMBIENT_IDLE_CORE_COUNT = 10                 # 其中贴近核心的粒子数
AMBIENT_IDLE_SPREAD = 440                    # 空闲态粒子扩散半径（px）
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
    # 颜色更"深"：饱和度上调、明度下调（观感更浓，配合整体提亮）
    "spriteSatLight": 86, "spriteLightLight": 70,
    "spriteSatDark": 90, "spriteLightDark": 64,
    "alphaScaleLight": 1.0, "alphaScaleDark": 1.05,
    # 光晕管线：先在 1/3 分辨率离屏画布上画，再高斯模糊后放大回主画布。
    # 这样几十个大 sprite 之间的叠加轮廓会被抹平成一整团，不会再看出一个个圈。
    "glowDownscale": 3,
    "glowBlur": 11,          # 单位是离屏像素（≈33 CSS px）
    # 光场渲染：分辨率 = 视口 / fieldDiv（浮点累加，整帧只量化一次）
    "fieldDiv": 5,
    "hueLUT": 720,
    "kernelSteps": 256,
    "fieldMaxRadius": 150,      # 场坐标里的最大半径（≈750 CSS px）：中心大光束不能被截断
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
  // 光场：浮点 RGB 累加缓冲 + 量化用的 8bit 画布
  var fw = 0, fh = 0, fieldDiv = 5, fieldR = null, fieldG = null, fieldB = null;
  var fieldCanvas = null, fieldCtx = null, fieldImage = null, fieldData = null;
  var hueLUT = null, hueLUTN = 0, kernel = null;
  var KERNEL_N = 256, FIELD_MAX_R = 60;
  var dpr = 1;
  var ditherPattern = null;
  var vw = 0, vh = 0, homeX = 0, homeY = 0;
  var idleParts = [], edgeParts = [];
  var state = "idle";
  var themeDark = false, themeAlpha = 1;   // 主题相关的 sprite 亮度与整体强度
  var blend = 0;              // 生成态过渡：0 = 空闲，1 = 生成中
  var gather = 0;             // 鼠标收束程度
  var focusX = 0, focusY = 0, mouseX = 0, mouseY = 0;
  var driftX = 0, driftY = 0, driftTargetX = 0, driftTargetY = 0;
  var spreadAnchorX = 0, spreadAnchorY = 0;   // 扩散起点（点开始生成时的鼠标位置）
  var pointerActive = false;
  var wanderAt = 0;
  var profileBuf = null;             // 调试剖面用的临时缓冲（只在 __ataAmbient.profile / profileAt 里用）
  var fieldN = 0;                    // data-field 诊断快照的帧计数
  var centerConc = 1;                // 中心光束当前的"聚集度"（见 draw() ③）
  var massCx = 0, massCy = 0, massRms = 0;   // 粒子团重心与散布半径（诊断用）
  var RING_EDGES = [0, 25, 60, 120, 200, 320, 460, 640, 900];
  var t0 = (window.performance && performance.now()) || Date.now();
  var frameAcc = 0, frameN = 0;      // 渲染耗时统计（写到 dataset.frameMs，便于排查性能）
  var raf = null, looping = false;
  var armTimer = null;
  var boxObserver = null, payloadObserver = null, observedBox = null, observedPayload = null;
  var bootInterval = null;

  function rand(a, b) { return a + Math.random() * (b - a); }
  function gauss() { return (Math.random() + Math.random() + Math.random() - 1.5) / 1.5; }
  function now() { return (window.performance && performance.now()) || Date.now(); }

  // ══ 光场构造（这一版的核心改动） ══
  // 每颗粒子 = 一个光源：在**浮点缓冲**里累加高斯贡献，整帧只在最后量化一次（并带抖动）。
  // 旧做法是几十张预渲染 8bit 光斑按不同透明度叠加——各自的量化台阶会露出可见边界与色带；
  // 浮点累加则不同色相在浮点域自然混合，从构造上就不存在"叠加边界"和"跳色"。
  function hslToRgb(h, s, l) {          // h/s/l ∈ 0..1 → [r,g,b] ∈ 0..1
    if (s <= 0) return [l, l, l];
    var q = l < 0.5 ? l * (1 + s) : l + s - l * s;
    var p = 2 * l - q;
    function f(t) {
      if (t < 0) t += 1;
      if (t > 1) t -= 1;
      if (t < 1 / 6) return p + (q - p) * 6 * t;
      if (t < 1 / 2) return q;
      if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
      return p;
    }
    return [f(h + 1 / 3), f(h), f(h - 1 / 3)];
  }

  // 色相 → RGB 查找表；取用时线性插值，色相是连续量，不会"跳档"
  function buildHueLUT() {
    var sat = themeDark ? (CFG.spriteSatDark || 82) : (CFG.spriteSatLight || 78);
    var light = themeDark ? (CFG.spriteLightDark || 70) : (CFG.spriteLightLight || 76);
    var n = CFG.hueLUT || 720;
    hueLUT = new Float32Array(n * 3);
    for (var i = 0; i < n; i++) {
      var rgb = hslToRgb(i / n, sat / 100, light / 100);
      hueLUT[i * 3] = rgb[0];
      hueLUT[i * 3 + 1] = rgb[1];
      hueLUT[i * 3 + 2] = rgb[2];
    }
    hueLUTN = n;
  }

  // 高斯衰减 exp(-3t)，t=(d/R)²：曲线与旧的多段渐变 stops 基本一致，保证样式不变
  function buildKernel() {
    kernel = new Float32Array(KERNEL_N + 1);
    for (var i = 0; i <= KERNEL_N; i++) kernel[i] = Math.exp(-3 * (i / KERNEL_N));
  }

  function isDarkTheme() {
    if (document.documentElement && document.documentElement.classList.contains("dark")) return true;
    return !!(document.body && document.body.classList.contains("dark"));
  }

  // 往光场里累加一个光源（坐标/半径都是 CSS 像素）
  function splat(x, y, radius, hue, alpha) {
    if (alpha <= 0.0008) return;
    var R = radius / fieldDiv;
    if (R < 0.7) R = 0.7;
    if (R > FIELD_MAX_R) R = FIELD_MAX_R;
    var h = ((hue % 360) + 360) % 360;
    var pos = (h / 360) * hueLUTN;
    var i0 = Math.floor(pos), f = pos - i0;
    var j0 = (i0 % hueLUTN) * 3, j1 = ((i0 + 1) % hueLUTN) * 3;
    var cr = hueLUT[j0] + (hueLUT[j1] - hueLUT[j0]) * f;
    var cg = hueLUT[j0 + 1] + (hueLUT[j1 + 1] - hueLUT[j0 + 1]) * f;
    var cb = hueLUT[j0 + 2] + (hueLUT[j1 + 2] - hueLUT[j0 + 2]) * f;
    var e = Math.min(1, alpha * themeAlpha);
    var cx = x / fieldDiv, cy = y / fieldDiv;
    var x0 = Math.max(0, Math.floor(cx - R)), x1 = Math.min(fw - 1, Math.ceil(cx + R));
    var y0 = Math.max(0, Math.floor(cy - R)), y1 = Math.min(fh - 1, Math.ceil(cy + R));
    var invR2 = 1 / (R * R);
    for (var py = y0; py <= y1; py++) {
      var dy = py - cy, dy2 = dy * dy, row = py * fw;
      for (var px = x0; px <= x1; px++) {
        var dx = px - cx;
        var t = (dx * dx + dy2) * invR2;
        if (t >= 1) continue;
        var k = kernel[(t * KERNEL_N) | 0] * e;
        var idx = row + px;
        fieldR[idx] += cr * k;
        fieldG[idx] += cg * k;
        fieldB[idx] += cb * k;
      }
    }
  }

  function clearField() {
    fieldR.fill(0); fieldG.fill(0); fieldB.fill(0);
  }

  // 光场 → 8bit（全流程唯一的量化点）→ 放大回主画布；抖动在 display 分辨率上叠加
  function compositeField() {
    var data = fieldData.data;
    var fi = 0, di = 0;
    for (var y = 0; y < fh; y++) {
      for (var x = 0; x < fw; x++, fi++, di += 4) {
        var sr = fieldR[fi], sg = fieldG[fi], sb = fieldB[fi];
        var a = sr > sg ? sr : sg;
        if (sb > a) a = sb;
        if (a <= 0.0005) { data[di + 3] = 0; continue; }
        var inv = 255 / a;
        data[di] = Math.min(255, sr * inv) | 0;
        data[di + 1] = Math.min(255, sg * inv) | 0;
        data[di + 2] = Math.min(255, sb * inv) | 0;
        data[di + 3] = Math.min(255, a * 255) | 0;
      }
    }
    fieldCtx.putImageData(fieldImage, 0, 0);
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.globalCompositeOperation = "source-over";
    ctx.globalAlpha = 1;
    ctx.imageSmoothingEnabled = true;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(fieldCanvas, 0, 0, canvas.width, canvas.height);
  }

  // 抖动噪声：预烘焙一张 1:1 设备像素的瓦片，每帧用 pattern 铺一次。
  // ⚠️ 必须"逐通道独立"取 0/255（而不是黑/白像素）：只抖动亮度动不了色度，
  // 实测 B-R（色偏）会停在 2/4/8/10 这种偶数档上，看起来就是彩色色带。
  function bakeDither() {
    var dpr = Math.min(window.devicePixelRatio || 1, 2);
    var px = Math.max(32, Math.round(128 * dpr));
    var c = document.createElement("canvas");
    c.width = c.height = px;
    var g = c.getContext("2d");
    var img = g.createImageData(px, px);
    var data = img.data;
    for (var i = 0; i < px * px; i++) {
      data[i * 4] = Math.random() < 0.5 ? 0 : 255;
      data[i * 4 + 1] = Math.random() < 0.5 ? 0 : 255;
      data[i * 4 + 2] = Math.random() < 0.5 ? 0 : 255;
      data[i * 4 + 3] = 6;          // ±3/255，平均色为中性
    }
    g.putImageData(img, 0, 0);
    ditherPattern = ctx.createPattern(c, "repeat");
  }

  function drawDither() {
    if (!ditherPattern || !canvas) return;
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0);          // 按设备像素 1:1 铺，避免被放大成色块
    ctx.globalCompositeOperation = "source-over";
    ctx.globalAlpha = 1;
    ctx.fillStyle = ditherPattern;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.restore();
  }

  // 主题切换：换一套 sprite 亮度和整体强度（同一帧内只重建一次）
  function refreshTheme(force) {
    var dark = isDarkTheme();
    if (!force && dark === themeDark && hueLUT) return;
    themeDark = dark;
    themeAlpha = dark ? (CFG.alphaScaleDark || 1.7) : (CFG.alphaScaleLight || 1);
    buildHueLUT();          // 主题决定饱和度/明度，色相表要重建
    if (reduce) draw(now());
  }

  // ── 尺寸 / 粒子 ──
  function measure() {
    vw = Math.max(window.innerWidth || 0, 320);
    vh = Math.max(window.innerHeight || 0, 320);
    homeX = vw * 0.5;
    homeY = vh * 0.32;
    // 扩散起点默认在光晕家位置；视口变化后若已跑到画面外就拉回来
    if (!spreadAnchorX && !spreadAnchorY) { spreadAnchorX = homeX; spreadAnchorY = homeY; }
    if (spreadAnchorX > vw || spreadAnchorY > vh) { spreadAnchorX = homeX; spreadAnchorY = homeY; }
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(vw * dpr);
    canvas.height = Math.round(vh * dpr);
    canvas.style.width = vw + "px";
    canvas.style.height = vh + "px";
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    // 光场缓冲：低分辨率浮点累加（每帧只用一次 8bit 量化）
    fieldDiv = Math.max(3, CFG.fieldDiv || 5);
    fw = Math.max(1, Math.ceil(vw / fieldDiv));
    fh = Math.max(1, Math.ceil(vh / fieldDiv));
    KERNEL_N = CFG.kernelSteps || 256;
    FIELD_MAX_R = CFG.fieldMaxRadius || 60;
    fieldR = new Float32Array(fw * fh);
    fieldG = new Float32Array(fw * fh);
    fieldB = new Float32Array(fw * fh);
    if (!fieldCanvas) {
      fieldCanvas = document.createElement("canvas");
      fieldCtx = fieldCanvas.getContext("2d");
    }
    fieldCanvas.width = fw;
    fieldCanvas.height = fh;
    fieldImage = fieldCtx.createImageData(fw, fh);
    fieldData = fieldImage;
    bakeDither();                       // DPR 可能变化，噪声瓦片按设备像素重建
  }

  function assignEdgeTargets() {
    // 从"扩散起点"（点开始生成时的鼠标位置）向四周射线到视口边框；
    // 角度用黄金角均匀铺开，保证每个方向都有粒子，不会随机挤成一堆。
    var ax = spreadAnchorX, ay = spreadAnchorY;
    var GOLDEN = 2.39996323;
    var n = idleParts.length;
    for (var i = 0; i < n; i++) {
      var p = idleParts[i];
      var angle = i * GOLDEN + p.angleJitter;
      var cosA = Math.cos(angle), sinA = Math.sin(angle);
      var t = Infinity, tt;
      if (sinA < 0) { tt = -ay / sinA; if (tt > 0 && tt < t) t = tt; }
      if (sinA > 0) { tt = (vh - ay) / sinA; if (tt > 0 && tt < t) t = tt; }
      if (cosA < 0) { tt = -ax / cosA; if (tt > 0 && tt < t) t = tt; }
      if (cosA > 0) { tt = (vw - ax) / cosA; if (tt > 0 && tt < t) t = tt; }
      if (!isFinite(t) || t <= 0) t = 0;
      var margin = 20;
      p.edgeAngle = angle;
      p.edgeX = ax + cosA * Math.max(t - margin, 0);
      p.edgeY = ay + sinA * Math.max(t - margin, 0);
      // 散到边缘后收成小一些的光斑（同时提亮一点，边缘才有存在感）
      p.edgeSize = rand(85, 155);
      p.edgeAlpha = rand(0.027, 0.050);
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
      var isCore = i < core;
      idleParts.push({
        offX: Math.cos(angle) * radius,
        offY: Math.sin(angle) * radius,
        jx: rand(-1, 1), jy: rand(-1, 1),
        x: homeX + Math.cos(angle) * radius,
        y: homeY + Math.sin(angle) * radius,
        // 大半径、低透明度的光斑：靠叠加形成连续光晕（不要能看出一个个圈）
        idleSize: isCore ? rand(200, 320) : rand(150, 270),
        // 汇聚时靠"抖动收紧"来集中（粒子半径要保持足够大：它们靠在光标处密集重叠
        // 把中心顶亮，半径缩太小反而会让中心变暗）
        gatherSize: isCore ? rand(60, 105) : rand(45, 85),
        idleAlpha: isCore ? rand(0.042, 0.075) : rand(0.020, 0.042),
        gatherAlpha: isCore ? rand(0.048, 0.085) : rand(0.026, 0.052),
        hueOff: rand(-16, 16),
        angleJitter: rand(-0.12, 0.12),
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
        edgeParts.push({ x: ex, y: ey, size: rand(150, 240), alpha: rand(0.029, 0.055),
                         hueOff: rand(-18, 18) });
      }
    }
    // 四角：每个角两颗大粒子（主角落压住角本身，副角落覆盖角内侧）
    var corners = [[0, 0], [vw, 0], [vw, vh], [0, vh]];
    for (var c = 0; c < 4; c++) {
      var cx = corners[c][0], cy = corners[c][1];
      var a2 = Math.atan2(cy - vh / 2, cx - vw / 2);
      edgeParts.push({ x: cx + Math.cos(a2) * 8, y: cy + Math.sin(a2) * 8,
                       size: rand(340, 460), alpha: rand(0.052, 0.091), hueOff: rand(-10, 10) });
      edgeParts.push({ x: cx + Math.cos(a2) * 26, y: cy + Math.sin(a2) * 26,
                       size: rand(250, 345), alpha: rand(0.039, 0.072), hueOff: rand(-14, 14) });
    }
    // 顶边：4 颗大粒子横跨顶部
    for (var t = 0; t < 4; t++) {
      edgeParts.push({ x: vw * (t + 0.5) / 4, y: 0,
                       size: rand(320, 435), alpha: rand(0.046, 0.085), hueOff: rand(-10, 10) });
    }
  }

  // ── 色相缓慢流动 ──
  function slowHue(ts) {
    var pal = CFG.huePalette || [212, 250, 196, 288];
    var n = pal.length;
    if (n < 2) return pal[0] || 212;
    // 闭环 + Catmull-Rom 插值：
    // ⚠️ 旧写法是"线性扫过调色板再回到第一色"，最后一段 [288 → 212] 会瞬间跳 ~76°，
    //    看起来就是"卡一下突然换了个颜色"。改成把首尾相接成环、并用 Catmull-Rom
    //    取相邻四点插值：跨段的一阶导连续，既不会有循环回绕的瞬跳，也不会在每个
    //    色相点上"到站停一下再走"。整轮时长 = 色相段长 × 段数（默认 4×10s = 40s）。
    var span = (CFG.hueSegmentMs || 10000) * n;
    var pos = ((Math.max(0, ts - t0)) % span) / span * n;
    var i = Math.floor(pos) % n;
    var f = pos - Math.floor(pos);
    var p0 = pal[(i - 1 + n) % n], p1 = pal[i];
    var p2 = pal[(i + 1) % n], p3 = pal[(i + 2) % n];
    var f2 = f * f, f3 = f2 * f;
    return 0.5 * (2 * p1 + (-p0 + p2) * f
                  + (2 * p0 - 5 * p1 + 4 * p2 - p3) * f2
                  + (-p0 + 3 * p1 - 3 * p2 + p3) * f3);
  }

  // 读出当前光场的亮度分布：峰值强度 + 峰值位置（CSS px）+ 内部缓冲。
  // 传 (px,py) 时顺带按"到该点的距离"分桶，给出同心环平均亮度（一趟扫完，不额外多扫）。
  // 亮度取 max(r,g,b)——和 compositeField() 里决定 alpha 的量一致。
  function profileAt(px, py) {
    if (!fieldR || !fw || !fh) return null;
    var n = fw * fh, i;
    if (!profileBuf || profileBuf.length !== n) profileBuf = new Float32Array(n);
    var max = 0, maxI = 0;
    for (i = 0; i < n; i++) {
      var a = fieldR[i];
      if (fieldG[i] > a) a = fieldG[i];
      if (fieldB[i] > a) a = fieldB[i];
      profileBuf[i] = a;
      if (a > max) { max = a; maxI = i; }
    }
    var out = { peak: max, peakX: (maxI % fw) * fieldDiv, peakY: ((maxI / fw) | 0) * fieldDiv };
    if (px == null || py == null) return out;
    var rings = RING_EDGES.length - 1, sum = new Float64Array(rings), cnt = new Float64Array(rings);
    var fx = px / fieldDiv, fy = py / fieldDiv;
    var edge = [], r;
    for (r = 0; r < RING_EDGES.length; r++) edge.push(RING_EDGES[r] / fieldDiv);
    for (var y = 0; y < fh; y++) {
      var dy = y - fy, dy2 = dy * dy;
      for (var x = 0; x < fw; x++) {
        var dx = x - fx;
        var d = Math.sqrt(dx * dx + dy2);
        for (r = 0; r < rings; r++) {
          if (d < edge[r + 1]) { sum[r] += profileBuf[y * fw + x]; cnt[r]++; break; }
        }
      }
    }
    out.rings = [];
    for (r = 0; r < rings; r++) out.rings.push(cnt[r] ? sum[r] / cnt[r] : 0);
    return out;
  }

  // ── 绘制 ──
  function draw(ts) {
    if (!ctx || !fieldCtx) return;
    var hue = slowHue(ts);
    var cx = homeX + driftX;
    var cy = homeY + driftY;
    // 生成中鼠标只保留 15% 的参与度
    var mouseWeight = 0.15 + 0.85 * (1 - Math.min(1, blend));
    var g = gather * mouseWeight;
    var ease = reduce ? 1 : 0.08;
    var edgeEase = Math.min(1, blend * 1.5);
    var centerAlpha = Math.max(0, 1 - blend * 1.2);   // 生成态中心光晕淡出

    // ① 清空浮点光场
    clearField();

    // ② 先更新粒子位置/尺寸/透明度（光束要跟着粒子团重心走，所以必须先算）
    var massX = 0, massY = 0, massXX = 0, massYY = 0, massW = 0;
    for (var i = 0; i < idleParts.length; i++) {
      var p = idleParts[i];
      var bx = cx + p.offX, by = cy + p.offY;
      var hx = bx, hy = by, size, alpha;
      if (blend > 0.01) {
        hx = bx + (p.edgeX - bx) * edgeEase;
        hy = by + (p.edgeY - by) * edgeEase;
      }
      var tx = hx + (focusX + p.jx * 32 - hx) * g;
      var ty = hy + (focusY + p.jy * 32 - hy) * g;
      p.x += (tx - p.x) * ease;
      p.y += (ty - p.y) * ease;

      var span = p.idleSize + (p.gatherSize - p.idleSize) * g;
      var baseA = p.idleAlpha + (p.gatherAlpha - p.idleAlpha) * g;
      if (blend > 0.01) {
        size = span + (p.edgeSize - span) * edgeEase;
        alpha = (baseA + (p.edgeAlpha - baseA) * edgeEase) * Math.max(0, 1 - blend * 0.5);
      } else {
        size = span;
        alpha = baseA;
      }
      p.curSize = size;
      p.curAlpha = alpha;
      if (alpha > 0.0008 && size > 0.5) {
        var w = alpha;                       // 用亮度当权重求重心
        massX += p.x * w; massY += p.y * w;
        massXX += p.x * p.x * w; massYY += p.y * p.y * w;
        massW += w;
      }
    }

    // ③ 中心光束：跟随**粒子团的实际重心**，而不是直接跟光标 ——
    //    否则快速移动时粒子还在路上、光束已经先到光标，看起来就是"鼠标上粘了一团光，
    //    其余的再慢慢挪过去"。锚在重心上，整团光晕才是一个整体在移动。
    //    另外中心亮度还要乘"聚集度"：粒子散在路上的时候（rms 大）只给 30% 亮度，
    //    否则重心虽然跟着走了，但收得很紧的亮核仍会先成形、看着还是像粘在光标的亮斑。
    //    鼠标在页面里时它负责收束成形；鼠标移出浏览器后（g→0）淡出，只剩散开的粒子。
    if (centerAlpha > 0.002 && g > 0.02) {
      var baseX, baseY, conc = 0.3;
      if (massW > 0.0001) {
        massCx = massX / massW; massCy = massY / massW;
        var vx = Math.max(0, massXX / massW - massCx * massCx);
        var vy = Math.max(0, massYY / massW - massCy * massCy);
        massRms = Math.sqrt(vx + vy);         // 粒子团相对重心的散布半径
        conc = 0.3 + 0.7 * Math.max(0, Math.min(1, 1 - massRms / 110));
        baseX = massCx;
        baseY = massCy;
      } else {
        baseX = cx + (focusX - cx) * g;
        baseY = cy + (focusY - cy) * g;
      }
      // 三层配比（外圈"大而淡"只负责远处的范围，中间收得紧、中心提亮）：
      //   ① 560px / 0.040 —— 远处泛光
      //   ② 190px / 0.155 —— 收束主体
      //   ③ 100px / 0.540 —— 中心高光核
      var beam = centerAlpha * g * conc;
      centerConc = conc;
      splat(baseX, baseY, 560, hue, 0.040 * beam);
      splat(baseX, baseY, 190, hue, 0.155 * beam);
      splat(baseX, baseY, 100, hue, 0.540 * beam);
    } else {
      centerConc = 1;
    }

    // ④ 粒子当光源逐个累加（生成态飞向视口边缘）
    for (var k = 0; k < idleParts.length; k++) {
      var pk = idleParts[k];
      if (pk.curAlpha <= 0.0008 || pk.curSize <= 0.5) continue;
      splat(pk.x, pk.y, pk.curSize, hue + pk.hueOff, pk.curAlpha);
    }

    // ⑤ 边缘粒子（生成态）
    if (blend > 0.002) {
      var breathe = 0.94 + 0.06 * Math.sin(ts * 0.0008 + t0 * 0.001);
      for (var j = 0; j < edgeParts.length; j++) {
        var ep = edgeParts[j];
        var dx = focusX - ep.x, dy = focusY - ep.y;
        var dist = Math.sqrt(dx * dx + dy * dy) || 1;
        var near = Math.max(0, 1 - dist / 520);      // 离光标越近的边缘粒子越亮
        var pull = 14 * g;                            // 被光标轻微牵引
        var ea = ep.alpha * blend * breathe * (1 + 0.5 * near * g);
        if (ea <= 0.0008) continue;
        splat(ep.x + (dx / dist) * pull, ep.y + (dy / dist) * pull, ep.size, hue + ep.hueOff, ea);
      }
    }

    // ⑥ 一次性量化 + 放大回主画布，最后叠 display 分辨率的抖动层
    compositeField();
    drawDither(ts);

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
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
    // 扩散起点 = 当前鼠标位置（没有指针时退回光晕当前位置），并据此重算边缘目标
    if (pointerActive && !coarse) {
      spreadAnchorX = mouseX;
      spreadAnchorY = mouseY;
    } else {
      spreadAnchorX = focusX || homeX;
      spreadAnchorY = focusY || homeY;
    }
    assignEdgeTargets();
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
    else if (state === "arming") blend += (0.5 - blend) * 0.03;
    else blend += (0 - blend) * (state === "settling" ? 0.045 : 0.05);
    if (blend < 0.001) blend = 0;
    if (blend > 0.999) blend = 1;

    // 触屏没有 hover：关闭收束，改成缓慢自动漂移
    var wantGather = pointerActive && !coarse ? 1 : 0;
    gather += (wantGather - gather) * 0.05;
    if (gather < 0.001) gather = 0;

    if (pointerActive && !coarse) {
      focusX += (mouseX - focusX) * 0.06;           // 光标跟随带一点惯性
      focusY += (mouseY - focusY) * 0.06;
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
    var tDraw = now();
    draw(ts);
    frameAcc += now() - tDraw;
    // 光场诊断（和 frameMs 一样只是排查用的快照，不影响渲染）：
    // 亮度峰值的位置/强度 + 聚集度，用来确认"中心没有粘在光标上"、收束范围有没有变化。
    if (++fieldN >= 6) {
      var prof = profileAt(focusX, focusY);
      if (prof && layer) {
        layer.dataset.field = (prof.peak * 1000 | 0) + "|"
          + (prof.peakX | 0) + "|" + (prof.peakY | 0) + "|"
          + (gather * 1000 | 0) + "|" + (blend * 1000 | 0) + "|"
          + (centerConc * 1000 | 0) + "|"
          + (massCx | 0) + "|" + (massCy | 0) + "|" + (massRms | 0) + "|"
          + (focusX | 0) + "|" + (focusY | 0) + "|"
          + prof.rings.map(function (v) { return v * 1000 | 0; }).join(",");
      }
      fieldN = 0;
    }
    if (++frameN >= 30) {
      if (layer) layer.dataset.frameMs = (frameAcc / frameN).toFixed(2);
      frameAcc = 0;
      frameN = 0;
    }
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
    refreshTheme(false);                       // 主题变了就重建色相表
    if (!idleParts.length) {
      measure();
      focusX = homeX; focusY = homeY;
      rebuildParticles();
    }
    if (!kernel) buildKernel();                // 高斯衰减表（一次）
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
    // 调试用：读当前光场的亮度剖面（a = alpha 通道强度，1.0 = 满亮），不改动渲染状态。
    // 传 (px, py) 时额外返回以该 CSS 点为中心的同心环平均值，便于量"收束范围/中心高光"。
    profile: function (px, py) {
      var prof = profileAt(px, py);
      if (!prof) return null;
      var out = {
        vw: vw, vh: vh, fieldDiv: fieldDiv,
        peak: prof.peak, peakX: prof.peakX, peakY: prof.peakY,
        focusX: focusX, focusY: focusY, gather: gather, blend: blend, state: state,
        conc: centerConc
      };
      if (prof.rings) out.rings = prof.rings;
      return out;
    },
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
