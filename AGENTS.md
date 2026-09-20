# AGENTS.md

Fork of `p0n1/epub_to_audiobook`, customized for a Chinese workflow (MiMo + MiniMax TTS, Apple-style Gradio UI). Upstream README usage docs are partially stale — trust the code.

## Entry points (all at repo root)
- `python3 main.py <input.epub|.doc|.docx> <output_dir> [--tts ...]` — CLI converter.
- `python3 main_ui.py [--host 127.0.0.1 --port 7862]` — Apple-style Gradio WebUI (sole UI; `audiobook_generator/ui/web_ui.py`).
- TTS providers registered in `audiobook_generator/tts_providers/base_tts_provider.py:get_supported_tts_providers()`.

## Environment & credentials
- Azure: `MS_TTS_KEY`, `MS_TTS_REGION`. Edge: no key. MiniMax: `MINIMAX_API_KEY` (WebSocket API).
- The `openai` provider was rewritten to target MiMo (xiaomimimo.com): defaults `model_name="mimo-v2.5-tts"`, accepts only MiMo voices, calls `chat.completions.create` with an `audio` block (not `audio.speech`).
- MiMo credentials resolve in order (`audiobook_generator/utils/mimo_config.py`): `OPENAI_API_KEY`/`OPENAI_BASE_URL` env → `mimo_config.json` at repo root (gitignored; template `mimo_config.json.example`) → interactive prompt.

## Gotchas
- ffmpeg/ffprobe are auto-detected (env `FFMPEG_PATH`/`FFPROBE_PATH` → `shutil.which` → common paths) in `main.py` and `chatterbox_tts_provider.py`; no longer hardcoded to `/opt/homebrew`. Install ffmpeg via `brew` (macOS) or `apt`/conda-forge (Linux).
- `chatterbox_tts_provider.py` imports torch lazily (`try/except`); the app starts without torch. Chatterbox features fail with a clear `ImportError` only when selected. API engines (MiMo/Edge/MiniMax) need no torch.
- WebUI (`web_ui.py`) does `from main import main` and builds a `GeneralConfig(None)`, then fills fields manually — config fields default to `None` (not CLI defaults); providers must handle `None`.
- Chapters are converted via `multiprocessing.Pool` (`imap_unordered`) — chapter order not guaranteed. `--worker_count` = pool size (default 1).
- WebUI runs conversion in a subprocess `Process`; the batch worker (`_batch_worker`) must stay module-top-level for pickling.
- 章节并行必须用 spawn：`audiobook_generator.py` 用 `multiprocessing.get_context("spawn").Pool`，WebUI 的 `_batch_worker` 用 `get_context("spawn").Process`。Linux 默认的 `fork` 会继承父进程已初始化的 CUDA 状态（父进程在 argparse 校验设备、构造 provider 时就会调用 `torch.cuda`），导致 worker 加载模型时报 `Cannot re-initialize CUDA in forked subprocess`。GPU 场景建议 `worker_count=1`（每个 worker 独立加载一份模型）。
- `.webui_settings.json` (repo root) auto-persists WebUI checkbox state.
- Logs go to `logs/` (`EtA_*.log`, `EtA_WebUI_*.log`); `setup_logging` resets root handlers.

## Tests
- `unittest`-based; no `pyproject.toml`/`setup.py`/pytest config; no test CI (GH Actions only builds Docker image on tag push).
- Run from repo root: `python3 -m pytest tests` (or `python3 -m unittest discover tests`). `tests/args_test.py` does `from main import handle_args`, so repo root must be on `sys.path`.
- `tests/test_utils.py` only defines config-builder helpers, not tests. Real tests: `args_test.py`, `split_test.py`, `tests/audiobook_generator/tts_providers/*_test.py`.

## Conventions
- No packaging/lint/format/typecheck config; deps in `requirements.txt`.
- UI strings and new comments are in Chinese — match that style for UI-facing text.

## Chatterbox TTS（本地离线语音引擎）

