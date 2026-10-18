"""记录本轮试听反馈，定位重复尾段；只使用本地音频和离线模型。"""
import argparse
import copy
import html
import os
import shutil
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import soundfile as sf

from flipped_casting_preview_v39 import ROOT, BASE, read, save, sha
from audiobook_generator.audio_core.models import CoreOptions, ReadingChunk, ResourceLimits
from audiobook_generator.audio_core.quality import QualityEvaluator
from audiobook_generator.audio_core.store import ArtifactStore
from audiobook_generator.audio_core.audio import assemble_pcm, edge_silence, load_audio, signal_features
from audiobook_generator.audio_core.annotations import _verify_pcm_layout
from audiobook_generator.audio_core.encoding import verify_encoded_audio
from audiobook_generator.audio_core.loudness_preview import measure_loudness
from audiobook_generator.audio_core.reviewed_edits import crop_confirmed_extra_suffix, compact_confirmed_silence
from audiobook_generator.audio_core.role_references import make_reference, load_reference
from audiobook_generator.ui.audio_quality import find_quality_reports, load_quality_report, preview_quality_issue

SOURCE = ROOT / 'listening_review/flipped_bryce_clone_chapter_20261017'
DEST = ROOT / 'listening_review/flipped_clone_local_repair_20261017'
FEEDBACK = SOURCE / 'human_feedback_v46.json'
REPLIES = [
    'R039读完后又重复了一遍前半段；R018读完后又重复了两遍no（实际读了5个no）；',
    '全部保留了原R001的年轻音色、像同一个人，且内容完整、无明显杂音或爆音',
    '修复后的接缝自然、音量合适，J076应缩到1秒左右',
]


def context():
    m = read(SOURCE / 'review_manifest.json')
    for row in m['items'] + m['boundaries']:
        assert sha(Path(row['path'])) == row['audio_sha256']
    assert sha(Path(m['output_file'])) == m['audio_sha256']
    return m


def evaluator():
    plan = read(BASE / 'bryce_clone_chapter_v44/plan.json')
    return QualityEvaluator(CoreOptions(language='en',
        asr_model_dir=str(ROOT / '.audio_quality_models/SenseVoiceSmall'),
        speaker_model_dir=str(ROOT / '.audio_quality_models/ecapa')),
        store=ArtifactStore(plan['project']))


def feedback():
    m = context()
    def bound(row):
        return {k: row[k] for k in ('sample_id', 'path', 'audio_sha256')}
    record = {'version': 'flipped-clone-human-feedback-v46', 'source': 'explicit_user_reply',
        'source_manifest': str(SOURCE / 'review_manifest.json'),
        'source_manifest_sha256': sha(SOURCE / 'review_manifest.json'),
        'confirmed_defects': [
            {**bound(m['items'][38]), 'confirmed_defect': 'extra_suffix', 'user_reply': REPLIES[0],
             'description': '完整读完后重复；用户描述为前半段，实际切点须独立定位。'},
            {**bound(m['items'][17]), 'confirmed_defect': 'extra_suffix', 'user_reply': REPLIES[0],
             'expected_no_count': 3, 'heard_no_count': 5},
            {**bound(m['boundaries'][75]), 'confirmed_defect': 'long_pause', 'user_reply': REPLIES[2],
             'target_pause_seconds': 1., 'heard_estimated_pause_seconds': 2.04}],
        'accepted_voice_samples': [
            {**bound(m['items'][n-1]), 'role_id': 'narrator',
             'voice_version': m['items'][n-1]['profile']['voice_version'],
             'content_complete': True, 'signal_acceptable': True, 'identity_accepted': True,
             'young_voice_preserved': True, 'user_reply': REPLIES[1]}
            for n in (1, 51, 100)],
        'accepted_join_contexts': [
            {**bound(m['boundaries'][n-1]), 'natural': True, 'loudness_acceptable': True,
             'user_reply': REPLIES[2]} for n in (9,13,23,21,22,48,49)],
        'scope': 'only_explicitly_reviewed_samples_and_join_contexts',
        'original_reference_R001_not_reclassified': True,
        'whole_chapter_listening_complete': False,
        'machine_reports_unchanged': True, 'new_repair_candidates_not_yet_accepted': True}
    save(FEEDBACK, record)
    print('人工反馈已绑定新试听音频指纹，未扩展为整章验收。', flush=True)


