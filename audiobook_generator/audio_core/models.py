"""跨进程只传纯数据，模型与连接均留在执行进程内。"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class ReadingChunk:
    chunk_id: str
    unit_id: str
    role_id: str
    source_text: str
    tts_text: str
    source_start: int
    source_end: int
    profile: dict[str, Any] = field(default_factory=dict)
    tone: Optional[str] = None
    pause_after_ms: int = 0
    boundary_kind: str = "sentence"
    edits: tuple[dict[str, Any], ...] = ()
    source_span: Optional[dict[str, int]] = None
    source_scope: str = "unit"
    sequence_index: int = 0
    language: str = "auto"


@dataclass(frozen=True)
class QualityIssue:
    code: str
    dimension: str
    scope_id: str
    severity: str = "warning"
    certainty: str = "suspected"
    start_seconds: Optional[float] = None
    end_seconds: Optional[float] = None
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class QualityReport:
    scope_id: str
    dimensions: dict[str, str] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    issues: list[QualityIssue] = field(default_factory=list)
    version: str = "audio-core-v1"

    @property
    def status(self):
        if any(issue.certainty == "confirmed" and issue.severity == "error" for issue in self.issues):
            return "failed"
        if self.issues or "incomplete" in self.dimensions.values():
            return "incomplete"
        return "passed"

    def to_dict(self):
        return {**asdict(self), "status": self.status}


@dataclass(frozen=True)
class ResourceLimits:
    max_requests: int = 1000
    max_repair_requests: int = 24
    max_seconds: float = 3600.0
    per_chunk_repairs: int = 2
    max_repair_characters: Optional[int] = None

    def __post_init__(self):
        import math
        if (any(type(n) is not int for n in (self.max_requests, self.max_repair_requests, self.per_chunk_repairs))
                or self.max_requests < 0 or self.max_repair_requests < 0 or self.per_chunk_repairs < 0
                or (self.max_repair_characters is not None and
                    (type(self.max_repair_characters) is not int or self.max_repair_characters < 0))
                or not math.isfinite(self.max_seconds) or self.max_seconds <= 0):
            raise ValueError("请求／重试限制不能为负，运行时限必须为有限正数")


@dataclass
class CoreOptions:
    chunk_chars: int = 300
    enable_asr: bool = True
    enable_speaker: bool = True
    enable_vad: bool = False
    auto_repair: bool = False
    tail_repeat_mode: str = 'review'
    max_rate: float = 4.3
    max_english_wpm: float = 300.0
    language: str = "auto"
    boundary_model: Optional[str] = None
    role_references: Optional[str] = None
    speaker_model_dir: Optional[str] = None
    asr_model_dir: Optional[str] = None
    reading_dictionary: dict[str, str] = field(default_factory=dict)
    transition_boundaries: list[str] = field(default_factory=list)
    transition_source_group: Optional[str] = None
    limits: ResourceLimits = field(default_factory=ResourceLimits)

    def __post_init__(self):
        import math
        if type(self.chunk_chars) is not int or not 20 <= self.chunk_chars <= 1500:
            raise ValueError("统一核心分块长度必须在 20～1500 字符之间")
        from .language import normalize_language
        self.language = normalize_language(self.language)
        if not isinstance(self.tail_repeat_mode,str) or self.tail_repeat_mode not in {'off','review','auto'}:
            raise ValueError('尾部重复模式必须为off、review或auto')
        if self.role_references is not None and (
                not isinstance(self.role_references, str) or not self.role_references.strip()):
            raise ValueError("角色固定参考必须为空或非空文件路径字符串")
        if isinstance(self.max_english_wpm, bool) or not math.isfinite(self.max_english_wpm) or self.max_english_wpm <= 0:
            raise ValueError("英文每分钟词数上限必须是有限正数")
        if not math.isfinite(self.max_rate) or self.max_rate <= 0:
            raise ValueError("语速上限必须是有限正数")
        from .reading import validate_reading_dictionary
        self.reading_dictionary = validate_reading_dictionary(self.reading_dictionary)
        if (not isinstance(self.transition_boundaries, list)
                or any(not isinstance(value, str) or len(value.split("|")) != 2
                       or not all(part.strip() for part in value.split("|")) for value in self.transition_boundaries)
                or len(set(self.transition_boundaries)) != len(self.transition_boundaries)):
            raise ValueError("起读处理接缝必须为不重复的左块编号|右块编号列表")
        self.transition_boundaries = list(self.transition_boundaries)
        if self.transition_source_group is not None and (
                not isinstance(self.transition_source_group, str) or len(self.transition_source_group) != 64
                or any(c not in "0123456789abcdef" for c in self.transition_source_group)):
            raise ValueError("起读处理来源指纹必须为报告中的 64 位小写十六进制 source_group_id")
        if self.transition_boundaries and self.transition_source_group is None:
            raise ValueError("指定起读处理接缝时必须同时指定 transition_source_group，以免应用到同编号的其他正文")

    @classmethod
    def from_config(cls, config):
        from .reading import load_reading_dictionary
        return cls(
            chunk_chars=getattr(config, "audio_core_chunk_chars", 300),
            enable_asr=not bool(getattr(config, "audio_core_no_asr", False)),
            enable_speaker=not bool(getattr(config, "audio_core_no_speaker", False)),
            enable_vad=bool(getattr(config, "audio_core_vad", False)),
            auto_repair=bool(getattr(config, "audio_core_repair", False)),
            tail_repeat_mode=getattr(config, 'audio_core_tail_repeat_mode', 'review'),
            max_rate=float(getattr(config, "role_quality_max_rate", 4.3) or 4.3),
            max_english_wpm=getattr(config, "audio_core_max_english_wpm", 300),
            language=getattr(config, "language", None) or "auto",
            boundary_model=getattr(config, "audio_core_boundary_model", None),
            role_references=getattr(config, "audio_core_role_references", None),
            speaker_model_dir=getattr(config, "audio_core_speaker_model", None),
            asr_model_dir=getattr(config, "audio_core_asr_model", None),
            reading_dictionary=load_reading_dictionary(getattr(config, "audio_core_reading_dictionary", None)),
            transition_boundaries=getattr(config, "audio_core_transition_boundaries", []),
            transition_source_group=getattr(config, "audio_core_transition_source_group", None),
            limits=ResourceLimits(
                max_requests=int(getattr(config, "audio_core_max_requests", 1000)),
                max_repair_requests=int(getattr(config, "audio_core_max_repairs", 24)),
                max_seconds=float(getattr(config, "audio_core_max_seconds", 3600)),
                max_repair_characters=getattr(config, "audio_core_max_repair_characters", None),
            ),
        )