### 环境
- **虚拟环境**: `venv_chatterbox/`（项目根目录），创建方式：`python3 -m venv venv_chatterbox --system-site-packages`
- **安装**: `./venv_chatterbox/bin/pip install chatterbox-tts`，随后必须 `./venv_chatterbox/bin/pip install --force-reinstall --no-deps gradio==5.50.0 gradio_client==1.14.0`（chatterbox-tts 会强装 gradio 6.8.0，破坏本 UI）。NVIDIA GPU 需先装 cu124 版 torch，详见 README「Linux 服务器部署（Miniconda）」。
- **注意**: chatterbox-tts 0.1.7 强制依赖 gradio 6.8.0，与项目使用的 gradio 5.50.0 冲突。虚拟环境通过 `--system-site-packages` 继承主环境 gradio 5.50.0，安装后仍需把 venv 内的 gradio 固定回 5.50.0，不要升级。
- **已知问题**: `perth` 包的 `PerthImplicitWatermarker` 因缺少 `perth_net` 依赖无法导入，已在 `chatterbox/tts.py` 中修补为回退到 `DummyWatermarker`。

### 模型缓存
- 所有模型文件下载到 `venv_chatterbox/.cache/huggingface/`，与虚拟环境一同管理
- 总计约 3.1 GB（`ve.safetensors`、`t3_cfg.safetensors` ~2GB、`s3gen.safetensors` ~1GB、`tokenizer.json`、`conds.pt`）
- 删除方式：`rm -rf venv_chatterbox/` 即可清除整个环境和模型缓存
- 如果网络下载失败，尝试 `unset http_proxy https_proxy ALL_PROXY && curl --noproxy "*"`

### 运行方式
- **CLI**: `./run_cli.sh input.epub output_dir --tts chatterbox --chatterbox_device cuda --chapter_start N --chapter_end N`（或 `python3 main.py ...`，会自动 execv 到 `venv_chatterbox/`）
- **Apple 风格 UI**: `./run_ui.sh`（默认 `0.0.0.0:7862`）
- UI 启动后在 TTS 提供商下拉菜单中选择 **Chatterbox**，在 **🎯 Chatterbox** 标签页中配置设备等参数
- `venv_chatterbox/run_with_chatterbox.sh` / `run_ui_chatterbox.sh` 为旧脚本，未纳入 git，优先使用根目录的 `run_cli.sh` / `run_ui.sh`

### CLI 参数
```
--chatterbox_device {auto,cpu,cuda,mps}  设备选择（默认 auto）
--chatterbox_reference_audio              参考音频路径，用于语音克隆（可选）
--chatterbox_exaggeration                 语气夸张程度 0.0-1.0（默认 0.5）
--chatterbox_cfg_weight                   CFG 引导权重 0.0-1.0（默认 0.5）
--chatterbox_speed                        语速显示值 0.2-2.0（默认 1.0，实际倍率 = 显示值 × 0.7）
```

### 默认值与实现要点（v2 调整）
- **输出格式默认 `mp3`**（`DEFAULT_CHATTERBOX_OUTPUT_FORMAT`）：非 wav 需要 ffmpeg，`validate_config` 会在缺失时给出中文报错。
- **语速对外用"显示值"**：`DEFAULT_CHATTERBOX_SPEED=1.0`、`CHATTERBOX_SPEED_SCALE=0.7`、范围 `0.2~2.0`（`get_chatterbox_speed_range()`）。
  provider 里 `display_speed` 是显示值、`speed` 是折算后的 atempo 倍率；显示 1.0 ≈ 旧版 0.7 的听感。WebUI 滑块与 CLI 默认值都取常量，避免多处硬编码。
- **分片合并**：`should_use_pydub_merge()` 决定合并方式 —— 只有"单分片 + wav"才用直接写入，
  其余（多分片或压缩格式）自动切 pydub 合并，否则直接拼接会丢音频（wav 只认第一块、mp3 拼接处丢帧）。无 ffmpeg 时回退直接写入并打 warning。
