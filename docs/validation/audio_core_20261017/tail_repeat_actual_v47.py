"""用既有真实样本检验尾部重复机制；不发送TTS／LLM请求，不修改章节。"""
from dataclasses import replace
from pathlib import Path
import time

from flipped_casting_preview_v39 import ROOT, BASE, read, save, sha
from audiobook_generator.audio_core.models import CoreOptions, ReadingChunk
from audiobook_generator.audio_core.quality import QualityEvaluator
from audiobook_generator.audio_core.store import ArtifactStore
from audiobook_generator.audio_core.tail_repeat import inspect_tail_repeat


def main():
    destination=ROOT/'audiobook_output/tail_repeat_detection_pilot_20261017'
    assert not (destination/'manifest.json').exists()
    destination.mkdir(parents=True,exist_ok=True)
    original=read(ROOT/'listening_review/flipped_full_chapter_20261017/review_manifest.json')
    clones=read(ROOT/'listening_review/flipped_bryce_clone_chapter_20261017/review_manifest.json')
    repaired=read(ROOT/'listening_review/flipped_clone_local_repair_20261017/assembly_manifest.json')
    plan=read(BASE/'bryce_clone_chapter_v44/plan.json')
    old_report=read(Path(original['source_report']))
    store=ArtifactStore(plan['project'])
    with store.connect() as db:
        before=db.execute('SELECT id,status,characters,artifact FROM requests ORDER BY id').fetchall()
    options=CoreOptions(language='en',enable_speaker=False,
        asr_model_dir=str(ROOT/'.audio_quality_models/SenseVoiceSmall'))
    evaluator=QualityEvaluator(options,store=store)
    samples=[]
    for n in (22,):
        samples.append((f'original_R{n:03d}',original['items'][n-1],old_report['chunks'][n-1]['chunk'],True))
    clone_assembly=read(ROOT/'listening_review/flipped_bryce_clone_chapter_20261017/assembly_manifest.json')
    for n in (39,18,1,51,100):
        samples.append((f'clone_R{n:03d}',clones['items'][n-1],clone_assembly['chunks'][n-1]['chunk'],n in (39,18)))
    for n in (18,39):
        samples.append((f'accepted_repair_R{n:03d}',repaired['items'][n-1],repaired['chunks'][n-1]['chunk'],False))
    rows=[]
    for name,row,data,confirmed_defect in samples:
        path=Path(row['path']); assert sha(path)==row['audio_sha256']
        c=ReadingChunk(**data); report=evaluator.evaluate_chunk(c,path)
        check=inspect_tail_repeat(c,path,report,evaluator,destination/name,deadline=time.perf_counter()+120)
        assert sha(path)==row['audio_sha256']
        result={'sample_id':name,'source_path':str(path),'source_audio_sha256':sha(path),
            'historically_human_confirmed_tail_repeat':confirmed_defect,'report':report.to_dict(),'check':check}
        rows.append(result)
        print(name,check['status'],'auto_eligible=',check.get('auto_eligible'),flush=True)
        save(destination/f'{name}.json',result)
    with store.connect() as db:
        assert db.execute('SELECT id,status,characters,artifact FROM requests ORDER BY id').fetchall()==before
    manifest={'version':'tail-repeat-actual-v47','samples':rows,'new_requests':0,'chapters_unchanged':True,
        'models':{'asr':evaluator.backend_identity('asr')},'scope':'small_selected_historical_examples_not_independent_test_set',
        'new_candidate_human_review_status':'pending','thresholds_calibrated':False}
    save(destination/'manifest.json',manifest)
    save(ROOT/'docs/validation/audio_core_20261017/tail_repeat_actual_v47.json',{
        'manifest':str(destination/'manifest.json'),'manifest_sha256':sha(destination/'manifest.json'),
        'results':[{k:r[k] for k in ('sample_id','historically_human_confirmed_tail_repeat')}|
            {'status':r['check']['status'],'auto_eligible':r['check'].get('auto_eligible')}
            for r in rows],'new_requests':0,'not_independent_validation':True})


if __name__=='__main__': main()
