"""离线补齐同参考对照、父母参考资格及v42证据，不发起外部请求。"""
import html
import shutil
from pathlib import Path
import numpy as np
import soundfile as sf
from flipped_casting_preview_v39 import ROOT, BASE, read, save, sha
from audiobook_generator.audio_core.audio import load_audio, mono_resampled, frame_rms
from audiobook_generator.audio_core.models import CoreOptions, ReadingChunk
from audiobook_generator.audio_core.quality import QualityEvaluator
from audiobook_generator.audio_core.store import ArtifactStore

SOURCE = ROOT / 'listening_review/flipped_full_chapter_20261017'
CLONE = ROOT / 'listening_review/flipped_r001_clone_20261017'
REPAIR = ROOT / 'listening_review/flipped_local_repair_20261017'


def effective_seconds(path):
    audio, rate = load_audio(path)
    mono = mono_resampled(audio, rate)
    return min(len(mono) / 16000, float(sum(frame_rms(mono, 16000) >= .003)) * .02)


def main():
    assert not (CLONE / 'same_reference_comparison.json').exists()
    review = read(SOURCE / 'review_manifest.json')
    original = read(Path(review['source_report']))
    whole = read(BASE / 'whole_chapter_run_v41.json')
    clone = read(CLONE / 'manifest.json')
    ref = CLONE / 'audio/R001_reference.wav'
    assert sha(ref) == clone['reference_sha256']
    evaluator = QualityEvaluator(CoreOptions(language='en',
        asr_model_dir=str(ROOT / '.audio_quality_models/SenseVoiceSmall'),
        speaker_model_dir=str(ROOT / '.audio_quality_models/ecapa')),
        store=ArtifactStore(whole['project']))
    anchor = (str(ref), clone['reference_report']['metrics'])
    evidence_kind = {'path': str(ref), 'sha256': sha(ref),
        'kind': 'user_preferred_synthetic_voice_content_not_yet_confirmed'}
    # 默认bootstrap名称不能解释成人工内容验收；保留最初报告另存后明确锚点性质。
    save(CLONE / 'manifest.initial_evaluation.json', clone)
    for probe in clone['probes']:
        probe['report']['metrics']['consistency_reference'] = evidence_kind
    clone['reference_human_scope'] = 'timbre_preference_only_not_content_or_identity_pair_acceptance'
    save(CLONE / 'manifest.json', clone, overwrite=True)
    baseline = []
    for n in (51, 100):
        item = review['items'][n - 1]
        path = Path(item['path'])
        assert sha(path) == item['audio_sha256']
        report = evaluator.evaluate_chunk(ReadingChunk(**original['chunks'][n - 1]['chunk']),
            path, anchor=anchor).to_dict()
        report['metrics']['consistency_reference'] = evidence_kind
        output = CLONE / 'audio' / (item['sample_id'] + '_original.wav')
        shutil.copy2(path, output)
        baseline.append({'sample_id': item['sample_id'], 'path': str(output),
            'audio_sha256': sha(output), 'text': item['text'], 'report': report})
    embeddings = [np.asarray(evaluator.embedding(p['path'])) for p in clone['probes'][1:]]
    distance = float(1 - np.dot(embeddings[0], embeddings[1]) /
        (np.linalg.norm(embeddings[0]) * np.linalg.norm(embeddings[1])))
    comparison = {'reference_path': str(ref), 'reference_sha256': sha(ref),
        'reference_human_scope': clone['reference_human_scope'], 'baseline': baseline,
        'K02_K03_cosine_distance': distance, 'calibrated': False,
        'same_text_independent_repeat': True, 'human_quality_conclusion': 'pending',
        'no_causal_or_statistical_superiority_claim': True}
    save(CLONE / 'same_reference_comparison.json', comparison)
    page = (CLONE / 'index.html').read_text()
    additions = '<section><h2>原版同文对照</h2><p>R051对应K01；R100对应K02/K03。三条克隆仅用于试听，没有替换整章。</p>'
    for b in baseline:
        additions += f"<p>{b['sample_id']} 原版</p><audio controls preload='none' src='audio/{Path(b['path']).name}'></audio><p>{html.escape(b['text'])}</p>"
    additions += '</section><p>R001只是用户偏好的音色参考，未单独确认其文字完整；距离未标定，不能单凭数值认定同人或更好。</p>'
    assert page.count('</html>') == 1
    (CLONE / 'index.html').write_text(page.replace('</html>', additions + '</html>'))

    parents = []
    for n in (20, 68):
        item = review['items'][n - 1]; path = Path(item['path'])
        assert sha(path) == item['audio_sha256']
        report = evaluator.evaluate_chunk(ReadingChunk(**original['chunks'][n - 1]['chunk']), path).to_dict()
        active = effective_seconds(path)
        embedding = evaluator.embedding(path)
        assert active >= 3 and len(embedding) > 0
        assert report['metrics']['content_alignment']['error_rate'] == 0
        parents.append({'sample_id': item['sample_id'], 'role_id': item['role_id'],
            'path': str(path), 'audio_sha256': sha(path), 'effective_seconds': active,
            'speaker_backend_extraction_succeeded': True, 'report': report,
            'human_content_complete': True, 'human_identity_accepted': True,
            'human_signal_acceptable': None, 'machine_signal_status': report['dimensions']['signal'],
            'human_reply': '两条均完整，声音一致',
            'profile': original['chunks'][n - 1]['chunk']['profile'],
            'request': original['chunks'][n - 1]['voice_reference_request'],
            'status': 'long_reference_candidate_content_identity_confirmed_signal_not_separately_rated'})
    save(BASE / 'role_reference_candidates.longer_parents.v42.json', {
        'version': 'flipped-longer-parent-reference-candidates-v42', 'candidates': parents,
        'production_registry_unchanged': True,
        'note': '已确认内容与身份；信号机器通过，但不伪造独立人工signal评分，未覆盖v41固定参考。'})

    repaired = read(REPAIR / 'manifest.json')
    assert sha(Path(repaired['output_file'])) == repaired['output_sha256']
    assert repaired['requests_sent'] == 0 and repaired['unchanged_chunk_count'] == 94
    assert repaired['pcm_layout_verified'] and not repaired['automatic_promotion']
    unchanged = 0
    repaired_pcm, rate = sf.read(repaired['output_file'], dtype='int16', always_2d=True)
    for n, (item, span) in enumerate(zip(review['items'], repaired['assembly']['spans']), 1):
        if n in repaired['replaced_indices']:
            continue
        pcm, sr = sf.read(item['path'], dtype='int16', always_2d=True)
        assert sr == rate and np.array_equal(pcm, repaired_pcm[span['start_sample']:span['end_sample']])
        unchanged += 1
    assert unchanged == 94
    verified_audio = 0
    import re
    for folder in (CLONE, REPAIR):
        for relative in re.findall(r"src=['\"]([^'\"]+)['\"]", (folder / 'index.html').read_text()):
            target = (folder / relative).resolve()
            assert target.is_relative_to(folder.resolve()) and target.is_file()
            assert sf.info(target).frames > 0
            verified_audio += 1
    run = read(BASE / 'r001_clone_probe_v42/manifest.json')
    events = ArtifactStore(run['project']).request_events(run_id=run['run_id'])
    assert len(events) == 3 and run['resources']['succeeded']['requests'] == 3
    assert run['resources']['succeeded']['characters'] == 541
    save(ROOT / 'docs/validation/audio_core_20261017/flipped_repairs_and_clone_v42.json', {
        'version': 'flipped-repair-clone-validation-v42',
        'human_feedback': str(SOURCE / 'human_feedback_v42.json'),
        'local_repair_manifest': str(REPAIR / 'manifest.json'),
        'local_repair_requests': 0, 'unchanged_chunks_verified': unchanged,
        'pause_seconds': {op['sample_id']:op['pause_after_seconds'] for op in repaired['operations'] if 'pause_after_seconds' in op},
        'cropped_content_asr_exact': [x['sample_id'] for x in repaired['content_checks'] if x['report']['metrics']['content_alignment']['error_rate'] == 0],
        'clone_manifest': str(CLONE / 'manifest.json'), 'clone_run_id': run['run_id'],
        'clone_resources': run['resources'], 'clone_requests_verified': len(events),
        'reference_upload_consent': str(BASE / 'r001_clone_probe_v42/reference_upload_consent.json'),
        'same_reference_comparison': str(CLONE / 'same_reference_comparison.json'),
        'longer_parent_reference_candidates': str(BASE / 'role_reference_candidates.longer_parents.v42.json'),
        'review_audio_links_verified': verified_audio,
        'full_tests': {'run': 567, 'passed': 537, 'skipped': 30, 'failures': 0, 'errors': 0,
            'seconds': 17.755, 'log': '/tmp/flipped_v42_full_tests.log'},
        'new_candidate_human_review': 'pending', 'whole_chapter_voice_replaced': False,
        'production_clone_enabled': False, 'other_chapters_sent': False})
    execution = read(BASE / 'execution_plan.json')
    execution.update(status='local_repairs_and_three_clone_probes_pending_listening',
        local_repair_review=str(REPAIR / 'index.html'), local_repair_requests=0,
        clone_probe_review=str(CLONE / 'index.html'), clone_probe_new_requests=3,
        clone_probe_characters=541, whole_chapter_voice_replaced=False,
        longer_parent_reference_candidates=str(BASE / 'role_reference_candidates.longer_parents.v42.json'))
    save(BASE / 'execution_plan.before_v42.json', read(BASE / 'execution_plan.json'))
    save(BASE / 'execution_plan.json', execution, overwrite=True)
    print(f'离线核验完成：94块PCM不变、{verified_audio}处试听链接有效、3条克隆请求留证。')
    for b in baseline:
        print(b['sample_id'], '对R001距离', b['report']['metrics'].get('speaker_distance'))
    print('K02/K03距离', distance)


if __name__ == '__main__':
    main()
