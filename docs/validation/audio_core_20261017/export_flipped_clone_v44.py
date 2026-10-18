"""首章克隆扩展的离线组装、逐块/接缝复检和试听导出；本脚本不访问TTS。"""
import argparse
import copy
import html
import json
import shutil
from collections import Counter
from dataclasses import asdict
from pathlib import Path

import numpy as np
import soundfile as sf

from flipped_casting_preview_v39 import ROOT, BASE, read, save, sha
from audiobook_generator.audio_core.annotations import _verify_pcm_layout
from audiobook_generator.audio_core.audio import assemble_pcm, edge_silence, load_audio, signal_features
from audiobook_generator.audio_core.loudness_preview import measure_loudness
from audiobook_generator.audio_core.models import CoreOptions, ReadingChunk
from audiobook_generator.audio_core.quality import QualityEvaluator
from audiobook_generator.audio_core.role_references import load_reference
from audiobook_generator.audio_core.store import ArtifactStore

RUN = BASE / 'bryce_clone_chapter_v44'
SOURCE = ROOT / 'listening_review/flipped_full_chapter_20261017'
DEST = ROOT / 'listening_review/flipped_bryce_clone_chapter_20261017'
ASSEMBLY = DEST / 'assembly_manifest.json'
QUALITY = DEST / 'quality.json'
NAMES = {'narrator': 'Bryce', 'bryce_father': '父亲', 'juli': 'Juli',
         'bryce_mother': '母亲', 'classmates': '同学代表'}


def context():
    plan, rendered = read(RUN / 'plan.json'), read(RUN / 'render_manifest.json')
    assert rendered['status'] == 'generated_pending_assembly_quality_and_human_review'
    assert rendered['plan_sha256'] == sha(RUN / 'plan.json')
    consent = read(RUN / 'reference_upload_consent.json')
    assert consent['plan_sha256'] == sha(RUN / 'plan.json')
    assert sha(Path(plan['reference_path'])) == plan['reference_sha256']
    assert sha(Path(plan['human_clone_acceptance'])) == plan['human_clone_acceptance_sha256']
    assert len(rendered['samples']) == len(plan['items']) == 100
    for actual, expected in zip(rendered['samples'], plan['items']):
        assert actual['sample_id'] == expected['sample_id'] and actual['chunk_id'] == expected['chunk_id']
        assert actual['operation'] == expected['operation'] and actual['source_span'] == expected['source_span']
        assert sha(Path(actual['path'])) == actual['audio_sha256']
    old = read(SOURCE / 'review_manifest.json')
    assert sha(Path(old['source_report'])) == old['source_report_sha256']
    report = read(Path(old['source_report']))
    return plan, rendered, old, report


