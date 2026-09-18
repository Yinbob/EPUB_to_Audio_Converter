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
  ⚠️ 三条容易踩的坑：① 整站颜色必须走 `var(--apple-*)` / `var(--ata-*)`，写死 `#fff` 之类会在暗色下漏白；
  ② Gradio 自带的 `--body-text-color-subdued` 等默认是 slate-400（浅底上仅 2.48:1），必须在
  `:root` 和 `:root:root .dark` 里重映射到我们的文字令牌（后者提高一级特异性，防止注入顺序不利）；
  ③ xterm 日志终端主题写死在组件里（浅底深字），暗色下只对 `.xterm-screen`（画字层）加
  `invert(1) hue-rotate(180deg)`，底色放在不会被反相的 `.xterm-viewport`。回归测试见
  `tests/audiobook_generator/ui/theme_test.py`（含两套主题的 WCAG 对比度计算）。
- **光晕的色彩断层与点击扩散**（`ambient_background.py`）：
  ① 断层三道防线——色相 32 档 + 相邻 sprite 交叉淡入（`drawGlowSprite` 画两次）、
  sprite 224px（减少放大倍率）、每帧最后铺一层"平均为零"的抖动噪声
  （`bakeDither`/`drawDither`，黑白各半 alpha 6 ≈ ±3/255）。实测色带平台从 27 段/最长 403px
  降到 8 段/最长 1px，取值档数 43 → 190；**改回写死渐变或去掉抖动会立刻复现条带**。
  ② 点「开始生成」的扩散：`signalStart()` 把 `spreadAnchorX/Y` 设成当前鼠标位置，
  `assignEdgeTargets()` 从该点向四周射线到视口边框，方向按**黄金角**（2.39996323）均匀铺开，
  保证每个方向都有粒子；`arming` 目标 0.5、约 1.2 秒可见地散开，收到 `active` 状态后走满量程。
  ③ 同一按钮的点击监听里 `window.scrollTo({top: 0, behavior: 'smooth'})`，整页滑回最顶端。

### 提供商文件
- `audiobook_generator/tts_providers/chatterbox_tts_provider.py` — Chatterbox TTS 提供商实现
- 支持多语言模型 `chatterbox-multilingual-v3`（默认）
- 支持语音克隆（通过 `reference_audio` 参数）
- 长文本自动分块处理（每块 500 字符）
