"""MiMo克隆先导：仅以用户选中的本章R001为参考，三次独立请求，不替换整章。"""
import argparse
import base64
import io
import html
from pathlib import Path
import soundfile as sf
from flipped_casting_preview_v39 import ROOT,BASE,read,save,sha
from audiobook_generator.audio_core.store import ArtifactStore,fingerprint
from audiobook_generator.audio_core.models import ResourceLimits,CoreOptions,ReadingChunk
from audiobook_generator.audio_core.quality import QualityEvaluator

SOURCE=ROOT/'listening_review/flipped_full_chapter_20261017'
OUT=BASE/'r001_clone_probe_v42'
REVIEW=ROOT/'listening_review/flipped_r001_clone_20261017'


def prepare():
    m=read(SOURCE/'review_manifest.json');r=read(Path(m['source_report']))
    ref=m['items'][0]
    assert ref['sample_id']=='R001' and sha(Path(ref['original_path']))==ref['original_audio_sha256']
    consent=read(BASE/'mimo_transfer_consent_v40.json')
    assert consent['user_reply']=='允许，仅该章用于MiMo语音合成' and consent['chapter_index']==5
    assert not consent['other_chapters_allowed']
    assert read(SOURCE/'human_feedback_v42.json')['preferred_Bryce_reference']=='R001'
    source=read(BASE/'source_chapters.json')['chapters'][4]['text']
    probes=[]
    for label,index in (('K01',51),('K02',100),('K03',100)):
        item=m['items'][index-1];chunk=r['chunks'][index-1]['chunk']
        span=chunk['source_span']
        assert source[span['start']:span['end']]==chunk['source_text']==chunk['tts_text']
        probes.append({'sample_id':label,'source_sample_id':item['sample_id'],'text':item['text'],
            'source_span':span,'independent_repeat_of':'K02' if label=='K03' else None})
    save(OUT/'plan.json',{'version':'flipped-r001-clone-probe-v42','model':'mimo-v2.5-tts-voiceclone',
        'reference_path':ref['original_path'],'reference_audio_sha256':ref['original_audio_sha256'],
        'heard_reference_path':ref['path'],'heard_reference_audio_sha256':ref['audio_sha256'],
        'reference_is_project_generated_synthetic_voice':True,'reference_source_chapter_index':5,
        'instructions':'Speak in clear, neutral American English at a steady, moderate audiobook pace. '
            'Keep the reference speaker voice identity. Read only the supplied text, without additions, omissions or repeats.',
        'probes':probes,'max_requests':3,'planned_text_characters':sum(len(p['text']) for p in probes),
        'no_other_chapters':True,'auto_retries':0,'whole_chapter_replacement':False,
        'official_api_source':'https://mimo.mi.com/docs/en-US/quick-start/usage-guide/audio/speech-synthesis-v2.5'})
    print('R001克隆先导已准备：三条，含一次独立重复，仅第一章正文和本章生成参考。',flush=True)


def render():
    from audiobook_generator.config.general_config import GeneralConfig
    from audiobook_generator.tts_providers.openai_tts_provider import OpenAITTSProvider
    plan=read(OUT/'plan.json')
    assert not (OUT/'manifest.json').exists(),'已有运行不能隐式重试'
    consent=read(OUT/'reference_upload_consent.json')
    assert consent['user_reply']=='允许，仅R001用于这3条MiMo克隆试听'
    assert consent['plan_sha256']==sha(OUT/'plan.json') and consent['max_requests']==3
    assert consent['reference_sha256']==plan['reference_audio_sha256'] and not consent['other_chapters_allowed']
    ref=Path(plan['reference_path']);assert sha(ref)==plan['reference_audio_sha256']
    payload=base64.b64encode(ref.read_bytes()).decode()
    assert len(payload)<10*1024*1024 and sf.info(ref).format=='WAV'
    whole=read(BASE/'whole_chapter_run_v41.json');store=ArtifactStore(whole['project'])
    run=store.start_run(ResourceLimits(max_requests=3,max_repair_requests=0,max_seconds=600))
    config=GeneralConfig(None);config.voice='mimo_default';config.stream=False;config.output_format='wav';config.language='en-US'
    provider=OpenAITTSProvider(config)
    manifest={**plan,'status':'running','run_id':run,'project':whole['project'],'samples':[]}
    save(OUT/'manifest.json',manifest)
    try:
        for probe in plan['probes']:
            route={'adapter':'mimo-clone-probe-v1','model':plan['model'],'reference_audio_sha256':sha(ref),
                'instructions':plan['instructions'],'language':'en','format':'wav','endpoint':str(provider.client.base_url)}
            key=fingerprint({'route':route,'text':probe['text']})
            request=store.reserve(run,key,len(probe['text']))
            try:
                client=provider.client.with_options(max_retries=0,timeout=min(120,store.remaining_seconds(run)))
                completion=client.chat.completions.create(model=plan['model'],
                    messages=[{'role':'user','content':plan['instructions']},{'role':'assistant','content':probe['text']}],
                    audio={'format':'wav','voice':'data:audio/wav;base64,'+payload})
                encoded=getattr(getattr(completion.choices[0].message,'audio',None),'data',None)
                if not encoded:raise ValueError('MiMo克隆响应没有音频')
                raw=base64.b64decode(encoded)
                assert sf.info(io.BytesIO(raw)).frames>0
                path=store.save_sample(key,raw,'wav')
                store.write_json(f'requests/{request}.json',{'request_id':request,'run_id':run,'text':probe['text'],
                    'request':route,'reference_path':str(ref),'reference_sha256':sha(ref),'audio_path':path,
                    'independent_probe_repeat':probe['independent_repeat_of'],'sdk_retries':0})
                store.settle(request,artifact=path)
            except Exception as exc:
                store.settle(request,error=exc);raise
            manifest['samples'].append({**probe,'path':path,'audio_sha256':sha(Path(path)),'request_id':request,'route':route})
            save(OUT/'manifest.json',manifest,overwrite=True)
        manifest['status']='generated_pending_local_evaluation_and_human_review'
    except Exception as exc:
        manifest.update(status='failed_partial_preserved',error_type=type(exc).__name__);raise
    finally:
        manifest['resources']=store.summary(run);save(OUT/'manifest.json',manifest,overwrite=True)
    print('三次克隆请求已完成；尚未选择或替换任何整章音频。',flush=True)


