"""人工确认后的接缝起读处理；按编号启用，不用于自动判定缺陷。"""
from pathlib import Path
import hashlib

import numpy as np
import soundfile as sf

from .audio import edge_silence

PRESET = "onset-gain50-100ms-v1"


def render_onset_transition(source, output):
    """使用与试听相同的 PCM16 线性幅度包络，不改变时间轴。"""
    source, output = Path(source), Path(output)
    if source.resolve() == output.resolve():
        raise ValueError("起读处理不能覆盖来源音频")
    before_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    pcm, rate = sf.read(source, dtype="int16", always_2d=True)
    onset = round(edge_silence(pcm.astype(np.float32) / 32768, rate, leading=True) * rate)
    width = round(.1 * rate)
    end = onset + width
    if width < 2 or end > len(pcm):
        raise ValueError("右段有效起读区不足 100 毫秒，保留原音频")
    candidate = pcm.copy()
    candidate[onset:end] = np.rint(pcm[onset:end].astype(float) * np.linspace(.5, 1., width)[:, None]).astype(np.int16)
    output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(output, candidate, rate, subtype="PCM_16")
    actual, actual_rate = sf.read(output, dtype="int16", always_2d=True)
    if (actual_rate != rate or not np.array_equal(actual, candidate)
            or hashlib.sha256(source.read_bytes()).hexdigest() != before_sha):
        output.unlink(missing_ok=True)
        raise ValueError("起读处理输出或来源完整性检查失败")
    return {"preset": PRESET, "kind": "reviewed_onset_gain", "initial_gain": .5,
            "final_gain": 1., "ramp_ms": 100, "start_sample": onset, "end_sample": end,
            "coordinate_scope": "right_chunk_pcm", "sample_rate": rate, "samples": len(pcm),
            "input_path": str(source), "input_sha256": before_sha,
            "output_path": str(output), "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "outside_operation_pcm_unchanged": True,
            "onset_kind": "low_energy_estimate_not_phoneme_alignment"}
