"""既有真实WAV的离线重放：验证正式管线能选用／拒选，不访问MiMo。"""
from pathlib import Path
from types import SimpleNamespace

from flipped_casting_preview_v39 import ROOT, read, save, sha
from audiobook_generator.audio_core.models import CoreOptions, ResourceLimits
from audiobook_generator.audio_core.pipeline import run_chapter
from audiobook_generator.audio_core.quality import QualityEvaluator
from audiobook_generator.audio_core.store import fingerprint
from audiobook_generator.core.audio_tags import AudioTags
from audiobook_generator.role_script.models import ChapterSynthesisPlan, SynthesisUnit, VoiceProfile


def main():
    manifest=read(ROOT/'audiobook_output/tail_repeat_detection_pilot_20261017/manifest.json')
    destination=ROOT/'audiobook_output/tail_repeat_pipeline_replay_20261017'
    assert not (destination/'manifest.json').exists()
    old=read(ROOT/'listening_review/flipped_full_chapter_20261017/review_manifest.json')
    old_report=read(Path(old['source_report']))
    new=read(ROOT/'listening_review/flipped_bryce_clone_chapter_20261017/assembly_manifest.json')
    outputs=[]
    class OfflineReplay:
        provider_id='openai'
        config=SimpleNamespace(model_name='existing_audio_offline_replay',language='en',stream=False,output_format='wav')
        def __init__(self,path): self.path=Path(path)
        def synthesize_observed_chunk(self,text,profile,store,run_id,*,resample=False,repair=False):
            if repair or resample: raise AssertionError('离线重放禁止合成或重采样请求')
            # 仅登记本地复制，故生成来源保持unknown；另存原样本来源，不伪造TTS收据。
            key=fingerprint({'offline_replay_audio':sha(self.path),'text':text})
            return store.cached(key) or store.save_sample(key,self.path.read_bytes(),'wav')
    for name,entry in (('original_R022',old_report['chunks'][21]),('clone_R039',new['chunks'][38])):
        sample=next(x for x in manifest['samples'] if x['sample_id']==name)
        source=Path(sample['source_path']); assert sha(source)==sample['source_audio_sha256']
        c=entry['chunk']; unit=SynthesisUnit('offline_replay:'+name,0,'离线重放 '+name,1,1,
            c['role_id'],c['role_id'],c['tts_text'],VoiceProfile(c['role_id'],c['role_id'],c['profile']))
        plan=ChapterSynthesisPlan(0,'离线重放 '+name,(unit,),'wav','openai')
        options=CoreOptions(language='en',enable_speaker=False,auto_repair=True,tail_repeat_mode='auto',
            chunk_chars=1500,asr_model_dir=str(ROOT/'.audio_quality_models/SenseVoiceSmall'),
            limits=ResourceLimits(max_requests=0,max_repair_requests=0,max_repair_characters=0))
        result=run_chapter(plan,OfflineReplay(source),destination/name/'candidate.wav',
            AudioTags('离线重放','测试','尾部重复',0),destination/name/'project',options=options)
        check=result['tail_repeat_checks'][0]
        assert not result['resource_summary'] and sha(source)==sample['source_audio_sha256']
        expected=name=='original_R022'
        assert check.get('selected',False)==expected
        if not expected: assert result['repair_attempts']==[]
        outputs.append({'sample_id':name,'source_path':str(source),'source_audio_sha256':sha(source),
            'run_id':result['run_id'],'expected_selected':expected,'selected':check.get('selected',False),
            'new_requests':0,'historical_audio_generation_not_claimed_zero':True,
            'quality_status':result['quality_status'],'final_pcm_equal':result['final_verification']['metrics']['pcm_equal'],
            'candidate_human_status':'pending_new_cut_not_transferred_from_prior_cut',
            'output_file':result['output_file'],'output_sha256':sha(Path(result['output_file']))})
        print(outputs[-1],flush=True)
    record={'version':'tail-repeat-real-pipeline-replay-v47','method':'existing_audio_offline_replay_not_online_MiMo_trial',
        'samples':outputs,'new_requests':0,'original_chapters_not_replaced':True}
    save(destination/'manifest.json',record)
    save(ROOT/'docs/validation/audio_core_20261017/tail_repeat_pipeline_actual_v47.json',record)


if __name__=='__main__': main()
