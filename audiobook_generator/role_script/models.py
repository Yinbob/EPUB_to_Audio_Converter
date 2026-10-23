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
    segment_id: Optional[str] = None
    source_span: Optional[SourceSpan] = None
    speaker: Optional[SpeakerDecision] = None
    # 自动拆分时的临时引文候选；写入 V2 前必须解析为带坐标的 evidence。
    evidence_candidates: Tuple[Tuple[str, str], ...] = ()
    # 段落用途与声音身份分开：人物自述仍是 narration，但 role_id 指向该人物。
    text_kind: Optional[str] = None


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
class SourceSpan:
    """解析后的章节正文中的 Unicode 字符区间，左闭右开。"""

    chapter_index: int
    start: int
    end: int


@dataclass(frozen=True)
class EvidenceSpan:
    span: SourceSpan
    kind: str
    quote: str
    relation: str = "said-by"


@dataclass(frozen=True)
class SpeakerDecision:
    entity_id: Optional[str]
    status: str
    confidence: Optional[float] = None
    evidence: Tuple[EvidenceSpan, ...] = ()
    model: Optional[str] = None
    confidence_kind: str = "uncalibrated"


@dataclass(frozen=True)
class AliasRecord:
    text: str
    status: str = "proposed"
    source_span: Optional[SourceSpan] = None
    confidence: Optional[float] = None


@dataclass(frozen=True)
class CharacterEntity:
    canonical_name: str
    aliases: Tuple[AliasRecord, ...] = ()
    voice_profile_id: Optional[str] = None
    voice_locked: bool = False
    gender: Optional[str] = None


@dataclass(frozen=True)
class RegistryWarning:
    chapter_index: int
    chunk_start: int
    rejected_items: int
    total_items: int
    message: str


@dataclass(frozen=True)
class RoleScriptV2(RoleScriptV1):
    entities: Dict[str, CharacterEntity] = field(default_factory=dict)
    parser_fingerprint: str = ""
    chapter_hashes: Dict[int, str] = field(default_factory=dict)
    registry_complete: bool = False
    registry_warnings: Tuple[RegistryWarning, ...] = ()


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
    source_span: Optional[SourceSpan] = None
    segment_id: Optional[str] = None


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
