"""比较实际合成计划；解释变化不使音频失效，返工写入独立批次。"""
import copy
import hashlib
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from .common import ServiceError, read_json
from audiobook_generator.role_script.research_io import digest, input_digest


def resource_digest(source):
    source = Path(source)
    if source.is_file():
        hasher = hashlib.sha256()
        with source.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                hasher.update(block)
        return hasher.hexdigest()
    if source.is_dir():
        return digest([(p.relative_to(source).as_posix(), resource_digest(p))
                       for p in sorted(source.rglob('*')) if p.is_file()])
    raise ServiceError('reference_missing', '参考音或质量资源已失效，请重新配置。', 409)


def clean_params(params):
    result = {}
    for key, value in params.items():
        if any(token in key.lower() for token in ('key', 'password', 'secret', 'token')):
            continue
        if isinstance(value, str) and value and (Path(value).is_absolute() or key.endswith(('_path', '_file')) or key in ('reference_audio', 'reference_wav_path', 'prompt_wav_path')):
            result[key + '_sha256'] = resource_digest(value)
        elif isinstance(value, dict):
            result[key] = clean_params(value)
        elif isinstance(value, list):
            result[key] = [clean_params({'value': item}) for item in value]
        elif isinstance(value, str) and value.startswith(('https://', 'http://')):
            url = urlsplit(value)
            result[key] = urlunsplit((url.scheme, url.netloc.rsplit('@', 1)[-1], url.path, '', ''))
        else:
            result[key] = value
    return result


def render_snapshot(plans, generation, state, config=None):
    from .portable_voices import endpoint_for
    endpoint = endpoint_for(generation.engine.provider) if generation.engine.provider in ('openai', 'minimax') else None
    values = vars(config) if config is not None else generation.model_dump()
    quality = {key: value for key, value in values.items() if
        (key.startswith('role_quality_') and generation.role_quality_enabled) or
        (key.startswith('audio_core_') and generation.audio_core_enabled)}
    quality = clean_params(quality)
    chapters = {}
    for plan in plans:
        payload = {'provider': plan.provider, 'model': generation.engine.model_dump().get('model_name'),
            'endpoint': clean_params({'endpoint': endpoint})['endpoint'], 'quality': quality,
            'format': plan.output_format, 'units': [{'text': unit.text, 'params': clean_params(unit.profile.provider_params),
                'tone': unit.tone, 'pause_after_ms': unit.pause_after_ms} for unit in plan.units]}
        chapters[str(plan.chapter_index)] = {'digest': digest(payload), 'plan': payload}
    return {'schema_version': 'research-render-v1', 'project_id': state['id'], 'revision': state['revision'],
            'research_digest': input_digest(state), 'book_sha256': state['script']['book_sha256'],
            'parser_fingerprint': state['script'].get('parser_fingerprint'),
            'source_digests': {i: hashlib.sha256(text.encode()).hexdigest() for i, text in state['sources'].items()},
            'chapters': chapters}


def validate_sources(state, catalog, chapters):
    if (catalog['book_sha256'] != state['script']['book_sha256'] or
            catalog['parser_fingerprint'] != state['script'].get('parser_fingerprint') or
            any(i < 1 or i > len(chapters) or chapters[i - 1][1] != text
                for key, text in state['sources'].items() for i in [int(key)])):
        raise ServiceError('research_source_invalid', '书籍、解析设置或正文已经变化，请重新建立研究项目。', 409)


def preview_render(projects, key, revision, generation, baseline_task_id):
    from .books import read_book, configs_for
    from .models import BookRequest
    from .projects import decode
    from audiobook_generator.role_script.planner import build_synthesis_plans, build_default_provider_params
    value = projects.check_revision(key, revision)
    state = projects.research.read(key)
    baseline = projects.manager.tasks.get(baseline_task_id) if projects.manager else None
    if not baseline or baseline.get('project_id') != key or not baseline.get('render_snapshot'):
        raise ServiceError('baseline_missing', '请选择同一项目包含合成快照的历史批次。', 409)
    if len(generation.file_ids) != 1:
        raise ServiceError('book_required', '请选择研究项目对应的一本书。')
    script = decode(value['script'])
    catalog, chapters = read_book(BookRequest(file_id=generation.file_ids[0],
        provider=generation.engine.provider, parser=generation.parser), projects.files)
    validate_sources(state, catalog, chapters)
    configs = configs_for(generation, projects.files, projects.root, script)
    planning = build_synthesis_plans(script, chapters, expected_book_sha256=catalog['book_sha256'],
        provider=generation.engine.provider, chapter_start=generation.chapter_start,
        chapter_end=len(chapters) if generation.chapter_end == -1 else generation.chapter_end,
        output_format=generation.engine.output_format,
        fallback_profile=build_default_provider_params(generation.engine.provider, configs[0]))
    if not planning.ok:
        raise ServiceError('project_coverage', '当前剧本与目标章节不匹配，请检查书籍和生成范围。', 409)
    snapshot = render_snapshot(planning.plans, generation, state, configs[0])
    changed = changed_chapters(snapshot, baseline)
    return {'revision': revision, 'baseline_revision': baseline['revision'], 'baseline_task_id': baseline_task_id,
        'changed_chapters': changed, 'unchanged_chapters': sorted(int(i) for i in snapshot['chapters'] if int(i) not in changed),
        'audio_current': not changed}


def changed_chapters(current, baseline):
    old = baseline['render_snapshot']
    if old['book_sha256'] != current['book_sha256']:
        raise ServiceError('baseline_book', '历史批次不属于同一书籍。', 409)
    completed = set()
    for directory in baseline.get('output_dirs', []):
        manifest = read_json(Path(directory) / 'manifest.json', {})
        completed.update(str(i) for i in manifest.get('completed_chapters', []))
    return sorted(int(i) for i, c in current['chapters'].items()
        if old['chapters'].get(i, {}).get('digest') != c['digest'] or
        (baseline.get('status') != 'succeeded' and i not in completed))


def prepare_regeneration(config, snapshot, baseline, batch_id=None):
    changed = changed_chapters(snapshot, baseline)
    if not changed:
        raise ServiceError('research_audio_current', '此批次的目标章节已与当前合成计划一致。', 409)
    ranges = []
    for index in changed:
        if ranges and index == ranges[-1][1] + 1:
            ranges[-1][1] = index
        else:
            ranges.append([index, index])
    output = Path(config.output_folder) / f'revision-{snapshot["revision"]}-{batch_id or uuid.uuid4().hex}'
    configs = []
    for start, end in ranges:
        cfg = copy.deepcopy(config)
        cfg.chapter_start, cfg.chapter_end = start, end
        cfg.output_folder = str(output / f'chapters-{start:06d}-{end:06d}')
        cfg.research_baseline_task_id = baseline['id']
        configs.append(cfg)
    return configs
