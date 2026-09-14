import sys
import os

# ═══════════════════════════════════════════════════════════════
# 自动检测 & 切换到 Chatterbox 虚拟环境
# 这样用户只需一条命令即可：
#   python3 main_ui_apple.py --host 0.0.0.0 --port 8080
# ═══════════════════════════════════════════════════════════════
_self_dir = os.path.dirname(os.path.abspath(__file__))
_venv_python = os.path.join(_self_dir, 'venv_chatterbox', 'bin', 'python3')
_venv_cache = os.path.join(_self_dir, 'venv_chatterbox', '.cache')

if os.path.exists(_venv_python) and sys.executable != _venv_python:
    # 设置所有缓存目录到 venv 内，方便统一删除
    os.environ.setdefault('NUMBA_CACHE_DIR', os.path.join(_venv_cache, 'numba'))
    os.environ.setdefault('HF_HOME', os.path.join(_venv_cache, 'huggingface'))
    os.environ.setdefault('HUGGINGFACE_HUB_CACHE', os.path.join(_venv_cache, 'huggingface', 'hub'))
    os.environ.setdefault('OMP_WAIT_POLICY', 'PASSIVE')
    # 确保缓存目录存在
    os.makedirs(os.environ['NUMBA_CACHE_DIR'], exist_ok=True)
    os.makedirs(os.path.join(_venv_cache, 'huggingface', 'hub'), exist_ok=True)
    # 用 venv 的 Python 重新执行当前脚本（保留所有参数）
    os.execv(_venv_python, [_venv_python] + sys.argv)
# ═══════════════════════════════════════════════════════════════

import argparse

from audiobook_generator.config.ui_config import UiConfig
from audiobook_generator.ui.web_ui_apple import host_ui


def handle_args():
    parser = argparse.ArgumentParser(
        description="Apple 风格 WebUI for Book to Audiobook converter (supports EPUB, DOC, DOCX)")
    parser.add_argument("--host", default="127.0.0.1", help="Host address")
    parser.add_argument("--port", default=7862, type=int, help="Port number (默认 7862，避免与旧版 7860 冲突)")

    ui_args = parser.parse_args()
    return UiConfig(ui_args)


def main():
    config = handle_args()
    host_ui(config)


if __name__ == "__main__":
    main()
