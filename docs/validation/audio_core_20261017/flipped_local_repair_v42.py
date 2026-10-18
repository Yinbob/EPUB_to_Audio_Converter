"""两条人工确认的多读及四处长停顿：零TTS请求的局部候选与整章重组。"""
import copy
import html
from dataclasses import asdict
from pathlib import Path
import numpy as np
import soundfile as sf
from flipped_casting_preview_v39 import ROOT,BASE,read,save,sha
from audiobook_generator.audio_core.reviewed_edits import crop_confirmed_extra_suffix,compact_confirmed_silence
from audiobook_generator.audio_core.audio import edge_silence,load_audio
from audiobook_generator.audio_core.annotations import _verify_pcm_layout
from audiobook_generator.audio_core.models import ReadingChunk,CoreOptions
from audiobook_generator.audio_core.quality import QualityEvaluator
from audiobook_generator.audio_core.store import ArtifactStore

SOURCE=ROOT/'listening_review/flipped_full_chapter_20261017'
DEST=ROOT/'listening_review/flipped_local_repair_20261017'


def main():
    m=read(SOURCE/'review_manifest.json')
    assert sha(Path(m['matched_audio']))==m['matched_audio_sha256']
    assert not DEST.exists()
    DEST.mkdir();(DEST/'audio').mkdir()
    replies={'content':'R022确认重复My mom knows where I am；R049朗读内容是go on don\'t just so placed（不确定单词） go on，前后都有go on；',
        'pauses':'都有些过长，停顿在1秒左右合适',
        'voice':'R51和R100的比较像同一个人，但我更喜欢R001的音色（更年轻），更贴合角色',
        'parents':'两条均完整，声音一致'}
    acceptance={'version':'flipped-human-feedback-v42','source':'explicit_user_reply','user_replies':replies,
        'content_defects':[{'sample_id':i['sample_id'],'audio_sha256':i['audio_sha256'],'confirmed_extra_suffix':True}
                           for i in m['items'] if i['sample_id'] in ('R022','R049')],
        'long_pauses':[{'sample_id':b['sample_id'],'audio_sha256':b['audio_sha256'],'target_seconds':1.}
                       for b in m['boundaries'] if b['sample_id'] in ('J009','J013','J023','J076')],
        'preferred_Bryce_reference':'R001','R051_R100_pair_similar':True,'R001_vs_others_same_identity':'not_explicitly_confirmed',
        'parent_confirmed_samples':[{'sample_id':i['sample_id'],'audio_sha256':i['audio_sha256']}
                                    for i in m['items'] if i['sample_id'] in ('R020','R068')],
        'unheard_other_samples_judged':False,'new_repair_candidates_accepted':False}
    save(SOURCE/'human_feedback_v42.json',acceptance)
    whole=read(BASE/'whole_chapter_run_v41.json')
    original=read(Path(m['source_report']))
    evaluator=QualityEvaluator(CoreOptions(language='en',asr_model_dir=str(ROOT/'.audio_quality_models/SenseVoiceSmall'),
        speaker_model_dir=str(ROOT/'.audio_quality_models/ecapa')),store=ArtifactStore(whole['project']))
    replacements,operations,checks={},[],[]
    for n,end in ((22,4.),(49,1.2)):
        item=m['items'][n-1];src=Path(item['path']);target=DEST/'audio'/(item['sample_id']+'_candidate.wav')
        rate=sf.info(src).samplerate
        approval={'audio_sha256':item['audio_sha256'],'confirmed_defect':'extra_suffix','user_reply':replies['content']}
        op=crop_confirmed_extra_suffix(src,target,end_sample=round(end*rate),expected_sha256=item['audio_sha256'],review=approval)
        q=evaluator.evaluate_chunk(ReadingChunk(**original['chunks'][n-1]['chunk']),target).to_dict()
        assert q['metrics']['content_alignment']['error_rate']==0, '裁切候选仍存在ASR差异，不自动用于整章'
        replacements[n]=target
        operations.append({'sample_id':item['sample_id'],**op,'output_path':str(target),'output_sha256':sha(target)})
        checks.append({'sample_id':item['sample_id'],'report':q,'human_review':'pending'})
    for n in (9,13,23,76):
        left,right=m['items'][n-1:n+1];src=Path(left['path'])
        a,rate=load_audio(src);b,_=load_audio(right['path'])
        tail,head=edge_silence(a,rate,leading=False),edge_silence(b,rate,leading=True)
        boundary=m['matched_assembly']['boundaries'][n-1]
        assert boundary['added_silence_samples']==0
        remove=round((tail+head-1.)*rate)
        target=DEST/'audio'/(left['sample_id']+'_pause_candidate.wav')
        approval={'audio_sha256':left['audio_sha256'],'confirmed_defect':'long_pause','user_reply':replies['pauses']}
        op=compact_confirmed_silence(src,target,quiet_start=len(a)-round(tail*rate),quiet_end=len(a),
            remove_samples=remove,expected_sha256=left['audio_sha256'],review=approval)
        altered,_=load_audio(target)
        after=edge_silence(altered,rate,leading=False)+head
        assert abs(after-1.)<=.021
        replacements[n]=target
        operations.append({'sample_id':f'J{n:03d}','left_sample_id':left['sample_id'],**op,
            'output_path':str(target),'output_sha256':sha(target),'pause_before_seconds':tail+head,'pause_after_seconds':after})
    # 保留每处原静音区的实际样本；不重新估计其他接缝，避免连带调整。
    baseline,rate=sf.read(m['matched_audio'],dtype='int16',always_2d=True)
    layout=copy.deepcopy(m['matched_assembly']);items=copy.deepcopy(original['chunks'])
    cursor=0;buffers=[]
    for n,(item,span,old) in enumerate(zip(items,layout['spans'],m['matched_assembly']['spans']),1):
        path=replacements.get(n,Path(m['items'][n-1]['path']))
        pcm,sr=sf.read(path,dtype='int16',always_2d=True);assert sr==rate
        item['rendered_path']=str(path);span.update(start_sample=cursor,end_sample=cursor+len(pcm),render_sha256=sha(path))
        buffers.append(pcm);cursor+=len(pcm)
        if n<len(items):
            oldb=m['matched_assembly']['boundaries'][n-1]
            gap=baseline[oldb['start_sample']:oldb['end_sample']]
            layout['boundaries'][n-1].update(start_sample=cursor,end_sample=cursor+len(gap))
            buffers.append(gap);cursor+=len(gap)
    layout['total_samples']=cursor
    target=DEST/'chapter_05_repaired.matched.wav'
    sf.write(target,np.concatenate(buffers),rate,subtype='PCM_16')
    _verify_pcm_layout(target,layout,items)
    pairs=[]
    for n in (9,13,23,76):
        beforeb=m['matched_assembly']['boundaries'][n-1];afterb=layout['boundaries'][n-1]
        for label,pcm,mapping,boundary in (('before',baseline,m['matched_assembly'],beforeb),
                                          ('after',np.concatenate(buffers),layout,afterb)):
            left,right=mapping['spans'][n-1:n+1]
            a=max(left['start_sample'],boundary['start_sample']-round(3.2*rate))
            z=min(right['end_sample'],boundary['end_sample']+round(1.3*rate))
            path=DEST/'audio'/f'J{n:03d}_{label}.wav'
            sf.write(path,pcm[a:z],rate,subtype='PCM_16')
            pairs.append({'sample_id':f'J{n:03d}','condition':label,'path':str(path),'audio_sha256':sha(path)})
    result={'version':'flipped-local-repair-v42','source_manifest':str(SOURCE/'review_manifest.json'),
        'source_manifest_sha256':sha(SOURCE/'review_manifest.json'),'source_audio_sha256':m['matched_audio_sha256'],
        'output_file':str(target),'output_sha256':sha(target),'duration_seconds':cursor/rate,
        'operations':operations,'content_checks':checks,'assembly':layout,'preview_pairs':pairs,
        'replaced_indices':sorted(replacements),'unchanged_chunk_count':len(items)-len(replacements),
        'pcm_layout_verified':True,'text_and_source_spans_unchanged':True,'requests_sent':0,
        'automatic_promotion':False,'human_review_status':'pending','Bryce_voice_changed':False}
    save(DEST/'manifest.json',result)
    esc=html.escape
    def audio(path):return f"<audio controls preload='none' src='{esc(str(Path(path).relative_to(DEST)))}'></audio>"
    body='<h1>第一章：局部修复候选</h1><p>零新增TTS请求。保留R022、R049首次正确朗读；四处停顿缩到约1秒。Bryce音色尚未更换，原件均保留；本页修复仍待试听。</p>'
    for n in (22,49):
        i=m['items'][n-1];body+=f"<section><h2>{i['sample_id']} 内容候选</h2>"+audio(replacements[n])+f"<p>{esc(i['text'])}</p><p>本地ASR与原文一致，仍请核对词尾及有无残余多读。</p></section>"
    for n in (9,13,23,76):
        body+=f'<section><h2>J{n:03d} 停顿前后</h2>'
        for p in pairs:
            if p['sample_id']==f'J{n:03d}':body+=('<p>原版</p>' if p['condition']=='before' else '<p>约1秒候选</p>')+audio(p['path'])
        body+='</section>'
    (DEST/'index.html').write_text("<!doctype html><html lang='zh-CN'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Flipped局部修复</title><style>body{max-width:820px;margin:36px auto;padding:0 18px;font:17px/1.65 system-ui;background:#f5f5f7;color:#222}section{padding:18px;margin:16px 0;background:white;border-radius:12px;border:1px solid #ddd}audio{width:100%}</style>"+body+f"<p><a href='{target.name}'>整章局部修复候选</a>（Bryce保持原音色）</p></html>",encoding='utf-8')
    (DEST/'README.md').write_text(f'# Flipped局部修复候选\n\n[试听页]({DEST/"index.html"})。先听R022/R049，再比较四处停顿。\n\n零新增TTS请求，保留全部原件；6块局部改动，94块逐样本不变。整章{cursor/rate:.2f}秒；Bryce音色尚未更换。机器检查不是人工验收，所有候选待试听。\n',encoding='utf-8')
    print(f'局部修复候选完成：{cursor/rate:.2f}秒；内容ASR一致，停顿约1秒，94块逐样本不变。',flush=True)


if __name__=='__main__':main()
