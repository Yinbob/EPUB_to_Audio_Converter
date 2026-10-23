"""目录、指纹及 GeneralConfig 的唯一映射。"""
import hashlib
import json
from pathlib import Path
from audiobook_generator.config.general_config import GeneralConfig
from .common import ServiceError
from .models import BookRequest


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def parser_config(options, files):
    config = GeneralConfig(None)
    for key, value in options.model_dump().items():
        if key == 'search_and_replace_file' and value:
            value = str(files.resolve(value))
        setattr(config, key, value)
    return config


def read_book(request, files):
    from audiobook_generator.book_parsers.base_book_parser import get_book_parser
    path = files.resolve(request.file_id)
    config = parser_config(request.parser, files)
    config.input_file = str(path)
    config.source_name = files.register(path)['name']
    break_string = '   ' if request.provider in ('openai', 'chatterbox', 'voxcpm') else ' @BRK#'
    try:
        parser = get_book_parser(config)
        chapters = [(title, text) for title, text in parser.get_chapters(break_string) if text.strip()]
    except Exception as exc:
        raise ServiceError('book_parse_failed', '无法读取此书籍，请确认文件完整且格式正确。') from exc
    if not chapters:
        raise ServiceError('book_empty', '书籍中没有可转换的章节。')
    options = request.parser.model_dump()
    options['provider'] = request.provider
    if options['search_and_replace_file']:
        options['search_and_replace_sha256'] = digest(files.resolve(options.pop('search_and_replace_file')))
    parser_fp = hashlib.sha256(json.dumps(options, sort_keys=True).encode()).hexdigest()
    book_sha = digest(path)
    catalog_fp = hashlib.sha256((book_sha + parser_fp).encode()).hexdigest()
    return {'book_sha256': book_sha, 'parser_fingerprint': parser_fp, 'fingerprint': catalog_fp,
            'chapters': [{'index': i, 'title': title, 'characters': len(text)}
                         for i, (title, text) in enumerate(chapters, 1)]}, chapters


def configs_for(request, files, output_root, project=None, *, allow_empty=False):
    if not request.file_ids and not allow_empty:
        raise ServiceError('book_required', '请先上传书籍文件。')
    if request.chapter_end != -1 and request.chapter_end < request.chapter_start:
        raise ServiceError('chapter_range', '结束章节不能早于起始章节。')
    if request.audio_core_enabled and request.engine.provider != 'openai':
        raise ServiceError('quality_provider', '统一质量核心当前仅支持 MiMo。')
    if project and (len(request.file_ids) != 1 or request.engine.provider not in ('openai', 'minimax')):
        raise ServiceError('role_provider', '角色模式仅支持单本书以及 MiMo / MiniMax。')
    if request.catalog_fingerprint:
        if len(request.file_ids) != 1:
            raise ServiceError('catalog_batch', '批量转换请使用数字章节范围。')
        catalog, _ = read_book(BookRequest(file_id=request.file_ids[0], provider=request.engine.provider,
                                           parser=request.parser), files)
        if catalog['fingerprint'] != request.catalog_fingerprint:
            raise ServiceError('catalog_changed', '书籍或解析选项已改变，请重新读取目录。', 409)
        if request.chapter_start > len(catalog['chapters']) or request.chapter_end > len(catalog['chapters']):
            raise ServiceError('chapter_range', '章节范围超过目录，请重新选择。')
    output = Path(request.output_dir).expanduser().resolve() if request.output_dir else Path(output_root)
    configs = []
    used_names = set()
    for file_id in request.file_ids or [None]:
        path = files.resolve(file_id) if file_id else None
        config = parser_config(request.parser, files)
        config.input_file = str(path) if path else None
        config.source_name = files.register(path)['name'] if path else '声音试听'
        name = ''.join(c if c.isalnum() or c in '._-' else '_' for c in Path(config.source_name).stem)
        name = name.strip('.')[:100] or '书籍'
        if name in used_names:
            name += '_' + file_id[:8]
        used_names.add(name)
        config.output_folder = str(output / name) if len(request.file_ids) > 1 else str(output)
        config.tts = request.engine.provider
        config.allow_custom_tts = config.tts == 'openai'
        config.worker_count = request.worker_count
        config.log = request.log_level
        config.no_prompt = True
        config.preview = request.preview and not bool(project)
        config.output_text = request.output_text
        config.chapter_start, config.chapter_end = request.chapter_start, request.chapter_end
        config.use_pydub_merge = True
        for key, value in request.engine.model_dump(exclude={'provider'}).items():
            target = key
            if config.tts in ('chatterbox', 'voxcpm') and key not in ('model_name', 'output_format'):
                target = f'{config.tts}_{key}'
            if config.tts == 'voxcpm' and ((key == 'reference_audio' and request.engine.mode == 'design') or (key == 'reference_text' and request.engine.mode != 'hifi')):
                value = None
            if key == 'reference_audio' and value:
                value = str(files.resolve(value))
            if config.tts == 'edge' and key in ('voice_rate', 'voice_volume', 'voice_pitch'):
                value = f'{value:+}{"Hz" if key == "voice_pitch" else "%"}'
            setattr(config, target, value)
        for key in ('allow_role_text_override', 'allow_role_title_mismatch', 'allow_role_fallback',
                    'role_quality_enabled', 'role_quality_max_rate', 'audio_core_enabled', 'audio_core_repair'):
            setattr(config, key, getattr(request, key))
        config.role_script = project
        config.language = getattr(config, 'language', None) or 'zh-CN'
        if request.voice_profile_id or request.voice_profile_version:
            if project:
                raise ServiceError('voice_profile_scope', '角色项目请逐个人物绑定声音卡；全局声音卡用于普通朗读。')
            from .portable_voices import PortableVoices
            config._portable_params, config.portable_voice_snapshot = PortableVoices(output_root).resolve(
                request.voice_profile_id, request.voice_profile_version, config.tts, config.model_name)
            if config.output_format not in ('mp3', 'wav', 'flac'):
                raise ServiceError('voice_profile_format', '声音卡朗读请使用 MP3/WAV/FLAC 格式。')
        if project:
            from audiobook_generator.role_script.deepseek_splitter import detect_role_script_language
            config.language = 'en-US' if detect_role_script_language(project) == 'en' else 'zh-CN'
        config.role_quality_enabled = bool(project) and request.role_quality_enabled and not request.audio_core_enabled
        if request.audio_core_enabled:
            from audiobook_generator.ui.audio_quality import apply_local_quality_defaults, apply_quality_settings
            apply_local_quality_defaults(config)
            apply_quality_settings(config, files.resolve(request.audio_core_settings_file) if request.audio_core_settings_file else None)
            if request.audio_core_casting_file:
                config.audio_core_casting = str(files.resolve(request.audio_core_casting_file))
            config.worker_count = 1
        configs.append(config)
    return configs
