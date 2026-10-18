"""首章Bryce克隆扩展：离线准备；render须另有绑定计划的明确参考上传授权。"""
import argparse
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from flipped_casting_preview_v39 import ROOT, BASE, read, save, sha
from audiobook_generator.audio_core.store import ArtifactStore, fingerprint
from audiobook_generator.audio_core.models import ResourceLimits
from audiobook_generator.tts_providers.mimo_voice import resolve_voice

OUT = BASE / 'bryce_clone_chapter_v44'
PLAN = OUT / 'plan.json'


def prepare():
    from audiobook_generator.role_script.loader import load_role_script
    from audiobook_generator.role_script.deepseek_splitter import role_script_to_dict
    from audiobook_generator.role_script.planner import build_synthesis_plans
    from audiobook_generator.audio_core.reading import build_reading_plan, nonspoken_source_units
    source = read(BASE / 'source_chapters.json')
    old_script = BASE / 'chapter_05.voices.confirmed.v41.json'
    script, report = load_role_script(old_script); assert report.ok
    pilot = read(BASE / 'r001_clone_probe_v42/manifest.json')
    acceptance = ROOT / 'listening_review/flipped_r001_clone_20261017/human_acceptance_v44.json'
    assert len(read(acceptance)['samples']) == 3
    assert sha(Path(pilot['reference_path'])) == pilot['reference_audio_sha256']
    params = {'voice_mode': 'clone', 'voice_language': 'en',
        'reference_audio_path': pilot['reference_path'], 'reference_audio_sha256': pilot['reference_audio_sha256'],
        'instructions': pilot['instructions'], 'voice_profile_id': 'flipped_bryce_r001_clone_v1',
        'voice_version': fingerprint({'reference': pilot['reference_audio_sha256'],
            'instructions': pilot['instructions'], 'model': pilot['model'], 'language': 'en'})}
    roles = dict(script.roles); roles['narrator'] = replace(roles['narrator'], provider_params=params)
    entities = dict(script.entities)
    entities['narrator'] = replace(entities['narrator'], voice_profile_id=params['voice_profile_id'], voice_locked=True)
    proposed = replace(script, roles=roles, entities=entities)
    assert proposed.chapters == script.chapters
    draft = OUT / 'chapter_05.bryce_clone.proposed.json'
    save(draft, role_script_to_dict(proposed))
    restored, check = load_role_script(draft); assert check.ok and restored == proposed
    chapters = [(x['title'], x['text']) for x in source['chapters']]
    plans = build_synthesis_plans(restored, chapters, expected_book_sha256=source['book_sha256'],
        provider='openai', chapter_start=5, chapter_end=5, output_format='wav')
    assert plans.ok and len(plans.plans) == 1
    chunks = build_reading_plan(plans.plans[0].units, language='en')
    assert len(chunks) == 100 and len(nonspoken_source_units(plans.plans[0].units)) == 4
    original = read(ROOT / 'listening_review/flipped_full_chapter_20261017/review_manifest.json')
    local = read(BASE / 'accepted_local_revision_v44/manifest.json')
    # 其他角色仅使用本次已保存的局部修复版本；不重复生成或变换。
    replacements = {x['sample_id']: x['output_path'] for x in local['operations'] if x['sample_id'].startswith('R')}
    config = SimpleNamespace(model_name='mimo-v2.5-tts', language='en-US', stream=False, output_format='wav')
    route = resolve_voice(config, params)
    assert route['model'] == pilot['model'] and route['instructions'] == pilot['instructions']
    records = []
    for chunk, old in zip(chunks, original['items']):
        assert (chunk.chunk_id, chunk.tts_text, chunk.role_id, chunk.source_span) == (
            old['chunk_id'], old['text'], old['role_id'], old['source_span'])
        if chunk.role_id != 'narrator':
            path = Path(replacements.get(old['sample_id'], old['path']))
            records.append({'sample_id': old['sample_id'], 'chunk_id': chunk.chunk_id,
                'role_id': chunk.role_id, 'operation': 'preserve_existing_accepted_revision_audio',
                'path': str(path), 'audio_sha256': sha(path), 'source_span': chunk.source_span})
            continue
        assert chunk.tone is None
        cached = next((p for p in pilot['samples'] if p['source_sample_id'] == old['sample_id']), None)
        row = {'sample_id': old['sample_id'], 'chunk_id': chunk.chunk_id, 'role_id': chunk.role_id,
            'text': chunk.tts_text, 'source_span': chunk.source_span, 'profile': params, 'request': route}
        if cached:
            assert cached['text'] == chunk.tts_text and cached['route']['model'] == route['model']
            assert cached['route']['instructions'] == route['instructions']
            assert cached['route']['reference_audio_sha256'] == route['reference_audio_sha256']
            path = Path(cached['path']); assert sha(path) == cached['audio_sha256']
            row.update(operation='reuse_human_accepted_clone_probe', path=str(path),
                audio_sha256=sha(path), origin_request_id=cached['request_id'])
        else:
            row['operation'] = 'new_clone_request'
        records.append(row)
    requested = [x for x in records if x['operation'] == 'new_clone_request']
    assert len(requested) == 67 and sum(len(x['text']) for x in requested) == 12925
    covered = sorted([(c.source_span['start'], c.source_span['end'], c.source_text) for c in chunks] +
        [(x['source_span']['start'], x['source_span']['end'], x['source_text']) for x in nonspoken_source_units(plans.plans[0].units)])
    cursor = 0; text = source['chapters'][4]['text']
    for a, b, value in covered:
        assert a == cursor and text[a:b] == value; cursor = b
    assert cursor == len(text) == 14311
    whole = read(BASE / 'whole_chapter_run_v41.json')
    save(PLAN, {'version': 'flipped-bryce-clone-expansion-v44', 'status': 'prepared_not_upload_authorized',
        'chapter_index': 5, 'chapter_title': source['chapters'][4]['title'],
        'book_sha256': source['book_sha256'], 'source_characters': len(text),
        'script': str(draft), 'script_sha256': sha(draft), 'original_script_sha256': sha(old_script),
        'reference_path': pilot['reference_path'], 'reference_sha256': pilot['reference_audio_sha256'],
        'project': whole['project'], 'endpoint': pilot['samples'][0]['route']['endpoint'],
        'max_new_requests': len(requested), 'new_text_characters': 12925,
        'reused_clone_probes': 2, 'preserved_other_role_blocks': 31,
        'auto_repair': False, 'sdk_retries': 0, 'other_chapters_allowed': False,
        'whole_chapter_overwrite': False, 'human_clone_acceptance': str(acceptance),
        'human_clone_acceptance_sha256': sha(acceptance), 'items': records})
    (OUT / 'README.md').write_text(f'# Bryce首章克隆扩展计划（尚未授权发送）\n\n'
        f'仅Diving Under，Bryce共69块：复用K01/K02对应的2块，最多67次新请求、12925正文字符；参考R001每次作为克隆音色条件上传。其余31块沿用已保存局部修复版本，原文及归属不变。\n\n'
        f'声音档案：[候选剧本]({draft})。逐块范围：[计划]({PLAN})。\n\n'
        '无自动追加修复或SDK重试，失败保留已完成样本；不发送其他章节，不覆盖整章原件。原3条试听授权不覆盖本计划。生成后的新声音接缝、响度与四处目标约1秒停顿须重新检查；旧试听结论不自动沿用。\n')
    print('计划已核验：100块原文与归属不变，67条新克隆／12925字符，2条复用，31条保留；尚未发送。')


