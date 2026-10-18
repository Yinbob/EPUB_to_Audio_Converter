#!/bin/bash
# 启动 WebUI（Apple 风格，默认监听 0.0.0.0:7862，适合后台/服务器运行）
# main_ui.py 优先使用已配置的 venv_audio_quality/，没有时回退 venv_chatterbox/。
# 已激活其他环境时尊重当前解释器。
# 用法:
#   ./run_ui.sh
#   ./run_ui.sh --host 127.0.0.1 --port 8080
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-7862}"

exec python3 main_ui.py --host "$HOST" --port "$PORT" "$@"
