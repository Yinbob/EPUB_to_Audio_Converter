"""完整正文之后的重复尾段筛查；有歧义只出试听候选，不把ASR当人工金标准。"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

import numpy as np
import soundfile as sf

from .audio import frame_rms
from .quality import align_text

VERSION = 'complete-body-tail-repeat-v1'


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def repeat_evidence(text, hypothesis, *, language='auto', dictionary=None):
    """先匹配完整原文，再要求额外文本恰为原文的连续子串；原文内的重复不删除。"""
    base = align_text(text, hypothesis, language=language, dictionary=dictionary)
    a, b = base['reference_tokens'], base['hypothesis_tokens']
    if not a or len(b) <= len(a) or len(a) > 500:
        return None
    joiner = '' if base['alignment_unit'] == 'character' else ' '
    minimum = 4 if base['alignment_unit'] == 'character' else 3
    short = len(a) < minimum + 2 or len(set(a)) < 3
    minimum = 1 if short else minimum
    found = []
    allowance = min(3, max(0, len(a)//8))
    for end in range(max(1,len(a)-allowance), min(len(b)-minimum,len(a)+allowance)+1):
        extra = b[end:]
        if len(extra) > len(a) or len(extra) < minimum:
            continue
        starts = [i for i in range(len(a)-len(extra)+1) if a[i:i+len(extra)] == extra]
        if not starts:
            continue
        prefix = align_text(text,joiner.join(b[:end]),language=language,dictionary=dictionary)
        exact = not prefix['operations']
        # 宽松匹配仅用于人工候选，绝不据此自动裁切。
        fuzzy = (len(a) >= 12 and prefix['error_rate'] <= .12 and prefix['deletions'] == 0
                 and b[max(0,end-3):end] == a[-3:])
        if exact or fuzzy:
            found.append({'complete_prefix_alignment':prefix,'extra_tokens':extra,
                'extra_matches_reference_positions':starts,'complete_prefix_end_token':end,
                'exact_body_match':exact,'short_or_low_diversity_text':short,
                'auto_eligible_text':exact and not short and len(starts)==1})
    return min(found,key=lambda r:(r['complete_prefix_alignment']['error_rate'],r['complete_prefix_end_token'])) if found else None


def render_checked_prefix(source, output, *, end_sample, expected_sha256):
    """严格PCM前缀裁切；恢复缓存时再次检验指纹和切点两侧100ms低能量保护。"""
    source,target = Path(source).resolve(),Path(output).resolve()
    if source == target or _sha(source) != expected_sha256:
        raise ValueError('尾部裁切来源发生变化或试图覆盖原件')
    info = sf.info(source)
    if info.format != 'WAV' or info.subtype != 'PCM_16':
        raise ValueError('尾部裁切只接受PCM16 WAV')
    pcm,rate = sf.read(source,dtype='int16',always_2d=True)
    guard = round(.1*rate)
    if (type(end_sample) is not int or not guard <= end_sample <= len(pcm)-guard
            or np.max(frame_rms(pcm[end_sample-guard:end_sample+guard].astype(np.float64)/32768.,rate)) >= .003):
        raise ValueError('切点未满足双侧100ms低能量保护')
    if _sha(source) != expected_sha256:
        raise ValueError('读取期间来源变化')
    if target.exists():
        existing,r = sf.read(target,dtype='int16',always_2d=True)
        if r != rate or not np.array_equal(existing,pcm[:end_sample]):
            raise ValueError('已有裁切候选与保留PCM不符')
    else:
        target.parent.mkdir(parents=True,exist_ok=True)
        sf.write(target,pcm[:end_sample],rate,subtype='PCM_16')
    if _sha(source) != expected_sha256:
        raise ValueError('写入期间来源变化')
    return {'kind':'local_tail_repeat','version':VERSION,'input_sha256':expected_sha256,
        'end_sample':end_sample,'sample_rate':rate,'quiet_guard_samples':guard,
        'output_sha256':_sha(target),'retained_pcm_bit_exact':True,
        'removed_samples':len(pcm)-end_sample}


def _inspect_tail_repeat(chunk, path, report, evaluator, directory, *, deadline=None, max_gaps=6):
    """最多六处停顿、十二次短ASR；优先筛查疑似尾重复，模型不可用时保留原件。"""
    record = {'policy':VERSION,'chunk_id':chunk.chunk_id,'source_path':str(path),
        'source_sha256':_sha(path),'status':'not_suspected','new_tts_requests':0,'probes':[]}
    hypothesis = (report.metrics.get('content_alignment') or {}).get('hypothesis')
    if not hypothesis:
        record['status'] = 'unavailable_transcript'; return record
    evidence = repeat_evidence(chunk.tts_text,hypothesis,language=chunk.language,
        dictionary=evaluator.options.reading_dictionary)
    if evidence is None:
        return record
    record.update(status='suspected_no_safe_cut',text_evidence=evidence)
    info = sf.info(path)
    if info.format != 'WAV' or info.subtype != 'PCM_16' or info.duration > 180:
        record['status'] = 'unsupported_audio'; return record
    pcm,rate = sf.read(path,dtype='int16',always_2d=True)
    frames = frame_rms(pcm.astype(np.float64)/32768.,rate)
    width = max(1,int(.02*rate)); quiet = frames < .003
    gaps,start = [],None
    for i,is_quiet in enumerate(list(quiet)+[False]):
        if is_quiet and start is None: start=i
        if not is_quiet and start is not None:
            a,b = start*width,min(i*width,len(pcm)); start=None
            if b-a >= round(.3*rate) and a >= round(.6*rate) and b < len(pcm)-round(.1*rate):
                gaps.append((a,b))
    # 大停顿更可能隔开重复；限制候选数后按时间先后找首次完整正文。
    gaps = sorted(sorted(gaps,key=lambda ab:ab[1]-ab[0],reverse=True)[:max_gaps])
    identity = evaluator.backend_identity('asr')
    record['asr_model'] = identity
    directory = Path(directory); directory.mkdir(parents=True,exist_ok=True)
    for n,(a,b) in enumerate(gaps):
        if deadline is not None and time.perf_counter() >= deadline:
            record['status'] = 'evaluation_time_limit'; break
        cut = min(a+round(.3*rate),(a+b)//2)
        prefix = directory / f'gap_{n:02d}_prefix.wav'
        suffix = directory / f'gap_{n:02d}_suffix.wav'
        render_checked_prefix(path,prefix,end_sample=cut,expected_sha256=record['source_sha256'])
        if suffix.exists():
            previous,r = sf.read(suffix,dtype='int16',always_2d=True)
            if r != rate or not np.array_equal(previous,pcm[cut:]): raise ValueError('诊断尾段已变化')
        else: sf.write(suffix,pcm[cut:],rate,subtype='PCM_16')
        kept = evaluator.transcript(prefix)
        if deadline is not None and time.perf_counter() >= deadline:
            record['status'] = 'evaluation_time_limit'; break
        removed = evaluator.transcript(suffix)
        prefix_alignment = align_text(chunk.tts_text,kept,language=chunk.language,dictionary=evaluator.options.reading_dictionary)
        pair_evidence = repeat_evidence(chunk.tts_text,kept+' '+removed,
            language=chunk.language,dictionary=evaluator.options.reading_dictionary)
        extra = align_text('',removed,language=chunk.language,dictionary=evaluator.options.reading_dictionary)['hypothesis_tokens']
        probe = {'end_sample':cut,'cut_seconds':cut/rate,'quiet_interval_samples':[a,b],
            'prefix_path':str(prefix),'prefix_sha256':_sha(prefix),'suffix_path':str(suffix),
            'suffix_sha256':_sha(suffix),'prefix_alignment':prefix_alignment,
            'suffix_transcript':removed,'suffix_tokens':extra}
        record['probes'].append(probe)
        valid = (pair_evidence is not None and extra == pair_evidence['extra_tokens']
            and (not prefix_alignment['operations'] or
                 pair_evidence['complete_prefix_alignment'] == prefix_alignment))
        if valid:
            if _sha(path) != record['source_sha256'] or evaluator.backend_identity('asr') != identity:
                raise ValueError('检测期间音频或ASR模型变化')
            operation = render_checked_prefix(path,directory/'candidate.wav',end_sample=cut,
                expected_sha256=record['source_sha256'])
            record.update(status='candidate_pending_review',candidate_path=str(directory/'candidate.wav'),
                candidate_sha256=operation['output_sha256'],operation=operation,
                candidate_prefix_alignment=prefix_alignment,
                auto_eligible=pair_evidence['auto_eligible_text'] and not prefix_alignment['operations'],
                human_review_status='pending',not_a_human_acceptance=True)
            return record
    if _sha(path) != record['source_sha256'] or evaluator.backend_identity('asr') != identity:
        raise ValueError('检测期间音频或ASR模型变化')
    return record


def inspect_tail_repeat(chunk, path, report, evaluator, directory, *, deadline=None, max_gaps=6):
    started = time.perf_counter()
    record = None
    try:
        record = _inspect_tail_repeat(chunk,path,report,evaluator,directory,deadline=deadline,max_gaps=max_gaps)
        return record
    finally:
        elapsed = time.perf_counter()-started
        evaluator.evaluation_seconds += elapsed
        if record is not None:
            record['evaluation_seconds'] = elapsed
