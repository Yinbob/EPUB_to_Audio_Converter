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
