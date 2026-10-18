"""仅恢复已授权的第一章短试听；校验旧缓存后才允许最多五次新请求。"""
import argparse
from dataclasses import asdict, replace
from pathlib import Path
from flipped_casting_preview_v39 import ROOT, BASE, OUTPUT, read, save, sha


def context():
    from audiobook_generator.role_script.loader import load_role_script
    from audiobook_generator.role_script.planner import build_synthesis_plans
    setup = read(BASE / 'casting_preview_plan_v39.json')
    consent = read(BASE / 'mimo_transfer_consent_v40.json')
    assert consent['preview_plan_sha256'] == sha(BASE / 'casting_preview_plan_v39.json')
    assert consent['user_reply'] == '允许，仅该章用于MiMo语音合成'
    assert not consent['other_chapters_allowed'] and consent['chapter_index'] == 5
    assert sha(Path(setup['script'])) == setup['script_sha256']
    source = read(BASE / 'source_chapters.json')
    assert sha(Path(source['book_path'])) == setup['book_sha256'] == consent['book_sha256']
    script, report = load_role_script(setup['script'])
    assert report.ok
    chapters = [(c['title'], c['text']) for c in source['chapters']]
    plans = build_synthesis_plans(script, chapters, expected_book_sha256=source['book_sha256'],
        provider='openai', chapter_start=5, chapter_end=5, output_format='wav')
    assert plans.ok
    return setup, source, plans.plans[0]


def audit():
    from audiobook_generator.audio_core.reading import build_reading_plan, nonspoken_source_units, PLAN_VERSION
    from audiobook_generator.audio_core.store import ArtifactStore
    setup, source, plan = context()
    chunks = build_reading_plan(plan.units, language='en')
    structural = nonspoken_source_units(plan.units)
    assert len(chunks) == 100 and len(structural) == 4
    spans = sorted([(c.source_span['start'], c.source_span['end'], c.source_text) for c in chunks] +
                   [(u['source_span']['start'], u['source_span']['end'], u['source_text']) for u in structural])
    text = source['chapters'][4]['text']
    cursor = 0
    for start, end, value in spans:
        assert start == cursor and text[start:end] == value
        cursor = end
    assert cursor == len(text) and ''.join(s[2] for s in spans) == text
    manifest = read(OUTPUT / 'manifest.json')
    events = []
    for item in manifest['request_ledgers']:
        events.extend(ArtifactStore(item['project']).request_events(run_id=item['run_id']))
    assert len(events) == 9 and all(e['status'] == 'succeeded' for e in events)
    for e in events:
        assert ArtifactStore(manifest['request_ledgers'][0]['project']).sample_provenance(e['artifact'])['origin_status'] != 'unknown'
    for item in manifest['generated_scenes'] + manifest['generated_classmates']:
        assert sha(Path(item['path'])) == item['audio_sha256']
    save(ROOT / 'docs/validation/audio_core_20261017/flipped_whitespace_v40.json', {
        'reading_plan_version': PLAN_VERSION, 'source_characters': len(text), 'spoken_chunks': len(chunks),
        'nonspoken_source_units': structural, 'full_source_coverage_verified': True,
        'script_unchanged_sha256': setup['script_sha256'], 'existing_requests': len(events),
        'existing_characters': sum(e['characters'] for e in events), 'remaining_preview_max_requests': 5,
        'whole_chapter_synthesized': False})
    print('离线检查通过：100个朗读块+4个纯空白结构单元完整覆盖原文；9次已有请求保留。', flush=True)


