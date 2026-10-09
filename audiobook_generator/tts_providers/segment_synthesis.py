"""角色模式 Provider 共用的段合成辅助函数。"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from typing import Any, Callable, Dict, Optional


ProgressCallback = Optional[Callable[[str], None]]


def segment_cache_key(
    *,
    provider: str,
    model: str,
    provider_params: Dict[str, Any],
    tone: Optional[str],
    text: str,
    request_options: Optional[Dict[str, Any]] = None,
) -> str:
    payload = {
        "provider": provider,
        "model": model,
        "provider_params": provider_params,
        "tone": tone,
        "text": text,
        "request_options": request_options or {},
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def emit_role_progress(progress: ProgressCallback, message: str) -> None:
    if progress is not None:
        progress(message)


def _remove_silently(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def atomic_write_bytes(path: str, content: bytes) -> None:
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    file_descriptor, temporary = tempfile.mkstemp(
        prefix=".segment-", suffix=".tmp", dir=directory
    )
    try:
        with os.fdopen(file_descriptor, "wb") as file_obj:
            file_obj.write(content)
            file_obj.flush()
            os.fsync(file_obj.fileno())
        os.replace(temporary, path)
    except Exception:
        _remove_silently(temporary)
        raise


def atomic_export_audio(audio: Any, path: str, *, format: str, **kwargs: Any) -> None:
    """原子导出 AudioSegment，异常时保证同目录临时文件不残留。"""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    file_descriptor, temporary = tempfile.mkstemp(
        prefix=".segment-", suffix=f".{format}.tmp", dir=directory
    )
    os.close(file_descriptor)
    try:
        audio.export(temporary, format=format, **kwargs)
        os.replace(temporary, path)
    except Exception:
        _remove_silently(temporary)
        raise