def diagnose():
    m = context(); assert FEEDBACK.is_file()
    assert not (DEST / 'diagnostics.json').exists()
    dest = DEST / 'diagnostics'; dest.mkdir(parents=True, exist_ok=True)
    quality = evaluator(); rows = []
    # 在长低能量区分开首次朗读与附加尾段；只做少量确定位置的诊断。
    for n, cuts in ((39, (10.8,)), (18, (3.0, 5.0))):
        row = m['items'][n-1]; pcm, rate = sf.read(row['path'], dtype='int16', always_2d=True)
        for seconds in cuts:
            cut = round(seconds*rate)
            for label, samples in (('prefix',pcm[:cut]),('suffix',pcm[cut:])):
                target = dest / f'{row["sample_id"]}_{seconds:g}s_{label}.wav'
                assert not target.exists()
                sf.write(target,samples,rate,subtype='PCM_16')
                text = quality.transcript(target)
                result = {'sample_id':row['sample_id'],'source_audio_sha256':row['audio_sha256'],
                    'cut_seconds':seconds,'part':label,'path':str(target),'audio_sha256':sha(target),
                    'transcript':text,'expected_text':row['text']}
                rows.append(result); print(result,flush=True)
    save(DEST / 'diagnostics.json', {'version':'flipped-repair-diagnostics-v46',
        'feedback_sha256':sha(FEEDBACK),'models':{'asr':quality.backend_identity('asr')},
        'requests_sent':0,'rows':rows,'not_human_acceptance':True})


