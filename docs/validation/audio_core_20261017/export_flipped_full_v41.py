"""整章离线响度对照、来源核验与按风险排列的试听材料，不追加模型请求。"""
import copy
import html
import json
import statistics
from pathlib import Path
import numpy as np
import soundfile as sf
from flipped_casting_preview_v39 import ROOT, BASE, REVIEW, read, save, sha
from flipped_full_chapter_v41 import MANIFEST
from audiobook_generator.audio_core.annotations import _verify_pcm_layout, export_review_pack
from audiobook_generator.audio_core.loudness_preview import measure_loudness
from audiobook_generator.audio_core.store import ArtifactStore

DEST = ROOT / 'listening_review/flipped_full_chapter_20261017'


def main():
    manifest = read(MANIFEST)
    assert manifest['status'] == 'generated_pending_whole_chapter_review'
    report = read(Path(manifest['report']))
    original = Path(manifest['output_file'])
    assert sha(original) == manifest['audio_sha256']
    _verify_pcm_layout(original, report['assembly'], report['chunks'])
    assert not DEST.exists(), '不覆盖已有听审包'
    DEST.mkdir()
    (DEST/'audio').mkdir()
    measured = []
    for entry in report['chunks']:
        try:
            measured.append(measure_loudness(entry['rendered_path']))
        except ValueError:
            measured.append({'status': 'unavailable_short_or_silent'})
    narrator_levels = [m['integrated_lufs'] for c,m in zip(report['chunks'], measured)
        if c['chunk']['role_id']=='narrator' and 'integrated_lufs' in m
        and c['report']['metrics']['duration_seconds'] >= 3]
    assert narrator_levels
    target = round(statistics.median(narrator_levels), 2)
    full,rate=sf.read(original,dtype='int16',always_2d=True)
    modified=full.copy()
    mapping, layout_items = copy.deepcopy(report['assembly']), copy.deepcopy(report['chunks'])
    items=[]
    already_heard={i['audio_sha256'] for i in read(REVIEW/'review_manifest.json')['items'] if i['role_id']!='mixed'}
    for index,(entry,span,measurement) in enumerate(zip(layout_items,mapping['spans'],measured),1):
        gain_db=min(0.,target-measurement['integrated_lufs']) if 'integrated_lufs' in measurement else 0.
        gain=10**(gain_db/20)
        start,end=span['start_sample'],span['end_sample']
        pcm=np.rint(full[start:end].astype(np.float64)*gain).astype(np.int16)
        modified[start:end]=pcm
        path=DEST/'audio'/f'R{index:03d}.wav'
        sf.write(path,pcm,rate,subtype='PCM_16')
        entry['rendered_path']=str(path)
        span['render_sha256']=sha(path)
        source=report['chunks'][index-1]
        metrics=source['report']['metrics']
        alignment=metrics.get('content_alignment',{})
        codes=[issue['code'] for issue in source['report']['issues']]
        unavailable={k:metrics[k] for k in ('asr_unavailable','speaker_unavailable') if k in metrics}
        priority=0 if alignment.get('operations') else 1 if codes or unavailable else 2
        row={'sample_id':f'R{index:03d}','chunk_id':entry['chunk']['chunk_id'],'role_id':entry['chunk']['role_id'],
             'text':entry['chunk']['tts_text'],'source_span':entry['chunk']['source_span'],
             'start_seconds':start/rate,'end_seconds':end/rate,'path':str(path),'audio_sha256':sha(path),
             'original_path':source['rendered_path'],'original_audio_sha256':sha(Path(source['rendered_path'])),
             'gain_db':gain_db,'gain':gain,'input_loudness':measurement,'machine_report':source['report'],
             'machine_priority':priority,'previously_heard_same_content_and_identity':sha(Path(source['rendered_path'])) in already_heard,
             'unavailable_evidence':unavailable,
             'whole_chapter_review_status':'pending'}
        items.append(row)
    matched=DEST/'chapter_05_full.matched.wav'
    sf.write(matched,modified,rate,subtype='PCM_16')
    assert sf.info(matched).frames == sf.info(original).frames
    _verify_pcm_layout(matched,mapping,layout_items)
    for b in mapping['boundaries']:
        assert np.array_equal(full[b['start_sample']:b['end_sample']],modified[b['start_sample']:b['end_sample']])
    assert mapping['boundaries']==report['assembly']['boundaries']
    # 逐块PCM变换已核验；不将原始机器质检冒充为响度对照的重跑结论。
    export_review_pack([manifest['report']], DEST/'original_review_pack')
    boundaries=[]
    for i,(b,q) in enumerate(zip(mapping['boundaries'],report['boundaries']),1):
        left,right=mapping['spans'][i-1:i+1]
        a=max(left['start_sample'],b['start_sample']-round(1.8*rate))
        z=min(right['end_sample'],b['end_sample']+round(1.8*rate))
        path=DEST/'audio'/f'J{i:03d}.wav'
        sf.write(path,modified[a:z],rate,subtype='PCM_16')
        boundaries.append({'sample_id':f'J{i:03d}','boundary_id':b['boundary_id'],'path':str(path),'audio_sha256':sha(path),
            'chapter_seconds':b['start_sample']/rate,'boundary_at_seconds':(b['start_sample']-a)/rate,
            'left_text':items[i-1]['text'],'right_text':items[i]['text'],'left_role':left['role_id'],'right_role':right['role_id'],
            'machine_report_on_original':q,'review_status':'pending'})
    store=ArtifactStore(manifest['project'])
    events=store.request_events(run_id=manifest['run_id'])
    assert len(events)<=86 and all(e['status']=='succeeded' and not e['repair'] for e in events)
    # 完整原文由朗读块和独立空白单元共同覆盖，不用忽略空格的比较掩盖缺口。
    source=read(BASE/'source_chapters.json')['chapters'][4]['text']
    intervals=sorted([(x['chunk']['source_span']['start'],x['chunk']['source_span']['end'],x['chunk']['source_text'])
                      for x in report['chunks']]+[(u['source_span']['start'],u['source_span']['end'],u['source_text'])
                      for u in report['nonspoken_source_units']])
    cursor=0
    for a,b,text in intervals:
        assert a==cursor and source[a:b]==text
        cursor=b
    assert cursor==len(source)
    record={'version':'flipped-whole-chapter-review-v41','book_sha256':manifest['book_sha256'],
        'chapter_index':5,'original_audio':str(original),'original_audio_sha256':sha(original),
        'matched_audio':str(matched),'matched_audio_sha256':sha(matched),'duration_seconds':len(full)/rate,
        'source_report':manifest['report'],'source_report_sha256':sha(Path(manifest['report'])),
        'target_lufs':target,'target_basis':'median_current_chapter_Bryce_chunks_at_least_3_seconds',
        'gain_policy':'attenuation_only_preserve_all_sample_positions','automatically_applied':False,
        'onset_fade_applied':False,'pcm_layout_verified':True,'full_source_coverage_verified':True,
        'items':items,'boundaries':boundaries,'original_assembly':report['assembly'],'matched_assembly':mapping,
        'original_quality_status':report['quality_status'],'human_review_status':'pending',
        'role_preview_accepted':True,'new_requests':len(events),'new_characters':sum(e['characters'] for e in events),
        'reused_preview_chunks':len(manifest['cached_chunks']),'requests_during_export':0,
        'cross_chapter_consistency_not_tested':True}
    save(DEST/'review_manifest.json',record)
    flagged=[x for x in items if x['machine_priority']<2]
    flagged.sort(key=lambda x:(x['machine_priority'],x['start_seconds']))
    flagged_joins=[b for b in boundaries if b['machine_report_on_original']['issues'] or
                   b['machine_report_on_original']['metrics'].get('asr_unavailable')]
    flagged_joins.sort(key=lambda b:(not any(i['dimension']=='stitching' for i in b['machine_report_on_original']['issues']),b['chapter_seconds']))
    names={'narrator':'Bryce','juli':'Juli','bryce_father':'父亲','bryce_mother':'母亲','classmates':'同学代表'}
    esc=html.escape
    def rel(path):return esc(str(Path(path).relative_to(DEST)))
    def stamp(seconds):return f'{int(seconds)//60:02d}:{seconds%60:05.2f}'
    sections=[]
    for item in flagged:
        alignment=item['machine_report']['metrics'].get('content_alignment',{})
        codes=', '.join(i['code'] for i in item['machine_report']['issues'])
        if item['unavailable_evidence']:
            codes += '；证据缺失：' + str(item['unavailable_evidence'])
        sections.append(f"<section id='{item['sample_id']}'><h3>{item['sample_id']} · {names[item['role_id']]} · {stamp(item['start_seconds'])}</h3>"
            f"<audio controls preload='none' src='{rel(item['path'])}'></audio><p>原文：{esc(item['text'])}</p>"
            f"<p>机器转写：{esc(alignment.get('hypothesis','未完成'))}</p><p>待核验提示：{esc(codes)}</p>"
            +('<p>该声音片段已在短试听中确认内容和身份；本次整章音量及上下文仍待听。</p>' if item['previously_heard_same_content_and_identity'] else '')+'</section>')
    join_sections=[]
    for b in flagged_joins:
        join_sections.append(f"<section><h3>{b['sample_id']} · {stamp(b['chapter_seconds'])} · {names[b['left_role']]} → {names[b['right_role']]}</h3>"
            f"<audio controls preload='none' src='{rel(b['path'])}'></audio><p>{esc(b['left_text'])}\n→ {esc(b['right_text'])}</p>"
            f"<p>接缝位于本试听第{b['boundary_at_seconds']:.2f}秒。机器提示待核验。</p></section>")
    (DEST/'index.html').write_text("<!doctype html><html lang='zh-CN'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Flipped 第一章整章试听</title>"
        "<style>body{max-width:880px;margin:36px auto;padding:0 18px;font:17px/1.65 system-ui;color:#222;background:#f5f5f7}section{background:white;border:1px solid #ddd;border-radius:12px;padding:16px;margin:16px 0}audio{width:100%}p{white-space:pre-wrap}h3{font-size:18px}</style>"
        f"<h1>Flipped · Diving Under 整章试听</h1><p>仅第一章。{len(full)/rate/60:.2f}分钟，100块、99处接缝。选角短试听已通过；本页整章尚未经人工验收。</p>"
        f"<section><h2>整章响度对照版</h2><audio controls preload='none' src='{matched.name}'></audio><p>以本章旁白实测中位数{target:.2f} LUFS为参照，仅降低偏响片段，较轻片段不放大。全部样本位置、停顿和语速保持不变，未做淡入。</p></section>"
        f"<p><a href='{original.as_uri()}'>原始整章WAV</a> · <a href='original_review_pack/README.md'>原版标注包</a></p>"
        "<p>建议先听整章，再按下面编号核对疑问。机器提示可能来自专名、短词或语气词识别错误；也可能是真实异常，需以试听为准。"
        "角色更换不视为声音漂移；本轮只验证单章，未验证跨章稳定性。</p>"
        f"<h2>机器提示片段（{len(flagged)}条）</h2>"+''.join(sections)+f"<h2>机器提示接缝（{len(flagged_joins)}处）</h2>"+''.join(join_sections)+
        "<p>全部100条逐块音频R001–R100及99处短接缝J001–J099位于audio目录，完整定位见review_manifest.json。未替用户填写通过标签。</p></html>",encoding='utf-8')
    lines=['# Flipped 第一章整章试听','',f'实际时长：{len(full)/rate/60:.2f}分钟；100块，99处接缝。',
        f'新增{len(events)}次MiMo请求、{sum(e["characters"] for e in events)}字符，复用14条试听缓存；没有追加修复请求。','',
        f'- [整章响度对照版]({matched})',f'- [原始整章]({original})',f'- [试听页]({DEST/"index.html"})','',
        f'先听整章；机器提示共{len(flagged)}条块及{len(flagged_joins)}处接缝，均尚未判定为真实缺陷。',
        '反馈请写R编号／J编号或整章时间，以及是否漏读、多读、音色改变、音量或接缝不自然。',
        '短试听通过结论不自动扩展到未听的整章。机器报告保留；原版标注表与响度对照音频不同，填写时须明确试听版本。','',
        f'响度目标由本章旁白实测中位数确定：{target:.2f} LUFS；只衰减，不放大；时长、停顿、语速和全部PCM位置保持一致。',
        '原文14311字符（包含4个不发声的独立空格）已逐字符核对。尚未验证其他章节或独立听众辨识收益。','']
    for item in flagged:
        lines.append(f"- {item['sample_id']} {stamp(item['start_seconds'])} {names[item['role_id']]}："+', '.join(i['code'] for i in item['machine_report']['issues']))
    (DEST/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    save(ROOT/'docs/validation/audio_core_20261017/flipped_full_v41.json',{
        'review_manifest':str(DEST/'review_manifest.json'),'review_manifest_sha256':sha(DEST/'review_manifest.json'),
        'duration_seconds':len(full)/rate,'chunks':100,'boundaries':99,'flagged_chunks':len(flagged),
        'flagged_boundaries':len(flagged_joins),'new_requests':len(events),'new_characters':sum(e['characters'] for e in events),
        'source_coverage_verified':True,'pcm_layout_verified':True,'human_review_status':'pending'})
    execution=read(BASE/'execution_plan.json')
    execution.update(status='whole_chapter_generated_pending_listening',whole_chapter_review=str(DEST/'index.html'),
                     whole_chapter_human_review='pending')
    save(BASE/'execution_plan.json',execution,overwrite=True)
    print(f'整章试听导出完成：{len(full)/rate:.2f}秒；{len(flagged)}条块、{len(flagged_joins)}处接缝待核验。',flush=True)


if __name__=='__main__':main()