- WebUI 顶部进度条解析见 `audiobook_generator/ui/progress_parser.py`（纯函数、有单测），支持 Chatterbox 的块级进度
  `chapter-<章>_<标题>_chunk_<i>_of_<n>`；批次标记由 `web_ui._batch_worker` 通过 logger 写入同一个日志文件。
- **进度条的 `gr.Timer` 绝不能放进 `visible=False` 的容器**：Gradio 前端对"有效可见性为 false"的组件不应用 `active` 更新、
  也不会启动 tick（`ct()` 判定 + Timer 在 onMount 里 setInterval），会导致进度条永远停在「等待开始生成...」（所有引擎一致）。
  另外用 `ui.load(fn=get_progress_info, ...)` 做页面加载同步，保证刷新/新会话也能看到当前进度；`webui_log_file` 需为绝对路径。
  回归测试：`tests/audiobook_generator/ui/progress_wiring_test.py`（结构 + 五态，需在 venv 解释器下运行，其他解释器自动跳过）。
  ⚠️ **页面上加载到的"终态"要按会话过滤**：`webui_log_file` 是**服务进程启动时创建一次**并一直累积的，
  批次结束（`running_process` 还在但已不存活）后 `decide_progress_state()` 会**永远**返回
  `mode=finished/interrupted/failed`。不设闸门的话，每次新开浏览器都会把"上一个文件已完成"的卡片
  弹出来闪一下（用户反馈过，顺带还会让背景跑马灯闪一下）。所以 `HEAD_HTML` 里用 `sawActive`
  记录"本会话见过 starting/running/book_done"，终态且 `!sawActive` 时**直接 return**——
  注意必须在 `box.classList.remove('idle', 'active', …)` **之前**返回，否则仍会被标成 `active`。
  实时状态（正在跑）对新会话照常显示；本次会话真跑完的终态仍按 `scheduleHide()` 显示
  （完成 6s、中断/失败 12s 后收起）。
- **「停止转换」必须整组终止**：`_batch_worker` 会先 `os.setsid()` 自成进程组，章节进程池 worker 继承该组；
  `web_ui._terminate_running_batch()` 用 `killpg` 先 SIGTERM 后 SIGKILL 终止整组。只 `terminate()` 批处理进程的话，
  正在合成的 worker 会变孤儿继续跑（表现为"停止按钮没反应"），对所有引擎都适用。停止后状态显示「⏹ 已停止（可再次点击开始）」。
- **日志页读取窗口**：`gradio_log.Log` 默认只从最后 100 行开始读，页面在生成中途打开/刷新时会显得"日志不全"，
  因此显式传 `tail=800, xterm_scrollback=2000`；`.app-card` 上不要加 `overflow: hidden`（会裁剪日志终端视图）。
- **氛围背景层**：`audiobook_generator/ui/ambient_background.py` 提供固定全屏 canvas 光晕
  （`#ata-bg` / `#ata-bg-base` / `#ata-bg-canvas`），由 `web_ui.py` 拼到 `HEAD_HTML` 与 `CUSTOM_CSS` 末尾。
  空闲态光晕随鼠标收束、移开缓慢漂移；点「开始生成」进入 `arming`，进度条类名变为 `active/starting/running`
  后进入 `generating`（光晕散向视口四周边框并呼吸），`done/warn/collapsed/idle` 或点「停止转换」回到 `settling`。
  分层靠 `.gradio-container { position: relative; z-index: 1 }` + 容器背景透明，所以**不要在 `.app-card` /
  `.gradio-container` 上写 `transform` / `filter` / `backdrop-filter` / `contain` / `will-change`**
  （会为 fixed 后代建立包含块，Gradio Dropdown 的选项面板会跑偏；毛玻璃只能画在 `.app-card::before` 上）。
  另外 `html, body` 的环境光渐变必须拆成 `background-image` + `background-color`：Gradio 前端压缩多值
  `background` 简写里带 `var()` 时会整段丢成空值。回归测试见 `tests/audiobook_generator/ui/ambient_background_test.py`。