def build():
    m = context(); approval = read(FEEDBACK)
    diag = read(DEST / 'diagnostics.json')
    assert diag['feedback_sha256'] == sha(FEEDBACK)
    assert not (DEST / 'assembly_manifest.json').exists(), '不得覆盖已产出的修复候选'
    original = read(SOURCE / 'assembly_manifest.json')
    q = read(SOURCE / 'quality.json')
    plan = read(BASE / 'bryce_clone_chapter_v44/plan.json')
    integration = read(BASE / 'bryce_clone_chapter_v44/standard_quality_report_v45.json')
    standard = read(Path(integration['standard_report']))
    assert sha(Path(integration['standard_report'])) == integration['standard_report_sha256']
    quality = evaluator(); store = quality.store
    prior_events = store.request_events(run_id=standard['run_id'])
    assert len(prior_events) == 67
    limits = ResourceLimits(max_requests=0, max_repair_requests=0, max_repair_characters=0)
    run_id = store.start_run(limits)
    report_dir = store.root / f'reports/{run_id}/chapter_000005'
    for folder in (DEST / 'audio', DEST / 'pairs', report_dir / 'audio'):
        folder.mkdir(parents=True, exist_ok=False)
    edits = {}
    for n, seconds in ((18,3.), (39,10.8)):
        row = m['items'][n-1]
        accepted = next(x for x in approval['confirmed_defects'] if x['sample_id'] == row['sample_id'])
        source = Path(row['path']); target = DEST / 'audio' / f'{row["sample_id"]}.wav'
        rate = sf.info(source).samplerate
        operation = crop_confirmed_extra_suffix(source, target, end_sample=round(seconds*rate),
            expected_sha256=row['audio_sha256'], review=accepted)
        a, _ = sf.read(source, dtype='int16', always_2d=True)
        b, _ = sf.read(target, dtype='int16', always_2d=True)
        assert np.array_equal(a[:len(b)],b)
        edits[row['sample_id']] = operation
    row = m['items'][75]; rate = sf.info(row['path']).samplerate
    pause_review = next(x for x in approval['confirmed_defects'] if x['sample_id'] == 'J076')
    pause_review = {**pause_review, 'sample_id':'R076', 'audio_sha256':row['audio_sha256'],
        'boundary_audio_sha256':pause_review['audio_sha256']}
    edits['R076'] = compact_confirmed_silence(row['path'],DEST / 'audio/R076.wav',
        quiet_start=round(1.18*rate),quiet_end=round(3.04*rate),remove_samples=round(1.04*rate),
        expected_sha256=row['audio_sha256'],review=pause_review)
    a, _ = sf.read(row['path'],dtype='int16',always_2d=True)
    b, _ = sf.read(DEST / 'audio/R076.wav',dtype='int16',always_2d=True)
    edit = edits['R076']
    assert np.array_equal(b,np.concatenate((a[:edit['removed_start_sample']],a[edit['removed_end_sample']:]),axis=0))
    entries, rows, chunks, paths = copy.deepcopy(original['chunks']),copy.deepcopy(m['items']),[],[]
    for entry,row in zip(entries,rows):
        target = DEST / 'audio' / f'{row["sample_id"]}.wav'
        if row['sample_id'] not in edits:
            shutil.copyfile(row['path'],target)
            assert sha(target) == row['audio_sha256']
        row.update(previous_path=row['path'],previous_audio_sha256=row['audio_sha256'],
            path=str(target),audio_sha256=sha(target))
        entry['rendered_path'] = str(target)
        chunks.append(ReadingChunk(**entry['chunk'])); paths.append(str(target))
    output = DEST / 'chapter_05.bryce_clone.local_repair.wav'
    layout = assemble_pcm(chunks,paths,output,
        expected_artifacts={row['chunk_id']:row['audio_sha256'] for row in rows})
    _verify_pcm_layout(output,layout,entries)
    affected = {17,18,38,39,75,76}
    for n,(boundary,previous) in enumerate(zip(layout['boundaries'],original['assembly']['boundaries']),1):
        left,rate = load_audio(paths[n-1]); right,_ = load_audio(paths[n])
        boundary['estimated_pause_seconds'] = edge_silence(left,rate,leading=False) + edge_silence(right,rate,leading=True) + boundary['added_silence_samples']/rate
        if n not in affected:
            assert boundary['added_silence_samples'] == previous['added_silence_samples']
    assert abs(layout['boundaries'][75]['estimated_pause_seconds']-1.) < .03
    for row,span in zip(rows,layout['spans']):
        row.update(start_seconds=span['start_sample']/rate,end_seconds=span['end_sample']/rate)
    frozen = {k:quality.backend_identity(k) for k in ('asr','speaker')}
    assert frozen == q['models'], '模型变更时不得复用旧质量证据'
    new_q = copy.deepcopy(q)
    for i,row in enumerate(rows):
        checked = new_q['chunks'][i]
        if row['sample_id'] in edits:
            c = chunks[i]; ref = q['references'][c.role_id]
            anchor = next(x['report']['metrics'] for x in q['chunks']
                if x['audio_sha256'] == ref['sha256']) if any(x['audio_sha256'] == ref['sha256'] for x in q['chunks']) else None
            if anchor is None:
                # 旧参考的完整指标由原评估配置重算，固定参考种类仍保持旧报告的诊断语义。
                old_review = read(ROOT / 'listening_review/flipped_full_chapter_20261017/review_manifest.json')
                old_report = read(Path(old_review['source_report']))
                ref_chunk = ReadingChunk(**old_report['chunks'][0]['chunk'])
                assert c.role_id == ref_chunk.role_id == 'narrator'
                anchor = quality.evaluate_chunk(ref_chunk,ref['path']).metrics
            anchor = {**anchor,'fixed_reference_kind':ref['kind'],'fixed_reference_sha256':ref['sha256']}
            result = quality.evaluate_chunk(c,row['path'],anchor=(ref['path'],anchor)).to_dict()
            checked.update(audio_sha256=row['audio_sha256'],report=result)
            checked['evidence_origin'] = 'reevaluated_after_local_edit'
            print(f'{row["sample_id"]} 复检：{result["metrics"].get("content_alignment",{})}',flush=True)
        else:
            assert checked['audio_sha256'] == row['audio_sha256']
            checked['evidence_origin'] = 'reused_exact_audio_same_models_same_reference'
        checked['report']['metrics'].update(start_seconds=row['start_seconds'],end_seconds=row['end_seconds'])
    joins = []
    with sf.SoundFile(output) as stream:
        for n,(boundary,checked) in enumerate(zip(layout['boundaries'],new_q['boundaries']),1):
            left,right = layout['spans'][n-1:n+1]
            pair = DEST / 'pairs' / f'J{n:03d}_full_pair.wav'
            stream.seek(left['start_sample'])
            sf.write(pair,stream.read(right['end_sample']-left['start_sample'],dtype='int16',always_2d=True),rate,subtype='PCM_16')
            if n in affected:
                report = quality.evaluate_boundary(chunks[n-1],chunks[n],paths[n-1],paths[n],assembled_window=str(pair)).to_dict()
                checked['evidence_origin'] = 'reevaluated_after_local_edit_full_left_right_context'
            else:
                assert sha(pair) == q['boundaries'][n-1]['pair_sha256']
                report = checked['report']
                checked['evidence_origin'] = 'reused_exact_pair_same_models'
            report['metrics'].update(assembled_window_sha256=sha(pair),
                left_audio_sha256=rows[n-1]['audio_sha256'],right_audio_sha256=rows[n]['audio_sha256'],
                estimated_pause_seconds=boundary['estimated_pause_seconds'],evaluation_models={'asr':frozen['asr']})
            checked.update(pair_path=str(pair),pair_sha256=sha(pair),report=report)
            start = max(left['start_sample'],boundary['start_sample']-round(3.2*rate))
            end = min(right['end_sample'],boundary['end_sample']+round(2*rate))
            stream.seek(start); preview = DEST / 'audio' / f'J{n:03d}.wav'
            sf.write(preview,stream.read(end-start,dtype='int16',always_2d=True),rate,subtype='PCM_16')
            joins.append({'sample_id':f'J{n:03d}','path':str(preview),'audio_sha256':sha(preview),
                'pair_path':str(pair),'pair_sha256':sha(pair),'chapter_seconds':boundary['start_sample']/rate,
                'boundary_at_seconds':(boundary['start_sample']-start)/rate,
                'estimated_pause_seconds':boundary['estimated_pause_seconds']})
            if n in affected: print(f'J{n:03d} 完整左右句复检完成',flush=True)
    # 新R001已获内容、身份、信号三项明确确认；仅注册为质量比较参考，不变更TTS克隆输入。
    accepted = approval['accepted_voice_samples'][0]
    assert accepted['audio_sha256'] == rows[0]['audio_sha256']
    key,record = make_reference('narrator',chunks[0].profile,'en',entries[0]['voice_reference_request'],
        accepted['path'],q['chunks'][0]['report']['metrics'],accepted)
    registry_path = BASE / 'role_references.clone_confirmed.v46.json'
    save(registry_path,{'schema_version':'mimo-role-references-v1','references':{key:record},
        'scope':'new_clone_Bryce_quality_reference_only',
        'tts_clone_input_unchanged':{'path':plan['reference_path'],'sha256':plan['reference_sha256']},
        'not_retroactively_applied_to_current_quality_reports':True})
    assert load_reference(registry_path,'narrator',chunks[0].profile,'en',entries[0]['voice_reference_request']) is not None
    manifest = {'version':'flipped-clone-local-repair-v46','run_id':run_id,'chapter_index':5,
        'source_manifest':str(SOURCE / 'review_manifest.json'),'source_manifest_sha256':sha(SOURCE / 'review_manifest.json'),
        'feedback':str(FEEDBACK),'feedback_sha256':sha(FEEDBACK),'diagnostics_sha256':sha(DEST / 'diagnostics.json'),
        'output_file':str(output),'audio_sha256':sha(output),'duration_seconds':layout['total_samples']/rate,
        'items':rows,'chunks':entries,'boundaries':joins,'assembly':layout,'edits':edits,
        'changed_chunks':3,'unchanged_chunks':97,'reevaluated_chunks':3,'reevaluated_boundaries':6,
        'reused_chunk_evidence':97,'reused_boundary_evidence':93,'models':frozen,
        'requests_sent':0,'original_audio_unchanged':True,'human_review_status':'pending_three_local_edits',
        'whole_chapter_listening_complete':False,'quality_reference_registry':str(registry_path)}
    save(DEST / 'assembly_manifest.json',manifest)
    new_q.update(version='flipped-clone-local-repair-quality-v46',
        assembly_manifest_sha256=sha(DEST / 'assembly_manifest.json'),
        status='screened_pending_human_review',human_review_status='pending_three_local_edits',
        final_signal=signal_features(output),requests_sent=0,
        final_loudness=measure_loudness(output),
        speaker_unavailable_count=sum('speaker_unavailable' in r['report']['metrics'] for r in new_q['chunks']),
        asr_unavailable_count=sum('asr_unavailable' in r['report']['metrics'] for r in new_q['chunks']+new_q['boundaries']),
        evidence_reuse={'source_quality':str(SOURCE / 'quality.json'),'sha256':sha(SOURCE / 'quality.json'),
            'changed_chunks':[18,39,76],'changed_boundaries':sorted(affected),
            'references_unchanged':True,'models_unchanged':True},
        warning_counts=dict(Counter(i['code'] for r in new_q['chunks']+new_q['boundaries'] for i in r['report']['issues'])))
    save(DEST / 'quality.json',new_q)
    # 标准报告与试听材料同源；本次本地运行请求预算为0，历史生成记录继续回溯。
    result = copy.deepcopy(standard)
    for i,(entry,row,checked) in enumerate(zip(result['chunks'],rows,new_q['chunks'])):
        target = report_dir / 'audio' / f'{row["sample_id"]}.wav'
        shutil.copyfile(row['path'],target); assert sha(target) == row['audio_sha256']
        entry.update(rendered_path=str(target),selected_rendered_path=str(target),report=copy.deepcopy(checked['report']))
        entry['render_operations'].append({'kind':'offline_reviewed_revision_v46',
            'source_path':row['path'],'source_audio_sha256':row['audio_sha256'],
            'edit':edits.get(row['sample_id']),'evidence_origin':checked['evidence_origin'],
            'feedback_path':str(FEEDBACK),'feedback_sha256':sha(FEEDBACK),
            'candidate_review_status':'pending' if row['sample_id'] in edits else 'unchanged_audio'})
    result['boundaries'] = []
    for checked,join,b in zip(new_q['boundaries'],joins,layout['boundaries']):
        target = report_dir / 'audio' / (join['sample_id']+'.wav')
        shutil.copyfile(join['path'],target)
        report = copy.deepcopy(checked['report'])
        report['metrics'].update(preview_path=str(target),preview_sha256=sha(target),
            preview_scope='short_listening_context_not_asr_input',
            asr_evaluation_window_path=join['pair_path'],asr_evaluation_window_sha256=join['pair_sha256'],
            start_seconds=b['start_sample']/rate,end_seconds=b['end_sample']/rate,
            preview_boundary_at_seconds=join['boundary_at_seconds'])
        result['boundaries'].append(report)
    final = report_dir / 'chapter.wav'; shutil.copyfile(output,final)
    assert sha(final) == manifest['audio_sha256']
    _verify_pcm_layout(final,layout,result['chunks'])
    verified = verify_encoded_audio(final,output,chunks,layout,report_dir / 'encoded_checks',
        SimpleNamespace(evaluation_seconds=0.),enable_asr=False).to_dict()
    assert verified['metrics']['pcm_equal'] and verified['status'] == 'passed'
    provenance = store.resource_provenance(run_id,[c['raw_path'] for c in result['chunks']],
        standard['resource_provenance']['recorded_generation']['chunks'])
    assert provenance['recorded_generation']['summary'] == standard['resource_provenance']['recorded_generation']['summary']
    assert provenance['recorded_generation']['history_incomplete'] == standard['resource_provenance']['recorded_generation']['history_incomplete']
    result.update(run_id=run_id,output_file=str(final),assembly=layout,final_verification=verified,
        resource_summary=store.summary(run_id),resource_limits=asdict(limits),resource_provenance=provenance,
        quality_status='incomplete',performance={'duration_seconds':manifest['duration_seconds'],'offline_revision':True},
        offline_import={'method':'reviewed_local_edits_with_frozen_unaffected_evidence','requests_sent':0,
            'source_standard_report':integration['standard_report'],'source_standard_report_sha256':integration['standard_report_sha256'],
            'source_review_manifest':str(DEST / 'assembly_manifest.json'),'source_review_manifest_sha256':sha(DEST / 'assembly_manifest.json'),
            'source_quality':str(DEST / 'quality.json'),'source_quality_sha256':sha(DEST / 'quality.json'),
            'human_review_status':'pending_three_local_edits','whole_chapter_listening_complete':False})
    report_path = report_dir / 'quality.json'
    store.write_json(str(report_path.relative_to(store.root)),result)
    _,issues,previews = load_quality_report(report_path)
    assert str(report_path) in find_quality_reports(store.root.parent.parent) and len(previews) == 200
    for scope,path in previews.items():
        assert Path(path).is_file() and preview_quality_issue(report_path,scope) == path
    assert store.request_events(run_id=run_id) == []
    assert store.request_events(run_id=standard['run_id']) == prior_events
    assert sha(Path(m['output_file'])) == m['audio_sha256']
    assert {k:quality.backend_identity(k) for k in ('asr','speaker')} == frozen
    validation = {'version':'flipped-clone-local-repair-validation-v46',
        'manifest':str(DEST / 'assembly_manifest.json'),'manifest_sha256':sha(DEST / 'assembly_manifest.json'),
        'quality_report':str(DEST / 'quality.json'),'quality_report_sha256':sha(DEST / 'quality.json'),
        'standard_report':str(report_path),'standard_report_sha256':sha(report_path),
        'chunks_unchanged':97,'chunks_changed':3,'boundaries_rechecked':6,'standard_preview_count':len(previews),
        'pcm_layout_verified':True,'decoded_pcm_equal':True,'source_audio_unchanged':True,
        'duration_seconds':manifest['duration_seconds'],'j076_pause_seconds':layout['boundaries'][75]['estimated_pause_seconds'],
        'new_requests':0,'prior_clone_run_requests_unchanged':67,
        'human_review_status':'pending_three_local_edits','overall_project_complete':False}
    save(ROOT / 'docs/validation/audio_core_20261017/flipped_clone_local_repair_v46.json',validation)
    print(validation,flush=True)


