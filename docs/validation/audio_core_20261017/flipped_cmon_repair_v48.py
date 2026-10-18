"""定位首章C'mon短句的重复／发音尝试，保留既有章节与人工结论。"""
import argparse
import copy
import html
import os
import shutil
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import soundfile as sf

from flipped_casting_preview_v39 import ROOT, BASE, read, save, sha
from audiobook_generator.audio_core.models import CoreOptions, ReadingChunk, ResourceLimits
from audiobook_generator.audio_core.quality import QualityEvaluator
from audiobook_generator.audio_core.store import ArtifactStore

SOURCE=ROOT/'listening_review/flipped_clone_local_repair_20261017'
DEST=ROOT/'listening_review/flipped_cmon_repair_20261017'
REPLY="3分59处原文有一个难发音的单词c'mon,在完整章节候选音频中的3:59-4:04位置，tts模型尝试发了2-3次音，这个应该也属于尾部重复问题吧，请修正"
SPOKEN='“Come on!”'


def context():
    m=read(SOURCE/'assembly_manifest.json'); row=m['items'][33]
    assert row['sample_id']=='R034' and row['start_seconds']==239. and row['text']=='“C\'mon!”'
    assert sha(Path(row['path']))==row['audio_sha256']
    assert sha(Path(m['output_file']))==m['audio_sha256']
    return m,row


def evaluator():
    return QualityEvaluator(CoreOptions(language='en',
        asr_model_dir=str(ROOT/'.audio_quality_models/SenseVoiceSmall'),
        speaker_model_dir=str(ROOT/'.audio_quality_models/ecapa')),
        store=ArtifactStore(read(BASE/'bryce_clone_chapter_v44/plan.json')['project']))


def diagnose():
    m,row=context(); assert not (DEST/'diagnostics.json').exists()
    save(DEST/'human_feedback_v48.json',{'version':'flipped-cmon-user-feedback-v48',
        'source':'explicit_user_reply','user_reply':REPLY,'source_manifest':str(SOURCE/'assembly_manifest.json'),
        'source_manifest_sha256':sha(SOURCE/'assembly_manifest.json'),
        'sample_id':'R034','audio_sha256':row['audio_sha256'],'chapter_seconds':[239.,244.92],
        'confirmed_issue':'user_heard_two_or_three_pronunciation_attempts',
        'complete_first_reading_not_yet_established':True,'whole_chapter_human_verified':False})
    pcm,rate=sf.read(row['path'],dtype='int16',always_2d=True)
    quality=evaluator(); rows=[]
    for label,start,end in [('first',0.,1.12),('middle',2.9,3.7),('last',4.6,5.92)]:
        path=DEST/'diagnostics'/f'{label}.wav'; assert not path.exists()
        path.parent.mkdir(parents=True,exist_ok=True)
        sf.write(path,pcm[round(start*rate):round(end*rate)],rate,subtype='PCM_16')
        transcript=quality.transcript(path)
        rows.append({'label':label,'start_seconds':start,'end_seconds':end,'path':str(path),
            'audio_sha256':sha(path),'asr':transcript})
        print(label,transcript,flush=True)
    save(DEST/'diagnostics.json',{'source_audio_sha256':row['audio_sha256'],'asr_model':quality.backend_identity('asr'),
        'rows':rows,'new_requests':0,'not_human_confirmation_of_correct_pronunciation':True})