- **板块内不能留不透明白底**：Gradio 的布局包装层（`.block` / `.wrap` / `.form` / `.panel` / `.contain` /
  `.styler` / `.gr-group`）默认白底，会整块盖住卡片毛玻璃，`AMBIENT_CSS` 里已统一改成透明；
  交互面（上传拖放区、开关行、幽灵/危险/迷你按钮、输入框、引擎分段选择器、日志终端、资源库空态）改成
  半透明白。高级设置弹窗的玻璃画在 `#advanced_modal .modal-box::before` 上，同样是为了避开
  `backdrop-filter` 建立包含块导致内部下拉面板错位的老问题。新增卡片/面板时请按同样思路检查：
  **只要发现白底元素，就把它改成透明或半透明白，并确认下拉选项面板（`ul.options`）保持不透明。**
- **深浅双主题**：设计令牌与切换脚本在 `audiobook_generator/ui/theme.py`，由 `web_ui.py` 拼到
  `CUSTOM_CSS` 头部（`THEME_TOKENS_CSS`）与末尾（`THEME_CSS`）。暗色选择器是 `:root .dark` /
  `:root.dark`——前者正是 Gradio 的暗色钩子（前端给 `body` 加 `.dark`，主题 CSS 写成 `:root .dark{}`），
  所以切换到暗色时 Gradio 自带组件会一起变暗。顶栏 `#ata-theme-toggle` 循环 跟随系统 → 浅色 → 深色，
  存 localStorage `ata-theme`。
  ⚠️ 四条容易踩的坑：① 整站颜色必须走 `var(--apple-*)` / `var(--ata-*)`，写死 `#fff` 之类会在暗色下漏白；
  ② Gradio 自带的 `--body-text-color-subdued` 等默认是 slate-400（浅底上仅 2.48:1），必须在
  `:root` 和 `:root:root .dark` 里重映射到我们的文字令牌（后者提高一级特异性，防止注入顺序不利）；
  ③ xterm 日志终端主题写死在组件里（浅底深字），暗色下只对 `.xterm-screen`（画字层）加
  `invert(1) hue-rotate(180deg)`，底色放在不会被反相的 `.xterm-viewport`；
  ④ **带 `var()` 的渐变绝不能写在 `background` 简写里**：Gradio 处理 CSS 时会把
  `background: linear-gradient(... var(...) ...)` 拆成**空值长写属性**（实测规则被改写成
  `background-image: ; background-color: ;`）。普通元素只是丢了渐变，但渐变文字
  （`.hero h1`：`background-clip: text` + `-webkit-text-fill-color: transparent`）会**整段透明消失**——
  "让文字化作声音"就是这样在 4 个页面同时消失的（用户反馈"转换完标题不见了"）。
  正解：渐变值的定义放进主题令牌（`--ata-title-grad`，值里不带 `var()`），
  规则里用长写属性引用（`background-image: var(--ata-title-grad)`）；
  `theme.py` 的 `guardTitles()` 还会在运行期检查 `getComputedStyle(h1).backgroundImage === "none"`，
  真丢了就加 `.ata-title-solid` 退回纯色，保证标题永远看得见。回归测试见
  `tests/audiobook_generator/ui/theme_test.py`（含两套主题的 WCAG 对比度计算）。
