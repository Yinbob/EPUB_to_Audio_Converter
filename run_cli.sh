#!/bin/bash
# CLI 有声书转换入口。
# 启用统一音频检查时优先使用 venv_audio_quality/；本地引擎沿用 venv_chatterbox/。
# 已激活环境时尊重当前解释器。
# 用法:
#   ./run_cli.sh input.epub output_dir --tts edge
#   ./run_cli.sh input.epub output_dir --tts chatterbox --chatterbox_device cuda
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

exec python3 main.py "$@"
