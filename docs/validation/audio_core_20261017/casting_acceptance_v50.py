"""将两处最终上下文的明确人工回复绑定原件，另存裁决并导出待核验先导包。"""
import copy
import csv
from collections import Counter
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from flipped_casting_preview_v39 import ROOT, read, save, sha
from audiobook_generator.audio_core.listening import (
    _listening_source, prepare_listening, score_listening,
)
from audiobook_generator.audio_core.quality_review import (
    VERSION, adjudicate_quality, validate_adjudicated_source,
)
from audiobook_generator.audio_core.repair_review import _read_report
from audiobook_generator.audio_core.store import fingerprint

SOURCE = ROOT/'audiobook_output/mimo_casting_english_common_gain_20261016'
FOCUS = ROOT/'listening_review/casting_final_focus_20261017'
OUTPUT = ROOT/'audiobook_output/casting_listener_pilot_20261017'
REPLY = 'T01、T02均完整，接缝正常'


def binding(path):
    path = Path(path).resolve()
    return {'path':str(path), 'sha256':sha(path)}


def main():
    manifest_path = FOCUS/'manifest.json'
    focused = read(manifest_path)
    evidence = read(ROOT/'docs/validation/audio_core_20261017/casting_focus_v50.json')
    assert sha(manifest_path) == evidence['manifest_sha256']
    samples = focused['samples']
    assert [r['sample_id'] for r in samples] == ['T01','T02']
    for row in samples:
        assert sha(Path(row['audio_path'])) == row['audio_sha256']
        assert sha(Path(row['source_report'])) == row['source_report_sha256']
    acceptance = {
        'version':'casting-final-focus-human-acceptance-v50',
        'source':'explicit_user_reply', 'user_reply':REPLY,
        'recorded_at':datetime.now().astimezone().isoformat(),
        'source_manifest':binding(manifest_path),
        'samples':[{
            'sample_id':r['sample_id'], 'audio':binding(r['audio_path']),
            'source_report':binding(r['source_report']), 'boundary_index':r['boundary_index'],
            'scope_id':r['scope_id'], 'verified_context_text':r['text'],
            'content_complete':True, 'bring_complete':True,
            'no_repetition_or_omission':True, 'joins_natural':True,
        } for r in samples],
        'whole_chapter_listening_complete':False, 'listener_identification_response':False,
        'identity_or_preference_score':None, 'machine_reports_unchanged':True,
        'new_tts_requests':0, 'new_llm_requests':0,
    }
    acceptance_path = FOCUS/'human_acceptance_v50.json'
    save(acceptance_path,acceptance)
    replacements, derived_records = {}, []
    for row in samples:
        source_path = Path(row['source_report'])
        source = _read_report(source_path)
        boundary = source['report']['boundaries'][row['boundary_index']]
        assert boundary['scope_id'] == row['scope_id']
        assert boundary['issues'] == [row['source_issue']]
        review_path = FOCUS/f"{row['sample_id']}.quality_review_v50.json"
        save(review_path,{
            'version':VERSION, 'source_report_sha256':source['report_sha256'],
            'source_audio_sha256':source['encoded_sha256'], 'reviewer':'project_user',
            'reviewed_at':acceptance['recorded_at'],
            'human_acceptance':binding(acceptance_path),
            'decisions':[{'scope':'boundary','index':row['boundary_index'],
                'issue_sha256':fingerprint(row['source_issue']),
                'resolution':'false_positive','reason':REPLY}],
        })
        derived = adjudicate_quality(source_path,review_path)
        destination = SOURCE/'reviewed_v50'/source_path.relative_to(SOURCE)
        save(destination,derived)
        assert len(validate_adjudicated_source(_read_report(destination))) == 2
        resolved = derived['boundaries'][row['boundary_index']]
        assert resolved['dimensions']['content'] == 'passed' and not resolved['issues']
        assert resolved['machine_evidence'] == boundary
        assert sha(source_path) == row['source_report_sha256']
        replacements[str(source_path)] = str(destination)
        derived_records.append(binding(destination))

    conditions = copy.deepcopy(read(SOURCE/'conditions.evaluated.json'))
    originals = {p:sha(Path(p)) for c in conditions for p in c['report_paths']}
    for condition in conditions:
        condition['report_paths'] = [replacements.get(p,p) for p in condition['report_paths']]
        for path in condition['report_paths']:
            _listening_source(path)
    conditions_path = SOURCE/'conditions.human_reviewed_v50.json'
    save(conditions_path,conditions)
    # 导出和评分均为离线处理，不允许误触合成接口。
    with patch('openai.OpenAI',side_effect=AssertionError('本次禁止API请求')):
        exported = prepare_listening(conditions,OUTPUT)
        empty_score = score_listening(OUTPUT/'private_answer_key.json',OUTPUT/'public/responses.csv')
    key = read(OUTPUT/'private_answer_key.json')
    public = read(OUTPUT/'public/trials.json')
    with (OUTPUT/'public/responses.csv').open(newline='',encoding='utf-8') as stream:
        responses = list(csv.DictReader(stream))
    assert len(responses) == len(public['trials']) == exported['trials'] == 36
    assert all(not r['participant_id'] and not r['response_role'] for r in responses)
    assert empty_score['conditions'] == {}
    assert set(key['answers']) == {t['trial_id'] for t in public['trials']}
    for trial in public['trials']:
        assert set(trial) == {'trial_id','audio','reference_voices','question'}
        assert set(trial['reference_voices']) == {'角色1','角色2','角色3'}
        answer = key['answers'][trial['trial_id']]
        assert trial['audio'] != trial['reference_voices'][answer['correct_role']]
    assert all(sha(OUTPUT/'public'/name) == expected for name,expected in key['public_sha256'].items())
    assert all(sha(Path(path)) == expected for path,expected in originals.items())
    counts = Counter((a['condition'],a['source_role']) for a in key['answers'].values())
    assert len(counts) == 9 and all(n > 0 for n in counts.values())
    # 保存本次范围，不把两个上下文的接受推广为九章人工验收。
    save(OUTPUT/'material_status.json',{
        'version':'casting-listener-material-status-v50',
        'human_acceptance':binding(acceptance_path),
        'source_conditions':binding(conditions_path), 'draft_ready':True,
        'whole_chapter_listening_complete':False, 'full_material_human_review_required':True,
        'participants':0, 'completed_responses':0, 'statistical_benefit_established':False,
        'condition_note':'interaction与random的分配相同，合并为一个条件，不作二者收益比较',
        'new_tts_requests':0, 'new_llm_requests':0,
    })
    page = FOCUS/'index.html'
    backup = FOCUS/'index.before_acceptance_v50.html'
    assert not backup.exists()
    backup.write_bytes(page.read_bytes())
    note = '<p><strong>最新人工核验：</strong>T01、T02均完整，接缝正常。已另存逐项误报裁决，原始告警保留。此确认仅覆盖本页两处完整上下文，不代表九章整章或听众辨识成绩。</p>'
    page.write_text(page.read_text().replace('</html>',note+'</html>'),encoding='utf-8')
    result = {
        'version':'casting-listener-export-actual-v50',
        'acceptance':binding(acceptance_path), 'derived_reports':derived_records,
        'conditions':binding(conditions_path), 'export':exported,
        'quality_gates_passed':9, 'conditions_count':3, 'scenes_per_condition':3,
        'roles':3, 'trials':36, 'public_checksums_verified':len(key['public_sha256']),
        'trial_counts':[{'condition':c,'role':r,'trials':n} for (c,r),n in sorted(counts.items())],
        'unanswered_score':empty_score, 'original_reports_unchanged':True,
        'focused_audio_unchanged':all(sha(Path(r['audio_path'])) == r['audio_sha256'] for r in samples),
        'whole_chapter_listening_complete':False, 'independent_listener_results':False,
        'new_tts_requests':0, 'new_llm_requests':0, 'overall_project_complete':False,
    }
    save(ROOT/'docs/validation/audio_core_20261017/casting_listener_actual_v50.json',result)
    print({'trials':36,'quality_gates_passed':9,'conditions':3,'participants':0,'requests':0})


if __name__ == '__main__':
    main()
