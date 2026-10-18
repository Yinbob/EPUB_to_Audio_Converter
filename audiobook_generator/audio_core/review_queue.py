"""冻结章节的集中复核计划；合并试听范围，不消除机器问题或推断人工接受。"""
from __future__ import annotations

import math
from collections import Counter

from .annotations import _verify_pcm_layout
from .quality_review import validate_adjudicated_source
from .repair_review import _read_report, _sha
from .report_sources import resolve_reference_pcm
from .store import fingerprint

VERSION = 'audio-consolidated-review-v1'
DIMENSIONS = ('stitching','consistency','content','signal')


def _priority(issue):
    if issue.get('certainty') == 'confirmed' or issue.get('severity') == 'error':
        return 0, 'confirmed_or_error'
    operations = issue.get('evidence',{}).get('operations',[])
    if issue.get('code') in {'asr_mismatch','boundary_content_mismatch'}:
        if operations and all(op.get('kind') == 'replace' for op in operations):
            return 2, 'asr_substitution_screening'
        return 1, 'content_insertion_deletion_or_unresolved'
    if issue.get('dimension') == 'consistency' and issue.get('code') in {
            'speaker_drift','pitch_drift','rate_drift'}:
        return 3, 'uncalibrated_consistency_screening'
    return 1, 'focused_review'