def assemble():
    plan, rendered, old, original_report = context()
    assert not DEST.exists(), '已有试听材料不得覆盖；先核验已有阶段产物'
    DEST.mkdir(); (DEST / 'audio').mkdir(); (DEST / 'pairs').mkdir()
    reference_copy = DEST / 'audio' / 'R001_original_reference.wav'
    shutil.copyfile(plan['reference_path'], reference_copy)
    assert sha(reference_copy) == plan['reference_sha256']
    target = old['target_lufs']
    rows, entries, paths, chunks = [], [], [], []
    for sample, original, previous in zip(rendered['samples'], original_report['chunks'], old['items']):
        data = copy.deepcopy(original['chunk'])
        assert data['chunk_id'] == sample['chunk_id'] and data['role_id'] == sample['role_id']
        if data['role_id'] == 'narrator':
            assert data['tts_text'] == sample['text']
            data['profile'] = sample['profile']
        chunk = ReadingChunk(**data)
        source = Path(sample['path']); pcm, rate = sf.read(source, dtype='int16', always_2d=True)
        info = sf.info(source)
        assert info.subtype == 'PCM_16' and rate == 24000 and pcm.shape[1] == 1 and len(pcm)
        output = DEST / 'audio' / (sample['sample_id'] + '.wav')
        try:
            loudness = measure_loudness(source)
        except ValueError:
            loudness = {'status': 'unavailable_short_or_silent'}
        gain_db = 0.
        if chunk.role_id == 'narrator' and 'integrated_lufs' in loudness:
            gain_db = min(0., target - loudness['integrated_lufs'])
        gain = 10 ** (gain_db / 20)
        if gain_db == 0:
            shutil.copyfile(source, output)
            assert sha(output) == sample['audio_sha256']
        else:
            adjusted = np.rint(pcm.astype(np.float64) * gain).astype(np.int16)
            sf.write(output, adjusted, rate, subtype='PCM_16')
            actual, _ = sf.read(output, dtype='int16', always_2d=True)
            assert np.array_equal(actual, adjusted) and len(actual) == len(pcm)
        if chunk.role_id != 'narrator':
            assert sha(output) == sample['audio_sha256'], '其他31块不重复调整音量或裁切'
        out_loudness = measure_loudness(output) if 'integrated_lufs' in loudness else loudness
        rows.append({**sample, 'raw_or_preserved_path': str(source),
            'raw_or_preserved_sha256': sample['audio_sha256'], 'path': str(output),
            'audio_sha256': sha(output), 'text': chunk.tts_text, 'gain_db': gain_db, 'gain': gain,
            'input_loudness': loudness, 'output_loudness': out_loudness,
            'human_review_status': 'pending_for_this_audio_and_context'})
        entries.append({'chunk': asdict(chunk), 'raw_path': str(source), 'rendered_path': str(output),
            'voice_reference_request': sample.get('request', original['voice_reference_request'])})
        paths.append(str(output)); chunks.append(chunk)
    source_text = read(BASE / 'source_chapters.json')['chapters'][4]['text']
    intervals = sorted([(c.source_span['start'], c.source_span['end'], c.source_text) for c in chunks] +
        [(u['source_span']['start'], u['source_span']['end'], u['source_text'])
         for u in original_report['nonspoken_source_units']])
    cursor = 0
    for start, end, text in intervals:
        assert start == cursor and source_text[start:end] == text; cursor = end
    assert cursor == len(source_text) == 14311
    audio = DEST / 'chapter_05.bryce_r001_clone.wav'
    layout = assemble_pcm(chunks, paths, audio,
        expected_artifacts={r['chunk_id']: r['audio_sha256'] for r in rows})
    _verify_pcm_layout(audio, layout, entries)
    pause_checks = []
    for index, boundary in enumerate(layout['boundaries']):
        left, rate = load_audio(paths[index]); right, _ = load_audio(paths[index + 1])
        pause = edge_silence(left, rate, leading=False) + edge_silence(right, rate, leading=True)
        pause += boundary['added_silence_samples'] / rate
        boundary['estimated_pause_seconds'] = pause
        if index + 1 in (9, 13, 23, 76):
            pause_checks.append({'sample_id': f'J{index+1:03d}', 'estimated_pause_seconds': pause,
                'human_requested_target_seconds': 1., 'target_tolerance_seconds': .3,
                'near_requested_target': abs(pause - 1.) <= .3,
                'old_cut_positions_reused': False, 'new_audio_edited': False,
                'human_review_status': 'pending_new_context'})
    for row, span in zip(rows, layout['spans']):
        row.update(start_seconds=span['start_sample'] / layout['sample_rate'],
                   end_seconds=span['end_sample'] / layout['sample_rate'])
    store = ArtifactStore(plan['project']); events = store.request_events(run_id=rendered['run_id'])
    assert len(events) <= 67 and all(e['status'] == 'succeeded' and not e['repair'] for e in events)
    assert sum(e['characters'] for e in events) <= 12925
    result = {'version': 'flipped-bryce-clone-assembly-v44', 'chapter_index': 5,
        'render_manifest': str(RUN / 'render_manifest.json'),
        'render_manifest_sha256': sha(RUN / 'render_manifest.json'),
        'plan_sha256': sha(RUN / 'plan.json'), 'book_sha256': plan['book_sha256'],
        'source_characters': cursor, 'nonspoken_source_units': original_report['nonspoken_source_units'],
        'source_coverage_verified': True, 'pcm_layout_verified': True,
        'output_file': str(audio), 'audio_sha256': sha(audio),
        'duration_seconds': layout['total_samples'] / layout['sample_rate'],
        'target_lufs': target, 'target_basis': 'reuse_previous_chapter_target_keep_31_existing_chunks_exact',
        'reference_preview': str(reference_copy), 'reference_sha256': sha(reference_copy),
        'gain_policy': 'constant_attenuation_only_on_69_clone_chunks_no_boost_no_onset_fade',
        'original_audio_sha256': old['original_audio_sha256'],
        'original_audio': old['original_audio'], 'original_not_overwritten': True,
        'old_pause_cut_positions_reused': False, 'pause_checks': pause_checks,
        'chunks': entries, 'items': rows, 'assembly': layout,
        'new_requests': len(events), 'new_characters': sum(e['characters'] for e in events),
        'reused_clone_probes': 2, 'preserved_other_role_chunks': 31,
        'offline_export_requests': 0, 'resources': rendered['resources'],
        'human_review_status': 'pending', 'quality_status': 'not_yet_evaluated'}
    assert sha(Path(old['original_audio'])) == old['original_audio_sha256']
    save(ASSEMBLY, result)
    print(f'组装完成：{result["duration_seconds"]:.2f}秒；100块来源及逐样本布局核验通过。', flush=True)