def prepare():
    m,row=context(); chunk=m['chunks'][33]
    assert read(DEST/'human_feedback_v48.json')['audio_sha256']==row['audio_sha256']
    assert chunk['chunk']['profile']['voice']=='Chloe'
    save(DEST/'repair_plan.json',{'version':'flipped-cmon-repair-plan-v48',
        'source_manifest':str(SOURCE/'assembly_manifest.json'),
        'source_manifest_sha256':sha(SOURCE/'assembly_manifest.json'),
        'sample_id':'R034','original_text':row['text'],'tts_text':SPOKEN,
        'profile':chunk['chunk']['profile'],'request':chunk['voice_reference_request'],
        'project':read(BASE/'bryce_clone_chapter_v44/plan.json')['project'],
        'endpoint':read(BASE/'bryce_clone_chapter_v44/plan.json')['endpoint'],
        'max_requests':1,'max_characters':len(SPOKEN),'sdk_retries':0,
        'audio_reference_upload':False,'other_chapters_allowed':False,
        'authorization':{'source':'explicit_user_request_to_repair_this_occurrence',
            'user_reply':REPLY,'prior_scope':'Flipped first chapter MiMo synthesis authorized',
            'spoken_expansion':'implementation_choice_for_this_occurrence_only'},
        'original_source_text_and_span_unchanged':True,'automatic_additional_requests':False})
    print('仅R034，Chloe预设，Come on展开读法；最多1次请求，无音频上传。',flush=True)


def render():
    from audiobook_generator.config.general_config import GeneralConfig
    from audiobook_generator.tts_providers.openai_tts_provider import OpenAITTSProvider
    from audiobook_generator.role_script.models import VoiceProfile
    m,row=context(); plan=read(DEST/'repair_plan.json')
    assert plan['source_manifest_sha256']==sha(SOURCE/'assembly_manifest.json')
    assert not (DEST/'render_manifest.json').exists(), '保留运行记录，不得隐式重试'
    config=GeneralConfig(None); config.voice_name='mimo_default'; config.language='en-US'
    config.stream=False; config.output_format='wav'
    provider=OpenAITTSProvider(config)
    assert str(provider.client.base_url)==plan['endpoint']
    route=provider.resolve_voice(plan['profile'])
    assert route==plan['request'] and route['mode']=='preset' and route['voice']=='Chloe'
    store=ArtifactStore(plan['project'])
    limits=ResourceLimits(max_requests=1,max_repair_requests=1,max_repair_characters=len(SPOKEN),max_seconds=180)
    run=store.start_run(limits)
    result={'version':'flipped-cmon-render-v48','run_id':run,'plan_sha256':sha(DEST/'repair_plan.json'),
        'status':'running','limits':asdict(limits),'request':route,'tts_text':SPOKEN}
    save(DEST/'render_manifest.json',result)
    try:
        path=provider.synthesize_observed_chunk(SPOKEN,VoiceProfile('juli','Juli',plan['profile']),
            store,run,resample=True,repair=True)
        result.update(path=str(path),audio_sha256=sha(Path(path)),status='generated_pending_quality_and_listening')
    except Exception as exc:
        result.update(status='failed_no_retry',error_type=type(exc).__name__)
        raise
    finally:
        result['resources']=store.summary(run)
        save(DEST/'render_manifest.json',result,overwrite=True)
    print('单条新音频已保存，等待本地复检与接缝重组。',flush=True)


