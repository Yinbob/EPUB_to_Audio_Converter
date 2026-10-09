"""多角色剧本领域模型与校验入口。"""

from .errors import ErrorItem, ValidationReport
from .models import (
    AudioArtifact,
    ChapterScript,
    ChapterSynthesisPlan,
    RoleDefinition,
    RoleScriptV1,
    RoleScriptV2,
    SegmentScript,
    SynthesisUnit,
    VoiceProfile,
)
from .planner import PlanningResult, build_synthesis_plans
from .validator import ValidationResult, validate_role_script

__all__ = [
    "AudioArtifact",
    "ChapterScript",
    "ChapterSynthesisPlan",
    "ErrorItem",
    "PlanningResult",
    "RoleDefinition",
    "RoleScriptV1",
    "RoleScriptV2",
    "SegmentScript",
    "SynthesisUnit",
    "ValidationReport",
    "ValidationResult",
    "VoiceProfile",
    "build_synthesis_plans",
    "validate_role_script",
]
