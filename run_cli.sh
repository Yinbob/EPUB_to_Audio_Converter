#!/bin/bash
# CLI 有声书转换入口。
# 若存在 venv_chatterbox/，main.py 会自动切换到该环境以支持 Chatterbox。
# 用法:
#   ./run_cli.sh input.epub output_dir --tts edge
#   ./run_cli.sh input.epub output_dir --tts chatterbox --chatterbox_device cuda
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

exec python3 main.py "$@"
