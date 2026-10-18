"""把本章高风险内容、实际长停顿和首中末声音抽查整理为短清单。"""
import html
from pathlib import Path
import soundfile as sf
from flipped_casting_preview_v39 import ROOT,BASE,read,save,sha
from export_flipped_full_v41 import DEST


def main():
    manifest=read(DEST/'review_manifest.json')
    assert not (DEST/'focused_review.html').exists()
    with sf.SoundFile(manifest['matched_audio']) as stream:
        rate=stream.samplerate
    joins=[]
    for boundary in manifest['boundaries']:
        q=boundary['machine_report_on_original']
        if not any(i['code']=='unexpected_gap' for i in q['issues']):continue
        index=int(boundary['sample_id'][1:])-1
        pos=manifest['matched_assembly']['boundaries'][index]
        left,right=manifest['matched_assembly']['spans'][index:index+2]
        features=q['metrics']['features']
        a=max(left['start_sample'],pos['start_sample']-round((features['left_tail_silence']+.9)*rate))
        z=min(right['end_sample'],pos['end_sample']+round((features['right_head_silence']+1.2)*rate))
        with sf.SoundFile(manifest['matched_audio']) as stream:
            stream.seek(a);pcm=stream.read(z-a,dtype='int16',always_2d=True)
        path=DEST/'audio'/(boundary['sample_id']+'_pause_context.wav')
        sf.write(path,pcm,rate,subtype='PCM_16')
        joins.append({**boundary,'focused_path':str(path),'focused_audio_sha256':sha(path),
            'context_start_seconds':a/rate,'pause_hint_seconds':features['left_tail_silence']+features['right_head_silence'],
            'duration_seconds':len(pcm)/rate})
    content=[i for i in manifest['items'] if i['sample_id'] in ('R022','R049')]
    voices=[i for i in manifest['items'] if i['sample_id'] in ('R001','R051','R100')]
    record={'version':'flipped-focused-review-v41','content':content,'long_pause_context':joins,'voice_sampling':voices,
        'whole_chapter_review':'pending','content_defects_confirmed':False,'requests_sent':0,
        'notes':'按机器插入／重复词提示优先核验两句；其余专名及短词ASR差异仍完整保留。首中末抽查不能替代全章一致性验收。'}
    save(DEST/'focused_review.json',record)
    esc=html.escape
    def audio(path):return f"<audio controls preload='none' src='{esc(str(Path(path).relative_to(DEST)))}'></audio>"
    def clip(item):
        a=item['machine_report']['metrics'].get('content_alignment',{})
        return f"<section><h3>{item['sample_id']} · 整章第{item['start_seconds']:.2f}秒</h3>"+audio(item['path'])+f"<p>原文：{esc(item['text'])}</p><p>机器转写：{esc(a.get('hypothesis',''))}</p></section>"
    blocks=['<h2>1. 两条内容提示（约15秒）</h2><p>R022是否在正常读完后又说了“My mom knows where I am”？R049是否只读了一次“Go on.”，还是又读了其他内容？</p>']
    blocks += [clip(i) for i in content]
    blocks += ['<h2>2. 四处停顿提示（约15秒）</h2><p>这些位置测得约1.9–2.3秒静音，请判断是否停顿过长；不是断音或漏音的确认结论。剪辑包含停顿前最后的发声与停顿后起读。</p>']
    for j in joins:
        blocks.append(f"<section><h3>{j['sample_id']} · 整章第{j['chapter_seconds']:.2f}秒 · 静音估算{j['pause_hint_seconds']:.2f}秒</h3>"
            +audio(j['focused_path'])+f"<p>前句：{esc(j['left_text'])}\n后句：{esc(j['right_text'])}</p></section>")
    blocks += ['<h2>3. Bryce首／中／末抽查（约40秒）</h2><p>请比较三条是否像同一个人、语速语调是否可接受。相对参考音存在机器声纹提示，不能直接判为身份改变。</p>']
    blocks += [clip(i) for i in voices]
    (DEST/'focused_review.html').write_text("<!doctype html><html lang='zh-CN'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>Flipped 首章优先核验</title><style>body{max-width:820px;margin:36px auto;padding:0 20px;font:17px/1.65 system-ui;background:#f5f5f7;color:#222}section{padding:18px;margin:16px 0;background:white;border:1px solid #ddd;border-radius:12px}audio{width:100%}p{white-space:pre-wrap}</style>"
        "<h1>第一章优先核验 · 约70秒</h1><p>整章已生成15分32秒。本页先核对两条内容疑点、四处停顿与Bryce首中末声音。全部使用本轮响度对照；人工结论待填写。</p>"
        +''.join(blocks)+"<p><a href='index.html'>整章及全部机器提示</a> · <a href='chapter_05_full.matched.wav'>整章响度对照</a></p></html>",encoding='utf-8')
    lines=['# Flipped 首章：优先核验清单','',f'[试听页]({DEST/"focused_review.html"})。先完成本清单约70秒，之后可继续整章。','',
        '1. R022：是否重复句尾“My mom knows where I am”？R049：是否在“Go on.”后多读了内容？',
        '2. J009、J013、J023、J076：停顿是否过长或影响连贯？这里静音约1.9–2.3秒，不预设为断音／漏音。',
        '3. R001、R051、R100：Bryce首中末是否像同一人，语速语调是否可接受？','',
        '可按编号反馈异常或说明正常。其他机器提示保留在整章页面，当前没有自动修复或新增API调用。','']
    for item in content+voices:lines.append(f"- [{item['sample_id']}]({item['path']})")
    for j in joins:lines.append(f"- [{j['sample_id']} 停顿上下文]({j['focused_path']})")
    (DEST/'focused_review.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('优先核验清单已导出：2条内容、4处停顿、首中末3条；无新合成。')


if __name__=='__main__':main()