def evaluate():
    import shutil
    from audiobook_generator.audio_core.loudness_preview import measure_loudness
    manifest=read(OUT/'manifest.json');assert len(manifest['samples'])==3
    assert not REVIEW.exists();REVIEW.mkdir();(REVIEW/'audio').mkdir()
    m=read(SOURCE/'review_manifest.json');source_report=read(Path(m['source_report']))
    ref=Path(manifest['reference_path']);assert sha(ref)==manifest['reference_audio_sha256']
    evaluator=QualityEvaluator(CoreOptions(language='en',asr_model_dir=str(ROOT/'.audio_quality_models/SenseVoiceSmall'),
        speaker_model_dir=str(ROOT/'.audio_quality_models/ecapa')),store=ArtifactStore(manifest['project']))
    reference_report=evaluator.evaluate_chunk(ReadingChunk(**source_report['chunks'][0]['chunk']),ref).to_dict()
    target=measure_loudness(ref)['integrated_lufs'];results=[]
    for item in manifest['samples']:
        assert sha(Path(item['path']))==item['audio_sha256']
        chunk=ReadingChunk(item['sample_id'],item['sample_id'],'narrator',item['text'],item['text'],0,len(item['text']),language='en')
        report=evaluator.evaluate_chunk(chunk,item['path'],anchor=(str(ref),reference_report['metrics'])).to_dict()
        loudness=measure_loudness(item['path']);gain_db=min(0.,target-loudness['integrated_lufs'])
        import numpy as np
        pcm,rate=sf.read(item['path'],dtype='int16',always_2d=True)
        dest=REVIEW/'audio'/(item['sample_id']+'.wav')
        sf.write(dest,np.rint(pcm.astype(float)*10**(gain_db/20)).astype(np.int16),rate,subtype='PCM_16')
        results.append({**item,'report':report,'preview_path':str(dest),'preview_sha256':sha(dest),'gain_db':gain_db,
            'human_review_status':'pending'})
    shutil.copy2(ref,REVIEW/'audio/R001_reference.wav')
    result={'version':'flipped-r001-clone-quality-v42','reference_sha256':sha(ref),'reference_report':reference_report,'probes':results,
        'resources':manifest['resources'],'production_support':'not_enabled_experimental_only',
        'human_review_status':'pending','whole_chapter_replaced':False}
    save(REVIEW/'manifest.json',result)
    body='<h1>Bryce · R001参考克隆小试</h1><p>参考声音是本项目生成且用户偏好的R001。K01为原R051正文，K02/K03为原R100正文的两次独立合成。尚未替换整章。请核验年轻音色、同人稳定性和文字完整。</p><section><h2>R001参考</h2><audio controls src="audio/R001_reference.wav"></audio></section>'
    for x in results:
        a=x['report']['metrics'].get('content_alignment',{});codes=', '.join(i['code'] for i in x['report']['issues'])
        body+=f"<section><h2>{x['sample_id']}</h2><audio controls preload='none' src='audio/{x['sample_id']}.wav'></audio><p>{html.escape(x['text'])}</p><p>机器转写：{html.escape(a.get('hypothesis',''))}</p><p>机器提示（待核验）：{html.escape(codes or '未触发规则提示，非人工通过')}</p></section>"
    (REVIEW/'index.html').write_text("<!doctype html><html lang='zh-CN'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Bryce克隆小试</title><style>body{max-width:820px;margin:36px auto;padding:0 18px;font:17px/1.65 system-ui;color:#222;background:#f5f5f7}section{background:white;padding:18px;margin:16px 0;border:1px solid #ddd;border-radius:12px}audio{width:100%}</style>"+body+'</html>',encoding='utf-8')
    (REVIEW/'README.md').write_text(f'# Bryce R001克隆小试\n\n[试听页]({REVIEW/"index.html"})。请比较K01/K02/K03是否接近R001的年轻音色、同人稳定、内容完整。\n\n仅3次独立请求，K02/K03刻意重复正文检验随机性；未修改既有角色档案或整章。声纹距离是未标定证据，不代替试听。\n',encoding='utf-8')
    print('克隆试听与离线评估已导出；人工判断待填写。',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','render','evaluate']);args=p.parse_args()
    {'prepare':prepare,'render':render,'evaluate':evaluate}[args.action]()
