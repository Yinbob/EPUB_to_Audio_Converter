// @ts-nocheck
// 由 tools/export_visuals.py 从原版光场生成。
export function mountAmbient() {
  var CFG = {
    enabled: true,
    huePalette: [212, 250, 196, 288],
    hueSegmentMs: 10000,
    hueCount: 32,
    spriteSize: 256,
    idleCount: 46,
    idleCoreCount: 10,
    idleSpread: 440,
    marqueeSeg: 230,
    marqueeAcross: 200,
    marqueeAlphaLight: 0.3,
    marqueeAlphaDark: 0.18,
    marqueeSatLight: 96,
    marqueeLightLight: 52,
    marqueeSatDark: 96,
    marqueeLightDark: 62,
    marqueeWaves: 5,
    marqueeFloor: 0.5,
    marqueeLapMs: 19000,
    marqueeHueSpread: 52,
    marqueeBreath: 0.14,
    armTimeoutMs: 6000,
    spriteSatLight: 86,
    spriteLightLight: 70,
    spriteSatDark: 90,
    spriteLightDark: 64,
    alphaScaleLight: 1.0,
    alphaScaleDark: 1.05,
    glowDownscale: 3,
    glowBlur: 11,
    fieldDiv: 5,
    hueLUT: 720,
    kernelSteps: 256,
    fieldMaxRadius: 150,
  };
  if (CFG.enabled === false) return;
  if (window.__ataAmbient) return window.__ataAmbient; // 脚本被重复注入时不再挂第二层

  var seed = Number(new URLSearchParams(location.search).get("ata-seed")) || 0;
  function random() {
    if (!seed) return Math.random();
    seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
    return seed / 4294967296;
  }
  var TAU = Math.PI * 2;
  var mq = function (q) {
    return !!(window.matchMedia && window.matchMedia(q).matches);
  };
  var reduce = mq("(prefers-reduced-motion: reduce)");
  var coarse = mq("(pointer: coarse)");
  // 调试用：URL 上带 ?ata-state=generating 就强制停在某个状态，
  // 方便不跑一次真实转换也能预览"跑马灯"（见 AGENTS.md）。
  var forcedState = (function () {
    var m = /[?&#]ata-state=([a-z]+)/.exec(
      (location.search || "") + "&" + (location.hash || ""),
    );
    return m && ["idle", "arming", "generating", "settling"].indexOf(m[1]) >= 0
      ? m[1]
      : null;
  })();

  var layer = null,
    base = null,
    canvas = null,
    ctx = null;
  // 光场：浮点 RGB 累加缓冲 + 量化用的 8bit 画布
  var fw = 0,
    fh = 0,
    fieldDiv = 5,
    fieldR = null,
    fieldG = null,
    fieldB = null;
  var fieldCanvas = null,
    fieldCtx = null,
    fieldImage = null,
    fieldData = null;
  var hueLUT = null,
    hueLUTDeep = null,
    hueLUTN = 0,
    kernel = null;
  var KERNEL_N = 256,
    FIELD_MAX_R = 60;
  var dpr = 1;
  var ditherPattern = null;
  var vw = 0,
    vh = 0,
    homeX = 0,
    homeY = 0;
  var idleParts = [],
    marquee = [],
    marqueeP = 0;
  var state = "idle";
  var themeDark = false,
    themeAlpha = 1; // 主题相关的 sprite 亮度与整体强度
  var blend = 0; // 生成态过渡：0 = 空闲，1 = 生成中
  var gather = 0; // 鼠标收束程度
  var focusX = 0,
    focusY = 0,
    mouseX = 0,
    mouseY = 0;
  var driftX = 0,
    driftY = 0,
    driftTargetX = 0,
    driftTargetY = 0;
  var spreadAnchorX = 0,
    spreadAnchorY = 0; // 扩散起点（点开始生成时的鼠标位置）
  var pointerActive = false;
  var wanderAt = 0;
  var profileBuf = null; // 调试剖面用的临时缓冲（只在 __ataAmbient.profile / profileAt 里用）
  var fieldN = 0; // data-field 诊断快照的帧计数
  var centerConc = 1; // 中心光束当前的"聚集度"（见 draw() ③）
  var massCx = 0,
    massCy = 0,
    massRms = 0; // 粒子团重心与散布半径（诊断用）
  var RING_EDGES = [0, 25, 60, 120, 200, 320, 460, 640, 900];
  var EDGE_BAND = 26; // 贴边光带的统计宽度（CSS px，诊断用）
  var t0 = (window.performance && performance.now()) || Date.now();
  var frameAcc = 0,
    frameN = 0; // 渲染耗时统计（写到 dataset.frameMs，便于排查性能）
  var raf = null,
    looping = false;
  var armTimer = null;
  var boxObserver = null,
    payloadObserver = null,
    observedBox = null,
    observedPayload = null;
  var bootInterval = null;

  function rand(a, b) {
    return a + random() * (b - a);
  }
  function now() {
    return (window.performance && performance.now()) || Date.now();
  }

  // ══ 光场构造（这一版的核心改动） ══
  // 每颗粒子 = 一个光源：在**浮点缓冲**里累加高斯贡献，整帧只在最后量化一次（并带抖动）。
  // 旧做法是几十张预渲染 8bit 光斑按不同透明度叠加——各自的量化台阶会露出可见边界与色带；
  // 浮点累加则不同色相在浮点域自然混合，从构造上就不存在"叠加边界"和"跳色"。
  function hslToRgb(h, s, l) {
    // h/s/l ∈ 0..1 → [r,g,b] ∈ 0..1
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
    var sat = themeDark ? CFG.spriteSatDark || 82 : CFG.spriteSatLight || 78;
    var light = themeDark
      ? CFG.spriteLightDark || 70
      : CFG.spriteLightLight || 76;
    var n = CFG.hueLUT || 720;
    hueLUT = new Float32Array(n * 3);
    for (var i = 0; i < n; i++) {
      var rgb = hslToRgb(i / n, sat / 100, light / 100);
      hueLUT[i * 3] = rgb[0];
      hueLUT[i * 3 + 1] = rgb[1];
      hueLUT[i * 3 + 2] = rgb[2];
    }
    // 光条专用的"深色"表：饱和度更高、明度更低 → 通道比值更浓。
    // 注意 compositeField() 会按最大通道归一化，所以明度只影响"颜色有多深"，
    // 不影响画出来的不透明度（不透明度由累加量 alpha 决定）。
    var dsat = themeDark ? CFG.marqueeSatDark || 96 : CFG.marqueeSatLight || 96;
    var dlight = themeDark
      ? CFG.marqueeLightDark || 62
      : CFG.marqueeLightLight || 52;
    hueLUTDeep = new Float32Array(n * 3);
    for (var j = 0; j < n; j++) {
      var rgb2 = hslToRgb(j / n, dsat / 100, dlight / 100);
      hueLUTDeep[j * 3] = rgb2[0];
      hueLUTDeep[j * 3 + 1] = rgb2[1];
      hueLUTDeep[j * 3 + 2] = rgb2[2];
    }
    hueLUTN = n;
  }

  // 高斯衰减 exp(-3t)，t=(d/R)²：曲线与旧的多段渐变 stops 基本一致，保证样式不变
  function buildKernel() {
    kernel = new Float32Array(KERNEL_N + 1);
    for (var i = 0; i <= KERNEL_N; i++)
      kernel[i] = Math.exp(-3 * (i / KERNEL_N));
  }

  function isDarkTheme() {
    if (
      document.documentElement &&
      document.documentElement.classList.contains("dark")
    )
      return true;
    return !!(document.body && document.body.classList.contains("dark"));
  }

  // 往光场里累加一个**椭圆**光源（中心/半轴都是 CSS 像素，轴对齐）。
  // 边缘光条就是用它画的：一长一短两个半轴 → 贴着边框的一条光带。
  function splatEllipse(x, y, rx, ry, hue, alpha, deep) {
    if (alpha <= 0.0008) return;
    var R2x = Math.max(0.7, Math.min(rx / fieldDiv, FIELD_MAX_R));
    var R2y = Math.max(0.7, Math.min(ry / fieldDiv, FIELD_MAX_R));
    var lut = deep ? hueLUTDeep : hueLUT;
    var h = ((hue % 360) + 360) % 360;
    var pos = (h / 360) * hueLUTN;
    var i0 = Math.floor(pos),
      f = pos - i0;
    var j0 = (i0 % hueLUTN) * 3,
      j1 = ((i0 + 1) % hueLUTN) * 3;
    var cr = lut[j0] + (lut[j1] - lut[j0]) * f;
    var cg = lut[j0 + 1] + (lut[j1 + 1] - lut[j0 + 1]) * f;
    var cb = lut[j0 + 2] + (lut[j1 + 2] - lut[j0 + 2]) * f;
    var e = Math.min(1, alpha * themeAlpha);
    var cx = x / fieldDiv,
      cy = y / fieldDiv;
    var x0 = Math.max(0, Math.floor(cx - R2x)),
      x1 = Math.min(fw - 1, Math.ceil(cx + R2x));
    var y0 = Math.max(0, Math.floor(cy - R2y)),
      y1 = Math.min(fh - 1, Math.ceil(cy + R2y));
    var invX = 1 / (R2x * R2x),
      invY = 1 / (R2y * R2y);
    for (var py = y0; py <= y1; py++) {
      var dy = py - cy,
        ty = dy * dy * invY,
        row = py * fw;
      for (var px = x0; px <= x1; px++) {
        var dx = px - cx;
        var t = dx * dx * invX + ty;
        if (t >= 1) continue;
        var k = kernel[(t * KERNEL_N) | 0] * e;
        var idx = row + px;
        fieldR[idx] += cr * k;
        fieldG[idx] += cg * k;
        fieldB[idx] += cb * k;
      }
    }
  }

  // 圆形光源 = 两个半轴相等
  function splat(x, y, radius, hue, alpha) {
    splatEllipse(x, y, radius, radius, hue, alpha);
  }

  function clearField() {
    fieldR.fill(0);
    fieldG.fill(0);
    fieldB.fill(0);
  }

  // 光场 → 8bit（全流程唯一的量化点）→ 放大回主画布；抖动在 display 分辨率上叠加
  function compositeField() {
    var data = fieldData.data;
    var fi = 0,
      di = 0;
    for (var y = 0; y < fh; y++) {
      for (var x = 0; x < fw; x++, fi++, di += 4) {
        var sr = fieldR[fi],
          sg = fieldG[fi],
          sb = fieldB[fi];
        var a = sr > sg ? sr : sg;
        if (sb > a) a = sb;
        if (a <= 0.0005) {
          data[di + 3] = 0;
          continue;
        }
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
      data[i * 4] = random() < 0.5 ? 0 : 255;
      data[i * 4 + 1] = random() < 0.5 ? 0 : 255;
      data[i * 4 + 2] = random() < 0.5 ? 0 : 255;
      data[i * 4 + 3] = 6; // ±3/255，平均色为中性
    }
    g.putImageData(img, 0, 0);
    ditherPattern = ctx.createPattern(c, "repeat");
  }

  function drawDither() {
    if (!ditherPattern || !canvas) return;
    ctx.save();
    ctx.setTransform(1, 0, 0, 1, 0, 0); // 按设备像素 1:1 铺，避免被放大成色块
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
    themeAlpha = dark ? CFG.alphaScaleDark || 1.7 : CFG.alphaScaleLight || 1;
    buildHueLUT(); // 主题决定饱和度/明度，色相表要重建
    if (reduce) draw(now());
  }

  // ── 尺寸 / 粒子 ──
  function measure() {
    vw = Math.max(window.innerWidth || 0, 320);
    vh = Math.max(window.innerHeight || 0, 320);
    homeX = vw * 0.5;
    homeY = vh * 0.32;
    // 扩散起点默认在光晕家位置；视口变化后若已跑到画面外就拉回来
    if (!spreadAnchorX && !spreadAnchorY) {
      spreadAnchorX = homeX;
      spreadAnchorY = homeY;
    }
    if (spreadAnchorX > vw || spreadAnchorY > vh) {
      spreadAnchorX = homeX;
      spreadAnchorY = homeY;
    }
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
    bakeDither(); // DPR 可能变化，噪声瓦片按设备像素重建
  }

  // ── 视口周长参数化 ──
  // 沿边框顺时针走：上边（左→右）→ 右边（上→下）→ 下边（右→左）→ 左边（下→上）。
  // 跑马灯的"亮块"和汇聚光束的落点都用这一套坐标，保证散开的光正好落在光条上。
  function perimeterPoint(s) {
    s = ((s % marqueeP) + marqueeP) % marqueeP;
    if (s < vw) return { x: s, y: 0 };
    s -= vw;
    if (s < vh) return { x: vw, y: s };
    s -= vh;
    if (s < vw) return { x: vw - s, y: vh };
    s -= vw;
    return { x: 0, y: vh - s };
  }

  // 沿四边均匀铺一排椭圆光条：中心压在边框线上（窗口里只看得到内侧一半，
  // 于是越靠边颜色越深、朝画面内渐淡）；每条的色相按周长位置错开 → 一圈上同时有几种颜色。
  function buildMarquee() {
    marqueeP = 2 * (vw + vh);
    marquee = [];
    var seg = Math.max(90, CFG.marqueeSeg || 230);
    var across = Math.max(60, CFG.marqueeAcross || 200);
    var spread = CFG.marqueeHueSpread || 46;
    var half = seg * 0.95;
    // 每条边的光条数按边长算，四边密度一致
    var nx = Math.max(2, Math.round(vw / seg));
    var ny = Math.max(2, Math.round(vh / seg));
    for (var axis = 0; axis < 2; axis++) {
      var count = axis === 0 ? nx : ny,
        len = axis === 0 ? vw : vh;
      for (var i = 0; i < count; i++) {
        var pos = (len * (i + 0.5)) / count;
        // 每边两个方向各一条（上/下、左/右）
        for (var side = 0; side < 2; side++) {
          var s, x, y;
          if (axis === 0 && side === 0) {
            s = pos;
            x = pos;
            y = 0;
          } // 上
          else if (axis === 0) {
            s = vw + vh + (vw - pos);
            x = pos;
            y = vh;
          } // 下
          else if (side === 0) {
            s = vw + pos;
            x = vw;
            y = pos;
          } // 右
          else {
            s = vw + vh + vw + (vh - pos);
            x = 0;
            y = pos;
          } // 左
          marquee.push({
            x: x,
            y: y,
            rx: axis === 0 ? half : across,
            ry: axis === 0 ? across : half,
            sn: s / marqueeP, // 0..1 的周长坐标（行进波用它）
            hueOff: Math.sin((s / marqueeP) * TAU * 2) * spread,
          });
        }
      }
    }
  }

  function assignEdgeTargets() {
    // 汇聚的光束散开时**沿周长均匀分配**落点（不是按角度射线）：这样四边会被均匀铺满，
    // 正好铺在跑马灯光条上。粒子按相对扩散起点的角度排序后依次取点，减少航线交叉。
    if (!marqueeP) buildMarquee();
    var ax = spreadAnchorX,
      ay = spreadAnchorY;
    var n = idleParts.length;
    var order = [];
    for (var i = 0; i < n; i++) order.push(i);
    order.sort(function (a, b) {
      var pa = idleParts[a],
        pb = idleParts[b];
      return (
        Math.atan2(pa.y - ay, pa.x - ax) - Math.atan2(pb.y - ay, pb.x - ax)
      );
    });
    for (var k = 0; k < n; k++) {
      var p = idleParts[order[k]];
      var pt = perimeterPoint(((k + 0.5 + p.angleJitter * 0.8) / n) * marqueeP);
      p.edgeX = pt.x;
      p.edgeY = pt.y;
      p.edgeSize = rand(70, 120);
      p.edgeAlpha = rand(0.03, 0.058);
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
      var angle = random() * TAU;
      var radius = i < core ? random() * 60 : Math.sqrt(random()) * spread;
      var isCore = i < core;
      idleParts.push({
        offX: Math.cos(angle) * radius,
        offY: Math.sin(angle) * radius,
        jx: rand(-1, 1),
        jy: rand(-1, 1),
        x: homeX + Math.cos(angle) * radius,
        y: homeY + Math.sin(angle) * radius,
        // 大半径、低透明度的光斑：靠叠加形成连续光晕（不要能看出一个个圈）
        idleSize: isCore ? rand(200, 320) : rand(150, 270),
        // 汇聚时靠"抖动收紧"来集中（粒子半径要保持足够大：它们靠在光标处密集重叠
        // 把中心顶亮，半径缩太小反而会让中心变暗）
        gatherSize: isCore ? rand(60, 105) : rand(45, 85),
        idleAlpha: isCore ? rand(0.042, 0.075) : rand(0.02, 0.042),
        gatherAlpha: isCore ? rand(0.048, 0.085) : rand(0.026, 0.052),
        hueOff: rand(-16, 16),
        angleJitter: rand(-0.12, 0.12),
        edgeX: 0,
        edgeY: 0,
        edgeSize: 0,
        edgeAlpha: 0,
      });
    }
    buildMarquee();
    assignEdgeTargets();
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
    var pos = ((Math.max(0, ts - t0) % span) / span) * n;
    var i = Math.floor(pos) % n;
    var f = pos - Math.floor(pos);
    var p0 = pal[(i - 1 + n) % n],
      p1 = pal[i];
    var p2 = pal[(i + 1) % n],
      p3 = pal[(i + 2) % n];
    var f2 = f * f,
      f3 = f2 * f;
    return (
      0.5 *
      (2 * p1 +
        (-p0 + p2) * f +
        (2 * p0 - 5 * p1 + 4 * p2 - p3) * f2 +
        (-p0 + 3 * p1 - 3 * p2 + p3) * f3)
    );
  }

  // 读出当前光场的亮度分布：峰值强度 + 峰值位置（CSS px）+ 内部缓冲。
  // 传 (px,py) 时顺带按"到该点的距离"分桶，给出同心环平均亮度（一趟扫完，不额外多扫）。
  // 亮度取 max(r,g,b)——和 compositeField() 里决定 alpha 的量一致。
  function profileAt(px, py) {
    if (!fieldR || !fw || !fh) return null;
    var n = fw * fh,
      i;
    if (!profileBuf || profileBuf.length !== n)
      profileBuf = new Float32Array(n);
    var max = 0,
      maxI = 0;
    for (i = 0; i < n; i++) {
      var a = fieldR[i];
      if (fieldG[i] > a) a = fieldG[i];
      if (fieldB[i] > a) a = fieldB[i];
      profileBuf[i] = a;
      if (a > max) {
        max = a;
        maxI = i;
      }
    }
    var out = {
      peak: max,
      peakX: (maxI % fw) * fieldDiv,
      peakY: ((maxI / fw) | 0) * fieldDiv,
    };
    if (px == null || py == null) return out;
    var rings = RING_EDGES.length - 1,
      sum = new Float64Array(rings),
      cnt = new Float64Array(rings);
    var fx = px / fieldDiv,
      fy = py / fieldDiv;
    var edge = [],
      r;
    for (r = 0; r < RING_EDGES.length; r++) edge.push(RING_EDGES[r] / fieldDiv);
    // 顺便统计"贴边光带"：离视口四边 EDGE_BAND 像素以内的平均亮度，
    // 以及顶边光带沿长度方向的 16 段剖面（看跑马灯的亮块有没有在跑）。
    var BAND = Math.max(1, Math.round(EDGE_BAND / fieldDiv));
    var PROFN = 16;
    var ebSum = 0,
      ebCnt = 0,
      prof = new Float64Array(PROFN),
      pcnt = new Float64Array(PROFN);
    for (var y = 0; y < fh; y++) {
      var dy = y - fy,
        dy2 = dy * dy;
      for (var x = 0; x < fw; x++) {
        var dx = x - fx;
        var d = Math.sqrt(dx * dx + dy2);
        for (r = 0; r < rings; r++) {
          if (d < edge[r + 1]) {
            sum[r] += profileBuf[y * fw + x];
            cnt[r]++;
            break;
          }
        }
        var v = profileBuf[y * fw + x];
        if (y < BAND || y >= fh - BAND || x < BAND || x >= fw - BAND) {
          ebSum += v;
          ebCnt++;
        }
        if (y < BAND) {
          var bi = Math.min(PROFN - 1, Math.floor((x * PROFN) / fw));
          prof[bi] += v;
          pcnt[bi]++;
        }
      }
    }
    out.rings = [];
    for (r = 0; r < rings; r++) out.rings.push(cnt[r] ? sum[r] / cnt[r] : 0);
    out.edgeMean = ebCnt ? ebSum / ebCnt : 0;
    out.topProf = [];
    for (r = 0; r < PROFN; r++)
      out.topProf.push(pcnt[r] ? prof[r] / pcnt[r] : 0);
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
    var centerAlpha = Math.max(0, 1 - blend * 1.2); // 生成态中心光晕淡出

    // ① 清空浮点光场
    clearField();

    // ② 先更新粒子位置/尺寸/透明度（光束要跟着粒子团重心走，所以必须先算）
    var massX = 0,
      massY = 0,
      massXX = 0,
      massYY = 0,
      massW = 0;
    for (var i = 0; i < idleParts.length; i++) {
      var p = idleParts[i];
      var bx = cx + p.offX,
        by = cy + p.offY;
      var hx = bx,
        hy = by,
        size,
        alpha;
      if (blend > 0.01) {
        hx = bx + (p.edgeX - bx) * edgeEase;
        hy = by + (p.edgeY - by) * edgeEase;
      }
      var tx = hx + (focusX + p.jx * 26 - hx) * g;
      var ty = hy + (focusY + p.jy * 26 - hy) * g;
      p.x += (tx - p.x) * ease;
      p.y += (ty - p.y) * ease;

      var span = p.idleSize + (p.gatherSize - p.idleSize) * g;
      var baseA = p.idleAlpha + (p.gatherAlpha - p.idleAlpha) * g;
      if (blend > 0.01) {
        size = span + (p.edgeSize - span) * edgeEase;
        alpha =
          (baseA + (p.edgeAlpha - baseA) * edgeEase) *
          Math.max(0, 1 - blend * 0.5);
      } else {
        size = span;
        alpha = baseA;
      }
      p.curSize = size;
      p.curAlpha = alpha;
      if (alpha > 0.0008 && size > 0.5) {
        var w = alpha; // 用亮度当权重求重心
        massX += p.x * w;
        massY += p.y * w;
        massXX += p.x * p.x * w;
        massYY += p.y * p.y * w;
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
      var baseX,
        baseY,
        conc = 0.3;
      if (massW > 0.0001) {
        massCx = massX / massW;
        massCy = massY / massW;
        var vx = Math.max(0, massXX / massW - massCx * massCx);
        var vy = Math.max(0, massYY / massW - massCy * massCy);
        massRms = Math.sqrt(vx + vy); // 粒子团相对重心的散布半径
        conc = 0.3 + 0.7 * Math.max(0, Math.min(1, 1 - massRms / 110));
        baseX = massCx;
        baseY = massCy;
      } else {
        baseX = cx + (focusX - cx) * g;
        baseY = cy + (focusY - cy) * g;
      }
      // 三层配比（外圈"大而淡"只负责远处的范围，中间收得紧、中心提亮）：
      //   ① 560px / 0.040 —— 远处泛光
      //   ② 190px / 0.158 —— 收束主体
      //   ③  76px / 0.600 —— 中心高光核（半径越小、高光越集中在正中）
      var beam = centerAlpha * g * conc;
      centerConc = conc;
      splat(baseX, baseY, 560, hue, 0.04 * beam);
      splat(baseX, baseY, 190, hue, 0.158 * beam);
      splat(baseX, baseY, 76, hue, 0.6 * beam);
    } else {
      centerConc = 1;
    }

    // ④ 粒子当光源逐个累加（生成态飞向视口边缘）
    for (var k = 0; k < idleParts.length; k++) {
      var pk = idleParts[k];
      if (pk.curAlpha <= 0.0008 || pk.curSize <= 0.5) continue;
      splat(pk.x, pk.y, pk.curSize, hue + pk.hueOff, pk.curAlpha);
    }

    // ⑤ 生成态：沿四边铺开的彩色光条 + 绕圈跑动的亮块（跑马灯）
    if (blend > 0.002 && marquee.length) {
      var lapMs = CFG.marqueeLapMs || 19000;
      var waves = CFG.marqueeWaves || 3;
      // 相位按"亮块绕视口跑一整圈 = lapMs"来推进（所以乘 waves：一圈里有 waves 个亮块）
      var phase = ((ts % lapMs) / lapMs) * waves;
      var breath =
        1 + (CFG.marqueeBreath || 0.12) * Math.sin(ts * 0.0007 + t0 * 0.0009);
      // 不透明度按主题取（浅色底要更足），色相用"深色表" → 浓而且醒目
      var marqueeA = themeDark
        ? CFG.marqueeAlphaDark || 0.18
        : CFG.marqueeAlphaLight || 0.3;
      var baseA = marqueeA * blend * breath;
      var floor = CFG.marqueeFloor || 0.45;
      for (var j = 0; j < marquee.length; j++) {
        var mq = marquee[j];
        // 行进波：亮块沿周长移动（方波化后是"亮段 + 暗段"，即跑马灯）
        var wv = 0.5 + 0.5 * Math.sin(TAU * (mq.sn * waves - phase));
        var a = baseA * (floor + (1 - floor) * wv * wv);
        if (a <= 0.0008) continue;
        splatEllipse(mq.x, mq.y, mq.rx, mq.ry, hue + mq.hueOff, a, true);
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
    var on = state === "generating" || state === "arming";
    if (on) layer.classList.add("generating");
    else layer.classList.remove("generating");
  }

  function setState(next) {
    if (reduce && next === "settling") next = "idle";
    if (next === state) return;
    state = next;
    if (armTimer && next !== "arming") {
      clearTimeout(armTimer);
      armTimer = null;
    }
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
      if (state === "arming") setState("idle"); // 表单校验没过：安静地退回去
    }, CFG.armTimeoutMs || 6000);
  }

  function signalSettle() {
    setState("settling");
  }

  // ── 交互 ──
  function onMouseMove(e) {
    pointerActive = true;
    mouseX = e.clientX;
    mouseY = e.clientY;
  }

  function onMouseLeave() {
    pointerActive = false;
    var dx = mouseX - homeX,
      dy = mouseY - homeY;
    var len = Math.sqrt(dx * dx + dy * dy) || 1;
    var d = 140 + random() * 100;
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
    if (
      btn.classList.contains("btn-primary") &&
      text.indexOf("开始生成") >= 0
    ) {
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

  function onThemeChange() {
    refreshTheme(false);
  }

  // ── 渲染循环 ──
  function step(ts) {
    if (!layer || !layer.isConnected) {
      cleanup();
      return;
    }

    if (state === "generating") blend += (1 - blend) * 0.03;
    // arming（已点按钮、还没收到后端"真的开跑"）里**不散开**：没选文件 / 表单报错时
    // 点按钮不会触发跑马灯，只有等进度条真的变成 active（blend 才会朝 1 走）才播放。
    else if (state === "arming") blend += (0 - blend) * 0.05;
    else blend += (0 - blend) * (state === "settling" ? 0.045 : 0.05);
    if (blend < 0.001) blend = 0;
    if (blend > 0.999) blend = 1;

    // 触屏没有 hover：关闭收束，改成缓慢自动漂移
    var wantGather = pointerActive && !coarse ? 1 : 0;
    gather += (wantGather - gather) * 0.05;
    if (gather < 0.001) gather = 0;

    if (pointerActive && !coarse) {
      focusX += (mouseX - focusX) * 0.06; // 光标跟随带一点惯性
      focusY += (mouseY - focusY) * 0.06;
      driftX += (0 - driftX) * 0.01;
      driftY += (0 - driftY) * 0.01;
    } else {
      if (coarse && ts > wanderAt) {
        wanderAt = ts + 7000; // 每 7 秒换一个漂移目标
        driftTargetX = rand(-90, 90);
        driftTargetY = rand(-60, 60);
      }
      driftX += (driftTargetX - driftX) * 0.006;
      driftY += (driftTargetY - driftY) * 0.006;
      var fx = homeX + driftX,
        fy = homeY + driftY;
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
        layer.dataset.field =
          ((prof.peak * 1000) | 0) +
          "|" +
          (prof.peakX | 0) +
          "|" +
          (prof.peakY | 0) +
          "|" +
          ((gather * 1000) | 0) +
          "|" +
          ((blend * 1000) | 0) +
          "|" +
          ((centerConc * 1000) | 0) +
          "|" +
          (massCx | 0) +
          "|" +
          (massCy | 0) +
          "|" +
          (massRms | 0) +
          "|" +
          (focusX | 0) +
          "|" +
          (focusY | 0) +
          "|" +
          prof.rings
            .map(function (v) {
              return (v * 1000) | 0;
            })
            .join(",") +
          "|" +
          ((prof.edgeMean * 1000) | 0) +
          "|" +
          prof.topProf
            .map(function (v) {
              return (v * 1000) | 0;
            })
            .join(",");
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
    refreshTheme(false); // 主题变了就重建色相表
    if (!idleParts.length) {
      measure();
      focusX = homeX;
      focusY = homeY;
      rebuildParticles();
    }
    if (!kernel) buildKernel(); // 高斯衰减表（一次）
    paintClass();

    if (forcedState) setState(forcedState); // 调试强制态（?ata-state=...）
    if (reduce) draw(now());
    else startLoop();
  }

  function cleanup() {
    if (layer) layer.remove();
    delete window.__ataAmbient;
    stopLoop();
    if (armTimer) {
      clearTimeout(armTimer);
      armTimer = null;
    }
    if (boxObserver) {
      boxObserver.disconnect();
      boxObserver = null;
    }
    if (payloadObserver) {
      payloadObserver.disconnect();
      payloadObserver = null;
    }
    if (bootInterval) {
      clearInterval(bootInterval);
      bootInterval = null;
    }
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
    getState: function () {
      return state;
    },
    getBlend: function () {
      return blend;
    },
    draw: draw,
    rebuild: function () {
      measure();
      rebuildParticles();
      draw(now());
    },
    // 调试用：读当前光场的亮度剖面（a = alpha 通道强度，1.0 = 满亮），不改动渲染状态。
    // 传 (px, py) 时额外返回以该 CSS 点为中心的同心环平均值，便于量"收束范围/中心高光"。
    profile: function (px, py) {
      var prof = profileAt(px, py);
      if (!prof) return null;
      var out = {
        vw: vw,
        vh: vh,
        fieldDiv: fieldDiv,
        peak: prof.peak,
        peakX: prof.peakX,
        peakY: prof.peakY,
        focusX: focusX,
        focusY: focusY,
        gather: gather,
        blend: blend,
        state: state,
        conc: centerConc,
      };
      if (prof.rings) out.rings = prof.rings;
      if (prof.topProf) {
        out.edgeMean = prof.edgeMean;
        out.topProf = prof.topProf;
      }
      return out;
    },
    cleanup: cleanup,
    reduceMotion: reduce,
    coarsePointer: coarse,
    forcedState: forcedState,
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

    document.addEventListener("ata-theme-change", onThemeChange);
    if (document.hidden) stopLoop();
  }

  init();

  return window.__ataAmbient;
}
