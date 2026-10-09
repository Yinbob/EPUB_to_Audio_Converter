"""单书 RoleScriptV2 的持久化与解析内容指纹。"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Sequence

from .deepseek_splitter import role_script_to_dict
from .loader import load_role_script
from .models import RoleScriptV2


def chapter_hashes(chapters: Sequence[tuple[str, str]]) -> dict[int, str]:
    return {
        index: hashlib.sha256(text.encode("utf-8")).hexdigest()
        for index, (_title, text) in enumerate(chapters, 1)
    }


def parser_fingerprint(options: dict[str, Any]) -> str:
    encoded = json.dumps(options, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def project_path(output_root: str | Path, book_sha256: str) -> Path:
    if len(book_sha256) != 64 or any(char not in "0123456789abcdef" for char in book_sha256):
        raise ValueError("书籍指纹必须是 64 位小写 SHA-256")
    return Path(output_root) / ".role_projects" / f"{book_sha256}.json"


def load_project(path: str | Path, *, book_sha256: str) -> RoleScriptV2 | None:
    source = Path(path)
    if not source.is_file():
        return None
    script, report = load_role_script(source)
    if not report.ok or not isinstance(script, RoleScriptV2):
        raise ValueError(f"已有全书人物项目损坏：{report.to_dict()}")
    if script.book_sha256 != book_sha256:
        raise ValueError("已有全书人物项目与书籍指纹不一致")
    return script


def save_project(script: RoleScriptV2, path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".role-project-", suffix=".tmp", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file_obj:
            json.dump(role_script_to_dict(script), file_obj, ensure_ascii=False, indent=2)
            file_obj.flush()
            os.fsync(file_obj.fileno())
        os.replace(temporary, destination)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return destination
