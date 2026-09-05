"""
MiniMax API 配置管理工具
支持从本地配置文件读取 API Key，若未配置则从环境变量读取。
"""

import json
import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 配置文件路径：放在项目根目录下
CONFIG_FILE = Path(__file__).parent.parent.parent / "minimax_config.json"


def load_minimax_config() -> dict:
    """
    从本地 minimax_config.json 加载配置。
    返回字典包含 api_key。
    """
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                config = json.load(f)
            logger.info(f"已从本地配置文件加载 MiniMax 配置: {CONFIG_FILE}")
            return config
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"读取配置文件失败: {e}")
    return {}


def save_minimax_config(api_key: str):
    """
    将 API Key 保存到本地配置文件。
    """
    config = {
        "api_key": api_key,
    }
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        logger.info(f"MiniMax 配置已保存到: {CONFIG_FILE}")
    except IOError as e:
        logger.error(f"保存配置文件失败: {e}")


def get_minimax_credentials() -> str:
    """
    获取 MiniMax API Key。
    优先级：
    1. 本地配置文件 minimax_config.json（WebUI配置，覆盖环境变量）
    2. 环境变量 MINIMAX_API_KEY
    """
    # 1. 优先从本地配置文件读取（WebUI配置）
    file_config = load_minimax_config()
    api_key = file_config.get("api_key")

    if api_key:
        logger.info("使用本地配置文件中的 MiniMax API Key")
        # 同步到环境变量，供 Provider 使用
        os.environ["MINIMAX_API_KEY"] = api_key
        return api_key

    # 2. 从环境变量读取
    env_api_key = os.environ.get("MINIMAX_API_KEY")
    if env_api_key:
        logger.info("使用环境变量中的 MINIMAX_API_KEY")
        return env_api_key

    # 未找到配置
    raise RuntimeError(
        f"未找到 MiniMax API 配置。请通过以下任一方式提供:\n"
        f"  1. 在 WebUI 设置页面中配置 API Key\n"
        f"  2. 设置环境变量 MINIMAX_API_KEY\n"
        f"  3. 创建配置文件 {CONFIG_FILE}，格式: {{\"api_key\": \"your-key\"}}"
    )


def mask_api_key(api_key: str) -> str:
    """
    遮挡 API Key，只显示后4位。
    """
    if not api_key or len(api_key) <= 4:
        return "••••••••"
    return "•" * (len(api_key) - 4) + api_key[-4:]


def test_minimax_connection(api_key: str) -> tuple[bool, str]:
    """
    测试 MiniMax API 连接。
    返回 (success, message)。
    """
    import websocket
    try:
        # 尝试建立 WebSocket 连接
        ws = websocket.create_connection(
            "wss://api.minimaxi.com/ws/v1/t2a_v2",
            header={"Authorization": f"Bearer {api_key}"},
            timeout=5
        )
        ws.close()
        return True, "连接成功"
    except Exception as e:
        return False, f"连接失败: {str(e)}"
