"""RoleScriptV1 共用的文本与角色属性规范化工具。"""
from __future__ import annotations

import unicodedata
from typing import Any, Optional


def is_semantic_whitespace(char: str) -> bool:
    """判断字符在剧本覆盖率比较中是否应视为空白。

    Python 的 ``str.isspace()`` 不覆盖零宽空格、BOM、软连字符等格式字符；
    这些字符出现在模型分段里时肉眼不可见，却会被当成“有内容”送入差异对齐，
    最终触发“规范化后为空”或覆盖率不一致。这里统一将 Unicode 格式字符和
    空格分隔符视为空白。
    """
    if not char:
        return True
    return char.isspace() or unicodedata.category(char) in {"Cf", "Zs"}


def normalize_coverage_text(text: str) -> str:
    """覆盖率比较用文本：NFKC、统一换行、去首尾空白并移除全部语义空白。"""
    normalized = (
        unicodedata.normalize("NFKC", text)
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    ).strip()
    return "".join(char for char in normalized if not is_semantic_whitespace(char))


def normalize_gender(value: Any) -> Optional[str]:
    """把模型/JSON 中的性别值归一为 male/female；unknown 或空值返回 None。"""
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    if text in {"male", "m", "男", "男性", "男生"}:
        return "male"
    if text in {"female", "f", "女", "女性", "女生"}:
        return "female"
    return None


def is_known_gender_value(value: Any) -> bool:
    """判断可选 gender 字段是否是允许的已声明值。"""
    if value is None:
        return True
    if not isinstance(value, str):
        return False
    text = value.strip().lower()
    return text in {
        "male", "m", "男", "男性", "男生",
        "female", "f", "女", "女性", "女生",
        "unknown", "未知", "",
    }
