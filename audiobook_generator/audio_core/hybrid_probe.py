"""固定六请求的 VoiceDesign 工程先导，与旧内置声音基线分开保存。"""
from __future__ import annotations
import hashlib
import html
import json
import shutil
from dataclasses import asdict
from pathlib import Path

from .models import CoreOptions, ReadingChunk, ResourceLimits
from .store import ArtifactStore, fingerprint
from audiobook_generator.role_script.models import VoiceProfile

PROMPTS = [
    'Morning sunlight fell across the quiet desk. She opened the old book and began to read.',
    'Do you remember where we agreed to meet? Please wait beside the bridge until I arrive.']


def run_probe(script, provider, output, roles):
    roles = list(roles)
    if len(roles) != 2 or len(set(roles)) != 2 or any(r not in script.roles for r in roles):
        raise ValueError('首轮先导需要恰好两个不同的描述角色')
    if any(script.roles[r].provider_params.get('voice_mode') != 'design'
           or script.roles[r].provider_params.get('voice_language') != 'en' for r in roles):
        raise ValueError('首轮先导仅接受已生成固定声音卡的英文描述角色')
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if (root / 'probes.json').exists() or (root / 'project').exists():
        raise ValueError('先导目录已有运行记录，禁止隐式重复六次请求；请查看既有清单')
    store = ArtifactStore(root / 'project')
    run = store.start_run(ResourceLimits(max_requests=6, max_seconds=600))
    manifest = {'schema_version': 'mimo-hybrid-probe-v1', 'language': 'en', 'run_id': run,
                'script_sha256': fingerprint(asdict(script)), 'probes': [], 'status': 'running',
                'research_status': 'engineering_pilot_not_listener_evidence'}
    def persist():
        manifest['resources'] = store.summary(run)
        target = root / 'probes.json'
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False))
        temporary.replace(target)
    persist()
    try:
        for role in roles:
            params = dict(script.roles[role].provider_params)
            profile = VoiceProfile(role, script.roles[role].display_name, params)
            route = provider.resolve_voice(params)
            for index in range(3):
                prompt_index = index if index < 2 else 0
                text = PROMPTS[prompt_index]
                path = provider.synthesize_observed_chunk(text, profile, store, run, resample=index == 2)
                manifest['probes'].append({'sample_id': f'{role}_{index + 1}', 'role_id': role,
                    'prompt_id': f'prompt_{prompt_index + 1}', 'independent_repeat': index == 2,
                    'text': text, 'path': path, 'profile': params, 'request': route,
                    'audio_sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                    'human_verified': False})
                persist()
        manifest['status'] = 'generated_pending_quality_and_human_review'
    except Exception as exc:
        manifest.update(status='failed_partial_preserved', error_type=type(exc).__name__)
        raise
    finally:
        persist()
    return manifest


def evaluate_probe(manifest_path, output, review_dir, *, asr_model, speaker_model, bank_path=None):
    import numpy as np
    from .quality import QualityEvaluator
    source = json.loads(Path(manifest_path).read_text())
    if source.get('schema_version') != 'mimo-hybrid-probe-v1' or len(source['probes']) != 6:
        raise ValueError('需要完整的六条混合声音探针')
    evaluator = QualityEvaluator(CoreOptions(language='en', asr_model_dir=asr_model,
        speaker_model_dir=speaker_model), store=ArtifactStore(Path(manifest_path).parent / 'project'))
    review = Path(review_dir).resolve()
    review.mkdir(parents=True, exist_ok=True)
    records, vectors, anchors, cells = [], {}, {}, []
    pending = []
    for sample in source['probes']:
        path = Path(sample['path'])
        if hashlib.sha256(path.read_bytes()).hexdigest() != sample['audio_sha256']:
            raise ValueError('原始探针音频指纹不符')
        chunk = ReadingChunk(chunk_id=sample['sample_id'], unit_id=sample['sample_id'], role_id=sample['role_id'],
            source_text=sample['text'], tts_text=sample['text'], source_start=0, source_end=len(sample['text']),
            profile=sample['profile'], language='en')
        report = evaluator.evaluate_chunk(chunk, str(path), anchor=anchors.get(sample['role_id']))
        # 仅先导诊断对比；未经人工核验的首条探针不会写入生产固定参考库。
        anchors.setdefault(sample['role_id'], (str(path), {**report.metrics, 'fixed_reference_kind': 'unverified_probe_diagnostic_only'}))
        vector = evaluator.embedding(str(path))
        vectors[sample['sample_id']] = vector
        destination = review / (sample['sample_id'] + '.wav')
        shutil.copyfile(path, destination)
        records.append({**sample, 'report': asdict(report), 'review_audio': str(destination)})
        pending.append({'sample_id': sample['sample_id'], 'role_id': sample['role_id'],
            'voice_version': sample['profile']['voice_version'], 'audio_sha256': sample['audio_sha256'],
            'content_complete': None, 'signal_acceptable': None, 'identity_accepted': None,
            'notes': ''})
        cells.append(f'<article><h2>{html.escape(sample["sample_id"])}</h2><p>{html.escape(sample["text"])}</p>'
                     f'<p>{"独立重复第一条文本" if sample["independent_repeat"] else "共同文本"}</p>'
                     f'<audio controls preload="none" src="{html.escape(destination.name)}"></audio></article>')
    distances = []
    for i, a in enumerate(records):
        for b in records[i + 1:]:
            distances.append({'left': a['sample_id'], 'right': b['sample_id'],
                'same_role': a['role_id'] == b['role_id'], 'same_text': a['prompt_id'] == b['prompt_id'],
                'cosine_distance': 1 - float(np.dot(vectors[a['sample_id']], vectors[b['sample_id']]))})
    preset_distances = []
    if bank_path:
        bank = json.loads(Path(bank_path).read_text())
        if bank.get('speaker_model_identity', {}).get('fingerprint') != evaluator.backend_identity('speaker')['fingerprint']:
            raise ValueError('内置探针与新描述探针的声纹模型指纹不同，不能直接比较')
        for record in records:
            for voice, data in bank['voices'].items():
                if data.get('verified') is not True or 'en' not in bank.get('languages', []):
                    raise ValueError('比较需要英语已核验内置探针')
                prompt = record['prompt_id']
                if data.get('texts', {}).get(prompt) != record['text']:
                    raise ValueError('内置探针与描述探针需要完全相同的共同文本')
                vector = np.asarray(data['embeddings'][prompt], dtype=float)
                vector /= np.linalg.norm(vector)
                preset_distances.append({'sample_id': record['sample_id'], 'preset_voice': voice,
                    'cosine_distance': 1 - float(np.dot(vectors[record['sample_id']], vector))})
    result = {'schema_version': 'mimo-hybrid-probe-quality-v1', 'source': str(Path(manifest_path).resolve()),
              'source_sha256': hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest(),
              'probes': records, 'speaker_distances': distances, 'preset_distances': preset_distances,
              'speaker_model_identity': evaluator.backend_identity('speaker'),
              'speaker_embeddings': {k: v.tolist() for k, v in vectors.items()},
              'human_review_status': 'pending', 'interpretation': 'uncalibrated_acoustic_proxy_not_listener_identification',
              'production_references_created': 0}
    Path(output).write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    review.joinpath('reference_reviews.pending.json').write_text(json.dumps(pending, ensure_ascii=False, indent=2))
    review.joinpath('index.html').write_text('<!doctype html><meta charset="utf-8"><title>混合声音首轮试听</title>'
        '<style>body{font:17px system-ui;max-width:880px;margin:40px auto;padding:20px}article{border-top:1px solid #ccc;padding:16px 0}audio{width:100%}</style>'
        '<h1>两名描述角色：共同文本与独立重复</h1><p>先核对有没有漏读、多读或重复，再比较同角色三条声音是否一致，最后比较两名角色是否容易区别。尚未进入混合章节。</p>'
        + ''.join(cells), encoding='utf-8')
    return result
