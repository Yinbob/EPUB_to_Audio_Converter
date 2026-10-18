"""确认选角后仅合成已授权第一章，复用14条缓存，不自动追加修复。"""
import argparse
from dataclasses import replace
from pathlib import Path
from flipped_casting_preview_v39 import ROOT, BASE, OUTPUT, REVIEW, read, save, sha
from flipped_casting_recovery_v40 import context

SCRIPT = BASE / 'chapter_05.voices.confirmed.v41.json'
REFERENCES = BASE / 'role_references.confirmed.v41.json'
MANIFEST = BASE / 'whole_chapter_run_v41.json'


def prepare():
    from audiobook_generator.audio_core.role_references import make_reference, load_reference
    from audiobook_generator.role_script.loader import load_role_script
    from audiobook_generator.role_script.deepseek_splitter import role_script_to_dict
    from audiobook_generator.audio_core.reading import build_reading_plan, nonspoken_source_units
    from audiobook_generator.tts_providers.mimo_voice import resolve_voice
    from types import SimpleNamespace
    setup, source, plan = context()
    preview = read(REVIEW / 'review_manifest.json')
    loudness = read(REVIEW / 'loudness_comparison/manifest.json')
    for item in preview['items']:
        assert sha(REVIEW / item['path']) == item['audio_sha256']
    for scene in loudness['scenes']:
        assert sha(Path(scene['path'])) == scene['audio_sha256']
    acceptance = {'version': 'flipped-preview-human-acceptance-v41', 'date': '2026-10-17',
        'source': 'explicit_user_reply', 'scene_reply': 'P01/P02均正常，角色合适',
        'classmates_reply': 'C1–C3均正常、一致且可区分',
        'heard_scenes': [{'sample_id': s['sample_id'], 'path': s['path'], 'audio_sha256': s['audio_sha256']}
                         for s in loudness['scenes']],
        'heard_classmates': [{'sample_id': i['sample_id'], 'audio_sha256': i['audio_sha256']}
                            for i in preview['items'] if i['sample_id'] in ('C1', 'C2', 'C3')],
        'scene_content_accepted': True, 'role_fit_accepted': True, 'bryce_matches_A': True,
        'scene_stitching_and_loudness_accepted': True, 'classmates_content_and_consistency_accepted': True,
        'classmates_distinguishable_from_bryce': True, 'original_raw_loudness_not_judged': True,
        'scope': 'these_preview_audio_only_not_unheard_whole_chapter', 'machine_reports_unchanged': True}
    save(REVIEW / 'human_acceptance_v41.json', acceptance)
    refs = read(Path(setup['references']))
    samples = {}
    for scene in preview['scenes']:
        report = read(Path(scene['report_path']))
        for chunk in report['chunks']:
            samples.setdefault(chunk['chunk']['role_id'], chunk)
    group = read(OUTPUT / 'classmates_quality_v40.json')['probes'][2]
    samples['classmates'] = {'chunk': {'role_id': 'classmates', 'profile': group['profile']},
        'rendered_path': group['path'], 'report': group['report'], 'voice_reference_request': group['request']}
    for role in ('bryce_father', 'juli', 'bryce_mother', 'classmates'):
        item = samples[role]
        path, profile = item['rendered_path'], item['chunk']['profile']
        review = {'role_id': role, 'voice_version': profile['voice_version'], 'audio_sha256': sha(Path(path)),
            'content_complete': True, 'signal_acceptable': True, 'identity_accepted': True,
            'human_acceptance_path': str(REVIEW / 'human_acceptance_v41.json'),
            'notes': '用户确认两处响度对照节选角色适合、内容与声音正常；同学三句一致且可区分。'
                     '参考使用保留的原始声学片段；与对照版仅存在已核验的恒定衰减，不改变身份、内容或时长。'
                     '这不表示原始片段响度已被接受。机器ASR差异完整保留。'}
        key, record = make_reference(role, profile, 'en', item['voice_reference_request'], path,
                                     item['report']['metrics'], review)
        refs['references'][key] = record
    save(REFERENCES, refs)
    script, report = load_role_script(setup['script'])
    assert report.ok
    locked = replace(script, entities={k: replace(v, voice_locked=True) for k,v in script.entities.items()})
    assert script.roles == locked.roles and script.chapters == locked.chapters
    save(SCRIPT, role_script_to_dict(locked))
    restored, report = load_role_script(SCRIPT)
    assert report.ok and restored == locked
    config = SimpleNamespace(model_name='mimo-v2.5-tts', language='en-US', stream=False, output_format='wav')
    for role, definition in restored.roles.items():
        assert load_reference(REFERENCES, role, definition.provider_params, 'en',
                              resolve_voice(config, definition.provider_params)) is not None
    chunks = build_reading_plan(plan.units, language='en')
    assert len(chunks) == 100 and len(nonspoken_source_units(plan.units)) == 4
    cache = read(ROOT / 'docs/validation/audio_core_20261017/flipped_cache_v40.json')
    assert cache['cached_chunks_verified'] == 14
    save(MANIFEST, {'version': 'flipped-whole-chapter-v41', 'status': 'prepared',
        'book_sha256': source['book_sha256'], 'chapter_index': 5, 'other_chapters_allowed': False,
        'script': str(SCRIPT), 'script_sha256': sha(SCRIPT), 'references': str(REFERENCES),
        'references_sha256': sha(REFERENCES), 'planned_spoken_chunks': 100, 'source_characters': 14311,
        'tts_characters': 14307, 'expected_cached_chunks': 14, 'max_new_requests': 86,
        'auto_repair': False, 'sdk_retries': 0, 'human_acceptance': str(REVIEW / 'human_acceptance_v41.json'),
        'output_file': str(BASE / 'chapter_05_full.original.wav'),
        'project': str(OUTPUT / '.audio_projects' / source['book_sha256']),
        'whole_chapter_human_review': 'pending'})
    execution = read(BASE / 'execution_plan.json')
    execution.update(status='cast_confirmed_whole_chapter_prepared', full_chapter_voice_assignment_confirmed=True,
        confirmed_voice_script=str(SCRIPT), role_references=str(REFERENCES), planned_chunks=100,
        planned_boundaries=99, same_role_chunk_boundaries=sum(a.role_id==b.role_id for a,b in zip(chunks,chunks[1:])),
        role_change_boundaries=sum(a.role_id!=b.role_id for a,b in zip(chunks,chunks[1:])),
        casting_preview_actual_tts_requests=14, casting_preview_actual_characters=616)
    save(BASE / 'execution_plan.json', execution, overwrite=True)
    print('全部五个角色已固定；参数与原文不变。首章100块，拟复用14块、最多新增86次。', flush=True)