def recover():
    from audiobook_generator.audio_core.models import CoreOptions, ResourceLimits
    from audiobook_generator.audio_core.pipeline import run_chapter
    from audiobook_generator.audio_core.reading import build_reading_plan
    from audiobook_generator.audio_core.store import ArtifactStore, fingerprint
    from audiobook_generator.config.general_config import GeneralConfig
    from audiobook_generator.tts_providers.openai_tts_provider import OpenAITTSProvider
    from audiobook_generator.core.audio_tags import AudioTags
    setup, source, full = context()
    manifest = read(OUTPUT / 'manifest.json')
    assert manifest['status'] == 'failed_partial_preserved'
    assert [s['sample_id'] for s in manifest['generated_scenes']] == ['P01']
    project = Path(manifest['request_ledgers'][0]['project'])
    store = ArtifactStore(project)
    previous = [event for item in manifest['request_ledgers'] for event in store.request_events(run_id=item['run_id'])]
    assert len(previous) == 9 and all(e['status'] == 'succeeded' for e in previous)
    # 完整校验九条缓存，损坏时停止，避免将补发误作复用。
    for event in previous:
        assert store.cached(event['request_key']) == event['artifact']
    for item in manifest['generated_scenes'] + manifest['generated_classmates']:
        assert sha(Path(item['path'])) == item['audio_sha256']
    save(OUTPUT / 'manifest.failed_snapshot_v40.json', manifest)
    scene = next(s for s in setup['scenes'] if s['sample_id'] == 'P02')
    units = [u for u in full.units if u.unit_id in scene['unit_ids']]
    plan = replace(full, units=tuple(replace(u, pause_after_ms=0 if i == len(units)-1 else u.pause_after_ms)
                                    for i, u in enumerate(units)))
    chunks = build_reading_plan(plan.units, language='en')
    assert len(chunks) == 6
    config = GeneralConfig(None)
    config.tts, config.language, config.output_format, config.stream = 'openai', 'en-US', 'wav', False
    provider = OpenAITTSProvider(config)
    cached = []
    for chunk in chunks:
        key = fingerprint({'adapter': 'mimo-observed-v2',
            'request': provider.resolve_voice(chunk.profile, tone=chunk.tone),
            'endpoint': str(provider.client.base_url), 'text': chunk.tts_text})
        cached.append(store.cached(key))
    assert sum(p is not None for p in cached) == 1 and cached[0] == previous[-1]['artifact']
    options = CoreOptions(language='en', chunk_chars=300, auto_repair=False,
        role_references=setup['references'], asr_model_dir=str(ROOT / '.audio_quality_models/SenseVoiceSmall'),
        speaker_model_dir=str(ROOT / '.audio_quality_models/ecapa'),
        limits=ResourceLimits(max_requests=5, max_repair_requests=0, max_seconds=600))
    run = store.start_run(options.limits)
    manifest['request_ledgers'].append({'project': str(project), 'run_id': run})
    manifest.update(status='resuming_remaining_five_only', recovery={'previous_manifest': str(OUTPUT / 'manifest.failed_snapshot_v40.json'),
        'reused_sample': cached[0], 'new_request_limit': 5, 'auto_repair': False})
    save(OUTPUT / 'manifest.json', manifest, overwrite=True)
    try:
        audio = OUTPUT / 'P02.wav'
        assert not audio.exists()
        result = run_chapter(plan, provider, audio, AudioTags('Diving Under excerpt P02', source['author'], source['title'], 5),
                             project, options=options, run_id=run)
        manifest['generated_scenes'].append({**scene, 'planned_chunks': 6, 'path': str(audio), 'audio_sha256': sha(audio),
            'quality_status': result['quality_status'], 'report': str(project / 'reports' / run / 'chapter_000005/quality.json')})
        manifest.update(status='generated_pending_role_fit_and_scene_review', effective_preview_requests=14,
                        effective_preview_characters=616, whole_chapter_synthesis=False)
    except Exception as exc:
        manifest.update(status='recovery_failed_partial_preserved', recovery_error_type=type(exc).__name__)
        raise
    finally:
        manifest['resources_by_run'] = [{**item, 'resources': store.summary(item['run_id'])} for item in manifest['request_ledgers']]
        save(OUTPUT / 'manifest.json', manifest, overwrite=True)
    print('P02恢复完成，原9次保留，仅新增5次请求。', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['audit', 'recover'])
    args = parser.parse_args()
    audit() if args.action == 'audit' else recover()
