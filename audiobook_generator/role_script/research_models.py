"""研究审阅的独立数据契约；不改变 RoleScriptV2 的导入格式。"""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class Record(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False, json_schema_serialization_defaults_required=True)


class Mention(Record):
    id: str
    span: dict
    text: str
    block_id: str


class IdentityClaim(Record):
    id: str
    kind: Literal['mention_entity', 'same_entity', 'distinct_entity', 'narrator_entity']
    subject: str
    entity_id: str
    scope: dict
    status: Literal['proposed', 'accepted', 'rejected', 'revoked'] = 'proposed'
    evidence: list[dict] = Field(default_factory=list)
    source: Literal['model', 'human', 'legacy'] = 'model'
    created_revision: int
    revoked_revision: int | None = None


class AttributionDecision(Record):
    id: str
    segment_id: str
    entity_id: str | None
    candidates: list[str] = Field(default_factory=list)
    evidence: list[dict] = Field(default_factory=list)
    against: list[dict] = Field(default_factory=list)
    status: Literal['proposed', 'unknown', 'human', 'stale'] = 'proposed'
    analyzer_version: str = 'legacy'


class DecisionDependency(Record):
    decision_id: str
    upstream_id: str
    kind: Literal['depends_on', 'context_refs']


class Conflict(Record):
    id: str
    kind: str
    refs: list[str]
    evidence: list[dict] = Field(default_factory=list)
    status: Literal['open', 'resolved'] = 'open'


class ReviewEvent(Record):
    operation_id: str
    action: str
    data: dict
    revision: int
    changes: list[dict] = Field(default_factory=list)


class ReviewProposal(Record):
    id: str
    base_revision: int
    input_digest: str
    analyzer_version: str
    changes: list[dict]
    mentions: list[dict] = Field(default_factory=list)
    claims: list[dict] = Field(default_factory=list)
    conflicts: list[dict] = Field(default_factory=list)
    applied_segments: list[str] = Field(default_factory=list)
    status: Literal['ready', 'partial', 'applied', 'stale'] = 'ready'


class ResearchState(Record):
    research_schema_version: Literal[1] = 1
    id: str
    revision: int
    confirmed: str = ''
    script: dict
    sources: dict[str, str]
    history_incomplete: bool = True
    mentions: dict[str, Mention] = Field(default_factory=dict)
    claims: dict[str, IdentityClaim] = Field(default_factory=dict)
    decisions: dict[str, AttributionDecision] = Field(default_factory=dict)
    dependencies: list[DecisionDependency] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    proposals: dict[str, ReviewProposal] = Field(default_factory=dict)
    events: list[ReviewEvent] = Field(default_factory=list)
    sessions: dict[str, dict] = Field(default_factory=dict)
    operations: dict[str, dict] = Field(default_factory=dict)
    unconfigured_entities: list[str] = Field(default_factory=list)
    context_checks: list[str] = Field(default_factory=list)
    runs: dict[str, dict] = Field(default_factory=dict)
    policy_version: str = 'review_policy_v1'
