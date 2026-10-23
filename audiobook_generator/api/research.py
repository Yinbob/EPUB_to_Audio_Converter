"""研究审阅具名接口；所有写操作由同一个项目服务提交。"""
from typing import Annotated, Literal, Union
from fastapi import Query
from pydantic import Field
from audiobook_generator.services.models import StrictModel, Generation
from audiobook_generator.role_script.research_models import ResearchState, ReviewProposal


class Write(StrictModel):
    revision: int = Field(ge=1)
    operation_id: str = Field(min_length=8, max_length=128)


class Merge(StrictModel):
    action: Literal['merge', 'distinct']
    source_id: str
    target_id: str


class Claim(StrictModel):
    action: Literal['accept', 'reject', 'revoke']
    claim_id: str


class Segment(StrictModel):
    action: Literal['segment']
    segment_id: str
    entity_id: str


class Narrator(StrictModel):
    action: Literal['narrator']
    chapter_index: int = Field(ge=1)
    entity_id: str


class CreateEntity(StrictModel):
    action: Literal['create_entity']
    name: str = Field(min_length=1, max_length=120)
    segment_ids: list[str] = Field(min_length=1)


Decision = Annotated[Union[Merge, Claim, Segment, Narrator, CreateEntity], Field(discriminator='action')]


class DecisionRequest(Write):
    decision: Decision


class ApplyRequest(Write):
    segment_ids: list[str] = Field(min_length=1)


class SessionRequest(Write):
    budget_seconds: int = Field(600, ge=1, le=86400)
    strategy: Literal['sequence', 'risk', 'impact'] = 'impact'
    seed: str = Field('review-v1', max_length=128)
    audit_every: int = Field(10, ge=0, le=100)


class SessionEvent(StrictModel):
    kind: Literal['shown', 'elapsed', 'skip', 'answered', 'pause', 'continue', 'end', 'resume']
    task_id: str = ''
    elapsed_seconds: float = Field(0, ge=0, le=86400)


class SessionEventRequest(Write):
    event: SessionEvent


class ExportRequest(Write):
    mode: Literal['snapshot', 'events'] = 'snapshot'


class ResearchView(StrictModel):
    state: ResearchState
    summary: dict
    project: dict


class RenderPreviewRequest(Write):
    generation: Generation
    baseline_task_id: str


class RenderPreview(StrictModel):
    revision: int
    baseline_revision: int
    baseline_task_id: str
    changed_chapters: list[int]
    unchanged_chapters: list[int]
    audio_current: bool


class ReviewTask(StrictModel):
    id: str
    kind: str
    segment_ids: list[str]
    chapters: list[int]
    evidence: list[dict]
    candidates: list[str]
    reason: str
    risk_score: float
    weighted_impact: float
    estimated_seconds: float
    score: float
    order: list[int]
    audit: bool = False
    sampling_probability: float = 1
    queue_version: int | None = None


class ReviewQueue(StrictModel):
    revision: int
    total: int
    items: list[ReviewTask]
    recommendation: ReviewTask | None = None


class DecisionPreview(StrictModel):
    revision: int
    action: str
    affected_segments: list[str]
    changes: list[dict]
    chapters: list[int]
    preview: bool


def register_research_routes(app, prefix):
    base = prefix + '/projects/{key}/research'

    @app.post(base + '/enable', response_model=ResearchView)
    def enable(key: str, body: Write):
        return app.state.projects.research.enable(key, body.revision, body.operation_id)

    @app.get(base, response_model=ResearchView)
    def get(key: str):
        return app.state.projects.research.view(key)

    @app.get(base + '/queue', response_model=ReviewQueue)
    def queue(key: str, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
              strategy: Literal['sequence', 'risk', 'impact'] = 'impact', session_id: str | None = None):
        return app.state.projects.research.queue(key, offset, limit, strategy, session_id)

    @app.post(base + '/preview', response_model=DecisionPreview)
    def preview(key: str, body: DecisionRequest):
        data = body.decision.model_dump()
        return app.state.projects.research.decide(key, body.revision, body.operation_id,
            data.pop('action'), data, preview=True)

    @app.post(base + '/decisions', response_model=ResearchView)
    def decision(key: str, body: DecisionRequest):
        data = body.decision.model_dump()
        return app.state.projects.research.decide(key, body.revision, body.operation_id, data.pop('action'), data)

    @app.get(base + '/proposals/{proposal_id}', response_model=ReviewProposal)
    def proposal(key: str, proposal_id: str):
        from audiobook_generator.services.common import ServiceError
        value = app.state.projects.research.read(key)['proposals'].get(proposal_id)
        if value is None:
            raise ServiceError('proposal_missing', '找不到分析草稿，请刷新项目。', 404)
        return value

    @app.post(base + '/proposals/{proposal_id}/apply', response_model=ResearchView)
    def apply(key: str, proposal_id: str, body: ApplyRequest):
        return app.state.projects.research.apply_proposal(key, body.revision, body.operation_id, proposal_id, body.segment_ids)

    @app.post(base + '/sessions')
    def session(key: str, body: SessionRequest):
        return app.state.projects.research.session(key, **body.model_dump())

    @app.post(base + '/sessions/{session_id}/events')
    def event(key: str, session_id: str, body: SessionEventRequest):
        return app.state.projects.research.session_event(key, body.revision, body.operation_id, session_id, body.event.model_dump())

    @app.post(base + '/export')
    def export(key: str, body: ExportRequest):
        return app.state.projects.research.export(key, **body.model_dump())

    @app.post(base + '/render-preview', response_model=RenderPreview)
    def render_preview(key: str, body: RenderPreviewRequest):
        from audiobook_generator.services.research_render import preview_render
        with app.state.projects.lock:
            app.state.projects.research.check(key, body.revision)
            return preview_render(app.state.projects, key, body.revision, body.generation, body.baseline_task_id)