def build():
    from collections import Counter
    from audiobook_generator.audio_core.audio import assemble_pcm, edge_silence, load_audio, signal_features
    from audiobook_generator.audio_core.annotations import _verify_pcm_layout
    from audiobook_generator.audio_core.encoding import verify_encoded_audio
    from audiobook_generator.audio_core.loudness_preview import measure_loudness
    from audiobook_generator.audio_core.role_references import load_reference
    m,old=context(); generated=read(DEST/'render_manifest.json'); plan=read(DEST/'repair_plan.json')
    assert generated['status']=='generated_pending_quality_and_listening'
    assert generated['plan_sha256']==sha(DEST/'repair_plan.json')
    raw=Path(generated['path']); assert sha(raw)==generated['audio_sha256']
    assert not (DEST/'assembly_manifest.json').exists()
    quality=evaluator(); store=quality.store
    q=read(SOURCE/'quality.json'); frozen={k:quality.backend_identity(k) for k in ('asr','speaker')}
    assert frozen==q['models']
    for folder in ('audio','pairs'):
        (DEST/folder).mkdir(exist_ok=False)
    entries=copy.deepcopy(m['chunks']); rows=copy.deepcopy(m['items']); paths=[]; chunks=[]
    loud=measure_loudness(raw); target_lufs=-21.56
    gain_db=min(0.,target_lufs-loud['integrated_lufs']); gain=10**(gain_db/20)
    pcm,rate=sf.read(raw,dtype='int16',always_2d=True)
    rendered=np.rint(pcm.astype(np.float64)*gain).clip(-32768,32767).astype(np.int16)
    new_path=DEST/'audio/R034.wav'; sf.write(new_path,rendered,rate,subtype='PCM_16')
    override={'kind':'occurrence_scoped_spoken_contraction_expansion','source_text':old['text'],
        'tts_text':SPOKEN,'source_span':entries[33]['chunk']['source_span'],
        'reason':'human_confirmed_repeated_pronunciation_attempts',
        'global_dictionary_changed':False,'source_text_changed':False}
    entries[33]['chunk']['tts_text']=SPOKEN
    entries[33]['chunk']['edits']=list(entries[33]['chunk']['edits'])+[override]
    entries[33]['raw_path']=str(raw)
    for i,(entry,row) in enumerate(zip(entries,rows)):
        target=DEST/'audio'/f'{row["sample_id"]}.wav'
        if i!=33:
            shutil.copyfile(row['path'],target); assert sha(target)==row['audio_sha256']
        row.update(previous_path=row['path'],previous_audio_sha256=row['audio_sha256'],
            path=str(target),audio_sha256=sha(target))
        entry['rendered_path']=str(target)
        if i==33:
            row.update(operation='single_preset_resynthesis_with_occurrence_reading_override',
                tts_text=SPOKEN,reading_override=override,raw_or_preserved_path=str(raw),
                raw_or_preserved_sha256=sha(raw),gain_db=gain_db,gain=gain,
                input_loudness=loud,output_loudness=measure_loudness(target),
                human_review_status='pending_new_R034_and_adjacent_joins')
        chunks.append(ReadingChunk(**entry['chunk'])); paths.append(str(target))
    output=DEST/'chapter_05.bryce_clone.cmon_repair.wav'
    layout=assemble_pcm(chunks,paths,output,
        expected_artifacts={r['chunk_id']:r['audio_sha256'] for r in rows})
    _verify_pcm_layout(output,layout,entries)
    for row,span in zip(rows,layout['spans']):
        row.update(start_seconds=span['start_sample']/rate,end_seconds=span['end_sample']/rate)
    anchor=load_reference(BASE/'role_references.confirmed.v41.json','juli',chunks[33].profile,'en',
        entries[33]['voice_reference_request'])
    assert anchor is not None and sha(Path(anchor[0]))==q['references']['juli']['sha256']
    new_q=copy.deepcopy(q)
    for i,(row,checked) in enumerate(zip(rows,new_q['chunks'])):
        if i==33:
            result=quality.evaluate_chunk(chunks[i],row['path'],anchor=anchor).to_dict()
            checked.update(audio_sha256=row['audio_sha256'],report=result,
                evidence_origin='reevaluated_new_audio_against_explicit_spoken_override')
            checked['report']['metrics']['source_reading_override']=override
            checked['report']['metrics']['raw_synthesis_signal']=signal_features(raw)
            print('R034',result['metrics'].get('content_alignment'),flush=True)
        else:
            assert checked['audio_sha256']==row['audio_sha256']
            checked['evidence_origin']='reused_exact_audio_same_models_same_reference'
        checked['report']['metrics'].update(start_seconds=row['start_seconds'],end_seconds=row['end_seconds'])
        row['machine_report']=copy.deepcopy(checked['report'])
    joins=[]
    with sf.SoundFile(output) as stream:
        for n,(boundary,checked) in enumerate(zip(layout['boundaries'],new_q['boundaries']),1):
            left,right=layout['spans'][n-1:n+1]
            a,_=load_audio(paths[n-1]); b,_=load_audio(paths[n])
            boundary['estimated_pause_seconds']=edge_silence(a,rate,leading=False)+edge_silence(b,rate,leading=True)+boundary['added_silence_samples']/rate
            pair=DEST/'pairs'/f'J{n:03d}_full_pair.wav'
            stream.seek(left['start_sample'])
            sf.write(pair,stream.read(right['end_sample']-left['start_sample'],dtype='int16',always_2d=True),rate,subtype='PCM_16')
            if n in (33,34):
                checked['report']=quality.evaluate_boundary(chunks[n-1],chunks[n],paths[n-1],paths[n],assembled_window=str(pair)).to_dict()
                checked['evidence_origin']='reevaluated_new_R034_full_left_right_context'
                print('J'+str(n),checked['report']['metrics'].get('content_alignment',checked['report']['metrics'].get('boundary_alignment')),flush=True)
            else:
                assert sha(pair)==q['boundaries'][n-1]['pair_sha256']
                checked['evidence_origin']='reused_exact_pair_same_models'
            checked.update(pair_path=str(pair),pair_sha256=sha(pair))
            checked['report']['metrics'].update(assembled_window_sha256=sha(pair),
                left_audio_sha256=rows[n-1]['audio_sha256'],right_audio_sha256=rows[n]['audio_sha256'],
                estimated_pause_seconds=boundary['estimated_pause_seconds'],evaluation_models={'asr':frozen['asr']})
            start=max(left['start_sample'],boundary['start_sample']-round(3.2*rate))
            end=min(right['end_sample'],boundary['end_sample']+round(2*rate))
            preview=DEST/'audio'/f'J{n:03d}.wav'; stream.seek(start)
            sf.write(preview,stream.read(end-start,dtype='int16',always_2d=True),rate,subtype='PCM_16')
            joins.append({'sample_id':f'J{n:03d}','path':str(preview),'audio_sha256':sha(preview),
                'pair_path':str(pair),'pair_sha256':sha(pair),'chapter_seconds':boundary['start_sample']/rate,
                'boundary_at_seconds':(boundary['start_sample']-start)/rate,
                'estimated_pause_seconds':boundary['estimated_pause_seconds']})
    manifest={'version':'flipped-cmon-repair-v48','run_id':generated['run_id'],'chapter_index':5,
        'source_manifest':str(SOURCE/'assembly_manifest.json'),'source_manifest_sha256':sha(SOURCE/'assembly_manifest.json'),
        'source_quality':str(SOURCE/'quality.json'),'source_quality_sha256':sha(SOURCE/'quality.json'),
        'output_file':str(output),'audio_sha256':sha(output),'duration_seconds':layout['total_samples']/rate,
        'items':rows,'chunks':entries,'boundaries':joins,'assembly':layout,'reading_overrides':[override],
        'new_requests':1,'changed_chunks':1,'unchanged_chunks':99,'reevaluated_boundaries':[33,34],
        'models':frozen,'source_audio_unchanged':True,'human_review_status':'pending_R034_and_joins',
        'whole_chapter_listening_complete':False,'prior_accepted_edits_unchanged':[18,39,76]}
    save(DEST/'assembly_manifest.json',manifest)
    new_q.update(version='flipped-cmon-quality-v48',assembly_manifest_sha256=sha(DEST/'assembly_manifest.json'),
        status='screened_pending_human_review',human_review_status='pending_R034_and_joins',requests_sent=1,
        final_signal=signal_features(output),final_loudness=measure_loudness(output),
        evidence_reuse={'source_quality':str(SOURCE/'quality.json'),'sha256':sha(SOURCE/'quality.json'),
            'changed_chunks':[34],'changed_boundaries':[33,34],'references_unchanged':True,'models_unchanged':True},
        warning_counts=dict(Counter(issue['code'] for r in new_q['chunks']+new_q['boundaries'] for issue in r['report']['issues'])),
        speaker_unavailable_count=sum('speaker_unavailable' in r['report']['metrics'] for r in new_q['chunks']),
        asr_unavailable_count=sum('asr_unavailable' in r['report']['metrics'] for r in new_q['chunks']+new_q['boundaries']))
    save(DEST/'quality.json',new_q)
    verified=verify_encoded_audio(output,output,chunks,layout,DEST/'encoded_checks',
        SimpleNamespace(evaluation_seconds=0.),enable_asr=False).to_dict()
    assert verified['status']=='passed' and verified['metrics']['pcm_equal']
    save(DEST/'pcm_verification.json',verified)
    for n in (18,39,76): assert rows[n-1]['audio_sha256']==m['items'][n-1]['audio_sha256']
    assert sha(Path(m['output_file']))==m['audio_sha256']
    assert len(store.request_events(run_id=generated['run_id']))==1
    print('整章已重组；99块音频及既有三处修复不变，等待新短句试听。',flush=True)