def evaluate():
    plan, rendered, old, _ = context()
    m = read(ASSEMBLY)
    assert m['render_manifest_sha256'] == sha(RUN / 'render_manifest.json')
    assert sha(Path(m['output_file'])) == m['audio_sha256']
    _verify_pcm_layout(m['output_file'], m['assembly'], m['chunks'])
    evaluator = QualityEvaluator(CoreOptions(language='en',
        asr_model_dir=str(ROOT / '.audio_quality_models/SenseVoiceSmall'),
        speaker_model_dir=str(ROOT / '.audio_quality_models/ecapa')),
        store=ArtifactStore(plan['project']))
    model_ids = {k: evaluator.backend_identity(k) for k in ('asr', 'speaker')}
    if QUALITY.exists():
        q = read(QUALITY)
        assert q['assembly_manifest_sha256'] == sha(ASSEMBLY) and q['models'] == model_ids
    else:
        q = {'version': 'flipped-bryce-clone-quality-v44', 'assembly_manifest_sha256': sha(ASSEMBLY),
            'models': model_ids, 'chunks': [], 'boundaries': [], 'status': 'running',
            'thresholds_calibrated': False, 'human_review_status': 'pending', 'requests_sent': 0}
    # 年轻音色由用户选定；R001的全文与信号尚未获完整人工核验，不注册合格参考。
    ref_path = Path(plan['reference_path'])
    ref_metrics = evaluator.evaluate_chunk(ReadingChunk(**read(Path(old['source_report']))['chunks'][0]['chunk']), ref_path).metrics
    ref_metrics.update(fixed_reference_kind='user_preferred_synthetic_voice_content_not_yet_confirmed',
                       fixed_reference_sha256=plan['reference_sha256'])
    anchors = {'narrator': (str(ref_path), ref_metrics)}
    # 已听过的长父母片段只作为诊断参考；不伪造缺失的人工signal评分。
    parent_feedback = read(SOURCE / 'human_feedback_v42.json')
    for role, n in (('bryce_father', 20), ('bryce_mother', 68)):
        previous = old['items'][n - 1]; path = Path(previous['path'])
        accepted = next(x for x in parent_feedback['parent_confirmed_samples'] if x['sample_id'] == previous['sample_id'])
        assert accepted['audio_sha256'] == sha(path) == previous['audio_sha256']
        chunk = ReadingChunk(**m['chunks'][n - 1]['chunk'])
        metrics = evaluator.evaluate_chunk(chunk, path).metrics
        metrics.update(fixed_reference_kind='human_content_identity_confirmed_signal_not_separately_rated',
                       fixed_reference_sha256=previous['audio_sha256'])
        anchors[role] = (str(path), metrics)
    for entry in m['chunks']:
        c = ReadingChunk(**entry['chunk'])
        if c.role_id not in anchors:
            anchors[c.role_id] = load_reference(BASE / 'role_references.confirmed.v41.json', c.role_id,
                c.profile, 'en', entry['voice_reference_request'])
            assert anchors[c.role_id] is not None
    references = {role: {'path': value[0], 'sha256': sha(Path(value[0])),
        'kind': value[1]['fixed_reference_kind']} for role, value in anchors.items()}
    if 'references' in q:
        assert q['references'] == references, '参考变化时不得混用已完成评估'
    q['references'] = references
    q['human_feedback_sources'] = [{'path': str(path), 'sha256': sha(path)} for path in (
        SOURCE / 'human_feedback_v42.json', Path(plan['human_clone_acceptance']),
        ROOT / 'listening_review/flipped_local_repair_20261017/human_acceptance_v44.json')]
    for index, entry in enumerate(m['chunks']):
        if index < len(q['chunks']):
            assert q['chunks'][index]['audio_sha256'] == sha(Path(entry['rendered_path']))
            continue
        chunk = ReadingChunk(**entry['chunk'])
        report = evaluator.evaluate_chunk(chunk, entry['rendered_path'], anchor=anchors[chunk.role_id]).to_dict()
        report['metrics']['reference_self_comparison'] = sha(Path(entry['rendered_path'])) == sha(Path(anchors[chunk.role_id][0]))
        q['chunks'].append({'sample_id': m['items'][index]['sample_id'], 'audio_sha256': sha(Path(entry['rendered_path'])), 'report': report})
        save(QUALITY, q, overwrite=QUALITY.exists())
        print(f'逐块复检 {index+1}/100', flush=True)
    rate = m['assembly']['sample_rate']
    for index, boundary in enumerate(m['assembly']['boundaries']):
        if index < len(q['boundaries']):
            continue
        left, right = m['chunks'][index:index+2]
        left_span, right_span = m['assembly']['spans'][index:index+2]
        pair = DEST / 'pairs' / f'J{index+1:03d}_full_pair.wav'
        with sf.SoundFile(m['output_file']) as stream:
            stream.seek(left_span['start_sample'])
            pcm = stream.read(right_span['end_sample'] - left_span['start_sample'], dtype='int16', always_2d=True)
        sf.write(pair, pcm, rate, subtype='PCM_16')
        report = evaluator.evaluate_boundary(ReadingChunk(**left['chunk']), ReadingChunk(**right['chunk']),
            left['rendered_path'], right['rendered_path'], assembled_window=str(pair)).to_dict()
        report['metrics'].update(assembled_window_sha256=sha(pair),
            left_audio_sha256=sha(Path(left['rendered_path'])), right_audio_sha256=sha(Path(right['rendered_path'])),
            estimated_pause_seconds=boundary['estimated_pause_seconds'],
            evaluation_models={'asr': model_ids['asr']})
        q['boundaries'].append({'sample_id': f'J{index+1:03d}', 'pair_path': str(pair), 'pair_sha256': sha(pair), 'report': report})
        save(QUALITY, q, overwrite=True)
        print(f'接缝复检 {index+1}/99', flush=True)
    _verify_pcm_layout(m['output_file'], m['assembly'], m['chunks'])
    assert sha(Path(m['output_file'])) == m['audio_sha256']
    assert {k: evaluator.backend_identity(k) for k in ('asr', 'speaker')} == model_ids
    q.update(status='screened_pending_human_review', final_signal=signal_features(m['output_file']),
        final_loudness=measure_loudness(m['output_file']), pcm_layout_verified=True,
        warning_counts=dict(Counter(i['code'] for row in q['chunks']+q['boundaries'] for i in row['report']['issues'])),
        speaker_unavailable_count=sum('speaker_unavailable' in row['report']['metrics'] for row in q['chunks']),
        asr_unavailable_count=sum('asr_unavailable' in row['report']['metrics'] for row in q['chunks']+q['boundaries']))
    save(QUALITY, q, overwrite=True)
    print('100块与99处完整左右句接缝复检完成；机器提示仍待人工核验。', flush=True)