def audit_reference():
    """交付前审计：参考音频须配自己的正文，保留早期诊断报表快照。"""
    validation_path = ROOT / 'docs/validation/audio_core_20261017/flipped_clone_local_repair_v46.json'
    v = read(validation_path); report_path = Path(v['standard_report'])
    qpath = DEST / 'quality.json'; q = read(qpath); standard = read(report_path)
    assert not q.get('reference_text_audit'), '不能重复修订已审计报告'
    paths = [qpath,report_path,validation_path]
    snapshots = []
    for path in paths:
        target = path.with_name(path.stem + '.before_reference_text_audit_v46.json')
        assert not target.exists(); shutil.copyfile(path,target)
        snapshots.append({'path':str(target),'sha256':sha(target)})
    quality = evaluator(); m = read(DEST / 'assembly_manifest.json')
    old_review = read(ROOT / 'listening_review/flipped_full_chapter_20261017/review_manifest.json')
    old_report = read(Path(old_review['source_report']))
    ref = q['references']['narrator']
    ref_chunk = ReadingChunk(**old_report['chunks'][0]['chunk'])
    anchor = quality.evaluate_chunk(ref_chunk,ref['path']).metrics
    anchor.update(fixed_reference_kind=ref['kind'],fixed_reference_sha256=ref['sha256'])
    for n in (39,):
        row = m['items'][n-1]; c = ReadingChunk(**m['chunks'][n-1]['chunk'])
        assert c.role_id == ref_chunk.role_id
        report = quality.evaluate_chunk(c,row['path'],anchor=(ref['path'],anchor)).to_dict()
        report['metrics'].update(start_seconds=row['start_seconds'],end_seconds=row['end_seconds'])
        q['chunks'][n-1]['report'] = report
        standard['chunks'][n-1]['report'] = copy.deepcopy(report)
    audit = {'method':'reference_audio_aligned_with_its_own_source_text',
        'reference_path':ref['path'],'reference_audio_sha256':sha(Path(ref['path'])),
        'reference_text':ref_chunk.tts_text,'changed_audio_files':0,
        'recomputed_consistency_reports':['R039'],
        'prior_diagnostics_preserved':snapshots,'requests_sent':0}
    q.update(reference_text_audit=audit,
        warning_counts=dict(Counter(i['code'] for r in q['chunks']+q['boundaries'] for i in r['report']['issues'])))
    save(qpath,q,overwrite=True)
    standard['offline_import']['reference_text_audit'] = audit
    standard['offline_import']['source_quality_sha256'] = sha(qpath)
    save(report_path,standard,overwrite=True)
    v.update(quality_report_sha256=sha(qpath),standard_report_sha256=sha(report_path),reference_text_audit=audit)
    save(validation_path,v,overwrite=True)
    print('参考正文审计完成，早期诊断快照保留；音频未变。',flush=True)