def export():
    from html.parser import HTMLParser
    from urllib.parse import unquote
    from audiobook_generator.audio_core.annotations import _verify_pcm_layout
    from audiobook_generator.audio_core.store import fingerprint
    from audiobook_generator.audio_core.encoding import verify_encoded_audio
    from audiobook_generator.ui.audio_quality import find_quality_reports, load_quality_report, preview_quality_issue
    m=read(DEST/'assembly_manifest.json'); q=read(DEST/'quality.json'); generated=read(DEST/'render_manifest.json')
    old,_=context(); quality=evaluator(); store=quality.store
    assert sha(Path(m['output_file']))==m['audio_sha256']
    previous=read(ROOT/'docs/validation/audio_core_20261017/flipped_clone_local_repair_v46.json')
    standard_path=Path(previous['standard_report']); assert sha(standard_path)==previous['standard_report_sha256']
    result=read(standard_path); lineages=copy.deepcopy(result['resource_provenance']['recorded_generation']['chunks'])
    events=store.request_events(run_id=generated['run_id']); assert len(events)==1 and events[0]['status']=='succeeded'
    lineages[33]['request_ids']=list(dict.fromkeys(lineages[33]['request_ids']+[events[0]['id']]))
    report_dir=store.root/f'reports/{generated["run_id"]}/chapter_000005'
    (report_dir/'audio').mkdir(parents=True,exist_ok=False)
    for i,(entry,row,checked,new_entry) in enumerate(zip(result['chunks'],m['items'],q['chunks'],m['chunks'])):
        target=report_dir/'audio'/f'{row["sample_id"]}.wav'; shutil.copyfile(row['path'],target)
        assert sha(target)==row['audio_sha256']
        if i==33:
            entry['previous_render_history']={'raw_path':entry['raw_path'],
                'render_operations':entry['render_operations'],'chunk':entry['chunk']}
            entry.update(chunk=new_entry['chunk'],raw_path=new_entry['raw_path'],
                render_operations=[{'kind':'constant_attenuation','gain_db':row['gain_db'],
                    'gain':row['gain'],'raw_audio_sha256':row['raw_or_preserved_sha256'],
                    'output_audio_sha256':row['audio_sha256']}],synthesis_parts=[],composition=None)
        entry.update(rendered_path=str(target),selected_rendered_path=str(target),report=copy.deepcopy(checked['report']))
    result['boundaries']=[]
    for checked,join,boundary in zip(q['boundaries'],m['boundaries'],m['assembly']['boundaries']):
        target=report_dir/'audio'/(join['sample_id']+'.wav'); shutil.copyfile(join['path'],target)
        report=copy.deepcopy(checked['report'])
        report['metrics'].update(preview_path=str(target),preview_sha256=sha(target),
            preview_scope='short_listening_context_not_asr_input',
            asr_evaluation_window_path=join['pair_path'],asr_evaluation_window_sha256=join['pair_sha256'],
            start_seconds=boundary['start_sample']/m['assembly']['sample_rate'],
            end_seconds=boundary['end_sample']/m['assembly']['sample_rate'],
            preview_boundary_at_seconds=join['boundary_at_seconds'])
        result['boundaries'].append(report)
    final=report_dir/'chapter.wav'; shutil.copyfile(m['output_file'],final)
    assert sha(final)==m['audio_sha256']; _verify_pcm_layout(final,m['assembly'],result['chunks'])
    encoded=verify_encoded_audio(final,m['output_file'],
        [ReadingChunk(**c['chunk']) for c in result['chunks']],m['assembly'],report_dir/'encoded_checks',
        SimpleNamespace(evaluation_seconds=0.),enable_asr=False).to_dict()
    assert encoded['status']=='passed' and encoded['metrics']['pcm_equal']
    spans=sorted([c['chunk']['source_span'] for c in result['chunks']]+
        [c['source_span'] for c in result['nonspoken_source_units']],key=lambda x:x['start'])
    cursor=0
    for span in spans:
        assert span['chapter_index']==5 and span['start']==cursor and span['end']>cursor
        cursor=span['end']
    assert cursor==14311
    for before,after in zip(old['chunks'],m['chunks']):
        for key in ('source_text','source_start','source_end','source_span','role_id','profile'):
            assert before['chunk'][key]==after['chunk'][key]
    provenance=store.resource_provenance(generated['run_id'],[c['raw_path'] for c in result['chunks']],lineages)
    assert provenance['recorded_generation']['summary']['succeeded']['requests']==101
    result['reading_configuration']['occurrence_reading_overrides']=m['reading_overrides']
    result.update(run_id=generated['run_id'],output_file=str(final),assembly=m['assembly'],
        final_verification=encoded,resource_summary=store.summary(generated['run_id']),
        resource_limits=generated['limits'],resource_provenance=provenance,quality_status='incomplete',
        source_group_id=fingerprint({'previous_source_group':result['source_group_id'],'occurrence_overrides':m['reading_overrides']}),
        performance={'duration_seconds':m['duration_seconds'],'one_occurrence_revision':True},
        offline_import={'method':'single_preset_resynthesis_and_local_reassembly','requests_sent':1,
            'source_standard_report':str(standard_path),'source_standard_report_sha256':sha(standard_path),
            'source_review_manifest':str(DEST/'assembly_manifest.json'),'source_review_manifest_sha256':sha(DEST/'assembly_manifest.json'),
            'source_quality':str(DEST/'quality.json'),'source_quality_sha256':sha(DEST/'quality.json'),
            'human_review_status':'pending_R034_and_joins','whole_chapter_listening_complete':False})
    report_path=report_dir/'quality.json'; store.write_json(str(report_path.relative_to(store.root)),result)
    _,_,previews=load_quality_report(report_path)
    assert str(report_path) in find_quality_reports(store.root.parent.parent) and len(previews)==200
    for scope,path in previews.items(): assert Path(path).is_file() and preview_quality_issue(report_path,scope)==path
    # 导出相同范围的新旧局部上下文；试听从句前开始，避免听众寻找3:59。
    rate=m['assembly']['sample_rate']
    contexts={}
    for label,manifest in [('before',old),('after',m)]:
        span=manifest['assembly']['spans'][33]
        start=max(manifest['assembly']['spans'][32]['start_sample'],span['start_sample']-round(3.5*rate))
        end=min(manifest['assembly']['spans'][34]['end_sample'],span['end_sample']+round(4.*rate))
        path=DEST/'audio'/f'R034_{label}_context.wav'
        with sf.SoundFile(manifest['output_file']) as stream:
            stream.seek(start); sf.write(path,stream.read(end-start,dtype='int16',always_2d=True),rate,subtype='PCM_16')
        contexts[label]={'path':str(path),'audio_sha256':sha(path),
            'target_at_seconds':(span['start_sample']-start)/rate}
    esc=html.escape
    def player(path): return f'<audio controls preload="none" src="{esc(os.path.relpath(path,DEST))}"></audio>'
    body='<h1>Flipped：C’mon 单句修复候选</h1><p>位置：原章3:59–4:04，Juli的R034。书中原文仍为“C’mon!”，本次仅将该处合成读法展开为“Come on!”；沿用Chloe预设。仅新增一次短句合成，其余99块及此前三处已确认修复均未改变。</p>'
    body+='<section><h2>先听：修复后的局部上下文</h2><p>约第3.5秒进入目标句。请确认只读一次Come on、发音完整自然，Juli声音合适，前后接缝和音量自然。</p>'+player(contexts['after']['path'])
    body+='<details><summary>修改前对照</summary>'+player(contexts['before']['path'])+'</details></section>'
    body+='<section><h2>修复短句</h2>'+player(m['items'][33]['path'])+'<p>单独转写：Comome on.；相邻两组完整上下文均识别为一次Come on，没有新增重复词。短语过短，声纹模型无法可靠核验，不能据此宣称发音或音色已人工通过。</p></section>'
    body+='<section><h2>更新后的完整章节候选</h2>'+player(m['output_file'])+f'<p>{m["duration_seconds"]:.2f}秒；目标句仍从3:59开始。原版保留，整章尚未完成全量人工验收。</p></section>'
    page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Flipped C’mon修复</title><style>body{max-width:850px;margin:30px auto;padding:0 18px;font:17px/1.65 system-ui;background:#f5f5f7;color:#222}section{padding:18px;margin:18px 0;background:white;border:1px solid #ddd;border-radius:12px}audio{width:100%}</style>'+body+'</html>'
    assert not (DEST/'index.html').exists(); (DEST/'index.html').write_text(page,encoding='utf-8')
    targets=[]
    class Links(HTMLParser):
        def handle_starttag(self,tag,attrs):
            for key,value in attrs:
                if key in ('src','href'):
                    target=(DEST/unquote(value)).resolve(); assert target.is_file(); targets.append(str(target))
    Links().feed(page)
    (DEST/'README.md').write_text('# Flipped C’mon单句修复候选\n\n'
        f'[试听页]({DEST/"index.html"})\n\n'
        '原R034是多次短词发音尝试，未能确认首次正确，未直接裁切。仅此处将朗读文本展开为Come on，书籍原文、来源区间与角色不变。Chloe原预设单次重合成，整体衰减匹配-21.56 LUFS；未上传参考音频。\n\n'
        '新句1.76秒，整章1054.12秒。99块及97处完整接缝音频逐字节不变，新增短句与两处完整相邻上下文重新筛查；原文14311字符覆盖及逐样本布局、解码一致性通过。两个上下文只识别一次Come on，但孤立转写为Comome on，短句声纹不可用；新发音、声音和接缝仍待人工确认，不能写作整体通过。\n',encoding='utf-8')
    validation={'version':'flipped-cmon-repair-validation-v48','manifest':str(DEST/'assembly_manifest.json'),
        'manifest_sha256':sha(DEST/'assembly_manifest.json'),'quality_report':str(DEST/'quality.json'),
        'quality_report_sha256':sha(DEST/'quality.json'),'standard_report':str(report_path),
        'standard_report_sha256':sha(report_path),'source_text_characters':cursor,
        'source_spans_unchanged':True,'chunks_unchanged':99,'chunks_changed':1,
        'boundary_pairs_unchanged':97,'boundaries_rechecked':[33,34],
        'new_requests':1,'new_characters':events[0]['characters'],'audio_reference_uploaded':False,
        'sdk_retries':0,'prior_accepted_edits_unchanged':[18,39,76],
        'source_audio_unchanged':sha(Path(old['output_file']))==old['audio_sha256'],
        'pcm_layout_verified':True,'decoded_pcm_equal':read(DEST/'pcm_verification.json')['metrics']['pcm_equal'],
        'standard_preview_count':len(previews),'html_targets_verified':len(targets),
        'contexts':contexts,'human_review_status':'pending_R034_and_joins','overall_project_complete':False}
    save(ROOT/'docs/validation/audio_core_20261017/flipped_cmon_repair_v48.json',validation)
    print({k:validation[k] for k in ('new_requests','new_characters','chunks_unchanged','standard_preview_count','human_review_status')},flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('action',choices=['diagnose','prepare','render','build','export']); globals()[p.parse_args().action]()
