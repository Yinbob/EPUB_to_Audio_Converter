"""可跨 spawn 进程传递的剧本领域模型。

本包只放纯数据；Provider、文件句柄、BytesIO、Gradio File 等对象不得进入这些 dataclass。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class RoleDefinition:
    display_name: str
    provider_params: Dict[str, Any] = field(default_factory=dict)
    # DeepSeek 推断出的性别只用于本地选音色，不进入 Provider 参数。
    gender: Optional[str] = None


@dataclass(frozen=True)
class SegmentScript:
    role_id: str
    text: str
    tone: Optional[str] = None
    pause_after_ms: Optional[int] = None


@dataclass(frozen=True)
class ChapterScript:
    chapter_index: int
    title: str
    segments: Tuple[SegmentScript, ...] = ()


@dataclass(frozen=True)
class RoleScriptV1:
    schema_version: int
    provider: str
    book_sha256: str
    default_pause_after_ms: int
    roles: Dict[str, RoleDefinition] = field(default_factory=dict)
    chapters: Tuple[ChapterScript, ...] = ()


@dataclass(frozen=True)
class VoiceProfile:
    role_id: str
    display_name: str
    provider_params: Dict[str, Any] = field(default_factory=dict)
    tone: Optional[str] = None


@dataclass(frozen=True)
class SynthesisUnit:
    unit_id: str
    chapter_index: int
    chapter_title: str
    segment_index: int
    segment_count: int
    role_id: str
    display_name: str
    text: str
    profile: VoiceProfile
    tone: Optional[str] = None
    pause_after_ms: int = 0
    is_fallback: bool = False


@dataclass(frozen=True)
class ChapterSynthesisPlan:
    chapter_index: int
    title: str
    units: Tuple[SynthesisUnit, ...]
    output_format: str
    provider: str

    @property
    def segment_count(self) -> int:
        return len(self.units)


@dataclass(frozen=True)
class AudioArtifact:
    """一段合成音频的实际元数据。path 指向章节 worker 临时目录内的文件。"""

    path: str
    format: str
    sample_rate: int
    channels: int
    duration_ms: int
    sha256: str
    cache_key: str
