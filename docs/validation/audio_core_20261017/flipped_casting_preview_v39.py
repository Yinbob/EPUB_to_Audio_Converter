"""采用已确认的Bryce A，准备原文选角试听；整章保持未合成。"""
import argparse
import hashlib
import json
import sys
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
BASE = ROOT / 'audiobook_output/flipped_chapter_pilot_20261017'
OUTPUT = ROOT / 'audiobook_output/flipped_casting_preview_20261017'
REVIEW = ROOT / 'listening_review/flipped_casting_preview_20261017'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def save(path, value, *, overwrite=False):
    if path.exists() and not overwrite:
        raise ValueError('拒绝覆盖已有文件：' + path.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def prepare():
    from audiobook_generator.audio_core.role_references import make_reference, load_reference
    from audiobook_generator.audio_core.store import fingerprint
    from audiobook_generator.tts_providers.mimo_voice import resolve_voice
    from audiobook_generator.role_script.loader import load_role_script
    from audiobook_generator.role_script.models import RoleDefinition
    from audiobook_generator.role_script.deepseek_splitter import role_script_to_dict
    from audiobook_generator.role_script.validator import validate_role_script
    from audiobook_generator.role_script.planner import build_synthesis_plans
    from audiobook_generator.audio_core.reading import build_reading_plan

    quality_path = ROOT / 'audiobook_output/mimo_bryce_candidates_20261017/quality.json'
    quality = read(quality_path)
    selected = [p for p in quality['probes'] if p['role_id'] == 'bryce_a']
    assert len(selected) == 3
    for p in selected:
        assert sha(Path(p['path'])) == p['audio_sha256']
        assert p['report']['metrics']['content_alignment']['error_rate'] == 0
        assert p['report']['metrics']['clipped_fraction'] == 0
    acceptance = {'schema_version': 'flipped-bryce-human-acceptance-v39', 'date': '2026-10-17',
        'source': 'explicit_user_reply', 'user_reply': 'A适合，A组三条一致且内容完整',
        'quality_source': str(quality_path), 'quality_sha256': sha(quality_path),
        'accepted_candidate': 'bryce_a', 'bound_book_role': 'narrator',
        'bound_identity': 'Bryce narration and own dialogue in chapter 05',
        'samples': [{'sample_id': p['sample_id'], 'audio_sha256': p['audio_sha256'],
            'content_complete': True, 'same_identity_consistent': True, 'bryce_suitable': True}
            for p in selected], 'candidate_b_judged': False, 'machine_reports_unchanged': True}
    save(ROOT / 'listening_review/flipped_bryce_candidates_20261017/human_acceptance_v39.json', acceptance)
    first = selected[0]
    review = {'sample_id': first['sample_id'], 'role_id': 'narrator',
        'voice_version': first['profile']['voice_version'], 'audio_sha256': first['audio_sha256'],
        'content_complete': True, 'signal_acceptable': True, 'identity_accepted': True,
        'notes': '用户选择A并确认组三条一致、内容完整；结合试听提问中的异常核对及信号检查通过，接纳首条作Bryce参考。'
                 '仅将同一Bryce候选身份绑定到本章narrator角色；不表示全书视角都为Bryce。',
        'human_acceptance_path': str(ROOT / 'listening_review/flipped_bryce_candidates_20261017/human_acceptance_v39.json')}
    key, record = make_reference('narrator', first['profile'], 'en', first['request'], first['path'],
                                 first['report']['metrics'], review)
    references = BASE / 'role_references.bryce_a.v39.json'
    save(references, {'schema_version': 'mimo-role-references-v1', 'references': {key: record}})
    config = SimpleNamespace(model_name='mimo-v2.5-tts', language='en-US', stream=False, output_format='wav')
    assert resolve_voice(config, first['profile']) == first['request']
    assert load_reference(references, 'narrator', first['profile'], 'en', first['request']) is not None
    script, report = load_role_script(BASE / 'chapter_05.reading.confirmed_unvoiced.json')
    assert report.ok
    params = {'narrator': first['profile']}
    for role, voice in [('bryce_father', 'Dean'), ('juli', 'Chloe'), ('bryce_mother', 'Mia')]:
        p = {'voice_mode': 'preset', 'voice': voice, 'voice_language': 'en',
             'instructions': 'Read in clear, natural American English at a steady, moderate audiobook pace. '
                             'Keep the same voice identity and do not overact.'}
        p['voice_version'] = fingerprint(p)
        p['voice_profile_id'] = 'flipped_' + role + '_preset_candidate_v1'
        params[role] = p
    p = {'voice_mode': 'design', 'voice_language': 'en',
        'voice_description': 'A youthful male voice in the teenage range, bright and slightly nasal in the upper middle register, '
            'with a slender, reedy timbre and lively, crisp consonants. Neutral American English accent. '
            'This is one representative student voice, with an easy conversational sound and a stable identity.',
        'instructions': 'Use a steady, moderate speaking pace and a natural conversational delivery. '
            'Read as one speaker. Keep the fixed identity consistent across lines, without theatrical shouting.'}
    p['voice_version'] = fingerprint(p)
    p['voice_profile_id'] = 'flipped_classmates_design_candidate_v1'
    params['classmates'] = p
    proposal = replace(script, roles={r: RoleDefinition(v.display_name, params[r], v.gender)
                                     for r, v in script.roles.items()},
        entities={r: replace(v, voice_profile_id=params[r]['voice_profile_id'], voice_locked=r == 'narrator')
                  for r, v in script.entities.items()})
    source = read(BASE / 'source_chapters.json')
    chapters = [(c['title'], c['text']) for c in source['chapters']]
    checked = validate_role_script(proposal, expected_book_sha256=source['book_sha256'], chapters=chapters,
                                   chapter_start=5, chapter_end=5)
    assert checked.ok, checked.report.to_dict()
    proposal_path = BASE / 'chapter_05.voices.proposed.v39.json'
    save(proposal_path, role_script_to_dict(proposal))
    reloaded, report = load_role_script(proposal_path)
    assert report.ok and reloaded == proposal
    plans = build_synthesis_plans(proposal, chapters, expected_book_sha256=source['book_sha256'],
        provider='openai', chapter_start=5, chapter_end=5, output_format='wav')
    assert plans.ok, plans.report.to_dict()
    quotes = {q['quote_id']: q for q in read(BASE / 'local_role_proposal.json')['quotes']}
    scenes = []
    for label, left, right in [('P01', 'Q02', 'Q04'), ('P02', 'Q19', 'Q22')]:
        start, end = quotes[left]['source_start'], quotes[right]['source_end']
        units = [u for u in plans.plans[0].units if start <= u.source_span.start and u.source_span.end <= end]
        assert ''.join(u.text for u in units) == chapters[4][1][start:end]
        scene = replace(plans.plans[0], units=tuple(replace(u, pause_after_ms=0 if i == len(units)-1
                                                         else u.pause_after_ms) for i, u in enumerate(units)))
        scenes.append({'sample_id': label, 'chapter_index': 5, 'source_start': start, 'source_end': end,
                       'unit_ids': [u.unit_id for u in scene.units],
                       'planned_chunks': len(build_reading_plan(scene.units, language='en')),
                       'text': chapters[4][1][start:end]})
    group = [{'sample_id': f'C{i}', 'quote_id': qid, 'text': quotes[qid]['text'],
              'source_start': quotes[qid]['source_start'], 'source_end': quotes[qid]['source_end']}
             for i, qid in enumerate(('Q32', 'Q33', 'Q34'), 1)]
    count = sum(s['planned_chunks'] for s in scenes) + len(group)
    assert count <= 15
    save(BASE / 'casting_preview_plan_v39.json', {'schema_version': 'flipped-casting-preview-plan-v39',
        'book_sha256': source['book_sha256'], 'script': str(proposal_path), 'script_sha256': sha(proposal_path),
        'references': str(references), 'scenes': scenes, 'classmates_probes': group, 'max_requests': count,
        'planned_characters': sum(len(s['text']) for s in scenes+group), 'auto_repair': False,
        'whole_chapter_synthesis': False, 'role_fit_status': {'narrator': 'human_confirmed',
            'bryce_father': 'proposed', 'juli': 'proposed', 'bryce_mother': 'proposed', 'classmates': 'proposed'},
        'classmates_representation': '同一代表声线朗读三处群体引语，不虚构有姓名的个体或多人合唱',
        'scope': 'chapter_05_original_excerpts_and_three_original_quote_probes'})
    plan = read(BASE / 'execution_plan.json')
    plan.update(status='bryce_a_confirmed_pending_other_role_preview', bryce_voice='candidate_A',
        bryce_reference=str(references), provisional_voice_script=str(proposal_path),
        full_chapter_voice_assignment_confirmed=False)
    save(BASE / 'execution_plan.json', plan, overwrite=True)
    print(f'准备完成：Bryce A已固定；2处原文节选+3句同学群体，最多{count}次请求。', flush=True)


def render():
    from audiobook_generator.role_script.loader import load_role_script
    from audiobook_generator.role_script.planner import build_synthesis_plans
    from audiobook_generator.role_script.models import VoiceProfile
    from audiobook_generator.config.general_config import GeneralConfig
    from audiobook_generator.tts_providers.openai_tts_provider import OpenAITTSProvider
    from audiobook_generator.audio_core.store import ArtifactStore
    from audiobook_generator.audio_core.models import ResourceLimits, CoreOptions
    from audiobook_generator.audio_core.pipeline import run_chapter
    from audiobook_generator.core.audio_tags import AudioTags

    setup = read(BASE / 'casting_preview_plan_v39.json')
    assert sha(Path(setup['script'])) == setup['script_sha256']
    if OUTPUT.exists():
        raise ValueError('已有试听运行目录，不重跑或追加隐式请求')
    script, report = load_role_script(setup['script'])
    assert report.ok
    source = read(BASE / 'source_chapters.json')
    assert sha(Path(source['book_path'])) == setup['book_sha256']
    chapters = [(c['title'], c['text']) for c in source['chapters']]
    planned = build_synthesis_plans(script, chapters, expected_book_sha256=source['book_sha256'],
        provider='openai', chapter_start=5, chapter_end=5, output_format='wav')
    assert planned.ok
    config = GeneralConfig(None)
    config.tts, config.language, config.output_format, config.stream = 'openai', 'en-US', 'wav', False
    provider = OpenAITTSProvider(config)
    OUTPUT.mkdir()
    manifest = {**setup, 'schema_version': 'flipped-casting-preview-v39', 'status': 'running',
                'generated_scenes': [], 'generated_classmates': [], 'request_ledgers': []}
    def persist():
        save(OUTPUT / 'manifest.json', manifest, overwrite=True)
    persist()
    try:
        # 与正式转换相同的书籍缓存位置；不同run保留独立报告，原始请求可复用。
        project = OUTPUT / '.audio_projects' / source['book_sha256']
        store = ArtifactStore(project)
        run = store.start_run(ResourceLimits(max_requests=3, max_repair_requests=0, max_seconds=360))
        manifest['request_ledgers'].append({'project': str(project), 'run_id': run})
        persist()
        role = script.roles['classmates']
        for probe in setup['classmates_probes']:
            path = provider.synthesize_observed_chunk(probe['text'], VoiceProfile('classmates', role.display_name,
                role.provider_params), store, run)
            manifest['generated_classmates'].append({**probe, 'path': path,
                'audio_sha256': sha(Path(path)), 'profile': role.provider_params,
                'request': provider.resolve_voice(role.provider_params), 'human_verified': False})
            persist()
        for scene in setup['scenes']:
            wanted = set(scene['unit_ids'])
            units = [u for u in planned.plans[0].units if u.unit_id in wanted]
            plan = replace(planned.plans[0], units=tuple(replace(u, pause_after_ms=0 if i==len(units)-1
                else u.pause_after_ms) for i,u in enumerate(units)))
            store = ArtifactStore(project)
            options = CoreOptions(language='en', chunk_chars=300, auto_repair=False,
                role_references=setup['references'], asr_model_dir=str(ROOT / '.audio_quality_models/SenseVoiceSmall'),
                speaker_model_dir=str(ROOT / '.audio_quality_models/ecapa'),
                limits=ResourceLimits(max_requests=scene['planned_chunks'], max_repair_requests=0, max_seconds=600))
            run = store.start_run(options.limits)
            manifest['request_ledgers'].append({'project': str(project), 'run_id': run})
            persist()
            audio = OUTPUT / (scene['sample_id'] + '.wav')
            print('开始原文节选 ' + scene['sample_id'], flush=True)
            result = run_chapter(plan, provider, audio, AudioTags('Diving Under excerpt '+scene['sample_id'],
                source['author'], source['title'], 5), project, options=options, run_id=run)
            manifest['generated_scenes'].append({**scene, 'path': str(audio), 'audio_sha256': sha(audio),
                'quality_status': result['quality_status'],
                'report': str(project / 'reports' / run / 'chapter_000005/quality.json')})
            persist()
        manifest['status'] = 'generated_pending_role_fit_and_scene_review'
    except Exception as exc:
        manifest.update(status='failed_partial_preserved', error_type=type(exc).__name__)
        raise
    finally:
        manifest['resources_by_run'] = [{**item, 'resources': ArtifactStore(item['project']).summary(item['run_id'])}
                                        for item in manifest['request_ledgers']]
        persist()
    print('原文选角试听生成完成；整章仍未合成。', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare', 'render'])
    args = parser.parse_args()
    prepare() if args.action == 'prepare' else render()
