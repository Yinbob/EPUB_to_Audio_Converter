"""记录本轮明确试听反馈，另存已接受局部编辑，不扩大音频上传授权。"""
import copy
import shutil
from pathlib import Path
from flipped_casting_preview_v39 import ROOT, BASE, read, save, sha


def main():
    clone = ROOT / 'listening_review/flipped_r001_clone_20261017'
    repair = ROOT / 'listening_review/flipped_local_repair_20261017'
    out = BASE / 'accepted_local_revision_v44'
    assert not out.exists()
    c, r = read(clone / 'manifest.json'), read(repair / 'manifest.json')
    assert len(c['probes']) == 3 and r['pcm_layout_verified']
    replies = {'clone': '这三条都保留了年轻的音色，像同一个人且内容完整',
               'repair': '内容两条正常，四处停顿合适'}
    ca = {'version': 'flipped-clone-human-acceptance-v44', 'source': 'explicit_user_reply',
        'user_reply': replies['clone'], 'heard_reference_sha256': c['reference_sha256'],
        'samples': [], 'whole_chapter_replacement_accepted': False,
        'further_reference_upload_authorized': False,
        'signal_not_separately_rated': True, 'machine_reports_unchanged': True}
    for sample in c['probes']:
        path = Path(sample['preview_path']); assert sha(path) == sample['preview_sha256']
        assert sha(Path(sample['path'])) == sample['audio_sha256']
        ca['samples'].append({'sample_id': sample['sample_id'], 'heard_path': str(path),
            'heard_audio_sha256': sha(path), 'raw_path': sample['path'],
            'raw_audio_sha256': sample['audio_sha256'], 'preview_gain_db': sample['gain_db'],
            'content_complete': True, 'same_identity_with_other_probes': True,
            'young_timbre_retained': True, 'R001_entire_content_accepted': False})
    save(clone / 'human_acceptance_v44.json', ca)
    ra = {'version': 'flipped-local-repair-human-acceptance-v44', 'source': 'explicit_user_reply',
        'user_reply': replies['repair'], 'accepted_content_samples': [], 'accepted_pause_samples': [],
        'scope': 'two_cropped_utterances_and_four_pause_contexts_only',
        'whole_chapter_listening_complete': False, 'machine_reports_unchanged': True}
    for op in r['operations']:
        path = Path(op['output_path']); assert sha(path) == op['output_sha256']
        if op['sample_id'].startswith('R'):
            ra['accepted_content_samples'].append({'sample_id': op['sample_id'],
                'path': str(path), 'audio_sha256': sha(path), 'content_complete': True,
                'extra_suffix_absent': True})
        else:
            pair = next(p for p in r['preview_pairs'] if p['sample_id'] == op['sample_id'] and p['condition'] == 'after')
            assert sha(Path(pair['path'])) == pair['audio_sha256']
            ra['accepted_pause_samples'].append({**pair, 'pause_seconds': op['pause_after_seconds'], 'natural': True})
    assert len(ra['accepted_content_samples']) == 2 and len(ra['accepted_pause_samples']) == 4
    save(repair / 'human_acceptance_v44.json', ra)
    out.mkdir()
    source = Path(r['output_file']); assert sha(source) == r['output_sha256']
    destination = out / 'chapter_05.local_repairs_accepted.wav'
    shutil.copy2(source, destination); assert sha(destination) == sha(source)
    revision = copy.deepcopy(r)
    revision.update(version='flipped-accepted-local-edits-v44', output_file=str(destination),
        output_sha256=sha(destination), human_review_status='specified_local_edits_accepted',
        acceptance=str(repair / 'human_acceptance_v44.json'),
        whole_chapter_human_review='pending_unreviewed_ranges', Bryce_voice_changed=False)
    save(out / 'manifest.json', revision)
    (out / 'README.md').write_text(f'# 首章局部修复已确认版\n\n[整章音频]({destination})，{r["duration_seconds"]:.2f}秒。\n\n用户已确认R022/R049内容完整且无多读，四处约1秒停顿合适。其余94块不变；Bryce仍为原描述声音。此记录只验收已听的局部编辑，整章其他范围未据此判为通过。\n')
    execution = read(BASE / 'execution_plan.json')
    save(BASE / 'execution_plan.before_v44.json', execution)
    execution.update(status='local_edits_and_clone_probes_accepted_clone_expansion_not_authorized',
        local_edits_human_accepted=True, clone_probes_human_accepted=True,
        accepted_local_revision=str(out / 'manifest.json'),
        clone_human_acceptance=str(clone / 'human_acceptance_v44.json'),
        whole_chapter_human_review='pending_unreviewed_ranges', whole_chapter_voice_replaced=False)
    save(BASE / 'execution_plan.json', execution, overwrite=True)
    print('已记录三条克隆、两条内容修复及四处停顿的真实反馈；另存局部修复已确认版，未新增上传或合成。')


if __name__ == '__main__':
    main()
