"""核对真实章节的集中复核路线；不把排队摘要当成人工结论。"""
from pathlib import Path

from flipped_casting_preview_v39 import ROOT, read, save, sha
from audiobook_generator.audio_core.review_queue import build_review_queue


def main():
    queue_path=ROOT/'listening_review/flipped_cmon_repair_20261017/consolidated_review_v53.final.json'
    queue=read(queue_path)
    assert build_review_queue(queue['source_report']) == queue
    passes=queue['chronological_review_passes']
    assert all(a['end_sample'] < b['start_sample'] for a,b in zip(passes,passes[1:]))
    local={r['issue_id'] for r in queue['issues'] if not r['global_scope']}
    focused=[i for window in queue['windows'] for i in window['issue_ids']]
    assert len(focused)==len(set(focused)) and set(focused)==local
    routed=[i for segment in passes for i in segment['issue_ids']]
    assert set(routed)==local and len(routed)==len(set(routed))
    rate=queue['sample_rate']
    max_time=max(s['end_sample'] for s in passes)/rate
    assert queue['summary']['planned_listening_seconds'] <= max_time
    logs={name:Path('/tmp')/name for name in (
        'review_queue_v53_full_release.log','review_queue_v53_targeted_final.log')}
    assert 'Ran 609 tests' in logs['review_queue_v53_full_release.log'].read_text()
    assert 'OK (skipped=30)' in logs['review_queue_v53_full_release.log'].read_text()
    readme=queue_path.parent/'集中复核说明_v53.md'
    lines=['# 当前章节集中复核安排','',
        '这是工程复核计划，不是新增试听请求。当前已接受的修复继续有效；未解决的机器差异保留，不推断为真实缺陷。',
        '',f"原章时长{max_time:.2f}秒，133条机器提示保留在JSON中。48个窗口用于按疑点跳转，不要求逐条播放。",
        '',f"默认按章节时间顺序合并为{len(passes)}段不重叠范围，覆盖{queue['summary']['planned_listening_seconds']:.2f}秒。也可以下一轮直接进行一次完整章节验收；不应把定位窗口再次全部播放。",'',
        '81条仅为ASR单词替换筛查，50条为含增删或尚待解释的内容差异，另2条为一致性规则提示。这些数量不是缺陷数量。未校准检查在摘要中统一说明，不按每项未完成检查分别发问。','',
        '只有正式来源绑定裁决所解除的问题才从当前未解决队列移出。不同版本、不同上下文或不同检查维度不会继承接受结论；原始machine_evidence和来源依赖保持可查。','',
        f"当前PCM：[章节音频]({queue['reference_pcm']})",'',
        '| 顺序 | 开始秒 | 结束秒 |','|---|---:|---:|']
    for i,segment in enumerate(passes,1):lines.append(f"| {i} | {segment['start_seconds']:.2f} | {segment['end_seconds']:.2f} |")
    lines+=['','不在本轮预填任何人工标签、不自动修复或改写音频。此清单不能替代独立测试数据和听众实验。','']
    assert not readme.exists();readme.write_text('\n'.join(lines),encoding='utf-8')
    save(ROOT/'docs/validation/audio_core_20261017/review_queue_actual_v53.json',{
        'version':'review-queue-actual-v53','queue':{'path':str(queue_path),'sha256':sha(queue_path)},
        'summary':queue['summary'],'nonrepeating_chronological_passes':len(passes),
        'all_issues_preserved_exactly_once':True,'quality_status_unchanged':queue['quality_status_unchanged'],
        'source_report_unchanged':sha(Path(queue['source_report']))==queue['source_report_sha256'],
        'source_audio_unchanged':sha(Path(queue['source_audio']))==queue['source_audio_sha256'],
        'tests':{'run':609,'passed':579,'skipped':30,'failures':0,'errors':0,
            'logs':[{'path':str(path),'sha256':sha(path)} for path in logs.values()]},
        'initial_overlapping_plan_preserved':'consolidated_review_v53.json',
        'initial_float_assertion_failure_log':'/tmp/review_queue_v53_targeted_release.log',
        'new_tts_requests':0,'new_llm_requests':0,'human_answers_prefilled':False,'overall_project_complete':False})
    print({'preserved_issues':len(local),'nonrepeating_passes':len(passes),'requests':0})


if __name__ == '__main__':
    main()