def export():
    context()
    m, q = read(ASSEMBLY), read(QUALITY)
    assert q['assembly_manifest_sha256'] == sha(ASSEMBLY) and q['status'] == 'screened_pending_human_review'
    assert not (DEST / 'review_manifest.json').exists()
    _verify_pcm_layout(m['output_file'], m['assembly'], m['chunks'])
    esc = html.escape
    def rel(path): return esc(str(Path(path).relative_to(DEST)))
    def player(path): return f"<audio controls preload='none' src='{rel(path)}'></audio>"
    def stamp(value): return f'{int(value)//60:02d}:{value%60:05.2f}'
    css = "body{max-width:880px;margin:32px auto;padding:0 18px;font:17px/1.65 system-ui;background:#f5f5f7;color:#222}section{padding:16px;margin:16px 0;background:#fff;border:1px solid #ddd;border-radius:12px}audio{width:100%}p{white-space:pre-wrap}a{color:#1457a8}"
    def page(title, content): return f"<!doctype html><html lang='zh-CN'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{title}</title><style>{css}</style><h1>{title}</h1>{content}</html>"
    rows = []
    for item, row in zip(m['items'], q['chunks']):
        assert item['sample_id'] == row['sample_id'] and item['audio_sha256'] == row['audio_sha256']
        rows.append({**item, 'machine_report': row['report']})
    joins = []
    with sf.SoundFile(m['output_file']) as stream:
        rate = stream.samplerate
        for index, (b, result) in enumerate(zip(m['assembly']['boundaries'], q['boundaries'])):
            left, right = m['assembly']['spans'][index:index+2]
            start = max(left['start_sample'], b['start_sample'] - round(3.2*rate))
            end = min(right['end_sample'], b['end_sample'] + round(2.0*rate))
            stream.seek(start); pcm = stream.read(end-start, dtype='int16', always_2d=True)
            path = DEST / 'audio' / f'J{index+1:03d}.wav'
            sf.write(path, pcm, rate, subtype='PCM_16')
            joins.append({'sample_id': f'J{index+1:03d}', 'path': str(path), 'audio_sha256': sha(path),
                'chapter_seconds': b['start_sample']/rate, 'boundary_at_seconds': (b['start_sample']-start)/rate,
                'estimated_pause_seconds': b['estimated_pause_seconds'], 'left_sample_id': rows[index]['sample_id'],
                'right_sample_id': rows[index+1]['sample_id'], 'machine_report': result['report'],
                'full_pair_path': result['pair_path'], 'full_pair_sha256': result['pair_sha256'],
                'human_review_status': 'pending'})
    def chunk_section(n):
        item = rows[n-1]; report = item['machine_report']; metrics = report['metrics']
        align = metrics.get('content_alignment', {})
        notes = ', '.join(i['code'] for i in report['issues']) or '未触发机器疑问'
        if metrics.get('speaker_unavailable'): notes += '；句子或参考的有效语音较短，声纹证据不足'
        return f"<section id='{item['sample_id']}'><h2>{item['sample_id']} · {NAMES[item['role_id']]} · {stamp(item['start_seconds'])}</h2>{player(item['path'])}<p>原文：{esc(item['text'])}</p><p>机器转写：{esc(align.get('hypothesis', '未完成'))}</p><p>筛查提示：{esc(notes)}；并非已确认缺陷。</p></section>"
    def join_section(n):
        item = joins[n-1]; left, right = rows[n-1:n+1]
        return f"<section id='{item['sample_id']}'><h2>{item['sample_id']} · {NAMES[left['role_id']]} → {NAMES[right['role_id']]} · {stamp(item['chapter_seconds'])}</h2>{player(item['path'])}<p>接缝在本试听第{item['boundary_at_seconds']:.2f}秒；估计停顿{item['estimated_pause_seconds']:.2f}秒。</p><p>左句结尾：{esc(left['text'][-180:])}\n右句开头：{esc(right['text'][:180])}</p><p><a href='{rel(item['full_pair_path'])}'>完整左右句上下文</a>。接缝短试听未用于全文ASR对齐。</p></section>"
    # 开头、中段及末段声音对照；内容风险优先展示插入/删除较多者。
    suspected = []
    for n, row in enumerate(rows, 1):
        a = row['machine_report']['metrics'].get('content_alignment', {})
        ins, deletes = a.get('insertions', 0), a.get('deletions', 0)
        # 短句少两个词同样可能是重复／漏读，不能只按绝对编辑量筛选。
        if ins + deletes >= 3 or (ins + deletes >= 2 and a.get('error_rate', 0) >= .25):
            suspected.append((-(ins+deletes), -a.get('error_rate', 0), n))
    content_priority = [x[2] for x in sorted(suspected)[:6]]
    focused = '<p>先核对新Bryce的年轻音色与前、中、末段一致性，再听接缝和机器提示的内容。所有新上下文尚待人工核验；原版完整保留。未追加修复请求。</p>'
    if content_priority:
        focused += '<h2>优先听：疑似多读／漏读</h2><p>以下可能是真实多读或漏读，也可能是机器转写错误。请以听到的内容为准。</p>' + ''.join(chunk_section(n) for n in content_priority)
    focused += f"<section><h2>已选定的原R001年轻音色参考</h2>{player(m['reference_preview'])}<p>这是此前选定的原R001；下面R001是本次新克隆输出。</p></section>"
    focused += '<h2>第1组：Bryce开头／中段／末段</h2>' + ''.join(chunk_section(n) for n in (1, 51, 100))
    focused += '<h2>第2组：新声音下的四处停顿与角色切换</h2>' + ''.join(join_section(n) for n in (9, 13, 23, 76))
    focused += '<h2>第3组：已修复内容在新上下文中的接缝</h2>' + ''.join(join_section(n) for n in (21, 22, 48, 49))
    focused += "<p><a href='index.html'>整章与全部逐块清单</a></p>"
    (DEST / 'focused_review.html').write_text(page('Flipped：R001音色克隆版优先核验', focused), encoding='utf-8')
    body = f"<p>仅Diving Under，{m['duration_seconds']/60:.2f}分钟；67次新请求、2条已确认克隆复用，其他角色31块音频逐字节保留。100块原文来源与PCM布局核验通过，质量仍待人工核验。</p>"
    body += f"<section><h2>整章候选</h2>{player(m['output_file'])}<p>新Bryce以既有章节响度目标{m['target_lufs']:.2f} LUFS仅作恒定衰减，不放大偏轻片段。未做起读淡入或套用旧停顿裁剪。</p></section>"
    body += "<p><a href='focused_review.html'>优先核验页</a>。所有机器提示均为筛查结果；短句证据不足不等于音色发生变化。本轮未验证其他章节或独立听众辨识收益。</p>"
    body += '<h2>逐块音频</h2>' + ''.join(chunk_section(n) for n in range(1, 101))
    body += '<h2>全部接缝</h2>' + ''.join(join_section(n) for n in range(1, 100))
    (DEST / 'index.html').write_text(page('Flipped · Bryce年轻音色克隆版', body), encoding='utf-8')
    record = {**{k:v for k,v in m.items() if k not in ('items','chunks')}, 'items': rows,
        'boundaries': joins, 'quality_report': str(QUALITY), 'quality_report_sha256': sha(QUALITY),
        'focused_content_samples': [f'R{n:03d}' for n in content_priority],
        'quality_status': 'screened_pending_human_review', 'cross_chapter_consistency_not_tested': True}
    save(DEST / 'review_manifest.json', record)
    (DEST / 'README.md').write_text(f'# Flipped首章：Bryce年轻音色克隆版\n\n'
        f'[优先核验]({DEST / "focused_review.html"}) · [整章试听]({DEST / "index.html"}) · [整章WAV]({m["output_file"]})\n\n'
        f'{m["duration_seconds"]:.2f}秒；新增{m["new_requests"]}次MiMo克隆、{m["new_characters"]}正文字符。'
        '复用2条克隆试听及其他角色31块，保留R022/R049内容修复。没有自动追加修复。\n\n'
        '先听R001/R051/R100，再核对四处停顿与内容修复的接缝，最后核对优先页机器提示。'
        '新声音不能沿用旧样本的裁剪位置，四处约1秒停顿偏好已重新测量，实际新上下文仍待听。\n\n'
        '100块、99处接缝已本地复检，原文14311字符逐字符覆盖，完整PCM与每块文件逐样本一致。'
        'ASR和未标定声纹阈值仅作筛查，不代表整章通过，不代表跨章稳定性结论。\n', encoding='utf-8')
    execution = read(BASE / 'execution_plan.json')
    execution.update(status='bryce_clone_chapter_screened_pending_human_review',
        clone_chapter_render_manifest=str(RUN / 'render_manifest.json'),
        clone_chapter_review=str(DEST / 'focused_review.html'),
        clone_chapter_output=m['output_file'], clone_chapter_resources=m['resources'],
        clone_chapter_human_review='pending', whole_chapter_human_review='pending')
    save(BASE / 'execution_plan.json', execution, overwrite=True)
    save(ROOT / 'docs/validation/audio_core_20261017/flipped_clone_chapter_actual_v44.json', {
        'review_manifest': str(DEST / 'review_manifest.json'), 'review_manifest_sha256': sha(DEST / 'review_manifest.json'),
        'render_manifest_sha256': sha(RUN / 'render_manifest.json'), 'consent_sha256': sha(RUN / 'reference_upload_consent.json'),
        'new_requests': m['new_requests'], 'new_characters': m['new_characters'],
        'duration_seconds': m['duration_seconds'], 'source_coverage_verified': True, 'pcm_layout_verified': True,
        'chunks_evaluated': len(q['chunks']), 'boundaries_evaluated': len(q['boundaries']),
        'warnings': q['warning_counts'], 'speaker_unavailable_count': q['speaker_unavailable_count'],
        'pause_checks': m['pause_checks'], 'human_review_status': 'pending', 'overall_project_complete': False})
    print('整章候选与优先试听页已导出，尚待人工核验。', flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('action', choices=['assemble','evaluate','export'])
    globals()[p.parse_args().action]()
