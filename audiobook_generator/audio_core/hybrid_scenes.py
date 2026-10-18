"""人工核验声音后的小规模混合场景；不自动扩展为整书。"""
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
import json

from audiobook_generator.role_script.models import ChapterSynthesisPlan, SynthesisUnit, VoiceProfile
from audiobook_generator.role_script.validator import validate_role_script
from audiobook_generator.core.audio_tags import AudioTags
from .models import CoreOptions, ResourceLimits
from .pipeline import run_chapter
from .quality import QualityEvaluator
from .role_references import load_reference
from .store import ArtifactStore, fingerprint


def run_scenes(script, provider, references, output, *, asr_model=None, speaker_model=None, evaluator=None):
    if not validate_role_script(script).ok or script.provider != 'openai':
        raise ValueError('混合场景需要校验通过的 MiMo 剧本')
    if len(script.chapters) > 3 or not script.chapters:
        raise ValueError('首轮仅允许一至三个自编测试场景')
    params = {r: v.provider_params for r, v in script.roles.items()}
    if not {'preset', 'design'} <= {v.get('voice_mode', 'preset') for v in params.values()}:
        raise ValueError('混合场景应同时包含内置和描述角色')
    for role, profile in params.items():
        if profile.get('voice_mode') in {'design', 'clone'}:
            ref = load_reference(references, role, profile, profile['voice_language'], provider.resolve_voice(profile))
            if ref is None:
                raise ValueError(f'描述角色尚无对应声音版本的人工固定参考：{role}')
    root = Path(output).resolve()
    if root.exists():
        raise ValueError('混合场景目录已存在，禁止无意重复线上请求')
    root.mkdir(parents=True)
    plans = []
    for chapter in script.chapters:
        units = tuple(SynthesisUnit(f'{chapter.chapter_index}:{i}:{seg.role_id}', chapter.chapter_index,
            chapter.title, i, len(chapter.segments), seg.role_id, script.roles[seg.role_id].display_name,
            seg.text, VoiceProfile(seg.role_id, script.roles[seg.role_id].display_name, dict(params[seg.role_id]), tone=seg.tone),
            tone=seg.tone, pause_after_ms=seg.pause_after_ms if seg.pause_after_ms is not None else script.default_pause_after_ms)
            for i, seg in enumerate(chapter.segments, 1))
        plans.append(ChapterSynthesisPlan(chapter.chapter_index, chapter.title, units, 'wav', 'openai'))
    from .reading import build_reading_plan
    request_count = sum(len(build_reading_plan(plan.units, language='en', chunk_chars=300)) for plan in plans)
    if request_count > 16:
        raise ValueError('首轮场景超过16块，请缩短自编材料')
    options = CoreOptions(language='en', role_references=str(Path(references).resolve()), auto_repair=False,
        asr_model_dir=asr_model, speaker_model_dir=speaker_model,
        limits=ResourceLimits(max_requests=request_count, max_repair_requests=0, max_seconds=900))
    store = ArtifactStore(root/'project')
    run = store.start_run(options.limits)
    evaluator = evaluator or QualityEvaluator(options, store=store)
    manifest = {'schema_version': 'mimo-hybrid-scenes-v1', 'script_sha256': fingerprint(asdict(script)),
        'scope': 'curated_test_scenes_not_whole_book', 'run_id': run, 'chapters': [],
        'max_requests': request_count, 'auto_repair': False, 'status': 'running',
        'references': str(Path(references).resolve())}
    def persist():
        manifest['resources'] = store.summary(run)
        target = root/'manifest.json'
        temp = target.with_suffix('.tmp')
        temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False))
        temp.replace(target)
    persist()
    try:
        for plan in plans:
            path = root / f'chapter_{plan.chapter_index:02d}_full.wav'
            result = run_chapter(plan, provider, path, AudioTags(plan.title, 'Original test material', 'Hybrid voice pilot', plan.chapter_index),
                root/'project', options=options, run_id=run, evaluator=evaluator)
            manifest['chapters'].append({'chapter_index': plan.chapter_index, 'path': str(path),
                'quality_status': result['quality_status'],
                'report': str(root/'project'/'reports'/run/f'chapter_{plan.chapter_index:06d}'/'quality.json')})
            persist()
        manifest['status'] = 'generated_pending_scene_review'
    except Exception as exc:
        manifest.update(status='failed_partial_preserved', error_type=type(exc).__name__)
        raise
    finally:
        persist()
    return manifest
