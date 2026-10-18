"""PCM 组装与轻量声学特征；不加载学习模型。"""
from __future__ import annotations

import hashlib
import math
import json
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf


def load_audio(path):
    try:
        samples, rate = sf.read(str(path), dtype="float32", always_2d=True)
    except (RuntimeError, sf.LibsndfileError):
        from pydub import AudioSegment
        audio = AudioSegment.from_file(str(path))
        samples = np.asarray(audio.get_array_of_samples(), dtype=np.float32).reshape(-1, audio.channels)
        samples /= float(2 ** (8 * audio.sample_width - 1))
        rate = audio.frame_rate
    if rate <= 0 or not np.all(np.isfinite(samples)):
        raise ValueError("音频采样率无效或包含非有限样本")
    return samples, rate


def audio_duration(path):
    """最终编码只探测元信息，避免把整章压缩音频展开到内存。"""
    try:
        return sf.info(str(path)).duration
    except (RuntimeError, sf.LibsndfileError):
        from audiobook_generator.role_script.audio_pipeline import require_ffmpeg_tools
        _, ffprobe = require_ffmpeg_tools()
        result = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration",
                                 "-of", "json", str(path)], capture_output=True, text=True, check=True)
        value = float(json.loads(result.stdout)["format"]["duration"])
        if not math.isfinite(value) or value <= 0:
            raise ValueError("最终音频时长无效")
        return value


