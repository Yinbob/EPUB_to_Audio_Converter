# AGENTS.md

Fork of `p0n1/epub_to_audiobook`, customized for a Chinese workflow (MiMo + MiniMax TTS, Apple-style Gradio UI). Upstream README usage docs are partially stale — trust the code.

## Entry points (all at repo root)
- `python3 main.py <input.epub|.doc|.docx> <output_dir> [--tts ...]` — CLI converter.
- `python3 main_ui.py [--host 127.0.0.1 --port 7860]` — Gradio WebUI (`audiobook_generator/ui/web_ui.py`).
- `main_ui_v2.py` — WIP alternate UI (port 7861) → `audiobook_generator/ui/web_ui_v3.py`. `web_ui_v2.py`/`web_ui_v3.py` are untracked WIP.
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
