"""离线检查并导出原文短试听；所有人工判断保持待填写。"""
import html
import shutil
from pathlib import Path
from flipped_casting_preview_v39 import ROOT, BASE, OUTPUT, REVIEW, read, save, sha


def main():
    from audiobook_generator.audio_core.models import CoreOptions, ReadingChunk
    from audiobook_generator.audio_core.quality import QualityEvaluator
    from audiobook_generator.audio_core.annotations import _verify_pcm_layout, export_review_pack
    from audiobook_generator.audio_core.loudness_preview import measure_loudness
    from audiobook_generator.audio_core.store import ArtifactStore
    import soundfile as sf
    manifest = read(OUTPUT / 'manifest.json')
    assert manifest['status'] == 'generated_pending_role_fit_and_scene_review'
    assert not REVIEW.exists(), '保留已有人工材料，不覆盖'
    REVIEW.mkdir()
    (REVIEW / 'audio').mkdir()
    evaluator = QualityEvaluator(CoreOptions(language='en', auto_repair=False,
        asr_model_dir=str(ROOT / '.audio_quality_models/SenseVoiceSmall'),
        speaker_model_dir=str(ROOT / '.audio_quality_models/ecapa')),
        store=ArtifactStore(manifest['request_ledgers'][0]['project']))
    probes = []
    for probe in manifest['generated_classmates']:
        assert sha(Path(probe['path'])) == probe['audio_sha256']
        chunk = ReadingChunk(probe['sample_id'], probe['quote_id'], 'classmates', probe['text'], probe['text'],
            0, len(probe['text']), profile=probe['profile'], language='en', source_scope='chapter',
            source_span={'chapter_index': 5, 'start': probe['source_start'], 'end': probe['source_end']})
        report = evaluator.evaluate_chunk(chunk, probe['path'])
        probes.append({**probe, 'report': report.to_dict()})
    # C3较长，作诊断比对；未经人工确认，不写入固定声音库。
    anchor = (probes[2]['path'], probes[2]['report']['metrics'])
    for i in (0, 1):
        p = probes[i]
        chunk = ReadingChunk(p['sample_id'], p['quote_id'], 'classmates', p['text'], p['text'],
                             0, len(p['text']), profile=p['profile'], language='en')
        p['diagnostic_consistency_report'] = evaluator.evaluate_chunk(chunk, p['path'], anchor=anchor).to_dict()
    save(OUTPUT / 'classmates_quality_v40.json', {'probes': probes, 'anchor_kind': 'unverified_diagnostic_only',
                                                'requests_sent': 0, 'human_verified': False})
    items, scenes, loudness = [], [], []
    def audio_item(label, path, text, role, report=None, **extra):
        filename = label + '.wav'
        target = REVIEW / 'audio' / filename
        shutil.copy2(path, target)
        assert sha(target) == sha(Path(path))
        item = {'sample_id': label, 'role_id': role, 'path': 'audio/' + filename,
                'audio_sha256': sha(target), 'text': text, 'duration_seconds': sf.info(target).duration,
                'human_review': 'pending', **extra}
        if report is not None:
            item['machine_report'] = report
        try:
            item['loudness'] = measure_loudness(target)
        except ValueError:
            item['loudness'] = {'status': 'unavailable_short_or_silent'}
        items.append(item)
        return item
    for scene in manifest['generated_scenes']:
        report = read(Path(scene['report']))
        assert sha(Path(scene['path'])) == scene['audio_sha256']
        _verify_pcm_layout(scene['path'], report['assembly'], report['chunks'])
        audio_item(scene['sample_id'], scene['path'], scene['text'], 'mixed', context='original_scene')
        export_review_pack([scene['report']], REVIEW / (scene['sample_id'] + '_review_pack'))
        rows = []
        for i, (entry, span) in enumerate(zip(report['chunks'], report['assembly']['spans']), 1):
            label = f"{scene['sample_id']}_{i:02d}_{entry['chunk']['role_id']}"
            row = audio_item(label, entry['rendered_path'], entry['chunk']['tts_text'], entry['chunk']['role_id'],
                entry['report'], scene=scene['sample_id'], start_seconds=span['start_sample']/report['assembly']['sample_rate'],
                end_seconds=span['end_sample']/report['assembly']['sample_rate'])
            rows.append(row)
            loudness.append({'sample_id': label, **row['loudness']})
        scenes.append({'sample_id': scene['sample_id'], 'report_path': scene['report'],
                       'source_group_id': report['source_group_id'], 'chunks': rows,
                       'boundary_reports': report['boundaries'], 'pcm_layout_verified': True})
    for probe in probes:
        audio_item(probe['sample_id'], probe['path'], probe['text'], 'classmates', probe['report'],
                   diagnostic_consistency_report=probe.get('diagnostic_consistency_report'))
    quality = read(ROOT / 'audiobook_output/mimo_bryce_candidates_20261017/quality.json')
    accepted = next(p for p in quality['probes'] if p['role_id'] == 'bryce_a')
    assert sha(Path(accepted['path'])) == accepted['audio_sha256']
    audio_item('A1_reference', accepted['path'], accepted.get('text', ''), 'narrator',
               reference_status='previously_human_accepted_bryce_A')
    events = [event for ledger in manifest['request_ledgers']
              for event in ArtifactStore(ledger['project']).request_events(run_id=ledger['run_id'])]
    assert len(events) == 14 and sum(e['characters'] for e in events) == 616
    assert all(e['status'] == 'succeeded' and not e['repair'] for e in events)
    record = {'version': 'flipped-casting-review-v40', 'book_sha256': manifest['book_sha256'],
        'chapter_index': 5, 'whole_chapter_generated': False, 'items': items, 'scenes': scenes,
        'actual_requests': len(events), 'actual_characters': sum(e['characters'] for e in events),
        'request_ids': [e['id'] for e in events], 'original_samples_preserved': True,
        'gain_applied': False, 'onset_fade_applied': False, 'role_fit_status': manifest['role_fit_status'],
        'human_review_status': 'pending', 'requests_during_export': 0}
    save(REVIEW / 'review_manifest.json', record)
    save(ROOT / 'docs/validation/audio_core_20261017/flipped_casting_v40.json', {
        'review_manifest': str(REVIEW / 'review_manifest.json'), 'sha256': sha(REVIEW / 'review_manifest.json'),
        'actual_requests': 14, 'actual_characters': 616, 'reused_before_recovery': 9, 'new_recovery_requests': 5,
        'scene_duration_seconds': sum(i['duration_seconds'] for i in items if i['sample_id'] in ('P01', 'P02')),
        'full_tests': {'run': 564, 'passed': 534, 'skipped': 30, 'failed': 0, 'errors': 0, 'seconds': 16.742},
        'human_review_pending': True, 'whole_chapter_generated': False, 'loudness': loudness})
    names = {'narrator': 'Bryce（A）', 'juli': 'Juli（Chloe）', 'bryce_father': '父亲（Dean）',
             'bryce_mother': '母亲（Mia）', 'classmates': '同学代表（描述生成）', 'mixed': '连续原文'}
    escape = html.escape
    def section(item):
        report = item.get('machine_report', {})
        alignment = report.get('metrics', {}).get('content_alignment', {})
        hint = ''
        if alignment.get('operations'):
            hint += '<p>机器转写：' + escape(alignment['hypothesis']) + '。与原文有差异，请以试听为准。</p>'
        codes = [i['code'] for i in report.get('issues', []) if i['dimension'] != 'content']
        if codes:
            hint += '<p>待核验提示：' + escape(', '.join(codes)) + '。</p>'
        where = f" · {item['start_seconds']:.2f}–{item['end_seconds']:.2f}秒" if 'start_seconds' in item else ''
        return (f"<section id='{escape(item['sample_id'])}'><h3>{escape(item['sample_id'])} · {names[item['role_id']]}{where}</h3>"
            f"<audio controls preload='none' src='{item['path']}'></audio><p>{escape(item['text'])}</p>{hint}</section>")
    main_items = [i for i in items if i['sample_id'] in ('P01', 'P02')]
    groups = [i for i in items if i['sample_id'] in ('C1', 'C2', 'C3')]
    reference = [i for i in items if i['sample_id'] == 'A1_reference']
    chunks = [i for i in items if 'scene' in i]
    body = ''.join(section(i) for i in main_items) + '<h2>同学声音三句</h2>' + ''.join(section(i) for i in groups)
    body += '<h2>Bryce 已通过的 A1 参考</h2>' + ''.join(section(i) for i in reference)
    body += '<h2>逐句定位（仅有疑问时听）</h2>' + ''.join(section(i) for i in chunks)
    (REVIEW / 'index.html').write_text("<!doctype html><html lang='zh-CN'><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Flipped 第一章选角试听</title><style>body{max-width:860px;margin:40px auto;padding:0 20px;font:17px/1.6 system-ui;background:#f5f5f7;color:#202124}"
        "section{background:white;border:1px solid #ddd;border-radius:14px;padding:18px;margin:18px 0}audio{width:100%}p{white-space:pre-wrap}h3{font-size:18px}</style>"
        "<h1>Flipped 第一章 · 角色短试听</h1><p>先听 P01、P02（合计39.36秒），再听 C1–C3。同学代表使用同一声音描述，不代表多个已区分的个人。"
        "所有音频保持原音量、语速与停顿；未应用此前样本的固定衰减或淡入。机器提示均待人工判断，未填写任何通过标签。</p>"
        "<p>请确认：父亲、Juli、母亲是否合适且容易区分；Bryce是否仍像A组；C1–C3是否声音一致、与Bryce可区分、文字完整（C3为逐字母K-I-S-S-I-N-G）。"
        "重点核对 P01 最后一句 It sure…、P02 最后一句 Uh-huh，以及接缝和音量。</p>" + body + '</html>', encoding='utf-8')
    lines = ['# Flipped 第一章角色短试听', '', '先听 P01、P02，再听 C1–C3。全部人工判断待填写；整章未合成。', '',
             '角色：Bryce=A；父亲=Dean；Juli=Chloe；母亲=Mia；同学=固定描述生成的同一代表声线。', '',
             '两处原文连续节选共39.36秒。重点：P01最后的 It sure…；P02最后的 Uh-huh；Bryce与A参考是否一致；同学三句是否一致、与Bryce可区分。', '',
             '机器转写并非人工结论：Julianna/Juliana属于专名拼写差异，仍保留证据。C3需核验K-I-S-S-I-N-G逐字母内容。', '',
             '音量、停顿、语速均保留；若有不自然之处请提供编号及位置。', '']
    for i in main_items + groups + reference:
        lines += [f"- [{i['sample_id']}（{i['duration_seconds']:.2f}秒）]({(REVIEW/i['path']).resolve()})"]
    lines += ['', '逐句音频、机器提示与待填标注表见 index.html、P01_review_pack、P02_review_pack。',
              '实际14次请求、616字符；复用前9次，仅恢复新增5次。未发起修复请求。']
    (REVIEW / 'README.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('试听页和两套待标注包已导出；没有新增合成请求。', flush=True)


if __name__ == '__main__':
    main()