- **光晕的色彩断层与"跑马灯"扩散**（`ambient_background.py`）：
  ① 断层三道防线——色相 32 档 + 相邻 sprite 交叉淡入（`drawGlowSprite` 画两次）、
  sprite 224px（减少放大倍率）、每帧最后铺一层"平均为零"的抖动噪声
  （`bakeDither`/`drawDither`，黑白各半 alpha 6 ≈ ±3/255）。实测色带平台从 27 段/最长 403px
  降到 8 段/最长 1px，取值档数 43 → 190；**改回写死渐变或去掉抖动会立刻复现条带**。
  ② 生成态的"跑马灯"：`signalStart()`（点「开始生成」）只记下扩散起点 `spreadAnchorX/Y`
  **不散开**；等进度条真的变成 `active`（后端确认开跑）才把 `blend` 推向 1，汇聚的光束
  沿视口**周长等分**飞出去，同时四边亮起彩色光条、亮块绕圈跑（见下一条）。
  ⚠️ 触发条件必须是"点了按钮 + 真的开跑"：没选文件/表单报错时进度条不会变 `active`，
  于是**什么都不播**（早期版本 arming 就散到 0.5，导致没选文件点一下也会整屏散开）。
  ③ 同一按钮的点击监听里 `window.scrollTo({top: 0, behavior: 'smooth'})`，整页滑回最顶端。
- **生成态光条 = 跑马灯**（`buildMarquee()` + `draw()` ⑤）：沿视口周长把椭圆光源铺满，
  每个椭圆中心压在边框线上、长轴沿边（`marqueeSeg` 230px 间距、`marqueeAcross` 200px 厚），
  窗口里只看得到内侧一半 → **越靠边颜色越深、朝画面内渐淡**。亮度乘一个沿周长移动的
  行进波 `sin(TAU*(sn*waves - phase))`（`marqueeWaves` **5** 个亮块、`marqueeLapMs` 19s 跑一圈），
  压一下得到 `marqueeFloor`~1.0（**0.5**~1.0）的亮暗起伏 = 亮块绕圈跑；
  再乘 `marqueeBreath`（±14%）做呼吸。
  每条光条的色相按 `sin(周长*2π)` 偏移 ±`marqueeHueSpread`（52°）→ 一圈上同时有几种颜色。
  ⚠️ 三个"看不见/不好看"的坑：① **浅色模式必须单独给更足的不透明度**——`alpha` 是"颜色叠在底色上的比例"，
  近白底上 0.085 的淡色几乎看不出来（实测边框只暗 7/255），深色底同样 0.085 却很明显；
  所以用 `marqueeAlphaLight`（0.30）/`marqueeAlphaDark`（0.18）分开给。实测浅色模式边框暗 25~38/255。
  ② **光条要用更"深"的配色**：`compositeField()` 会按最大通道归一化，于是颜色深浅只由**通道比值**决定，
  所以另建了一张 `hueLUTDeep`（`marqueeSat*` 96 / `marqueeLight*` 52~62），叠出来是浓色带而不是粉彩；
  只调 alpha 不改配色，颜色会越来越"白亮"而不是"深"。
  ③ `marqueeFloor` 太低（0.34）时暗段几乎看不见，看着就是"某几条边没亮" → 用户反馈"周围不够均匀"；
  现在 0.5 保底 + 5 个亮块，四边始终亮着、只有亮块处更亮。
  椭圆光源用 `splatEllipse(x, y, rx, ry, ...)`（轴对齐，不需要旋转矩阵）；
  `splat()` 只是它两轴相等的特例。实测量（浅色模式）：贴边 26px 带内平均亮度 **0.25**、
  顶边剖面的暗段 0.19 / 亮块 0.36，
  顶边 16 段剖面的波峰约 7 秒扫过整条上边（= 19s 跑完一圈的 0.32），`frameMs` 1.4~2.1ms。
  ⚠️ 旧的"每条边 12 颗圆形粒子 + 四角大粒子"那层已经删掉（`edgeParts`/`edgePerSide` 不再存在），
  别把圆形光斑层加回来——圆斑只会在边上糊成一片，出不来"光条"的形。
