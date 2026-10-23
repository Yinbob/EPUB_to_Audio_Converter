"""公开的结构化产物。原文位置与音频时间均来自实际解析/PCM 组装。"""
import hashlib
import json
import uuid
import os
import shutil
import tempfile
from pathlib import Path

from .common import atomic_json, read_json


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def write_sources(parser, chapters, config):
    sources = getattr(parser, 'source_chapters', None)
    if not isinstance(sources, list):
        return False
    sources = [s for s in sources if s['text'].strip()]
    if len(sources) != len(chapters):
        raise ValueError('原文映射与解析章节数量不一致')
    output = Path(config.output_folder)
    paragraphs, chapter_rows = [], []
    for index, ((title, text), source) in enumerate(zip(chapters, sources), 1):
        if source['text'] != text:
            raise ValueError('原文映射与解析正文不一致')
        chapter_rows.append({'index': index, 'title': title, 'text': text,
                             'sha256': hashlib.sha256(text.encode()).hexdigest()})
        for i, p in enumerate(source['paragraphs'], 1):
            paragraphs.append({**p, 'id': f'ch{index}:p{i}', 'chapter_index': index})
    source_file = Path(config.input_file)
    book_hash = sha256(source_file)
    research = getattr(config, 'research_render_snapshot', None)
    if research and (book_hash != research['book_sha256'] or any(
            research.get('source_digests', {}).get(str(c['index'])) != c['sha256']
            for c in chapter_rows if str(c['index']) in research['chapters'])):
        raise ValueError('研究项目原文在生成前发生变化，未提交本次生成产物')
    saved_source = output / '.source' / ('original-' + book_hash + source_file.suffix.lower())
    saved_source.parent.mkdir(parents=True, exist_ok=True)
    if not saved_source.is_file() or sha256(saved_source) != book_hash:
        descriptor, temporary = tempfile.mkstemp(dir=saved_source.parent, suffix='.tmp')
        os.close(descriptor)
        try:
            shutil.copyfile(source_file, temporary)
            if sha256(temporary) != book_hash:
                raise ValueError('源文件在复制期间发生变化，请重新读取书籍')
            os.replace(temporary, saved_source)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    atomic_json(output / 'chapters.json', {'schema_version': 'book-chapters-v1', 'book_sha256': book_hash, 'chapters': chapter_rows})
    atomic_json(output / 'source_map.json', {'schema_version': 'source-map-v1', 'book_sha256': book_hash,
        'coordinates': 'Unicode codepoints, half-open [start,end)', 'paragraphs': paragraphs})
    script = getattr(config, 'role_script', None)
    if isinstance(script, (str, Path)) and script:
        from audiobook_generator.role_script.loader import load_role_script
        script, report = load_role_script(script)
        if script is None or not report.ok:
            raise ValueError('无法读取用于原文溯源的角色剧本')
    if script:
        from .projects import encode
        atomic_json(output / 'roles.json', encode(script))
        profiles = {key: {'display_name': r.display_name, 'provider': script.provider, 'params': r.provider_params,
                         'version': hashlib.sha256(json.dumps(r.provider_params, sort_keys=True, ensure_ascii=False).encode()).hexdigest()}
                    for key, r in script.roles.items()}
    else:
        params = getattr(config, '_portable_params', None) or {key: getattr(config, key, None) for key in ('model_name', 'voice_name', 'speed', 'instructions')}
        profiles = {'narrator': {'display_name': '旁白', 'provider': config.tts, 'params': params,
            'version': hashlib.sha256(json.dumps(params, sort_keys=True, ensure_ascii=False).encode()).hexdigest()}}
        atomic_json(output / 'roles.json', {'roles': {'narrator': {'display_name': '旁白'}}})
    snapshot = getattr(config, 'portable_voice_snapshot', None)
    atomic_json(output / 'voices.json', {'schema_version': 'rendered-voices-v1', 'profiles': profiles,
        'portable_voice_snapshot': snapshot,
        'role_portable_voice_snapshots': getattr(config, 'role_portable_voice_snapshots', {}),
        'portable_voice_version': snapshot.get('version') if isinstance(snapshot, dict) else None})
    atomic_json(output / 'manifest.json', {'schema_version': 'audiobook-manifest-v1', 'book_sha256': book_hash,
        'source_name': getattr(config, 'source_name', None) or source_file.name,
        'source_file': saved_source.relative_to(output).as_posix(),
        'title': parser.get_book_title(), 'author': parser.get_book_author(), 'provider': config.tts,
        'chapter_range': [config.chapter_start, config.chapter_end], 'status': 'prepared',
        'render_id': uuid.uuid4().hex,
        'research_render_snapshot': getattr(config, 'research_render_snapshot', None),
        'research_baseline_task_id': getattr(config, 'research_baseline_task_id', None),
        'files': ['chapters.json', 'source_map.json', 'roles.json', 'voices.json', 'timeline.json'],
        'alignment': 'paragraph-to-audio-chunk; no word-level forced alignment'})
    # 重跑只汇总本次有相同原文和音频摘要的时间线。
    return True