def render():
    from audiobook_generator.config.general_config import GeneralConfig
    from audiobook_generator.tts_providers.openai_tts_provider import OpenAITTSProvider
    from audiobook_generator.role_script.models import VoiceProfile
    plan = read(PLAN)
    assert not (OUT / 'render_manifest.json').exists(), '已有运行不得隐式重试'
    consent = read(OUT / 'reference_upload_consent.json')
    assert consent['plan_sha256'] == sha(PLAN) and consent['reference_sha256'] == plan['reference_sha256']
    assert consent['chapter_index'] == 5 and not consent['other_chapters_allowed']
    assert consent['max_requests'] == 67 and consent['source'] == 'explicit_user_reply' and consent['user_reply']
    assert sha(Path(plan['reference_path'])) == plan['reference_sha256']
    assert sha(Path(plan['script'])) == plan['script_sha256']
    assert sha(Path(plan['human_clone_acceptance'])) == plan['human_clone_acceptance_sha256']
    config = GeneralConfig(None); config.voice_name='mimo_default'; config.language='en-US'
    config.stream=False; config.output_format='wav'
    provider = OpenAITTSProvider(config)
    assert str(provider.client.base_url) == plan['endpoint']
    store = ArtifactStore(plan['project'])
    run = store.start_run(ResourceLimits(max_requests=67, max_repair_requests=0, max_seconds=3600))
    result = {'version': 'flipped-bryce-clone-render-v44', 'status': 'running', 'run_id': run,
        'plan_sha256': sha(PLAN), 'samples': [], 'whole_chapter_replaced': False}
    save(OUT / 'render_manifest.json', result)
    try:
        for item in plan['items']:
            if item['operation'] == 'new_clone_request':
                profile = VoiceProfile('narrator', 'Bryce', item['profile'])
                assert provider.resolve_voice(item['profile']) == item['request']
                path = provider.synthesize_observed_chunk(item['text'], profile, store, run)
            else:
                path = item['path']; assert sha(Path(path)) == item['audio_sha256']
            result['samples'].append({**item, 'path': str(path), 'audio_sha256': sha(Path(path))})
            save(OUT / 'render_manifest.json', result, overwrite=True)
        result['status'] = 'generated_pending_assembly_quality_and_human_review'
    except Exception as exc:
        result.update(status='failed_partial_preserved', error_type=type(exc).__name__)
        raise
    finally:
        result['resources'] = store.summary(run)
        save(OUT / 'render_manifest.json', result, overwrite=True)
    print('候选块已保存，仍须组装与质量核验；原整章未覆盖。')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('action', choices=['prepare', 'render'])
    {'prepare': prepare, 'render': render}[parser.parse_args().action]()
