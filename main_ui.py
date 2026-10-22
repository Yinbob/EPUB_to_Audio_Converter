import os
from audiobook_generator.utils.project_runtime import bootstrap_project_python

if __name__ == '__main__':
    bootstrap_project_python(os.path.dirname(os.path.abspath(__file__)), 'ui')

import argparse

from audiobook_generator.config.ui_config import UiConfig


def handle_args():
    parser = argparse.ArgumentParser(
        description="Apple 风格 WebUI for Book to Audiobook converter (supports EPUB, DOC, DOCX)")
    parser.add_argument("--host", default="127.0.0.1", help="Host address")
    parser.add_argument("--port", default=7862, type=int, help="Port number (默认 7862)")

    parser.add_argument("--ui", choices=["vue", "gradio"], default="gradio", help="界面选择（迁移验收前默认 gradio）")
    ui_args = parser.parse_args()
    config = UiConfig(ui_args)
    config.ui = ui_args.ui
    return config


def main():
    config = handle_args()
    if config.ui == 'vue':
        from pathlib import Path
        from audiobook_generator.services.common import ROOT
        if not (ROOT / 'frontend' / 'dist' / 'index.html').exists():
            raise SystemExit('缺少 Vue 构建文件：请在 frontend 目录执行 npm ci 与 npm run build。')
        import uvicorn
        from audiobook_generator.api.app import create_app
        uvicorn.run(create_app(), host=config.host, port=config.port, workers=1)
    else:
        from audiobook_generator.services.common import RuntimeLock
        runtime = RuntimeLock().acquire()
        try:
            from audiobook_generator.utils.gradio_compat import configure_gradio_status_compat
            configure_gradio_status_compat()
            from audiobook_generator.ui.web_ui import host_ui
            host_ui(config)
        finally:
            runtime.close()


if __name__ == "__main__":
    main()
