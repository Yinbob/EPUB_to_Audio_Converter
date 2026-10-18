"""记录九章质量预审，绑定两个同音频先导包，不填写辨识成绩。"""
from datetime import datetime
from pathlib import Path

import numpy as np
import soundfile as sf

from flipped_casting_preview_v39 import ROOT, read, save, sha
from audiobook_generator.audio_core.annotations import _verify_pcm_layout
from audiobook_generator.audio_core.listening import score_listening
from audiobook_generator.audio_core.repair_review import _read_report
from audiobook_generator.audio_core.report_sources import resolve_reference_pcm


def binding(path):
    path = Path(path).resolve()
    return {'path':str(path),'sha256':sha(path)}


def main():
    review_root = ROOT/'listening_review/casting_english_common_gain_20261016'
    template = review_root/'chapter_review.json'
    pending = read(template)
    assert pending['status'] == 'pending' and len(pending['chapters']) == 9
    rows=[]
    for row in pending['chapters']:
        assert row['human_status'] == 'pending'
        report_path = Path(row['report'])
        assert sha(report_path) == row['report_sha256']
        source = _read_report(report_path)
        pcm = resolve_reference_pcm(source['report'],report_path,require_hash=True)
        _verify_pcm_layout(pcm,source['report']['assembly'],source['report']['chunks'])
        played = review_root/row['audio']
        a,rate = sf.read(played,dtype='int16',always_2d=True)
        b,pcm_rate = sf.read(pcm,dtype='int16',always_2d=True)
        assert rate == pcm_rate and np.array_equal(a,b)
        rows.append({'chapter':row['chapter'],'condition':row['condition'],'scene':row['scene'],
            'played_audio':binding(played),'source_report':binding(report_path),
            'source_pcm':binding(pcm),'duration_seconds':len(a)/rate,
            'human_status':'accepted_for_asked_quality_checks',
            'content_complete':True,'no_repetition_or_omission':True,'joins_acceptable':True,
            'no_obvious_signal_noise':True,'loudness_and_rate_acceptable':True,
            'same_role_consistency_acceptable_within_condition':True})
    acceptance = {'version':'casting-common-gain-material-acceptance-v52',
        'source':'explicit_user_reply','question_item_id':'call_bedf747bd7564f8ea9f6c2dec4063cca:0',
        'user_reply':'9章上述质量检查均正常”','reviewer':'project_user',
        'recorded_at':datetime.now().astimezone().isoformat(),
        'source_pending_template':binding(template),'chapters':rows,
        'same_role_consistency_scope':'within_each_condition_only',
        'total_seconds':sum(r['duration_seconds'] for r in rows),
        'listener_identification_result':False,'independent_listener':False,
        'machine_reports_modified':False,'new_tts_requests':0,'new_llm_requests':0}
    acceptance_path=review_root/'human_acceptance_v52.json'
    save(acceptance_path,acceptance)
    packs=[]
    for folder in ('casting_listener_pilot_20261017','casting_listener_pilot_player_20261017'):
        root=ROOT/'audiobook_output'/folder
        key_path=root/'private_answer_key.json';key=read(key_path)
        assert len(key['answers']) == 36
        for name,expected in key['public_sha256'].items():assert sha(root/'public'/name)==expected
        assert score_listening(key_path,root/'public/responses.csv')['conditions']=={}
        record={'version':'casting-material-quality-release-v52',
            'human_acceptance':binding(acceptance_path),'private_key':binding(key_path),
            'public_sha256':key['public_sha256'],'audio_quality_preflight_complete':True,
            'same_frozen_audio_only':True,'participants':0,'completed_responses':0,
            'listener_identification_results_available':False,
            'player_real_browser_verified':False if 'player' in folder else None,
            'browser_status':'播放器真实浏览器待验收；原JSON/CSV材料可用于描述性先导',
            'condition_note':'interaction与random本批合并，不能比较二者收益',
            'new_tts_requests':0,'new_llm_requests':0}
        release=root/'material_quality_release_v52.json';save(release,record)
        packs.append(binding(release))
    page=review_root/'index.html';backup=review_root/'index.before_acceptance_v52.html'
    assert not backup.exists();backup.write_bytes(page.read_bytes())
    note='<p><strong>最新质量预审：</strong>用户确认九章上述质量检查均正常。结论绑定本版音频，仅记录质量接受，不是角色辨识成绩；原始待审模板和机器报告保留。</p>'
    page.write_text(page.read_text()+note,encoding='utf-8')
    save(ROOT/'docs/validation/audio_core_20261017/casting_material_acceptance_actual_v52.json',{
        'version':'casting-material-acceptance-actual-v52','acceptance':binding(acceptance_path),
        'chapters':9,'total_seconds':acceptance['total_seconds'],'listener_trials':36,
        'released_material_records':packs,'original_pending_template_unchanged':sha(template)==acceptance['source_pending_template']['sha256'],
        'source_reports_unchanged':all(sha(Path(r['source_report']['path']))==r['source_report']['sha256'] for r in rows),
        'participants':0,'new_tts_requests':0,'new_llm_requests':0,'overall_project_complete':False})
    print({'quality_accepted_chapters':9,'seconds':acceptance['total_seconds'],'listener_trials':36,'participants':0})


if __name__ == '__main__':
    main()