- **光晕是"浮点光场"，不是"叠 sprite"**（重要约束，别改回去）：
  每颗粒子（46 颗，半径 110~240px，另有中心三层光束与边缘光条）只作为一个**光源**，
  在 `Float32Array` 的 RGB 缓冲里按高斯核 `exp(-3t)` 累加（`splat()`），
  整帧只在 `compositeField()` 里量化一次，再放大到主画布、最后叠 display 分辨率的抖动层。
  **绝不能回到"预渲染多张 8bit 光斑再叠加"**：那样各自的量化台阶会露出可见边界与色带
  （历史版本实测色带平台 403px、可见边缘像素 6.7%）。现在实测：可见边缘 1.2~1.9%、
  亮度剖面相邻跳变 ≤0.5 级、色度 ≤2.8 级、渲染 0.4~1.2ms/帧。
  另外两条：① 抖动噪声必须**逐通道独立**取 0/255（只抖亮度动不了色度）；
  ② 中心弥散光要**跟随鼠标**且用 `g` 加权（鼠标移出浏览器后淡出），
  否则鼠标挪开后正中会残留一团浅色圆、颜色还随色相变化（"中间有个圆在闪"）。
  亮度/范围/浓淡的调参位置：粒子半径与透明度在 `rebuildParticles()`（当前 150~270 / 200~320，
  核心更亮），中心三层 `splat()` 的半径与 alpha 在 `draw()`
  （560px/0.040 大而淡负责远处范围、190px/0.158 收束主体、76px/0.600 中心高光核），
  色彩浓淡在 `CFG.spriteSat*/spriteLight*`（浅 86/70、深 90/64）。注意 `CFG.fieldMaxRadius`
  必须大于最大半径，否则中心光束会被静默截断（曾经 60 格 = 300px，把 580px 的光束切掉了，
  表现为"改大了却没变化"）。光晕变强后浅色主题的次要文字压到了 `#52525a`，
  以保证 hero 文案在最亮色相下仍 ≥4.5:1。
  **调"鼠标在页面内时收束得多紧"只看中心三层**：它们数值上压过粒子，只改粒子的
  `gatherSize` 看不出收紧（踩过两次），而且会**反噬中心亮度**——把汇聚尺寸从
  60~105/45~85 收到 55~92/40~72，中心 60~120px 环的亮度直接掉三成（粒子靠密集重叠
  把中心顶亮，半径一缩就散了）。收敛时只把**抖动**收到 ±32px。
  **中心光束必须锚在"粒子团重心"上，不能锚在光标**：`focusX/focusY` 只滞后 ~0.35s，
  粒子云却要 ~1s 才跟上，锚在光标就会"鼠标上先粘一团光、其余部分再挪过去"（用户原话）。
  现在用 alpha 加权的 `massCx/massCy`，并乘一个**聚集度** `conc = 0.3 + 0.7·clamp(1 − rms/110)`
  （粒子散开时只给 30% 亮度）。注意粒子云是**刚体平移**（所有粒子共用同一 `ease` 和同一目标），
  正常移动时 rms 恒定、`conc` 不起作用；它管的是 `rebuildParticles()` 之后、
  散向边缘、鼠标移出这些真正散开的时刻。
  **调参验证不要再靠截图差分**：`draw()` 每 6 帧把光场快照写到 `#ata-bg.dataset.field`
  （`峰值|峰值x|峰值y|gather|blend|conc|重心x|重心y|rms|focusX|focusY|8 个同心环均值`，
  都是 ×1000 整数，环边界见 `RING_EDGES`）。它比截图干净（只有光晕、没有页面内容），
  但**每次刷新粒子布局都是随机的**，同一档位重复测量噪声约 ±5%。
  ⚠️ 更坑的是：reload 后如果鼠标事件还没被监听到，`gather` 会一直停在 0，
  量到的是"散开态"（峰值从 2.1 掉到 0.7、远环翻倍），拿这种帧做 A/B 会得出反向结论
  （踩过一次：三连测平均出"高光更散了"）。**采样前必须校验 `gather > 0.98 && 0 < rms < 27`**，
  不满足就重发一次 mousemove / 再等，然后 5 帧平均。
  ⚠️ 浏览器自动化的只读 evaluate 作用域里读不到 `window.__ataAmbient`（自定义全局被过滤），
  `dataset` 是唯一可靠的读取口——这也是保留 `data-field` 的原因。
  三层各自的职责：**③ 中心高光核的半径决定"高光集中不集中"**（100px → 76px 时
  25–60px 环 −6%、60–120px 环 −27%，而 120px 以外几乎不动），
  ② 主体决定肩部、① 外圈决定整团的范围——想让"高光更集中但整体别变小"就只动③，
  想整体收小就动①（踩过：三层一起收，结果整团缩了一圈）。
  另外汇聚抖动（`p.jx * N`，当前 ±26px）同时影响中心浓度与粒子云脚印，别和③一起大改。
  **想不跑一次真实转换就预览生成态**：URL 上加 `?ata-state=generating`（也认 `#ata-state=`），
  页面加载后强制停在该状态（`forcedState`，见 `boot()`/`syncFromProgress()`），
  调跑马灯的亮度/速度/厚度时用它，省得反复上传文件。
  诊断快照 `#ata-bg.dataset.field` 末尾还多带两项：贴边 26px 带的平均亮度 `edgeMean`
  与顶边 16 段剖面 `topProf`（看亮块有没有在跑：波峰索引应随时间单调移动）。
 色相循环（`slowHue`）必须是**闭环 + Catmull-Rom**：旧写法"线性扫过调色板再回到第一色"
  在最后一段 `288 → 212` 会瞬间跳 ~76°（实测 -72.2°/2.5s，是典型步进的 4.9 倍），
  看起来就是"卡一下突然换色"。现在首尾相接成环、取相邻四点插值，跨段一阶导连续，
  整轮 40s（`hueSegmentMs × 段数`），接缝处步进只有 0.21°。
