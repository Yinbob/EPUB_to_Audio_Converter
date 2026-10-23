"""spawn 子进程入口；推理和核心模块只在子进程中导入。"""
import logging
import os
import shutil
from pathlib import Path
from .common import atomic_json


class BatchConversionError(RuntimeError):
    def __init__(self, message, result):
        super().__init__(message)
        self.result = result


def preview_book(config, log):
    """只解析选定章节；不构造 Provider，也不读取 API 密钥。"""
    from audiobook_generator.book_parsers.base_book_parser import get_book_parser
    from audiobook_generator.utils.filename_sanitizer import make_safe_filename
    parser = get_book_parser(config)
    chapters = [(title, text) for title, text in parser.get_chapters(
        '   ' if config.tts in ('openai', 'chatterbox', 'voxcpm') else ' @BRK#') if text.strip()]
    start = config.chapter_start
    end = len(chapters) if config.chapter_end == -1 else config.chapter_end
    if not 1 <= start <= end <= len(chapters):
        raise ValueError(f'章节范围 {start}～{end} 超出目录（共 {len(chapters)} 章）。')
    from .provenance import write_sources, finalize
    if write_sources(parser, chapters, config):
        finalize(config.output_folder, status='parsed')
    log.info('Chapters count: %s', len(chapters))
    log.info('Converting chapters from %s to %s.', start, end)
    summaries = []
    for index, (title, text) in enumerate(chapters[start - 1:end], start):
        log.info('第 %s 章 %s · %s 字符', index, title, len(text))
        summaries.append({'index': index, 'title': title, 'characters': len(text)})
        if config.output_text:
            output = Path(config.output_folder)
            output.mkdir(parents=True, exist_ok=True)
            name = make_safe_filename(title=title, idx=index, output_dir=str(output),
                                      ext='.txt', collision_check=False)
            (output / name).write_text(text, encoding='utf-8')
    return summaries


def run_task(payload, result_path, log_path, ready):
    os.setsid()
    ready.set()
    stream = open(log_path, 'a', encoding='utf-8', buffering=1)
    # 第三方 print 同样进入任务日志；服务端读取时再次脱敏。
    import sys
    sys.stdout = sys.stderr = stream
    sys.stdin = open(os.devnull, 'r')
    logging.basicConfig(level=logging.INFO, stream=stream, force=True,
                        format='%(asctime)s - %(levelname)s - %(message)s')
    log = logging.getLogger('studio.task')
    try:
        from audiobook_generator.role_script.split_control import SplitControl, split_control_scope
        control = SplitControl(report=lambda *a, **k: log.info('%s', k.get('desc', a)))
        control.resumable = payload['kind'] in ('split', 'casting_analyze', 'casting_draft', 'research_analyze', 'research_reanalyze')
        from audiobook_generator.role_script.context_budget import checkpoint_scope
        import hashlib
        cfg = payload['configs'][0]
        from .settings import credentials
        endpoint = credentials('deepseek')
        identity = hashlib.sha256((endpoint.get('base_url', '') + endpoint.get('model', '')).encode()).hexdigest()
        checkpoint = Path(payload.get('root', cfg.output_folder)) / '.split_checkpoints' / identity
        with split_control_scope(control), checkpoint_scope(checkpoint):
            result = execute(payload, log, result_path)
        atomic_json(result_path, {'ok': True, 'result': result or {}})
    except BaseException as exc:
        log.exception('任务失败')
        atomic_json(result_path, {'ok': False, 'error': str(exc), 'result': getattr(exc, 'result', {})})
    finally:
        stream.flush()


