"""DeepSeek API 配置管理。

配置文件优先于环境变量；缺失 API Key 时不在这里抛异常，由调用方决定是提示用户还是
进入无凭证预览路径。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_FILE = Path(__file__).parent.parent.parent / "deepseek_config.json"
DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"


def deepseek_completion_options(model: str | None) -> dict:
    """当前官方模型默认开启思考；结构化拆分显式使用非思考模式。"""
    selected = (model or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    options = {"model": selected}
    if selected in {'deepseek-flash', 'deepseek-v4-pro', 'deepseek-v4-flash', 'deepseek-v4-flash-vision-exp'}:
        options['extra_body'] = {'thinking': {'type': 'disabled'}}
    return options


def load_deepseek_config() -> dict:
    """读取本地 deepseek_config.json；损坏或不可读时返回空配置。"""
    if not CONFIG_FILE.exists():
        return {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as file_obj:
            config = json.load(file_obj)
        if not isinstance(config, dict):
            raise ValueError("配置根节点必须是对象")
        logger.info("已从本地配置文件加载 DeepSeek 配置: %s", CONFIG_FILE)
        return config
    except (json.JSONDecodeError, OSError, ValueError) as exc:
        logger.warning("读取 DeepSeek 配置文件失败: %s", exc)
        return {}


def save_deepseek_config(api_key: str, base_url: str, model: str) -> None:
    """保存 DeepSeek API 配置到项目根目录。"""
    config = {
        "api_key": (api_key or "").strip(),
        "base_url": (base_url or DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL,
        "model": (model or DEFAULT_MODEL).strip() or DEFAULT_MODEL,
    }
    with open(CONFIG_FILE, "w", encoding="utf-8") as file_obj:
        json.dump(config, file_obj, indent=2, ensure_ascii=False)
    logger.info("DeepSeek 配置已保存到: %s", CONFIG_FILE)


def get_deepseek_credentials() -> tuple[str, str, str]:
    """返回 ``(api_key, base_url, model)``。

    优先级：本地配置文件 > ``DEEPSEEK_*`` 环境变量 > 默认 Base URL / 模型。
    API Key 缺失时返回空字符串，调用方可据此显示明确提示。
    """
    file_config = load_deepseek_config()
    file_api_key = str(file_config.get("api_key") or "").strip()
    env_api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    api_key = file_api_key or env_api_key
    base_url = str(
        file_config.get("base_url")
        or os.environ.get("DEEPSEEK_BASE_URL")
        or DEFAULT_BASE_URL
    ).strip()
    model = str(
        file_config.get("model")
        or os.environ.get("DEEPSEEK_MODEL")
        or DEFAULT_MODEL
    ).strip()
    return api_key, base_url or DEFAULT_BASE_URL, model or DEFAULT_MODEL


def mask_api_key(api_key: str) -> str:
    """遮挡 API Key，只保留最后 4 位。"""
    if not api_key or len(api_key) <= 4:
        return "••••••••"
    return "•" * (len(api_key) - 4) + api_key[-4:]


def test_deepseek_connection(api_key: str, base_url: str, model: str) -> tuple[bool, str]:
    """用一次极小的 chat completion 验证凭证、地址和模型是否可用。"""
    if not (api_key or "").strip():
        return False, "请先填写 DeepSeek API Key"
    try:
        from openai import OpenAI

        client = OpenAI(
            api_key=api_key.strip(),
            base_url=(base_url or DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL,
            max_retries=0,
            timeout=20.0,
        )
        client.chat.completions.create(
            **deepseek_completion_options(model),
            messages=[{"role": "user", "content": "请只回复 OK"}],
            max_tokens=4,
            temperature=0,
        )
        return True, "连接成功"
    except Exception as exc:  # SDK 会抛出多种异常，UI 只需要稳定的失败文本
        logger.warning("DeepSeek 连接测试失败: %s", exc)
        return False, f"连接失败: {exc}"