- **标签页 hover 一律毛玻璃**：Gradio 默认给 `.tab-container button:hover` 实心填充
  （浅色下 `rgb(248,250,252)`，看着像贴了一块白框），`THEME_CSS` 里统一改成
  `var(--ata-glass-soft)` + `blur(14px)` + 内描边；新增标签类组件时记得别让默认白底漏出来。
- **顶栏是一块圆角玻璃条，必须和卡片同宽**（`.app-header`，规则在 `web_ui.CUSTOM_CSS`）：
  `gr.HTML` 的包装层 `.html-container.padding` 自带 `10px 12px` 内边距，会把玻璃条挤得比卡片
  窄 24px、logo 贴到离边框 4px 的地方（实测顶栏 680px vs 卡片 704px）。修法是给顶栏加
  `margin: 0 -12px` 把宽度撑回卡片带，内边距改由它自己给（`padding: 12px 18px`），
  再配 `border-radius: var(--radius)` + 卡片同款 `border`/`box-shadow`、`top: 8px` 悬浮式 sticky。
  为什么不用 `:has()` 去改包装层：那是 Gradio 生成的 DOM，直接改包装层会波及其他 `gr.HTML`
  （hero 段落也用它），负外边距只影响顶栏自己。窄屏（<720px）在 `AMBIENT_CSS` 的媒体查询里
  收到 `14px`（顶部保留 `env(safe-area-inset-top)`）。

### 提供商文件
- `audiobook_generator/tts_providers/chatterbox_tts_provider.py` — Chatterbox TTS 提供商实现
- 支持多语言模型 `chatterbox-multilingual-v3`（默认）
- 支持语音克隆（通过 `reference_audio` 参数）
- 长文本自动分块处理（每块 500 字符）

## VoxCPM TTS（本地多模态语音引擎）