def build_review_queue(report_path, *, max_window_seconds=45):
    """从当前报告生成单次集中清单；原问题逐一保留并绑定来源。"""
    if (isinstance(max_window_seconds,bool) or not isinstance(max_window_seconds,(int,float))
            or not math.isfinite(max_window_seconds) or max_window_seconds <= 0):
        raise ValueError('合并试听时长须为有限正数')
    source = _read_report(report_path)
    dependencies = validate_adjudicated_source(source)
    report = source['report']
    pcm = resolve_reference_pcm(report,source['path'],require_hash=True)
    _verify_pcm_layout(pcm,report['assembly'],report['chunks'])
    pcm_sha = _sha(pcm)
    spans = report['assembly']['spans']
    rate = report['assembly']['sample_rate']
    by_id = {span['chunk_id']:span for span in spans}
    checks, missing, records, duplicates = [], Counter(), {}, 0
    for index,(item,span) in enumerate(zip(report['chunks'],spans)):
        checks.append(('chunk',index,item['report'],span['start_sample'],span['end_sample']))
        for inner_index,check in enumerate((item.get('composition') or {}).get('internal_reports',[])):
            checks.append((f'internal:{index}',inner_index,check,span['start_sample'],span['end_sample']))
    if len(report['boundaries']) != len(report['assembly']['boundaries']):
        raise ValueError('缺少完整接缝报告，不能汇总后静默遗漏')
    for index,(check,join) in enumerate(zip(report['boundaries'],report['assembly']['boundaries'])):
        left,right = by_id[join['left_chunk_id']],by_id[join['right_chunk_id']]
        checks.append(('boundary',index,check,left['start_sample'],right['end_sample']))
    final = report['final_verification']
    checks.append(('final',0,final,0,report['assembly']['total_samples']))
    for index,check in enumerate(final.get('metrics',{}).get('checks',[])):
        if 'report' in check:check = check['report']
        if check.get('issues'):
            checks.append(('encoded',index,check,0,report['assembly']['total_samples']))
    for scope,index,check,start,end in checks:
        for dimension,status in check.get('dimensions',{}).items():
            if status == 'incomplete':missing[dimension] += 1
        for issue in check.get('issues',[]):
            key = fingerprint({'issue':issue,'start':start,'end':end})
            occurrence = {'scope':scope,'index':index,'scope_id':check.get('scope_id')}
            if key in records:
                records[key]['occurrences'].append(occurrence);duplicates += 1
                continue
            priority,reason = _priority(issue)
            records[key] = {'issue_id':key,'issue':issue,'occurrences':[occurrence],
                'priority':priority,'priority_reason':reason,'start_sample':start,'end_sample':end,
                'global_scope':scope in {'final','encoded'}}
    local = sorted((r for r in records.values() if not r['global_scope']),
                   key=lambda r:(r['start_sample'],r['end_sample'],r['issue_id']))
    windows=[]
    for record in local:
        start,end = record['start_sample'],record['end_sample']
        if (windows and start < windows[-1]['end_sample']
                and ((max(end,windows[-1]['end_sample'])-windows[-1]['start_sample'])/rate <= max_window_seconds
                    or (start == windows[-1]['start_sample'] and end == windows[-1]['end_sample']))):
            windows[-1]['end_sample'] = max(end,windows[-1]['end_sample'])
            windows[-1]['issue_ids'].append(record['issue_id'])
        else:windows.append({'start_sample':start,'end_sample':end,'issue_ids':[record['issue_id']]})
    for window in windows:
        window['priority'] = min(records[key]['priority'] for key in window['issue_ids'])
        window['dimension_priority'] = min(DIMENSIONS.index(records[key]['issue'].get('dimension'))
            if records[key]['issue'].get('dimension') in DIMENSIONS else len(DIMENSIONS) for key in window['issue_ids'])
        window['start_seconds'],window['end_seconds'] = window['start_sample']/rate,window['end_sample']/rate
        window['duration_seconds'] = (window['end_sample']-window['start_sample'])/rate
        window['single_context_exceeds_limit'] = window['duration_seconds'] > max_window_seconds
        window['window_id'] = fingerprint({'pcm':pcm_sha,'start':window['start_sample'],'end':window['end_sample']})[:16]
        window['chunks'] = [{'chunk_id':item['chunk']['chunk_id'],'role_id':item['chunk']['role_id'],
            'source_text':item['chunk']['source_text'],'tts_text':item['chunk']['tts_text']}
            for item,span in zip(report['chunks'],spans)
            if span['start_sample'] < window['end_sample'] and span['end_sample'] > window['start_sample']]
    windows.sort(key=lambda w:(w['priority'],w['dimension_priority'],w['start_sample']))
    # 热点适合定位，但重叠热点不能成为默认逐条任务，否则可能比整章更费时。
    # 默认路线按时间合并区间并仅听一次；较长区间用原章时间轴，不裁剪语音。
    passes=[]
    if any(r['global_scope'] for r in records.values()):
        passes=[{'start_sample':0,'end_sample':report['assembly']['total_samples'],
                 'issue_ids':list(records)}]
    else:
        for window in sorted(windows,key=lambda w:w['start_sample']):
            if passes and window['start_sample'] <= passes[-1]['end_sample']:
                passes[-1]['end_sample']=max(passes[-1]['end_sample'],window['end_sample'])
                passes[-1]['issue_ids'].extend(window['issue_ids'])
            else:
                passes.append({'start_sample':window['start_sample'],'end_sample':window['end_sample'],
                               'issue_ids':list(window['issue_ids'])})
    for segment in passes:
        segment['issue_ids']=list(dict.fromkeys(segment['issue_ids']))
        segment['start_seconds'],segment['end_seconds']=segment['start_sample']/rate,segment['end_sample']/rate
        segment['duration_seconds']=(segment['end_sample']-segment['start_sample'])/rate
    if (_sha(source['path']) != source['report_sha256'] or _sha(source['audio']) != source['encoded_sha256']
            or _sha(pcm) != pcm_sha or any(_sha(d['path']) != d['sha256'] for d in dependencies)):
        raise ValueError('汇总期间来源改变，不能发布过期复核清单')
    return {'version':VERSION,'source_report':source['path'],'source_report_sha256':source['report_sha256'],
        'source_audio':str(source['audio']),'source_audio_sha256':source['encoded_sha256'],
        'reference_pcm':str(pcm),'reference_pcm_sha256':pcm_sha,'review_dependencies':dependencies,
        'quality_status_unchanged':report['quality_status'],'sample_rate':rate,
        'priority_note':'优先级只安排复核顺序；单词替换和未校准提示仍未解决，不自动通过',
        'issues':list(records.values()),'windows':windows,'chronological_review_passes':passes,
        'review_instruction':'按chronological_review_passes顺序集中复核，不逐条重复播放windows；windows仅为可选疑点定位索引',
        'global_issue_ids':[r['issue_id'] for r in records.values() if r['global_scope']],
        'incomplete_check_counts':dict(missing),
        'summary':{'machine_issue_occurrences':len(records)+duplicates,'unique_machine_issues':len(records),
            'exact_duplicate_occurrences':duplicates,'consolidated_windows':len(windows),
            'priority_counts':dict(Counter(r['priority_reason'] for r in records.values())),
            'optional_overlapping_window_seconds':sum(w['duration_seconds'] for w in windows),
            'planned_listening_seconds':sum(s['duration_seconds'] for s in passes)},
        'human_answers_prefilled':False,'requests_sent':0}
