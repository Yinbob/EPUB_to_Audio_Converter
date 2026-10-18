"""编码后内容保留检查：流式解码，按已记录的实际样本区间复检。"""
from __future__ import annotations

import hashlib
import logging
import subprocess
import time
from pathlib import Path

import numpy as np
import soundfile as sf

from .models import QualityIssue, QualityReport
from .quality import align_text
from .language import join_reading_texts

logger = logging.getLogger(__name__)


def _file_hash(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def verify_encoded_audio(encoded, reference_pcm, chunks, mapping, directory, evaluator, *,
                         enable_asr=True, dictionary=None):
    """检验编码是否损伤选中 PCM；ASR 相同不构成人工质量金标准。"""
    from audiobook_generator.role_script.audio_pipeline import require_ffmpeg_tools
    started = time.perf_counter()
    report = QualityReport("chapter:encoded", {"encoding": "incomplete", "content": "incomplete"},
                           metrics={"check_scope": "preservation_of_selected_pcm", "checks": []})
    destination = Path(directory).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    decoded = destination / "decoded.wav"
    rate, channels, total = mapping["sample_rate"], mapping["channels"], mapping["total_samples"]
    try:
        ffmpeg, _ = require_ffmpeg_tools()
        report.metrics["encoded_sha256"] = _file_hash(encoded)
        report.metrics["reference_pcm_sha256"] = _file_hash(reference_pcm)
        report.metrics["reference_pcm_path"] = str(Path(reference_pcm).resolve())
        subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(encoded),
                        "-vn", "-ar", str(rate), "-ac", str(channels), "-c:a", "pcm_s16le", str(decoded)],
                       capture_output=True, check=True, timeout=max(30, total / rate * 2 + 10))
        report.metrics["decoded_path"] = str(decoded)
        info = sf.info(decoded)
        delta = info.frames - total
        report.metrics.update(decoded_samples=info.frames, expected_samples=total,
                              sample_count_delta=delta, sample_tolerance=round(.15 * rate))
        if not info.frames or abs(delta) > max(1, round(.15 * rate)):
            report.issues.append(QualityIssue("encoded_length_mismatch", "encoding", report.scope_id,
                                             "error", "confirmed", evidence={"sample_count_delta": delta}))
            report.dimensions["encoding"] = "failed"
            return report
        report.dimensions["encoding"] = "passed"
        equal, peak, clipped, count = True, 0., 0, 0
        with sf.SoundFile(reference_pcm) as original, sf.SoundFile(decoded) as final:
            if original.frames != total or original.samplerate != rate or original.channels != channels:
                raise ValueError("参考 PCM 与时间表不一致")
            while True:
                a = original.read(65536, dtype="float32", always_2d=True)
                b = final.read(65536, dtype="float32", always_2d=True)
                if not len(a) and not len(b):
                    break
                equal &= bool(np.array_equal(a, b))
                if len(b):
                    peak = max(peak, float(np.max(np.abs(b))))
                    clipped += int(np.count_nonzero(np.abs(b) >= .999))
                    count += b.size
        report.metrics.update(pcm_equal=equal, peak=peak, clipped_fraction=clipped / max(1, count))
        if clipped / max(1, count) > .002:
            report.issues.append(QualityIssue("encoded_clipping", "signal", report.scope_id, "error", "confirmed"))
        if peak < .003:
            report.issues.append(QualityIssue("encoded_too_quiet", "signal", report.scope_id, "error", "confirmed"))
        if equal:
            report.metrics["content_method"] = "exact_pcm_equivalence"
            report.dimensions["content"] = "passed"
            return report
        report.metrics["content_method"] = "asr_on_decoded_chunks_and_pairs"
        if not enable_asr:
            report.metrics["asr_unavailable"] = "disabled"
            return report
        spans = mapping["spans"]
        if len(spans) != len(chunks) or any(s["chunk_id"] != c.chunk_id for s, c in zip(spans, chunks)):
            raise ValueError("编码复检的分块与实际时间表不一致")
        checks = [(f"chunk_{i + 1:06d}", chunk.chunk_id, span["start_sample"], span["end_sample"], chunk.tts_text, chunk.language)
                  for i, (chunk, span) in enumerate(zip(chunks, spans))]
        checks += [(f"boundary_{i + 1:06d}", f"{chunks[i].chunk_id}|{chunks[i + 1].chunk_id}",
                    spans[i]["start_sample"], spans[i + 1]["end_sample"], join_reading_texts([chunks[i].tts_text, chunks[i + 1].tts_text]),
                    chunks[i].language if chunks[i].language == chunks[i + 1].language else "auto")
                   for i in range(len(chunks) - 1)]
        with sf.SoundFile(decoded) as stream:
            for index, (name, scope, start, end, text, language) in enumerate(checks, 1):
                logger.info("编码后内容复检 %s/%s：%s", index, len(checks), scope)
                path = destination / (name + ".wav")
                item = {"scope_id": "encoded:" + scope, "path": str(path), "start_seconds": start / rate,
                        "end_seconds": min(end, info.frames) / rate, "status": "incomplete"}
                report.metrics["checks"].append(item)
                try:
                    if start >= info.frames or end <= start:
                        raise ValueError("编码后片段区间为空")
                    stream.seek(start)
                    samples = stream.read(min(end, info.frames) - start, dtype="int16", always_2d=True)
                    sf.write(path, samples, rate, subtype="PCM_16")
                    alignment = align_text(text, evaluator.transcript(path), dictionary=dictionary, language=language)
                    item["content_alignment"] = alignment
                    if alignment["operations"]:
                        report.issues.append(QualityIssue("encoded_asr_mismatch", "content", item["scope_id"],
                            start_seconds=start / rate, end_seconds=item["end_seconds"], evidence=alignment))
                    else:
                        item["status"] = "passed"
                except Exception as exc:
                    item["error_type"] = type(exc).__name__
        if checks and all(item["status"] == "passed" for item in report.metrics["checks"]):
            report.dimensions["content"] = "passed"
    except subprocess.CalledProcessError:
        report.dimensions["encoding"] = "failed"
        report.issues.append(QualityIssue("encoded_decode_failed", "encoding", report.scope_id, "error", "confirmed"))
    except Exception as exc:
        report.metrics["verification_unavailable"] = type(exc).__name__
    finally:
        report.metrics["evaluation_seconds"] = time.perf_counter() - started
        if isinstance(getattr(evaluator, "evaluation_seconds", None), (int, float)):
            evaluator.evaluation_seconds += report.metrics["evaluation_seconds"]
    return report