### 环境
- **Python 版本硬限制**：voxcpm 只支持 Python 3.10~3.12（本机 venv_chatterbox 是 3.13，装不上）；Ubuntu 部署必须用 README「Linux 服务器部署（Miniconda）」的 conda **3.11** 环境创建 `venv_chatterbox --system-site-packages`。
- 安装顺序：cu124 torch 2.6.0 → `pip install voxcpm` → **必须** `pip install --force-reinstall --no-deps gradio==5.50.0 gradio_client==1.14.0`（voxcpm 依赖 gradio>=6,<7，会破坏 UI）。
- 系统依赖：`ffmpeg`、`libsndfile1`（soundfile 底层）；国内模型下载用 `export HF_ENDPOINT=https://hf-mirror.com`，SenseVoice/降噪走 ModelScope（入口脚本已设 `MODELSCOPE_CACHE`）。

### 关键实现约定
- **模型没有内置音色表**：不开参考音频每次随机音色。内置 6 个中文预设 = 固定描述+固定 seed+固定试听文本，首次使用生成 5~10s 参考音频缓存到 `voices/preset_*.wav` + 指纹 `*.json`（原子写入 + flock）；指纹字段见 `voxcpm_voices.py` 的 `VOXCPM_FINGERPRINT_FIELDS`，任一变化自动重生成。生成文件被 .gitignore 忽略。
- **三种模式**（`voxcpm_tts_provider.py`）：design（`(描述)正文` + 固定 seed，预设自动用缓存参考音频）、clone（`reference_wav_path` + 可选风格描述）、hifi（`prompt_wav_path + prompt_text + reference_wav_path` 同一份音频；描述被模型忽略）。hifi 转写：手填优先 → 预设自带试听文本（仅当没用用户上传的参考音频）→ SenseVoice 自动（`utils/voxcpm_asr.py`，固定 CPU）。
- **长文本必须分块**：官方警告语速漂移/爆音/OOM/不停止；默认 `chunk_chars=400` 按句分块、尾部 <80 字并入前块、pydub 合并、逐块打 `chunk_i_of_n` 进度标记（progress_parser 已支持）。
- **CUDA Graphs 不支持多线程**：`optimize=True` 默认开；转换走 spawn 子进程单 worker（`worker_count=1` 默认），WebUI 试听用 `cache=False` 临时加载模型、用完 `del + torch.cuda.empty_cache()` 释放，避免主进程长期占显存与 worker 抢资源。
- **设备惰性解析**：provider `__init__` 不碰 `torch.cuda`（只有构造 WebUI 下拉时的 `get_voxcpm_supported_devices()` 会探测），设备规范化与模型加载都在 worker 内完成，避免父进程 CUDA 状态被 fork 继承（配合 spawn 双保险）。
- **输出格式**：默认 mp3（非 wav 需 ffmpeg，validate_config 报中文错误）；多分片/压缩格式一律 pydub 合并（复用 `should_use_pydub_merge`）。
- **时长校验**：每块按 4.5 字/秒估算，实际时长偏差 >0.2~3.0 倍仅告警不中断。

### 提供文件
- `audiobook_generator/tts_providers/voxcpm_tts_provider.py` — Provider + 试听/加载/速度工具
- `audiobook_generator/utils/voxcpm_voices.py` — 预设音色库、指纹、文件锁、原子写入
- `audiobook_generator/utils/voxcpm_asr.py` — SenseVoice 懒加载自动转写
- `tests/audiobook_generator/tts_providers/voxcpm_tts_provider_test.py`、`tests/audiobook_generator/utils/voxcpm_voices_test.py` — 单元测试（mock 模型，不需要 GPU）

### WebUI 接线（web_ui.py）
- 引擎标签「🔊 VoxCPM」在 Chatterbox 之后；`_PROVIDER_LABEL`、`process_form`（参数顺序必须与 `start_btn.inputs` 一致）、`_PROVIDER_IDS`、tab.select 循环、试听按钮 click 都要同步新增。
- 引擎标签列数：`.engine-tabs > .tab-nav` 已从 `repeat(5,1fr)` 改为 `repeat(6,1fr)`，窄屏 3 列。
- 试听按钮走 `voxcpm_preview_voice` → `preview_voxcpm_preset_audio`（缓存命中不加载模型；失败返回 `gr.update()` 并 `gr.Warning`，不阻塞开始按钮）。
