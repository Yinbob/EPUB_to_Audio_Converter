import os
from audiobook_generator.utils.project_runtime import bootstrap_project_python

if __name__ == '__main__':
    bootstrap_project_python(os.path.dirname(os.path.abspath(__file__)), 'ui')

import argparse

from audiobook_generator.utils.gradio_compat import configure_gradio_status_compat

# 在最终解释器中、导入 Gradio 前设置，自动切换虚拟环境后也会执行。
configure_gradio_status_compat()

from audiobook_generator.config.ui_config import UiConfig
from audiobook_generator.ui.web_ui import host_ui


def handle_args():
    parser = argparse.ArgumentParser(
        description="Apple 风格 WebUI for Book to Audiobook converter (supports EPUB, DOC, DOCX)")
    parser.add_argument("--host", default="127.0.0.1", help="Host address")
    parser.add_argument("--port", default=7862, type=int, help="Port number (默认 7862)")

    ui_args = parser.parse_args()
    return UiConfig(ui_args)


def main():
    config = handle_args()
    host_ui(config)


if __name__ == "__main__":
    main()
