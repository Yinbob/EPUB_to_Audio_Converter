"""
MiMo API 配置管理工具
支持从本地配置文件读取 API Key 和 Base URL，若未配置则交互式提示用户输入。
"""

import json
import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 配置文件路径：放在项目根目录下
CONFIG_FILE = Path(__file__).parent.parent.parent / "mimo_config.json"

DEFAULT_BASE_URL = "https://token-plan-cn.xiaomimimo.com/v1"


def load_mimo_config() -> dict:
    """
    从本地 mimo_config.json 加载配置。
    返回字典包含 api_key 和 base_url。
    """
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
            logger.info(f"已从本地配置文件加载 MiMo 配置: {CONFIG_FILE}")
            return config
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"读取配置文件失败: {e}")
    return {}


def save_mimo_config(api_key: str, base_url: str):
    """
    将 API Key 和 Base URL 保存到本地配置文件。
    """
    config = {
        "api_key": api_key,
        "base_url": base_url,
    }
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        logger.info(f"MiMo 配置已保存到: {CONFIG_FILE}")
    except IOError as e:
        logger.error(f"保存配置文件失败: {e}")


def get_mimo_credentials() -> tuple[str, str]:
    """
    获取 MiMo API 凭证（api_key, base_url）。
    优先级：
    1. 本地配置文件 mimo_config.json（WebUI配置，覆盖环境变量）
    2. 环境变量 OPENAI_API_KEY / OPENAI_BASE_URL
    3. 交互式提示用户输入（并询问是否保存）
    """
    # 1. 优先从本地配置文件读取（WebUI配置）
    file_config = load_mimo_config()
    api_key = file_config.get("api_key")
    base_url = file_config.get("base_url", DEFAULT_BASE_URL)

    if api_key:
        logger.info("使用本地配置文件中的 MiMo API Key")
        # 同步到环境变量，供 OpenAI SDK 使用
        os.environ["OPENAI_API_KEY"] = api_key
        os.environ["OPENAI_BASE_URL"] = base_url
        return api_key, base_url

    # 2. 从环境变量读取
    env_api_key = os.environ.get("OPENAI_API_KEY")
    env_base_url = os.environ.get("OPENAI_BASE_URL")

    if env_api_key:
        logger.info("使用环境变量中的 OPENAI_API_KEY")
        return env_api_key, env_base_url or DEFAULT_BASE_URL

    if api_key:
        logger.info("使用本地配置文件中的 MiMo API Key")
        # 同步到环境变量，供 OpenAI SDK 使用
        os.environ["OPENAI_API_KEY"] = api_key
        os.environ["OPENAI_BASE_URL"] = base_url
        return api_key, base_url

    # 3. 交互式提示用户输入（仅在终端交互模式下）
    if not os.isatty(0):
        # 非交互模式（如 WebUI），无法提示输入，抛出异常
        raise RuntimeError(
            f"未找到 MiMo API 配置。请通过以下任一方式提供:\n"
            f"  1. 设置环境变量 OPENAI_API_KEY（和可选的 OPENAI_BASE_URL）\n"
            f"  2. 创建配置文件 {CONFIG_FILE}，格式参考 mimo_config.json.example\n"
            f"  3. 先通过 CLI 模式运行一次，按提示输入并保存"
        )

    print("\n" + "=" * 60)
    print("  未检测到 MiMo API 配置")
    print("=" * 60)
    api_key = input("请输入 MiMo API Key: ").strip()
    if not api_key:
        raise ValueError("API Key 不能为空")

    base_url_input = input(f"请输入 Base URL (直接回车使用默认: {DEFAULT_BASE_URL}): ").strip()
    base_url = base_url_input if base_url_input else DEFAULT_BASE_URL

    # 询问是否保存到本地
    save_choice = input("是否将配置保存到本地文件？(y/n, 默认 y): ").strip().lower()
    if save_choice != "n":
        save_mimo_config(api_key, base_url)
        print(f"✅ 配置已保存到 {CONFIG_FILE}")
    else:
        print("ℹ️  配置未保存，下次运行需要重新输入。")

    # 同步到环境变量
    os.environ["OPENAI_API_KEY"] = api_key
    os.environ["OPENAI_BASE_URL"] = base_url

    return api_key, base_url


def mask_api_key(api_key: str) -> str:
    """
    遮挡 API Key，只显示后4位。
    """
    if not api_key or len(api_key) <= 4:
        return "••••••••"
    return "•" * (len(api_key) - 4) + api_key[-4:]


def test_mimo_connection(api_key: str, base_url: str) -> tuple[bool, str]:
    """
    测试 MiMo API 连接。
    返回 (success, message)。
    """
    import requests
    try:
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