def execute(payload, log, result_path):
    kind = payload['kind']
    configs = payload['configs']
    work = Path(result_path).parent
    if kind in ('generate', 'research_regenerate'):
        from audiobook_generator.core.audiobook_generator import AudiobookGenerator
        from pydub import AudioSegment
        AudioSegment.converter = shutil.which("ffmpeg") or next((p for p in ("/opt/homebrew/bin/ffmpeg", "/usr/bin/ffmpeg", "/usr/local/bin/ffmpeg") if Path(p).is_file()), "ffmpeg")
        total, books, failures = len(configs), [], []
        for index, cfg in enumerate(configs, 1):
            name = getattr(cfg, 'source_name', None) or Path(cfg.input_file).name
            log.info('📚 [%s/%s] 开始转换: %s', index, total, name)
            entry = {'name': name, 'output_dir': cfg.output_folder}
            try:
                if cfg.preview:
                    entry['chapters'] = preview_book(cfg, log)
                    log.info('📋 [%s/%s] 预解析完成（未生成音频）: %s', index, total, name)
                else:
                    cfg.log_file = work / 'EtA_task.log'
                    logging.getLogger().setLevel(cfg.log)
                    if AudiobookGenerator(cfg).run() is not True:
                        raise RuntimeError('转换未成功完成，请查看章节错误日志。')
                    log.info('✅ [%s/%s] 完成: %s', index, total, name)
                entry['status'] = 'succeeded'
            except Exception as exc:
                entry.update(status='failed', error=str(exc))
                failures.append(name)
                log.exception('❌ [%s/%s] 转换失败: %s；继续处理后续书籍。', index, total, name)
            books.append(entry)
        result = {'output_dirs': [cfg.output_folder for cfg in configs], 'books': books}
        if failures:
            message = f'批量处理结束：{total - len(failures)} 本成功，{len(failures)} 本失败（' + '、'.join(failures) + '）。请查看日志。'
            log.error(message)
            raise BatchConversionError(message, result)
        log.info('🎉 全部处理完毕！共 %s 本书', total)
        return result
    cfg = configs[0]
    script = payload.get('script')
    if kind in ('research_analyze', 'research_reanalyze'):
        from audiobook_generator.role_script.research_analysis import analyze
        from .settings import credentials
        cred = credentials('deepseek')
        return {'research_proposal': analyze(payload['research_state'], payload['chapters'],
            api_key=cred['api_key'], base_url=cred['base_url'], model=cred['model'],
            target_ids=payload.get('segment_ids'), progress=lambda message: log.info('%s', message))}
    if kind == 'voice_clone':
        from .minimax_clone import clone
        from .settings import credentials
        clone(payload['reference_path'], payload['clone_voice_id'],
              api_key=credentials('minimax')['api_key'], root=payload['root'], log=log)
    if kind == 'split':
        from audiobook_generator.role_script.v2_generation import generate_v2_for_book
        from audiobook_generator.role_script.deepseek_splitter import role_script_to_dict
        from .settings import credentials
        cred = credentials('deepseek')
        result = generate_v2_for_book(payload['chapters'], cfg.chapter_start, cfg.chapter_end,
            cfg.tts, payload['catalog']['book_sha256'], cred['api_key'], cred['base_url'], cred['model'],
            parser_fingerprint=payload['catalog']['parser_fingerprint'], previous=script,
            index_full_book=payload.get('full_book', False), progress=lambda message: log.info('%s', message))
        return {'script': role_script_to_dict(result)}
    if kind in ('casting_analyze', 'casting_draft'):
        from audiobook_generator.ui.book_casting import BookCasting, load_bank, draft_rows
        from .settings import credentials
        cred = credentials('deepseek')
        controller = BookCasting(payload['root'], payload['chapters'], payload['catalog']['parser_fingerprint'],
                                 script, source_revision=str(payload['revision']))
        if kind == 'casting_analyze':
            return {'coverage': controller.analyze(api_key=cred['api_key'], base_url=cred['base_url'],
                       model=cred['model'], progress=lambda *a, **k: log.info('%s', k.get('desc', a)))}
        from openai import OpenAI
        bank = load_bank(payload['bank_path'], payload['language'])
        draft = controller.make_draft(bank, payload['language'],
                    client=OpenAI(api_key=cred['api_key'], base_url=cred['base_url']), model=cred['model'],
                    progress=lambda *a, **k: log.info('%s', k.get('desc', a)))
        return {'draft_id': draft['draft_id'], 'rows': draft_rows(draft)}
    from audiobook_generator.tts_providers.base_tts_provider import get_tts_provider
    from audiobook_generator.core.audio_tags import AudioTags
    from audiobook_generator.role_script.models import VoiceProfile
    if script:
        from audiobook_generator.role_script.deepseek_splitter import detect_role_script_language
        cfg.language = 'en-US' if detect_role_script_language(script) == 'en' else 'zh-CN'
    if kind == 'calibrate':
        cfg.output_format = 'wav'
    provider = get_tts_provider(cfg)
    text = payload['text'].strip()
    if not text:
        raise ValueError('请输入试听文本。')
    if kind == 'calibrate':
        from audiobook_generator.role_script.pace_calibration import calibrated_speeds
        from .projects import encode
        from dataclasses import replace
        if cfg.tts != 'openai' or not 20 <= len(text) <= 400:
            raise ValueError('语速校准仅适用于 MiMo，请输入 20～400 字试听文本。')
        durations, speeds = {}, {}
        for role_id, role in script.roles.items():
            profile = VoiceProfile(role_id, role.display_name, dict(role.provider_params))
            artifact = provider.synthesize_segment(text, profile, str(work / role_id), None)
            from pydub import AudioSegment
            durations[role_id] = len(AudioSegment.from_file(artifact.path))
            speeds[role_id] = role.provider_params.get('speed', 1)
        baseline = 'narrator' if 'narrator' in durations else next(iter(durations))
        calibrated, limited = calibrated_speeds(durations, baseline, speeds[baseline])
        roles = {key: replace(role, provider_params={**role.provider_params, 'speed': calibrated[key]})
                 for key, role in script.roles.items()}
        return {'script': encode(replace(script, roles=roles)),
                'calibration': {'baseline': baseline, 'durations_ms': durations, 'speeds': calibrated, 'limited': limited}}
    if script and payload.get('role_id'):
        role = script.roles[payload['role_id']]
        profile = VoiceProfile(payload['role_id'], role.display_name, dict(role.provider_params))
        artifact = provider.synthesize_segment(text, profile, str(work / 'preview'), None)
        from audiobook_generator.role_script.audio_pipeline import render_role_preview
        artifact = render_role_preview(artifact, profile, cfg.tts, str(work / 'preview_processed.wav'))
        return {'audio_path': artifact.path}
    if cfg.tts in ('openai', 'minimax'):
        from audiobook_generator.role_script.audio_pipeline import render_role_preview
        from audiobook_generator.role_script.planner import build_default_provider_params
        profile = VoiceProfile('narrator', '旁白', build_default_provider_params(cfg.tts, cfg))
        artifact = provider.synthesize_segment(text, profile, str(work / 'preview'), None)
        artifact = render_role_preview(artifact, profile, cfg.tts, str(work / 'preview_processed.wav'))
        return {'audio_path': artifact.path}
    if cfg.tts == 'voxcpm' and cfg.voxcpm_mode == 'design':
        from audiobook_generator.tts_providers.voxcpm_tts_provider import preview_voxcpm_preset_audio
        path = preview_voxcpm_preset_audio(cfg.voxcpm_voice, cfg.voxcpm_voice_dir, cfg.model_name,
                 cfg.voxcpm_device, cfg.voxcpm_cfg_value, cfg.voxcpm_inference_timesteps,
                 cfg.voxcpm_regenerate_voice, cfg.voxcpm_optimize)
        return {'audio_path': path}
    path = work / ('preview.' + provider.get_output_file_extension().lstrip('.'))
    provider.text_to_speech(text, str(path), AudioTags('试听', '', '有声书工坊', 1))
    return {'audio_path': str(path)}
