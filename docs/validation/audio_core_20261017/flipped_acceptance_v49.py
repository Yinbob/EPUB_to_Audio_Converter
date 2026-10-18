"""绑定本轮人工结论，验证正式裁决入口，汇集已核验修复个案；不合成。"""
from datetime import datetime
from pathlib import Path

from flipped_casting_preview_v39 import ROOT, BASE, read, save, sha
from audiobook_generator.audio_core.quality_review import (
    VERSION, adjudicate_quality, validate_adjudicated_source,
)
from audiobook_generator.audio_core.repair_review import _read_report
from audiobook_generator.audio_core.store import ArtifactStore, fingerprint
from audiobook_generator.ui.audio_quality import load_quality_report

DEST = ROOT/'listening_review/flipped_cmon_repair_20261017'
REPLY = '只读一次，发音与接缝均正常'


def binding(path):
    path = Path(path).resolve()
    return {'path':str(path), 'sha256':sha(path)}


def checked(row):
    path = Path(row['path'])
    assert sha(path) == row['audio_sha256']
    return {'sample_id':row['sample_id'], 'path':str(path), 'audio_sha256':sha(path)}


def main():
    v48 = read(ROOT/'docs/validation/audio_core_20261017/flipped_cmon_repair_v48.json')
    m = read(DEST/'assembly_manifest.json')
    assert sha(DEST/'assembly_manifest.json') == v48['manifest_sha256']
    assert sha(Path(m['output_file'])) == m['audio_sha256']
    acceptance = {'version':'flipped-cmon-local-human-acceptance-v49',
        'source':'explicit_user_reply', 'user_reply':REPLY,
        'recorded_at':datetime.now().astimezone().isoformat(),
        'source_manifest':binding(DEST/'assembly_manifest.json'),
        'source_chapter':binding(m['output_file']),
        'accepted_content_sample':{**checked(m['items'][33]),
            'source_text':m['items'][33]['text'], 'tts_text':m['chunks'][33]['chunk']['tts_text'],
            'content_complete':True, 'no_additions':True, 'pronunciation_acceptable':True},
        'accepted_contexts':[{**binding(r['path']), 'target_at_seconds':r['target_at_seconds'],
            'adjacent_joins_natural':True} for label,r in v48['contexts'].items() if label == 'after'],
        'identity_accepted':None, 'signal_separately_rated':None,
        'scope':'R034_single_reading_pronunciation_and_adjacent_joins_only',
        'whole_chapter_listening_complete':False, 'machine_reports_unchanged':True}
    acceptance_path = DEST/'human_acceptance_v49.json'
    save(acceptance_path, acceptance)
    standard_path = Path(v48['standard_report'])
    assert sha(standard_path) == v48['standard_report_sha256']
    original = read(standard_path)
    check = original['chunks'][33]['report']
    issue = next(i for i in check['issues'] if i['code'] == 'asr_mismatch')
    review = {'version':VERSION, 'source_report_sha256':sha(standard_path),
        'source_audio_sha256':m['audio_sha256'], 'reviewer':'project_user',
        'reviewed_at':acceptance['recorded_at'],
        'human_acceptance':binding(acceptance_path),
        'decisions':[{'scope':'chunk', 'index':33, 'issue_sha256':fingerprint(issue),
            'resolution':'false_positive', 'reason':REPLY,
            'verified_tts_text':m['chunks'][33]['chunk']['tts_text'],
            'content_complete':True, 'no_additions':True}]}
    review_path = DEST/'asr_review_v49.json'; save(review_path, review)
    derived = adjudicate_quality(standard_path, review_path)
    out = standard_path.with_name('quality.human_reviewed_v49.json')
    save(out, derived)
    assert len(validate_adjudicated_source(_read_report(out))) == 2
    resolved = derived['chunks'][33]['report']
    assert resolved['dimensions']['content'] == 'passed'
    assert resolved['dimensions']['consistency'] == check['dimensions']['consistency'] == 'incomplete'
    assert resolved['machine_evidence'] == check
    assert sha(standard_path) == v48['standard_report_sha256']
    assert len(load_quality_report(out)[2]) == 200

    # 同一书、同一章、同一原始谱系统一分组，J076两个版本不冒充独立样本。
    cases = []
    group = 'e89f8bdf8d54aeae297aa3d34798142c94382187243e621051a35d6c7db20011:chapter5'
    def add(case_id,kind,before,after,feedback_path,acceptance_path,before_evidence,after_evidence):
        assert sha(Path(before['path'])) == before['audio_sha256']
        assert sha(Path(after['path'])) == after['audio_sha256']
        assert before_evidence['audio_sha256'] == before['audio_sha256']
        assert after_evidence['audio_sha256'] == after['audio_sha256']
        cases.append({'case_id':case_id,'kind':kind,'group_id':group,
            'before':checked(before),'after':checked(after),
            'defect_feedback':binding(feedback_path),'repair_acceptance':binding(acceptance_path),
            'partial_before_labels':{'unexpected_gap':True} if kind=='long_pause' else {'content_repetition_or_extra_reading':True},
            'partial_after_labels':{'unexpected_gap':False} if kind=='long_pause' else {'content_repetition_or_extra_reading':False},
            'unmentioned_labels':'unknown','training_eligible':False,
            'split':'unassigned','human_verified_repair_only':True})
    p0 = ROOT/'listening_review/flipped_full_chapter_20261017'
    p1 = ROOT/'listening_review/flipped_local_repair_20261017'
    p2 = ROOT/'listening_review/flipped_bryce_clone_chapter_20261017'
    p3 = ROOT/'listening_review/flipped_clone_local_repair_20261017'
    baseline = read(p0/'review_manifest.json')
    feedback = read(p0/'human_feedback_v42.json'); accepted = read(p1/'human_acceptance_v44.json')
    for defect in feedback['content_defects']:
        after = next(r for r in accepted['accepted_content_samples'] if r['sample_id'] == defect['sample_id'])
        before = next(r for r in baseline['items'] if r['sample_id'] == defect['sample_id'])
        add('original:'+defect['sample_id'],'extra_suffix',before,after,
            p0/'human_feedback_v42.json',p1/'human_acceptance_v44.json',defect,after)
    for defect in feedback['long_pauses']:
        before = next(r for r in baseline['boundaries'] if r['sample_id'] == defect['sample_id'])
        after = next(r for r in accepted['accepted_pause_samples'] if r['sample_id'] == defect['sample_id'])
        add('original:'+defect['sample_id'],'long_pause',before,after,
            p0/'human_feedback_v42.json',p1/'human_acceptance_v44.json',defect,after)
    baseline = read(p2/'review_manifest.json'); feedback = read(p2/'human_feedback_v46.json')
    accepted = read(p3/'human_acceptance_v47.json')
    for defect in feedback['confirmed_defects']:
        if defect['sample_id'].startswith('J'):
            before = next(r for r in baseline['boundaries'] if r['sample_id'] == defect['sample_id'])
            after = accepted['accepted_pause_context']; kind = 'long_pause'
        else:
            before = next(r for r in baseline['items'] if r['sample_id'] == defect['sample_id'])
            after = next(r for r in accepted['accepted_content_samples'] if r['sample_id'] == defect['sample_id'])
            kind = 'extra_suffix'
        add('clone:'+defect['sample_id'],kind,before,after,
            p2/'human_feedback_v46.json',p3/'human_acceptance_v47.json',defect,after)
    before = read(p3/'assembly_manifest.json')['items'][33]
    evidence = read(DEST/'human_feedback_v48.json')
    add('clone:R034','pronunciation_restart',before,m['items'][33],DEST/'human_feedback_v48.json',
        acceptance_path,evidence,acceptance['accepted_content_sample'])
    assert len(cases) == 10 and len({r['case_id'] for r in cases}) == 10
    corpus = {'version':'flipped-reviewed-repair-cases-v49','cases':cases,
        'case_count':10,'unique_source_groups':1,
        'selected_after_discovery':True,'independent_test_set':False,
        'population_success_rate_estimable':False,'not_boundary_training_rows':True,
        'note':'这些已成功修复的回顾个案不能估计总体修复成功率；未提及的标签保持未知。'}
    corpus_path = BASE/'reviewed_repair_cases_v49.json'; save(corpus_path, corpus)
    plan_path = BASE/'execution_plan.json'; plan = read(plan_path)
    save(BASE/'execution_plan.before_v49.json',plan)
    plan.update(status='reviewed_local_edits_accepted_full_chapter_review_pending',
        latest_chapter_candidate=m['output_file'],latest_chapter_sha256=m['audio_sha256'],
        cmon_repair_human_acceptance=str(acceptance_path),cmon_repair_human_acceptance_sha256=sha(acceptance_path),
        latest_reviewed_quality_report=str(out),latest_reviewed_quality_report_sha256=sha(out),
        cmon_repair_human_review='single_reading_pronunciation_and_joins_accepted',
        reviewed_repair_cases=str(corpus_path),whole_chapter_listening_complete=False,overall_project_complete=False)
    save(plan_path,plan,overwrite=True)
    # 页面和说明追加当前结论，保留生成时的待审记录和所有原始机器证据。
    page_path = DEST/'index.html'; page = page_path.read_text()
    save(DEST/'index.before_acceptance_v49.json',{'html':page,'sha256':sha(page_path)})
    note = '<section><h2>最新人工确认</h2><p>用户已确认：“只读一次，发音与接缝均正常”。仅覆盖此处R034及相邻衔接；整章尚未全量人工验收。原机器报告保留，单句ASR误报另存人工裁决报告；声纹等未完成检查未改为通过。</p></section>'
    page_path.write_text(page.replace('</html>',note+'</html>'),encoding='utf-8')
    with (DEST/'README.md').open('a',encoding='utf-8') as stream:
        stream.write('\n最新人工反馈（v49）：只读一次，发音与接缝均正常。接受记录见human_acceptance_v49.json；仅接受R034及相邻衔接，原机器提示保持。逐问题ASR误报裁决另存，不将声纹未完成或整章状态改为通过。\n')
    save(ROOT/'docs/validation/audio_core_20261017/asr_adjudication_actual_v49.json',{
        'version':'asr-adjudication-actual-v49','acceptance':binding(acceptance_path),
        'derived_report':binding(out),'review':binding(review_path),'case_registry':binding(corpus_path),
        'cases':10,'unique_groups':1,'human_content_resolution':'R034_only',
        'consistency_stays_incomplete':True,'original_machine_report_unchanged':True,
        'preview_count':200,'new_tts_requests':0,'new_llm_requests':0,'overall_project_complete':False})
    print('R034人工确认已登记；ASR误报正式裁决保留声纹未完成；10个回顾个案同组未划分。')


if __name__ == '__main__':
    main()