def render():
    from audiobook_generator.role_script.loader import load_role_script
    from audiobook_generator.role_script.planner import build_synthesis_plans
    from audiobook_generator.config.general_config import GeneralConfig
    from audiobook_generator.tts_providers.openai_tts_provider import OpenAITTSProvider
    from audiobook_generator.audio_core.models import CoreOptions, ResourceLimits
    from audiobook_generator.audio_core.pipeline import run_chapter
    from audiobook_generator.audio_core.reading import build_reading_plan
    from audiobook_generator.audio_core.store import ArtifactStore, fingerprint
    from audiobook_generator.core.audio_tags import AudioTags
    setup, source, _ = context()  # 再次核对第一章授权及书籍／初始剧本指纹。
    manifest = read(MANIFEST)
    assert manifest['status'] == 'prepared'
    assert sha(SCRIPT) == manifest['script_sha256'] and sha(REFERENCES) == manifest['references_sha256']
    assert not Path(manifest['output_file']).exists()
    script, report = load_role_script(SCRIPT)
    assert report.ok and all(v.voice_locked for v in script.entities.values())
    planned = build_synthesis_plans(script, [(c['title'],c['text']) for c in source['chapters']],
        expected_book_sha256=source['book_sha256'], provider='openai', chapter_start=5, chapter_end=5, output_format='wav')
    assert planned.ok and len(planned.plans) == 1
    plan = planned.plans[0]
    store = ArtifactStore(manifest['project'])
    config = GeneralConfig(None)
    config.tts,config.language,config.output_format,config.stream='openai','en-US','wav',False
    provider = OpenAITTSProvider(config)
    chunks = build_reading_plan(plan.units, language='en')
    hits = []
    for chunk in chunks:
        key = fingerprint({'adapter':'mimo-observed-v2','request':provider.resolve_voice(chunk.profile,tone=chunk.tone),
                           'endpoint':str(provider.client.base_url),'text':chunk.tts_text})
        if store.cached(key):
            hits.append({'chunk_id': chunk.chunk_id, 'path': store.cached(key), 'audio_sha256': sha(Path(store.cached(key)))})
    assert len(chunks)==100 and len(hits)==14
    options = CoreOptions(language='en', chunk_chars=300, auto_repair=False, role_references=str(REFERENCES),
        asr_model_dir=str(ROOT/'.audio_quality_models/SenseVoiceSmall'), speaker_model_dir=str(ROOT/'.audio_quality_models/ecapa'),
        limits=ResourceLimits(max_requests=86, max_repair_requests=0, max_seconds=3600))
    run = store.start_run(options.limits)
    manifest.update(status='running', run_id=run, cached_chunks=hits)
    save(MANIFEST,manifest,overwrite=True)
    execution=read(BASE/'execution_plan.json')
    execution.update(status='whole_chapter_running',whole_chapter_tts_started=True,whole_chapter_run_id=run)
    save(BASE/'execution_plan.json',execution,overwrite=True)
    try:
        result=run_chapter(plan,provider,manifest['output_file'],AudioTags('Diving Under',source['author'],source['title'],5),
            manifest['project'],options=options,run_id=run,
            progress=lambda *args: print('朗读进度',*args,flush=True))
        manifest.update(status='generated_pending_whole_chapter_review',audio_sha256=sha(Path(manifest['output_file'])),
            report=str(Path(manifest['project'])/'reports'/run/'chapter_000005/quality.json'),quality_status=result['quality_status'])
    except Exception as exc:
        manifest.update(status='failed_partial_preserved',error_type=type(exc).__name__)
        raise
    finally:
        manifest['resources']=store.summary(run)
        save(MANIFEST,manifest,overwrite=True)
        execution=read(BASE/'execution_plan.json')
        execution.update(status=manifest['status'],whole_chapter_manifest=str(MANIFEST),
            whole_chapter_resources=manifest['resources'])
        save(BASE/'execution_plan.json',execution,overwrite=True)
    print('第一章合成与自动检查完成；整章人工核验仍待完成。',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['prepare','render'])
    args=parser.parse_args()
    prepare() if args.action=='prepare' else render()