def mono_resampled(samples, rate, target_rate=16000):
    mono = np.mean(samples, axis=1) if samples.ndim == 2 else samples
    if rate != target_rate and len(mono):
        # 优先有抗混叠滤波的实现；只有依赖缺失时使用 ffmpeg 解码调用方的统一副本。
        from scipy.signal import resample_poly
        divisor = math.gcd(int(rate), int(target_rate))
        mono = resample_poly(mono, target_rate // divisor, rate // divisor)
    return np.asarray(mono, dtype=np.float32)


def frame_rms(samples, rate):
    width = max(1, int(rate * .02))
    return np.asarray([np.sqrt(np.mean(samples[i:i + width] ** 2))
                       for i in range(0, len(samples), width)], dtype=np.float64)


def edge_silence(samples, rate, *, leading):
    # 只认可整段低能量帧，保守估计可安全调整的静音。
    frames = frame_rms(samples, rate)
    if not leading:
        frames = frames[::-1]
    count = 0
    for rms in frames:
        if rms >= .003:
            break
        count += 1
    return min(len(samples), count * max(1, int(rate * .02))) / rate


def pitch_summary(samples, rate):
    mono = mono_resampled(samples, rate, 8000)
    pitches = []
    for start in range(0, max(0, len(mono) - 320), 160):
        frame = mono[start:start + 320].astype(np.float64)
        frame -= frame.mean()
        if np.sqrt(np.mean(frame ** 2)) < .01:
            continue
        frame *= np.hanning(len(frame))
        corr = np.correlate(frame, frame, mode="full")[len(frame) - 1:]
        if corr[0] <= 0:
            continue
        lag = 16 + int(np.argmax(corr[16:134]))
        if corr[lag] / corr[0] >= .55:
            pitches.append(8000 / lag)
    return {"median_hz": float(np.median(pitches)) if pitches else None,
            "iqr_hz": float(np.percentile(pitches, 75) - np.percentile(pitches, 25)) if pitches else None,
            "voiced_frames": len(pitches)}


def signal_features(path):
    samples, rate = load_audio(path)
    duration = len(samples) / rate
    rms = frame_rms(samples, rate)
    active = rms >= .003
    return {"duration_seconds": duration, "sample_rate": rate, "samples": len(samples),
            "peak": float(np.max(np.abs(samples))) if len(samples) else 0.0,
            "clipped_fraction": float(np.mean(np.abs(samples) >= .999)) if len(samples) else 0.0,
            "active_seconds": float(np.sum(active) * .02),
            "silence_fraction": float(1 - np.mean(active)) if len(active) else 1.0,
            "rms_dbfs": float(20 * np.log10(max(float(np.sqrt(np.mean(samples ** 2))) if len(samples) else 0, 1e-10))),
            "pitch": pitch_summary(samples, rate)}


def boundary_features(left_path, right_path, *, same_speaker, planned_pause_ms=0, window_seconds=2.0):
    left, left_rate = load_audio(left_path)
    right, right_rate = load_audio(right_path)
    a = mono_resampled(left[-int(left_rate * window_seconds):], left_rate)
    b = mono_resampled(right[:int(right_rate * window_seconds)], right_rate)
    if not len(a) or not len(b):
        raise ValueError("拼接边界一侧没有有效样本")
    width = 320
    ar, br = float(np.sqrt(np.mean(a[-width:] ** 2))), float(np.sqrt(np.mean(b[:width] ** 2)))
    sa = np.abs(np.fft.rfft(a[-min(len(a), 512):], n=512))
    sb = np.abs(np.fft.rfft(b[:512], n=512))
    spectral = float(np.linalg.norm(sa / max(np.linalg.norm(sa), 1e-10) - sb / max(np.linalg.norm(sb), 1e-10)))
    tail = edge_silence(left, left_rate, leading=False)
    head = edge_silence(right, right_rate, leading=True)
    added_pause = planned_pause_ms / 1000 - tail - head
    jump = max(abs(float(a[-1])), abs(float(b[0]))) if added_pause > 0 else abs(float(a[-1] - b[0]))
    return {"sample_jump": jump,
            "rms_jump_db": abs(20 * math.log10(max(ar, 1e-8) / max(br, 1e-8))),
            "spectral_distance": spectral,
            "left_speech_edge": float(ar >= .003), "right_speech_edge": float(br >= .003),
            "left_tail_silence": tail,
            "right_head_silence": head,
            "planned_pause_seconds": planned_pause_ms / 1000,
            "same_speaker": float(same_speaker)}


def render_pcm(path, output, *, speed=1.0, sample_rate=24000, channels=1):
    from audiobook_generator.role_script.audio_pipeline import (
        _decode_normalized, build_audio_artifact, require_ffmpeg_tools,
    )
    if not math.isfinite(speed) or not .25 <= speed <= 4:
        raise ValueError("本地语速必须在 0.25～4.0 之间")
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    ffmpeg, _ = require_ffmpeg_tools()
    _decode_normalized(build_audio_artifact(str(path)), str(output), sample_rate, channels, speed, ffmpeg)
    return str(output)


def render_safe_boundary(path, output, *, kind, edge, keep_silence_ms=20):
    """只移除数字零或隔离于数字静音的单样本脉冲，不裁弱语音。"""
    if edge not in {"head", "tail"} or kind not in {"local_trim_silence", "local_edge_fade"}:
        raise ValueError("不支持的安全边界动作")
    if not math.isfinite(keep_silence_ms) or not 0 <= keep_silence_ms <= 10000:
        raise ValueError("保留静音必须在 0～10000 毫秒之间")
    if sf.info(str(path)).subtype != "PCM_16":
        raise ValueError("安全边界动作只处理统一的 PCM_16，避免重写时改动其余样本")
    samples, rate = load_audio(path)
    if not len(samples):
        raise ValueError("空音频不能执行边界修复")
    oriented = samples if edge == "head" else samples[::-1]
    operation = {"kind": kind, "edge": edge, "input_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()}
    if kind == "local_trim_silence":
        nonzero = np.flatnonzero(np.any(oriented != 0, axis=1))
        if not len(nonzero):
            raise ValueError("全静音音频不能当作正常片段缩短")
        zeros = int(nonzero[0])
        keep = max(round(.02 * rate), round(keep_silence_ms / 1000 * rate))
        remove = zeros - keep
        if remove <= 0:
            raise ValueError("边缘没有可安全移除的额外数字静音")
        result = samples[remove:] if edge == "head" else samples[:-remove]
        operation.update(removed_samples=remove, retained_silence_samples=keep, removed_only_digital_zero=True)
    else:
        guard = max(1, round(.05 * rate))
        if (len(samples) <= guard or np.max(np.abs(oriented[0])) <= .15
                or np.any(oriented[1:guard + 1] != 0)):
            raise ValueError("边缘脉冲没有足够数字静音隔离，不能安全淡化")
        result = samples.copy()
        width = max(2, round(.002 * rate))
        if edge == "head":
            result[:width] *= np.linspace(0, 1, width, dtype=np.float32)[:, None]
        else:
            result[-width:] *= np.linspace(1, 0, width, dtype=np.float32)[:, None]
        operation.update(fade_samples=width, isolated_impulse_samples=1, zero_guard_samples=guard)
    destination = Path(output)
    if destination.resolve() == Path(path).resolve():
        raise ValueError("本地修复不得覆盖输入音频")
    destination.parent.mkdir(parents=True, exist_ok=True)
    sf.write(destination, result, rate, subtype="PCM_16")
    return operation


def assemble_pcm(chunks, paths, output, *, expected_artifacts=None):
    """按计划串接 PCM，保留所有语音，只补足不足的静音。"""
    if len(chunks) != len(paths) or not chunks:
        raise ValueError("分块计划与产物数量不一致或为空")
    if len({c.chunk_id for c in chunks}) != len(chunks):
        raise ValueError("发现重复分块编号")
    positions = [c.sequence_index for c in chunks]
    if all(positions) and positions != list(range(positions[0], positions[0] + len(positions))):
        raise ValueError("分块顺序与朗读计划不一致")
    if expected_artifacts is not None:
        for chunk, path in zip(chunks, paths):
            if expected_artifacts.get(chunk.chunk_id) != hashlib.sha256(Path(path).read_bytes()).hexdigest():
                raise ValueError("音频产物与分块编号不匹配或已损坏")
    current, rate = load_audio(paths[0])
    channels = current.shape[1]
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    cursor, spans, boundaries = 0, [], []
    with sf.SoundFile(str(output), "w", samplerate=rate, channels=channels, subtype="PCM_16") as sink:
        for index, (chunk, path) in enumerate(zip(chunks, paths)):
            samples = current
            if not len(samples) or samples.shape[1] != channels:
                raise ValueError("组装前所有 PCM 必须非空且采样率、声道一致")
            sink.write(samples)
            spans.append({"chunk_id": chunk.chunk_id, "role_id": chunk.role_id, "start_sample": cursor,
                          "end_sample": cursor + len(samples), "source_start": chunk.source_start,
                          "source_end": chunk.source_end, "unit_id": chunk.unit_id,
                          "source_span": chunk.source_span, "source_scope": chunk.source_scope,
                          "render_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()})
            cursor += len(samples)
            if index < len(chunks) - 1:
                current, next_rate = load_audio(paths[index + 1])
                if next_rate != rate:
                    raise ValueError("组装前所有 PCM 必须非空且采样率、声道一致")
                existing = edge_silence(samples, rate, leading=False) + edge_silence(current, rate, leading=True)
                added = max(0, round((chunk.pause_after_ms / 1000 - existing) * rate))
                boundaries.append({"boundary_id": f"{chunk.chunk_id}|{chunks[index + 1].chunk_id}",
                                   "left_chunk_id": chunk.chunk_id, "right_chunk_id": chunks[index + 1].chunk_id,
                                   "start_sample": cursor, "end_sample": cursor + added,
                                   "same_speaker": chunk.role_id == chunks[index + 1].role_id,
                                   "boundary_kind": chunk.boundary_kind, "added_silence_samples": added})
                if added:
                    sink.write(np.zeros((added, channels), dtype=np.float32))
                cursor += added
    actual = sf.info(str(output)).frames
    if actual != cursor:
        raise RuntimeError("PCM 组装长度与计划不一致")
    return {"sample_rate": rate, "channels": channels, "total_samples": cursor,
            "spans": spans, "boundaries": boundaries}
