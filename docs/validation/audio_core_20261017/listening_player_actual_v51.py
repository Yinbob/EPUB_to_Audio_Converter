"""另存带离线页面的同题先导草稿；原v50材料与空白回答不变。"""
import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from flipped_casting_preview_v39 import ROOT, read, save, sha
from audiobook_generator.audio_core.listening import prepare_listening, score_listening


def main():
    original = ROOT/'audiobook_output/casting_listener_pilot_20261017'
    output = ROOT/'audiobook_output/casting_listener_pilot_player_20261017'
    conditions = ROOT/'audiobook_output/mimo_casting_english_common_gain_20261016/conditions.human_reviewed_v50.json'
    prior = read(ROOT/'docs/validation/audio_core_20261017/casting_listener_actual_v50.json')
    assert sha(conditions) == prior['conditions']['sha256']
    old_key = read(original/'private_answer_key.json')
    with patch('openai.OpenAI',side_effect=AssertionError('本次禁止API请求')):
        result = prepare_listening(read(conditions),output)
        assert score_listening(output/'private_answer_key.json',output/'public/responses.csv')['conditions'] == {}
    new_key = read(output/'private_answer_key.json')
    assert new_key['answers'] == old_key['answers']
    assert new_key['sources'] == old_key['sources']
    assert (original/'public/trials.json').read_bytes() == (output/'public/trials.json').read_bytes()
    assert (original/'public/responses.csv').read_bytes() == (output/'public/responses.csv').read_bytes()
    for name,expected in old_key['public_sha256'].items():
        assert sha(original/'public'/name) == expected
        if name.startswith('audio/'):
            assert sha(output/'public'/name) == expected
    node = '/opt/homebrew/bin/node'
    events = subprocess.run([node,str(ROOT/'tests/audiobook_generator/audio_core/listening_player_test.js'),
        str(output/'public/index.html')],check=True,capture_output=True,text=True,timeout=10)
    synthetic = json.loads(events.stdout)
    assert synthetic['synthetic_only'] is True
    with tempfile.TemporaryDirectory() as temporary:
        csv = Path(temporary)/'synthetic_qa.csv'
        csv.write_text(synthetic['csv'],encoding='utf-8')
        score = score_listening(output/'private_answer_key.json',csv)
        assert sum(c['total'] for c in score['conditions'].values()) == 1
    # 不保存构造回答，不污染真实空白表或听众统计。
    status = {**read(original/'material_status.json'),
        'version':'casting-listener-player-status-v51', 'draft_only':True,
        'real_browser_verified':False, 'visual_review':'recapture_required_policy_blocked',
        'browser_block':'浏览器工具禁止打开file://，未以其他浏览器、服务或间接执行绕过',
        'offline_event_logic_verified':True, 'synthetic_responses_saved':False,
        'source_material':str(original), 'same_trials_and_audio_as_source':True}
    save(output/'material_status.json',status)
    save(ROOT/'docs/validation/audio_core_20261017/listening_player_actual_v51.json',{
        'version':'listening-player-actual-v51','export':result,'public_page':str(output/'public/index.html'),
        'page_sha256':sha(output/'public/index.html'),'verified_public_files':len(new_key['public_sha256']),
        'same_trial_ids_answers_sources_and_audio':True,'old_pack_unchanged':True,
        'empty_real_responses':True,'synthetic_event_test_passed':True,'real_browser_verified':False,
        'independent_static_review':'未发现必须修复的代码/数据泄露/CSV互操作问题；不涵盖实际浏览器',
        'visual_review_disposition':'recapture','screenshots_available':False,
        'contrast':{'minimum_declared_text_ratio':4.96,'disabled_opacity_removed':True,
            'detector_false_positive':'dark #b8b8c0 paired with light-only #ffffff',
            'actual_dark_secondary_ratios':[7.95,9.17],
            'exception_scope':'low-contrast only in listening_player.html'},
        'tests':{'full_run':604,'full_passed':574,'skipped':30,'failures':0,'errors':0,
            'full_log':'/tmp/listening_player_v51_full.log','full_seconds':19.121,
            'final_targeted':21,'final_targeted_log':'/tmp/listening_player_v51_final_targeted.log'},
        'whole_material_human_review_pending':True,'listener_results_available':False,
        'new_tts_requests':0,'new_llm_requests':0,'overall_project_complete':False,
    })
    print({'trials':result['trials'],'draft_only':True,'real_browser_verified':False,'requests':0})


if __name__ == '__main__':
    main()