def write_timeline(output_file, chapter_index, spans, *, sample_rate, precision='chunk'):
    output = Path(output_file)
    root = output.parent
    chapters = read_json(root / 'chapters.json', {}).get('chapters', [])
    chapter = next((c for c in chapters if c['index'] == chapter_index), None)
    if chapter is None:
        return
    if type(sample_rate) is not int or sample_rate <= 0:
        raise ValueError('音频时间线采样率必须为正整数')
    manifest = read_json(root / 'manifest.json', {})
    paragraphs = read_json(root / 'source_map.json', {}).get('paragraphs', [])
    rows = []
    previous_end = 0
    for i, span in enumerate(spans, 1):
        exact_source = bool(span.get('source_span')) or ('source_start' in span and 'source_end' in span)
        source = span.get('source_span') or {'start': span.get('source_start', 0), 'end': span.get('source_end', len(chapter['text']))}
        if (any(type(source.get(key)) is not int for key in ('start', 'end'))
                or not 0 <= source['start'] <= source['end'] <= len(chapter['text'])
                or source.get('chapter_index', chapter_index) != chapter_index):
            raise ValueError('音频时间线原文范围不合法')
        if (any(type(span.get(key)) is not int for key in ('start_sample', 'end_sample'))
                or not previous_end <= span['start_sample'] < span['end_sample']):
            raise ValueError('音频时间线采样范围不合法或存在重叠')
        previous_end = span['end_sample']
        links = [p['id'] for p in paragraphs if p['chapter_index'] == chapter_index
                 and p['start'] < source['end'] and p['end'] > source['start']]
        rows.append({**span, 'id': span.get('chunk_id') or f'ch{chapter_index}:audio{i}',
                     'chapter_index': chapter_index, 'source_start': source['start'], 'source_end': source['end'],
                     'paragraph_ids': links, 'start_seconds': span['start_sample'] / sample_rate,
                     'end_seconds': span['end_sample'] / sample_rate,
                     'precision': precision if exact_source else 'chapter'})
    atomic_json(root / '.source' / f'chapter-{chapter_index:06d}.json', {
        'chapter_index': chapter_index, 'source_sha256': chapter['sha256'], 'audio': output.name,
        'audio_sha256': sha256(output), 'sample_rate': sample_rate, 'spans': rows,
        'book_sha256': manifest.get('book_sha256'), 'render_id': manifest.get('render_id')})


def write_plans(output_dir, plans):
    """保留真正进入合成的参数，涵盖语言修正和全局回退。"""
    root = Path(output_dir)
    voices = read_json(root / 'voices.json', {})
    if not voices:
        return
    rendered = {}
    for plan in plans:
        for unit in plan.units:
            identity = dict(unit.profile.provider_params)
            identity.pop('reference_audio_path', None)
            version = hashlib.sha256(json.dumps({'provider': plan.provider, 'params': identity},
                sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            rendered[f'{unit.role_id}:{version}'] = {'provider': plan.provider, 'role_id': unit.role_id,
                'display_name': unit.profile.display_name, 'params': unit.profile.provider_params, 'version': version}
    voices['planned_profiles'] = rendered
    atomic_json(root / 'voices.json', voices)


def finalize(output_dir, *, status='succeeded'):
    root = Path(output_dir)
    manifest = read_json(root / 'manifest.json', {})
    if not manifest:
        return
    chapters = {c['index']: c for c in read_json(root / 'chapters.json', {})['chapters']}
    first, last = manifest.get('chapter_range', [1, -1])
    first = first or 1
    last = max(chapters, default=0) if last in (None, -1) else last
    timelines = []
    for path in sorted((root / '.source').glob('chapter-*.json')):
        value = read_json(path, {})
        chapter = chapters.get(value.get('chapter_index'))
        audio = root / value.get('audio', '')
        if (chapter and first <= chapter['index'] <= last
                and value.get('render_id') == manifest.get('render_id')
                and value.get('book_sha256') == manifest.get('book_sha256')
                and value.get('source_sha256') == chapter['sha256']
                and audio.resolve().parent == root.resolve() and audio.is_file()
                and sha256(audio) == value.get('audio_sha256')):
            timelines.append(value)
    alignment = 'chapter' if any(s.get('precision') == 'chapter' for c in timelines for s in c['spans']) else 'chunk'
    atomic_json(root / 'timeline.json', {'schema_version': 'audio-timeline-v1', 'book_sha256': manifest['book_sha256'],
        'render_id': manifest.get('render_id'), 'alignment': alignment, 'chapters': timelines})
    manifest['status'] = status
    manifest['completed_chapters'] = [c['chapter_index'] for c in timelines]
    atomic_json(root / 'manifest.json', manifest)
