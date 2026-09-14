# AGENTS.md

Fork of `p0n1/epub_to_audiobook`, customized for a Chinese workflow (MiMo + MiniMax TTS, Apple-style Gradio UI). Upstream README usage docs are partially stale — trust the code.

## Entry points (all at repo root)
- `python3 main.py <input.epub|.doc|.docx> <output_dir> [--tts ...]` — CLI converter.
- `python3 main_ui.py [--host 127.0.0.1 --port 7860]` — Gradio WebUI (`audiobook_generator/ui/web_ui.py`).
- `python3 main_ui_apple.py [--host 127.0.0.1 --port 7861]` — Apple-style WebUI (`audiobook_generator/ui/web_ui_apple.py`).
- TTS providers registered in `audiobook_generator/tts_providers/base_tts_provider.py:get_supported_tts_providers()`.

## Environment & credentials
- Azure: `MS_TTS_KEY`, `MS_TTS_REGION`. Edge: no key. MiniMax: `MINIMAX_API_KEY` (WebSocket API).
- The `openai` provider was rewritten to target MiMo (xiaomimimo.com): defaults `model_name="mimo-v2.5-tts"`, accepts only MiMo voices, calls `chat.completions.create` with an `audio` block (not `audio.speech`).
- MiMo credentials resolve in order (`audiobook_generator/utils/mimo_config.py`): `OPENAI_API_KEY`/`OPENAI_BASE_URL` env → `mimo_config.json` at repo root (gitignored; template `mimo_config.json.example`) → interactive prompt.

## Gotchas
- `main.py:13-14` hardcodes `AudioSegment.converter="/opt/homebrew/bin/ffmpeg"` (and ffprobe). Keep on macOS; breaks on Linux/Docker/Windows. Requires `brew install ffmpeg`.
- WebUI (`web_ui.py`) does `from main import main` and builds a `GeneralConfig(None)`, then fills fields manually — config fields default to `None` (not CLI defaults); providers must handle `None`.
- Chapters are converted via `multiprocessing.Pool` (`imap_unordered`) — chapter order not guaranteed. `--worker_count` = pool size (default 1).
- WebUI runs conversion in a subprocess `Process`; the batch worker (`_batch_worker`) must stay module-top-level for pickling.
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
- **安装**: `./venv_chatterbox/bin/pip install chatterbox-tts`
- **注意**: chatterbox-tts 0.1.7 强制依赖 gradio 6.8.0，与项目使用的 gradio 5.50.0 冲突。虚拟环境通过 `--system-site-packages` 继承系统 gradio 5.50.0，不要升级 gradio。
- **已知问题**: `perth` 包的 `PerthImplicitWatermarker` 因缺少 `perth_net` 依赖无法导入，已在 `chatterbox/tts.py` 中修补为回退到 `DummyWatermarker`。

### 模型缓存
- 所有模型文件下载到 `venv_chatterbox/.cache/huggingface/`，与虚拟环境一同管理
- 总计约 3.1 GB（`ve.safetensors`、`t3_cfg.safetensors` ~2GB、`s3gen.safetensors` ~1GB、`tokenizer.json`、`conds.pt`）
- 删除方式：`rm -rf venv_chatterbox/` 即可清除整个环境和模型缓存
- 如果网络下载失败，尝试 `unset http_proxy https_proxy ALL_PROXY && curl --noproxy "*"`

### 运行方式
- **CLI**: `./venv_chatterbox/run_with_chatterbox.sh input.epub output_dir --tts chatterbox --chatterbox_device cpu --chapter_start N --chapter_end N`
- **Apple 风格 UI**: `./venv_chatterbox/run_ui_chatterbox.sh`（默认端口 7862）
- **旧版 UI**: `./venv_chatterbox/run_ui_chatterbox.sh --old-ui`（默认端口 7861）
- UI 启动后在 TTS 提供商下拉菜单中选择 **Chatterbox**，在 **🎯 Chatterbox** 标签页中配置设备等参数

### CLI 参数
```
--chatterbox_device {auto,cpu,cuda,mps}  设备选择（默认 auto）
--chatterbox_reference_audio              参考音频路径，用于语音克隆（可选）
--chatterbox_exaggeration                 语气夸张程度 0.0-1.0（默认 0.5）
--chatterbox_cfg_weight                   CFG 引导权重 0.0-1.0（默认 0.5）
```

### 提供商文件
- `audiobook_generator/tts_providers/chatterbox_tts_provider.py` — Chatterbox TTS 提供商实现
- 支持多语言模型 `chatterbox-multilingual-v3`（默认）
- 支持语音克隆（通过 `reference_audio` 参数）
- 长文本自动分块处理（每块 500 字符）
