"""用既有MiMo音频验证新证据绑定，不合成、不修改人工结论或旧报告。"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from audiobook_generator.audio_core.models import CoreOptions, ReadingChunk
from audiobook_generator.audio_core.quality import QualityEvaluator, AUDIO_EVIDENCE_VERSION
from audiobook_generator.audio_core.role_references import load_reference
from audiobook_generator.audio_core.store import ArtifactStore


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    base = ROOT / 'audiobook_output/flipped_chapter_pilot_20261017'
    clone_dir = ROOT / 'listening_review/flipped_r001_clone_20261017'
    output = ROOT / 'docs/validation/audio_core_20261017/reference_integrity_actual_v43.json'
    assert not output.exists()
    manifest = read(clone_dir / 'manifest.json')
    source = read(ROOT / 'listening_review/flipped_full_chapter_20261017/review_manifest.json')
    report = read(source['source_report'])
    run = read(base / 'r001_clone_probe_v42/manifest.json')
    store = ArtifactStore(run['project'])
    before = store.request_events(run_id=run['run_id'])
    evaluator = QualityEvaluator(CoreOptions(language='en',
        asr_model_dir=str(ROOT / '.audio_quality_models/SenseVoiceSmall'),
        speaker_model_dir=str(ROOT / '.audio_quality_models/ecapa')), store=store)
    ref = clone_dir / 'audio/R001_reference.wav'
    assert sha(ref) == manifest['reference_sha256']
    reference = evaluator.evaluate_chunk(ReadingChunk(**report['chunks'][0]['chunk']), ref)
    records = []
    for item in manifest['probes']:
        text = item['text']; path = Path(item['path'])
        chunk = ReadingChunk(item['sample_id'], item['sample_id'], 'narrator', text, text, 0, len(text), language='en')
        result = evaluator.evaluate_chunk(chunk, path, anchor=(ref, reference.metrics))
        evidence = result.metrics['consistency_reference']
        assert result.metrics['audio_sha256'] == item['audio_sha256'] == sha(path)
        assert result.metrics['audio_evidence_version'] == AUDIO_EVIDENCE_VERSION
        assert evidence['sha256'] == sha(ref)
        assert evidence['source_binding'] == 'matched_recorded_sha256'
        if reference.metrics['content_alignment']['operations']:
            assert evidence['kind'] == 'external_reference_unverified'
        assert result.dimensions['consistency'] == 'incomplete'
        records.append({'sample_id': item['sample_id'], 'report': result.to_dict()})
    registry = base / 'role_references.confirmed.v41.json'
    loaded = []
    for record in read(registry)['references'].values():
        fixed = load_reference(registry, record['role_id'], record['profile'], record['language'], record['request'])
        assert fixed and sha(fixed[0]) == fixed[1]['fixed_reference_sha256']
        loaded.append(record['role_id'])
    assert len(loaded) == 5
    assert before == store.request_events(run_id=run['run_id']) and len(before) == 3
    output.write_text(json.dumps({'version': 'reference-integrity-actual-v43',
        'reference_report': reference.to_dict(), 'probes': records,
        'historical_fixed_registry_loaded_roles': loaded,
        'historical_registry_sha256': sha(registry), 'new_tts_requests': 0,
        'source_clone_manifest_sha256': sha(clone_dir / 'manifest.json'),
        'audio_unchanged': True, 'human_acceptance_unchanged': True}, ensure_ascii=False, indent=2))
    print('真实音频离线复评完成：三条指纹匹配、参考来源如实标记、五角色旧注册表可读取，零新请求。')


if __name__ == '__main__':
    main()
