import hashlib
import json
import re
from pathlib import Path

root = Path('/Users/yinzh/PycharmProjects/EPUB_to_Audio_Converter-1')
out = root / 'audiobook_output/casting_english_plan_20261016'
review = root / 'listening_review/casting_english_plan_20261016'
evidence_dir = root / 'docs/validation/audio_core_20261016'
def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(p,v):
    p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
summary = json.loads((out/'offline_validation.json').read_text())
script = json.loads((out/'role_script.proposed.json').read_text())
source = json.loads((out/'source_chapters.json').read_text())
human = json.loads((review/'human_review.pending.json').read_text())
assert sha(Path(summary['voice_bank'])) == summary['voice_bank_sha256']
assert sha(out/'source_chapters.json') == script['book_sha256'] == summary['source_container_sha256']
assert human['status'] == 'pending' and human['reviewer'] is None
assert len(human['role_assignments']) == 12
assert all(x['accepted'] is None and x['corrected_role'] is None for x in human['role_assignments'])
assert all(v is None for values in human['fit_penalties'].values() for v in values.values())
assert all(not x['voice_locked'] for x in script['entities'].values())
base = None
word_counts = []
for condition in summary['conditions']:
    plans = json.loads((out/f"plans.{condition['strategy']}.json").read_text())
    signature = []
    for ci,(plan,src) in enumerate(zip(plans,source),1):
        assert len(plan['units']) == 4
        assert ''.join(u['text'] for u in plan['units']) == src['text']
        for unit in plan['units']:
            params = unit['profile']['provider_params']
            assert params['voice'] == condition['assignment'][unit['role_id']]
            assert params['speed'] == 1.0 and unit['tone'] is None
            signature.append((unit['unit_id'], unit['role_id'], unit['text'], unit['source_span'],
                              unit['pause_after_ms'], params['instructions'], params['speed']))
    if base is None:
        base = signature
        word_counts = [len(re.findall(r"\b[A-Za-z]+(?:'[A-Za-z]+)?\b",x[2])) for x in signature]
    else:
        assert signature == base
for chapter,src in zip(script['chapters'],source):
    assert ''.join(s['text'] for s in chapter['segments']) == src['text']
    for s in chapter['segments']:
        span = s['source_span']
        assert src['text'][span['start']:span['end']] == s['text']
        assert s['speaker']['status'] == 'proposed'
readme = review/'README.md'
links = re.findall(r'\]\(([^)]+)\)',readme.read_text())
for link in links:
    assert (readme.parent/link).resolve().is_file(),link
hashes = {str(p.relative_to(root)):sha(p) for folder in (out,review)
          for p in sorted(folder.iterdir()) if p.is_file() and p.name!='artifact_hashes.json'}
dump(out/'artifact_hashes.json',hashes)
evidence = {
    'version':'casting_english_materials_v24','execution':'completed_offline_only',
    'purpose':'准备选角先导正文及分配，检查真实已核验英语声音库上的分配与约束',
    'summary':str(out/'offline_validation.json'),'summary_sha256':sha(out/'offline_validation.json'),
    'review_readme':str(readme),'artifact_manifest':str(out/'artifact_hashes.json'),
    'artifact_manifest_sha256':sha(out/'artifact_hashes.json'),
    'checks':{'source_spans_and_hashes':True,'three_conditions_fixed_nonvoice_variables':True,
              'roles_proposed_not_confirmed':True,'human_answers_and_fit_table_blank':True,
              'all_review_links_resolve':True,'verified_bank_unchanged':True,
              'client_constructor_disabled_during_preparation':True},
    'text_word_counts_not_measured_audio_durations':word_counts,
    'observed_result':'互动图与 seed=42 随机分配相同；全局互换两种声音，共享角色关系和公共代理值相同；未展示策略优势。',
    'participant_count':0,'new_tts_requests':0,'audio_generated':False,
    'synthetic_lock_check_not_user_lock':True,'new_training_data':False,
    'production_code_changed':False,'full_test_suite_rerun':False,
    'latest_existing_full_regression':{'ran':507,'skipped':30,'status':'OK',
                                      'log':'reevaluation_source_regression_v23.log'},
    'source_code_sha256':{str(p.relative_to(root)):sha(p) for p in [
        root/'audiobook_generator/audio_core/casting.py',
        root/'audiobook_generator/role_script/planner.py']},
    'pending':['正文与角色归属人工审查','人工声音适配表','E06T 人工试听确认；Milo 仍未入库',
               '英文数字先导人工核验','更多独立来源、质量合格音频和听众辨识实验',
               '真实边界阳性与独立划分；不得用本材料训练或证明质量检出效果'],
}
dump(evidence_dir/'casting_english_materials_v24.json',evidence)
aggregate_path = evidence_dir/'engineering_evidence.json'
aggregate = json.loads(aggregate_path.read_text())
assert 'casting_english_materials_v24' not in aggregate
aggregate['casting_english_materials_v24'] = evidence
dump(aggregate_path,aggregate)
print(json.dumps({'status':'OK','checked_links':len(links),'artifact_count':len(hashes),
                  'tts_requests':0,'human_review':'pending','word_counts':word_counts},ensure_ascii=False))
