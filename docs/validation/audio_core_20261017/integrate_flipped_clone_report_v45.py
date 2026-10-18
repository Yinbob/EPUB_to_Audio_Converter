"""将已生成克隆章的冻结证据接入标准报告；零合成、保留原试听和原报告。"""
import copy
import shutil
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

from flipped_casting_preview_v39 import ROOT, BASE, read, save, sha
from audiobook_generator.audio_core.annotations import _verify_pcm_layout
from audiobook_generator.audio_core.encoding import verify_encoded_audio
from audiobook_generator.audio_core.models import ReadingChunk
from audiobook_generator.audio_core.reading import PLAN_VERSION, VERSION, pronunciation_review
from audiobook_generator.audio_core.report_sources import resolve_reference_pcm
from audiobook_generator.audio_core.store import ArtifactStore, fingerprint
from audiobook_generator.ui.audio_quality import find_quality_reports, load_quality_report, preview_quality_issue, resource_summary_text

REVIEW = ROOT / 'listening_review/flipped_bryce_clone_chapter_20261017'
RUN = BASE / 'bryce_clone_chapter_v44'


def main():
    plan, rendered = read(RUN / 'plan.json'), read(RUN / 'render_manifest.json')
    m, a, quality = (read(REVIEW / name) for name in ('review_manifest.json','assembly_manifest.json','quality.json'))
    assert rendered['status'] == 'generated_pending_assembly_quality_and_human_review'
    assert m['quality_report_sha256'] == sha(REVIEW / 'quality.json')
    assert quality['assembly_manifest_sha256'] == sha(REVIEW / 'assembly_manifest.json')
    assert m['audio_sha256'] == sha(Path(m['output_file']))
    assert len(m['items']) == len(quality['chunks']) == 100 and len(m['boundaries']) == 99
    old_review = read(ROOT / 'listening_review/flipped_full_chapter_20261017/review_manifest.json')
    old = read(Path(old_review['source_report']))
    assert sha(Path(old_review['source_report'])) == old_review['source_report_sha256']
    store = ArtifactStore(plan['project'])
    before_events = store.request_events(run_id=rendered['run_id'])
    assert len(before_events) == 67 and all(e['status'] == 'succeeded' for e in before_events)
    prefix = f'reports/{rendered["run_id"]}/chapter_000005'
    destination = store.root / prefix
    assert not destination.exists(), '已有标准报告不覆盖'
    (destination / 'audio').mkdir(parents=True)
    entries, paths, lineages, chunks = [], [], [], []

    def exact_copy(source, target, expected):
        assert sha(Path(source)) == expected
        shutil.copy2(source, target)
        assert sha(Path(source)) == sha(target) == expected
        return str(target)

    for n, (row, checked, generated, entry) in enumerate(zip(m['items'], quality['chunks'], rendered['samples'], a['chunks'])):
        assert row['chunk_id'] == entry['chunk']['chunk_id'] == generated['chunk_id']
        assert row['audio_sha256'] == checked['audio_sha256'] == checked['report']['metrics']['audio_sha256']
        output = exact_copy(row['path'], destination / 'audio' / (row['sample_id'] + '.wav'), row['audio_sha256'])
        # 其他角色的当前文件经过响度处理或人工裁切，raw必须回溯到账本原始样本。
        raw = generated['path'] if row['role_id'] == 'narrator' else old['chunks'][n]['raw_path']
        origin = store.sample_provenance(raw)
        assert origin['origin_status'] == 'recorded'
        ids = set(origin['origin_request_ids'])
        if row['role_id'] != 'narrator':
            prior = next(x for x in old['resource_provenance']['recorded_generation']['chunks'] if x['chunk_id'] == row['chunk_id'])
            ids.update(prior['request_ids'])
            incomplete = prior['history_incomplete']
        else:
            incomplete = False
        chunk = ReadingChunk(**entry['chunk']); chunks.append(chunk)
        report = copy.deepcopy(checked['report'])
        report['metrics'].update(start_seconds=row['start_seconds'], end_seconds=row['end_seconds'])
        operations = [{'kind': 'import_existing_reviewed_candidate', 'source_path': row['path'],
            'source_audio_sha256': row['audio_sha256'], 'source_manifest': str(REVIEW / 'review_manifest.json'),
            'source_manifest_sha256': sha(REVIEW / 'review_manifest.json'),
            'generation_operation': generated['operation'], 'gain_db_from_raw_or_preserved': row['gain_db'],
            'human_status': 'pending_for_current_context', 'no_audio_transform_during_import': True}]
        if row['role_id'] != 'narrator':
            operations[0]['inherited_local_revision'] = str(BASE / 'accepted_local_revision_v44/manifest.json')
            operations[0]['inherited_local_revision_sha256'] = sha(BASE / 'accepted_local_revision_v44/manifest.json')
        entries.append({'chunk': asdict(chunk), 'raw_path': raw, 'rendered_path': output,
            'selected_rendered_path': output, 'voice_reference_request': entry['voice_reference_request'],
            'speed': 1., 'render_operations': operations, 'synthesis_parts': [], 'composition': None,
            'report': report})
        paths.append(raw)
        lineages.append({'chunk_id': row['chunk_id'], 'request_ids': sorted(ids), 'history_incomplete': incomplete})
    boundaries = []
    for row, checked, position in zip(m['boundaries'], quality['boundaries'], m['assembly']['boundaries']):
        report = copy.deepcopy(checked['report'])
        output = exact_copy(row['path'], destination / 'audio' / (row['sample_id'] + '.wav'), row['audio_sha256'])
        assert sha(Path(row['full_pair_path'])) == row['full_pair_sha256'] == checked['pair_sha256']
        report['metrics'].update(preview_path=output, preview_sha256=row['audio_sha256'],
            preview_scope='short_listening_context_not_asr_input',
            asr_evaluation_window_path=row['full_pair_path'], asr_evaluation_window_sha256=row['full_pair_sha256'],
            start_seconds=position['start_sample']/m['assembly']['sample_rate'],
            end_seconds=position['end_sample']/m['assembly']['sample_rate'],
            preview_boundary_at_seconds=row['boundary_at_seconds'])
        boundaries.append(report)
    output = exact_copy(m['output_file'], destination / 'chapter.wav', m['audio_sha256'])
    _verify_pcm_layout(output, m['assembly'], entries)
    final = verify_encoded_audio(output, m['output_file'], chunks, m['assembly'], destination / 'encoded_checks',
        SimpleNamespace(evaluation_seconds=0.), enable_asr=False).to_dict()
    assert final['metrics']['pcm_equal'] and final['status'] == 'passed'
    # 编码保留检查通过仅证明复制无损；不覆盖已保留的内容／声音疑问。
    source = read(BASE / 'source_chapters.json')['chapters'][4]['text']
    source_group = fingerprint(source)
    assert source_group == old['source_group_id']
    provenance = store.resource_provenance(rendered['run_id'], paths, lineages)
    # 旧预览缓存的候选历史可能不完整；已找到本次选中原始请求也不能抹去未知历史。
    assert provenance['recorded_generation']['history_incomplete'] == any(x['history_incomplete'] for x in lineages)
    summary = provenance['recorded_generation']['summary']
    assert sum(v['requests'] for v in summary.values()) == 100
    result = {'schema_version': 'audio-core-v1', 'provider': 'openai', 'run_id': rendered['run_id'],
        'chapter_index': 5, 'output_file': output, 'generation_status': 'generated', 'quality_status': 'incomplete',
        'reading_plan_version': PLAN_VERSION, 'nonspoken_source_units': a['nonspoken_source_units'],
        'reading_configuration': {'normalization_version': VERSION, 'language': 'en', 'reading_dictionary': {},
            'max_english_wpm': 300., 'role_references': None,
            'diagnostic_references': quality['references'],
            'note': '此处为冻结的离线复检；诊断参考不自动登记为合格角色声音库。'},
        'pronunciation_review': pronunciation_review(chunks), 'output_conditioning': {
            'scope': 'existing_candidate_import_only', 'onset_fade_applied': False,
            'gain_policy': m['gain_policy'], 'target_lufs': m['target_lufs'], 'operations_during_import': []},
        'chunks': entries, 'boundaries': boundaries, 'assembly': m['assembly'], 'final_verification': final,
        'repair_attempts': [], 'resource_summary': store.summary(rendered['run_id']),
        'resource_limits': asdict(store.run_limits(rendered['run_id'])), 'resource_provenance': provenance,
        'limits_reached': [], 'source_group_id': source_group,
        'offline_import': {'method': 'existing_generated_audio_and_frozen_quality_evidence',
            'requests_sent': 0, 'source_review_manifest': str(REVIEW / 'review_manifest.json'),
            'source_review_manifest_sha256': sha(REVIEW / 'review_manifest.json'),
            'source_quality': str(REVIEW / 'quality.json'), 'source_quality_sha256': sha(REVIEW / 'quality.json'),
            'human_review_status': 'pending', 'pipeline_synthesis_replayed': False,
            'source_render_manifest': str(RUN / 'render_manifest.json'), 'source_render_manifest_sha256': sha(RUN / 'render_manifest.json')},
        'performance': {'duration_seconds': m['duration_seconds'], 'import_only': True,
            'original_render_performance_not_reconstructed': True}}
    target = destination / 'quality.json'
    assert not target.exists()
    store.write_json(str(target.relative_to(store.root)), result)
    report, rows, previews = load_quality_report(target)
    assert str(target) in find_quality_reports(store.root.parent.parent)
    assert len(previews) == 200 and len(rows) >= 199
    assert report['quality_status'] == 'incomplete'
    for scope, path in previews.items():
        assert Path(path).is_file() and Path(path).is_relative_to(store.root)
        assert preview_quality_issue(target, scope) == path
    assert resolve_reference_pcm(result, target, require_hash=True) == Path(m['output_file'])
    assert store.request_events(run_id=rendered['run_id']) == before_events
    record = {'version': 'flipped-clone-standard-report-v45', 'standard_report': str(target),
        'standard_report_sha256': sha(target), 'source_review_manifest_sha256': sha(REVIEW / 'review_manifest.json'),
        'discovery_output_dir': str(store.root.parent.parent), 'preview_count': len(previews),
        'issue_rows': len(rows), 'chunks': len(entries), 'boundaries': len(boundaries),
        'source_group_matches_original': True, 'pcm_equal': True, 'source_audio_unchanged': sha(Path(m['output_file'])) == m['audio_sha256'],
        'current_run_requests': 67, 'recorded_generation_history_requests': 100,
        'generation_history_incomplete': provenance['recorded_generation']['history_incomplete'],
        'import_new_requests': 0, 'resource_summary_text': resource_summary_text(result),
        'quality_status': 'incomplete', 'human_review_status': 'pending', 'overall_project_complete': False}
    save(ROOT / 'docs/validation/audio_core_20261017/flipped_clone_standard_report_v45.json', record)
    save(RUN / 'standard_quality_report_v45.json', record)
    print(record)


if __name__ == '__main__':
    main()
