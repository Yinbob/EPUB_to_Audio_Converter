"""从统一增益后的真实选角对照提取两个待复核上下文，不合成、不裁决。"""
import html
import json
from pathlib import Path

import numpy as np
import soundfile as sf

from flipped_casting_preview_v39 import ROOT, read, save, sha
from audiobook_generator.audio_core.annotations import _verify_pcm_layout
from audiobook_generator.audio_core.listening import _listening_source
from audiobook_generator.audio_core.report_sources import resolve_reference_pcm

SOURCE = ROOT/'audiobook_output/mimo_casting_english_common_gain_20261016'
DEST = ROOT/'listening_review/casting_final_focus_20261017'


def main():
    assert not DEST.exists(), '保留既有试听及反馈，不得覆盖'
    rows = []
    for number,condition in enumerate((2,3),1):
        path = SOURCE/f'condition_{condition:02d}/scene_03/quality.json'
        report = read(path); check = report['boundaries'][0]
        issue = check['issues'][0]
        assert len(check['issues']) == 1 and issue['code'] == 'boundary_content_mismatch'
        operations = issue['evidence']['operations']
        assert len(operations) == 1 and operations[0]['reference'] == 'bring' and operations[0]['hypothesis'] == 'b'
        pcm = resolve_reference_pcm(report,path,require_hash=True)
        _verify_pcm_layout(pcm,report['assembly'],report['chunks'])
        left,right = report['assembly']['spans'][:2]
        rate = report['assembly']['sample_rate']
        with sf.SoundFile(pcm) as stream:
            stream.seek(left['start_sample'])
            samples = stream.read(right['end_sample']-left['start_sample'],dtype='int16',always_2d=True)
        candidate = Path(check['metrics']['preview_path'])
        existing,existing_rate = sf.read(candidate,dtype='int16',always_2d=True)
        assert existing_rate == rate and np.array_equal(existing,samples)
        out = DEST/'audio'/f'T{number:02d}.wav'; out.parent.mkdir(parents=True,exist_ok=True)
        sf.write(out,samples,rate,subtype='PCM_16'); assert sha(out) == sha(candidate)
        rows.append({'sample_id':f'T{number:02d}','source_report':str(path),'source_report_sha256':sha(path),
            'chapter':report['chapter_index'],'boundary_index':0,'scope_id':check['scope_id'],
            'audio_path':str(out),'audio_sha256':sha(out),'duration_seconds':len(samples)/rate,
            'boundary_at_seconds':(right['start_sample']-left['start_sample'])/rate,
            'text':' '.join(c['chunk']['tts_text'].strip() for c in report['chunks'][:2]),
            'human_review_status':'pending','source_issue':issue})
    body='<h1>英语选角：两处最终音频核验</h1><p>沿用已生成的统一音量对照，不是新合成。请核对完整两句，尤其后一句开头Bring是否完整，有无额外重复、漏词或异常接缝。此前对旧版的确认不自动写入本版。</p>'
    for row in rows:
        body+=f'<section><h2>{row["sample_id"]}</h2><p>共{row["duration_seconds"]:.2f}秒，Bring位于约{row["boundary_at_seconds"]:.2f}秒。</p><audio controls preload="none" src="audio/{row["sample_id"]}.wav"></audio><p>{html.escape(row["text"])}</p></section>'
    body+='<p>本页用于制备实验材料，不是独立听众辨识测试；回答前不记录通过结论，也不解除原告警。</p>'
    (DEST/'index.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>两处最终音频核验</title><style>body{font:17px/1.7 system-ui;max-width:850px;margin:30px auto;padding:0 18px}section{padding:18px;margin:18px 0;border:1px solid #8886;border-radius:12px}audio{width:100%}@media(prefers-color-scheme:dark){body{background:#17171a;color:#eee}}</style>'+body+'</html>',encoding='utf-8')
    gates=[]
    conditions=read(SOURCE/'conditions.evaluated.json')
    for condition in conditions:
        for path in condition['report_paths']:
            try:
                _listening_source(path); status='quality_gate_passed_draft_only'
            except ValueError as exc:
                status='needs_review'; gates.append({'path':path,'reason':str(exc)})
    assert len(gates) == 2
    save(DEST/'manifest.json',{'version':'casting-focused-material-v50','samples':rows,
        'pending_gates':gates,'new_tts_requests':0,'new_llm_requests':0,
        'human_review_complete':False,'listener_pack_exported':False})
    save(ROOT/'docs/validation/audio_core_20261017/casting_focus_v50.json',{
        'version':'casting-focus-validation-v50','manifest':str(DEST/'manifest.json'),
        'manifest_sha256':sha(DEST/'manifest.json'),'verified_full_pairs':2,
        'total_seconds':sum(row['duration_seconds'] for row in rows),
        'conditions':3,'reports':9,'quality_gates_passed':7,'quality_gates_pending':2,
        'new_tts_requests':0,'original_reports_unchanged':all(sha(Path(r['source_report']))==r['source_report_sha256'] for r in rows),
        'human_review_pending':True,'overall_project_complete':False})
    print(json.dumps({'pairs':len(rows),'seconds':sum(row['duration_seconds'] for row in rows),'remaining_gates':len(gates)}))


if __name__ == '__main__':
    main()