def export():
    m = read(DEST / 'assembly_manifest.json'); q = read(DEST / 'quality.json')
    assert sha(Path(m['output_file'])) == m['audio_sha256']
    assert not (DEST / 'index.html').exists()
    esc = html.escape
    def player(path):
        return f"<audio controls preload='none' src='{esc(os.path.relpath(path,DEST))}'></audio>"
    def link(path): return esc(os.path.relpath(path,DEST))
    content = '<p>只需核验本次两条裁切和一处停顿。均为本地编辑，没有追加MiMo请求。其余97块逐字节保留；整章尚未完成全量人工验收。</p>'
    for n in (39,18):
        row = m['items'][n-1]; metrics = q['chunks'][n-1]['report']['metrics']
        content += f"<section><h2>{row['sample_id']}：去除重复尾段</h2><p>请确认正文完整、末尾没有重复，结束是否自然。</p>{player(row['path'])}<p>原文：{esc(row['text'])}</p><p>本地转写：{esc(metrics.get('content_alignment',{}).get('hypothesis',''))}</p><details><summary>修改前对照</summary>{player(row['previous_path'])}</details>"
        for join_n in (n-1,n):
            join = m['boundaries'][join_n-1]
            content += f"<p>{join['sample_id']} · 修复后的相邻接缝（接点在{join['boundary_at_seconds']:.2f}秒）</p>{player(join['path'])}"
        content += '</section>'
    join = m['boundaries'][75]; old = context()['boundaries'][75]
    content += f"<section><h2>J076：停顿从2.04秒缩至{join['estimated_pause_seconds']:.2f}秒</h2><p>请确认停顿自然，前后语音完整。</p>{player(join['path'])}<details><summary>修改前对照</summary>{player(old['path'])}</details></section>"
    content += f"<section><h2>完整章节候选</h2>{player(m['output_file'])}<p>{m['duration_seconds']/60:.2f}分钟。<a href='{link(m['output_file'])}'>打开完整音频</a></p></section>"
    content += '<p>R039裁切后仍有缩写、所有格的ASR差异提示，不能把它当成真实错读；本次只处理人工已确认的重复。新R001已登记为质量比对参考，生成时使用的原R001参考未改变。</p>'
    page = "<!doctype html><html lang='zh-CN'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Flipped：三处局部修复</title><style>body{max-width:850px;margin:30px auto;padding:0 18px;font:17px/1.65 system-ui;background:#f5f5f7;color:#222}section{padding:18px;margin:18px 0;background:white;border:1px solid #ddd;border-radius:12px}audio{width:100%}p{white-space:pre-wrap}</style><h1>Flipped：三处局部修复</h1>"+content+'</html>'
    (DEST / 'index.html').write_text(page,encoding='utf-8')
    (DEST / 'README.md').write_text('# Flipped 克隆版局部修复\n\n'
        f'[试听页]({DEST / "index.html"})\n\n'
        'R039保留首次完整朗读，删除附加重复；R018保留三次No，删除附加两次；J076只移除1.04秒低能量静音，合计停顿约1秒。\n\n'
        '未追加合成。97块音频未变；3块与6处相邻完整左右句已本地复检，其他质量证据按相同音频、模型与参考复用。'
        '完整章节逐样本布局及解码一致性检查通过；新剪辑仍需试听确认。\n',encoding='utf-8')
    print('三处修复试听页已导出。',flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('action', choices=['feedback','diagnose','build','audit_reference','export'])
    globals()[parser.parse_args().action]()
