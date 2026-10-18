"""人工确认问题后的局部候选编辑；不接入无人值守的自动修复。"""
from __future__ import annotations

import hashlib
from pathlib import Path
import numpy as np
import soundfile as sf
from .audio import frame_rms


def _source(path, output, expected_sha256, review, defect):
    source, target = Path(path).resolve(), Path(output).resolve()
    if target == source or target.exists():
        raise ValueError('人工编辑候选不能覆盖原件或已有文件')
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if (digest != expected_sha256 or review.get('audio_sha256') != digest
            or review.get('confirmed_defect') != defect or not review.get('user_reply')):
        raise ValueError('编辑须绑定原音频指纹及明确的人工问题确认')
    info = sf.info(source)
    if info.format != 'WAV' or info.subtype != 'PCM_16':
        raise ValueError('局部候选只接受PCM16 WAV')
    pcm, rate = sf.read(source, dtype='int16', always_2d=True)
    return pcm, rate, target, digest


def _quiet(pcm, rate):
    rms = frame_rms(pcm.astype(np.float64) / 32768., rate)
    return bool(len(rms) and np.max(rms) < .003)


def crop_confirmed_extra_suffix(path, output, *, end_sample, expected_sha256, review):
    """生成待复核的前缀，切点两侧各保留100ms低能量保护，不声称ASR或人工已验收。"""
    pcm, rate, target, digest = _source(path, output, expected_sha256, review, 'extra_suffix')
    guard = round(.1 * rate)
    if (type(end_sample) is not int or not guard <= end_sample <= len(pcm)-guard
            or not _quiet(pcm[end_sample-guard:end_sample+guard], rate)):
        raise ValueError('内容裁切点必须位于两侧均有100ms保护的低能量区')
    target.parent.mkdir(parents=True, exist_ok=True)
    sf.write(target, pcm[:end_sample], rate, subtype='PCM_16')
    return {'kind':'reviewed_extra_suffix_crop','input_sha256':digest,'retained_start_sample':0,
            'retained_end_sample':end_sample,'removed_samples':len(pcm)-end_sample,
            'quiet_guard_samples':guard,'sample_rate':rate,'approval':review,
            'retained_pcm_bit_exact':True,'human_candidate_review':'pending'}


def compact_confirmed_silence(path, output, *, quiet_start, quiet_end, remove_samples,
                              expected_sha256, review):
    """只移除已确认长停顿的低能量区中央；保护两端发声，不裁语音边缘。"""
    pcm, rate, target, digest = _source(path, output, expected_sha256, review, 'long_pause')
    guard = round(.1 * rate)
    if (any(type(v) is not int for v in (quiet_start,quiet_end,remove_samples))
            or not 0 <= quiet_start < quiet_end <= len(pcm) or remove_samples <= 0
            or quiet_end-quiet_start-remove_samples < 2*guard
            or not _quiet(pcm[quiet_start:quiet_end], rate)):
        raise ValueError('仅能缩短经核验的低能量区中央，且两端须各保留至少100ms')
    a = quiet_start + (quiet_end-quiet_start-remove_samples)//2
    b = a+remove_samples
    result = np.concatenate((pcm[:a],pcm[b:]),axis=0)
    target.parent.mkdir(parents=True, exist_ok=True)
    sf.write(target,result,rate,subtype='PCM_16')
    return {'kind':'reviewed_pause_compaction','input_sha256':digest,'removed_start_sample':a,
            'removed_end_sample':b,'removed_samples':remove_samples,'sample_rate':rate,
            'quiet_start_sample':quiet_start,'quiet_end_sample':quiet_end,'approval':review,
            'remaining_pcm_bit_exact':True,'human_candidate_review':'pending'}
