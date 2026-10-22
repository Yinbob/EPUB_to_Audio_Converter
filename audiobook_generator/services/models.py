"""具名请求模型；不同引擎的参数互不混用。"""
from typing import Annotated, Literal, Union
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class MiMo(StrictModel):
    provider: Literal['openai'] = 'openai'
    model_name: str = 'mimo-v2.5-tts'
    voice_name: str = 'mimo_default'
    output_format: Literal['mp3', 'aac', 'flac', 'opus', 'wav'] = 'mp3'
    speed: float = Field(1, ge=.25, le=4)
    instructions: str = ''
    stream: bool = True


class MiniMax(StrictModel):
    provider: Literal['minimax']
    model_name: str = 'speech-2.8-hd'
    voice_name: str = 'male-qn-qingse'
    output_format: Literal['mp3', 'wav', 'pcm', 'flac'] = 'mp3'


class Edge(StrictModel):
    provider: Literal['edge']
    language: str = 'zh-CN'
    voice_name: str = 'zh-CN-XiaoxiaoNeural'
    output_format: str = 'mp3'
    voice_rate: int = Field(0, ge=-100, le=100)
    voice_volume: int = Field(0, ge=-100, le=100)
    voice_pitch: int = Field(0, ge=-100, le=100)
    break_duration: int = Field(500, ge=0, le=10000)
    proxy: str = ''


class Qwen(StrictModel):
    provider: Literal['qwen']
    language: str = 'Auto'
    voice_name: str = 'Vivian'
    output_format: str = 'mp3'


class Chatterbox(StrictModel):
    provider: Literal['chatterbox']
    model_name: str = 'chatterbox-multilingual-v3'
    output_format: Literal['mp3', 'wav', 'aac', 'flac'] = 'mp3'
    device: Literal['auto', 'cpu', 'cuda', 'mps'] = 'auto'
    reference_audio: str | None = None
    exaggeration: float = Field(.5, ge=0, le=1)
    cfg_weight: float = Field(.5, ge=0, le=1)
    speed: float = Field(1, ge=.2, le=2)


class VoxCPM(StrictModel):
    provider: Literal['voxcpm']
    model_name: str = 'openbmb/VoxCPM2'
    output_format: Literal['mp3', 'wav', 'aac', 'flac'] = 'mp3'
    device: Literal['auto', 'cpu', 'cuda', 'mps'] = 'auto'
    mode: Literal['design', 'clone', 'hifi'] = 'design'
    voice: str = 'preset:沉稳男声'
    voice_dir: str = 'voices'
    voice_description: str = ''
    regenerate_voice: bool = False
    reference_audio: str | None = None
    reference_text: str = ''
    auto_transcribe: bool = True
    denoise: bool = False
    normalize: bool = True
    cfg_value: float = Field(2, ge=.5, le=8)
    inference_timesteps: int = Field(10, ge=1, le=50)
    speed: float = Field(1, ge=.5, le=2)
    chunk_chars: int = Field(400, ge=50, le=1200)
    optimize: bool = True


Engine = Annotated[Union[MiMo, MiniMax, Edge, Qwen, Chatterbox, VoxCPM], Field(discriminator='provider')]


class ParserOptions(StrictModel):
    title_mode: Literal['auto', 'tag_text', 'first_few'] = 'auto'
    newline_mode: Literal['single', 'double', 'none'] = 'double'
    remove_endnotes: bool = False
    remove_reference_numbers: bool = False
    search_and_replace_file: str | None = None


class BookRequest(StrictModel):
    file_id: str
    provider: Literal['openai', 'minimax', 'edge', 'qwen', 'chatterbox', 'voxcpm'] = 'openai'
    parser: ParserOptions = Field(default_factory=ParserOptions)


class Generation(StrictModel):
    file_ids: list[str] = Field(min_length=1)
    engine: Engine = Field(default_factory=MiMo)
    parser: ParserOptions = Field(default_factory=ParserOptions)
    output_dir: str = ''
    worker_count: int = Field(1, ge=1, le=16)
    log_level: Literal['DEBUG', 'INFO', 'WARNING', 'ERROR'] = 'INFO'
    output_text: bool = False
    preview: bool = False
    chapter_start: int = Field(1, ge=1)
    chapter_end: int = -1
    catalog_fingerprint: str | None = None
    project_id: str | None = None
    project_revision: int | None = None
    allow_role_text_override: bool = False
    allow_role_title_mismatch: bool = False
    allow_role_fallback: bool = False
    role_quality_enabled: bool = False
    role_quality_max_rate: float = Field(4.3, gt=0)
    audio_core_enabled: bool = False
    audio_core_repair: bool = False
    audio_core_settings_file: str | None = None
    audio_core_casting_file: str | None = None


class TaskRequest(StrictModel):
    request_id: str = Field(min_length=8, max_length=128)
    kind: Literal['generate', 'split', 'preview', 'casting_analyze', 'casting_draft', 'calibrate'] = 'generate'
    generation: Generation
    project_id: str | None = None
    revision: int | None = None
    text: str = '你好，欢迎来到有声书工坊。'
    role_id: str | None = None
    full_book: bool = False
    bank_id: str | None = None
    language: Literal['zh', 'en'] = 'zh'


class ProjectEdit(StrictModel):
    revision: int
    operation: Literal['replace', 'narrator', 'segment', 'merge', 'lock', 'voice', 'confirm', 'casting_apply']
    data: dict = Field(default_factory=dict)


class ConfigUpdate(StrictModel):
    api_key: str = ''
    base_url: str = ''
    model: str = ''
    clear_key: bool = False


class Selection(StrictModel):
    folder: str
    names: list[str] = Field(default_factory=list)
    acknowledged: bool = False


class TaskSnapshot(StrictModel):
    id: str
    request_id: str
    kind: str
    status: Literal['starting', 'running', 'stopping', 'stopped', 'succeeded', 'failed']
    created_at: float
    finished_at: float | None = None
    project_id: str | None = None
    revision: int | None = None
    result: dict = Field(default_factory=dict)
    error: str = ''
    output_dirs: list[str] = Field(default_factory=list)
    progress: dict = Field(default_factory=dict)
