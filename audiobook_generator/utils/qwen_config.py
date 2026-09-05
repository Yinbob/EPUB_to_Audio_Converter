"""
Qwen TTS API 配置管理工具
支持从本地配置文件读取 API Key、Base URL 和 Model。
"""

import json
import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 配置文件路径：放在项目根目录下
CONFIG_FILE = Path(__file__).parent.parent.parent / "qwen_config.json"

DEFAULT_BASE_URL = "https://gpu.ncut.edu.cn/v1"
DEFAULT_MODEL = "qwen3-tts-12hz-1.7b-voicedesign"


def load_qwen_config() -> dict:
    """
    从本地 qwen_config.json 加载配置。
    返回字典包含 api_key、base_url、model。
    """
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
            logger.info(f"已从本地配置文件加载 Qwen 配置: {CONFIG_FILE}")
            return config
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"读取配置文件失败: {e}")
    return {}


def save_qwen_config(api_key: str, base_url: str, model: str):
    """
    将 API Key、Base URL 和 Model 保存到本地配置文件。
    """
    config = {
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
    }
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        logger.info(f"Qwen 配置已保存到: {CONFIG_FILE}")
    except IOError as e:
        logger.error(f"保存配置文件失败: {e}")


def get_qwen_credentials() -> tuple[str, str, str]:
    """
    获取 Qwen TTS API 凭证（api_key, base_url, model）。
    优先级：
    1. 本地配置文件 qwen_config.json（WebUI配置，覆盖环境变量）
    2. 环境变量 QWEN_TTS_API_KEY / QWEN_TTS_BASE_URL / QWEN_TTS_MODEL
    3. 默认值
    """
    # 1. 优先从本地配置文件读取（WebUI配置）
    file_config = load_qwen_config()
    api_key = file_config.get("api_key")
    base_url = file_config.get("base_url")
    model = file_config.get("model")

    if api_key:
        logger.info("使用本地配置文件中的 Qwen API Key")
        # 同步到环境变量，供 Provider 使用
        os.environ["QWEN_TTS_API_KEY"] = api_key
        if base_url:
            os.environ["QWEN_TTS_BASE_URL"] = base_url
        if model:
            os.environ["QWEN_TTS_MODEL"] = model
        return api_key, base_url or DEFAULT_BASE_URL, model or DEFAULT_MODEL

    # 2. 从环境变量读取
    env_api_key = os.environ.get("QWEN_TTS_API_KEY")
    env_base_url = os.environ.get("QWEN_TTS_BASE_URL")
    env_model = os.environ.get("QWEN_TTS_MODEL")

    if env_api_key:
        logger.info("使用环境变量中的 QWEN_TTS_API_KEY")
        return env_api_key, env_base_url or DEFAULT_BASE_URL, env_model or DEFAULT_MODEL

    # 3. 返回默认值（原代码有硬编码默认值，这里保持兼容）
    logger.info("使用默认 Qwen 配置")
    return "", DEFAULT_BASE_URL, DEFAULT_MODEL


def mask_api_key(api_key: str) -> str:
    """
    遮挡 API Key，只显示后4位。
    """
    if not api_key or len(api_key) <= 4:
        return "••••••••"
    return "•" * (len(api_key) - 4) + api_key[-4:]


def test_qwen_connection(api_key: str, base_url: str, model: str) -> tuple[bool, str]:
    """
    测试 Qwen TTS API 连接。
    返回 (success, message)。
    """
    import requests
    try:
        # 尝试发送一个简单的请求来验证连接
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        # 使用一个简单的 GET 请求来测试连接
        response = requests.get(f"{base_url}/models", headers=headers, timeout=10)
        if response.status_code == 200:
            return True, "连接成功"
        else:
            return False, f"连接失败: HTTP {response.status_code}"
    except Exception as e:
        return False, f"连接失败: {str(e)}"
