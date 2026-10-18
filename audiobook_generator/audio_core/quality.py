"""多维质量证据；没有模型或参考时不把未知当作通过。"""
from __future__ import annotations

import hashlib
import math
import re
import time
import uuid
from pathlib import Path

import numpy as np

from .audio import boundary_features, signal_features
from .models import CoreOptions, QualityIssue, QualityReport
from .reading import VERSION, comparison_details, reading_count
from .language import join_reading_texts, resolve_language
from .store import fingerprint

RATE_POLICY_VERSION = "reference-rate-content-gate-v1"
AUDIO_EVIDENCE_VERSION = 'audio-reference-integrity-v1'


def _audio_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def attach_composition_report(report, composition):
    """将子块证据并入父块；不把缺少内部检查解释成通过。"""
    if not composition:
        return report
    report.metrics["composition_reports"] = composition["internal_reports"]
    for inner in composition["internal_reports"]:
        for dimension, status in inner["dimensions"].items():
            if status != "passed" and (status == "failed" or report.dimensions.get(dimension) != "failed"):
                report.dimensions[dimension] = status
        for issue in inner["issues"]:
            if issue["dimension"] in {"stitching", "content", "signal"} or issue["code"] != "too_fast":
                report.issues.append(QualityIssue(**{**issue, "scope_id": report.scope_id,
                    "evidence": {**issue.get("evidence", {}), "internal_scope": inner["scope_id"]}}))
    return report


def inspect_composition(parts, path, mapping, evaluator, *, anchor=None, expected_sha256=None):
    """内部位置以组合 PCM 为准；派生文件变动时要求先恢复，避免复用旧判断。"""
    import hashlib
    import soundfile as sf
    from .models import ReadingChunk
    if len(parts) != 2 or len(mapping["spans"]) != 2:
        raise ValueError("首轮内容修复只支持两个连续子块")
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    info = sf.info(path)
    if (expected_sha256 and digest != expected_sha256) or info.frames != mapping["total_samples"]:
        raise ValueError("组合音频与选中产物不一致，请从原始样本恢复")
    chunks, paths, reports = [], [], []
    for part, span in zip(parts, mapping["spans"]):
        chunk, audio = ReadingChunk(**part["chunk"]), part["rendered_path"]
        if span["chunk_id"] != chunk.chunk_id or hashlib.sha256(Path(audio).read_bytes()).hexdigest() != span["render_sha256"]:
            raise ValueError("子块音频与内部时间表不一致，请从原始样本恢复")
        report = evaluator.evaluate_chunk(chunk, audio, anchor=anchor)
        report.metrics.update(preview_path=audio, start_seconds=span["start_sample"] / mapping["sample_rate"],
                              end_seconds=span["end_sample"] / mapping["sample_rate"])
        chunks.append(chunk)
        paths.append(audio)
        reports.append(report.to_dict())
    boundary = evaluator.evaluate_boundary(*chunks, *paths, assembled_window=str(path))
    boundary.metrics["preview_path"] = str(path)
    reports.append(boundary.to_dict())
    return {"base_assembly": mapping, "render_sha256": digest, "coordinate_scope": "parent_rendered_pcm",
            "internal_reports": reports}


def align_text(reference, hypothesis, *, dictionary=None, language="auto"):
    reference_details = comparison_details(reference, dictionary=dictionary, language=language)
    a, resolved, unit = reference_details["tokens"], reference_details["language"], reference_details["unit"]
    hypothesis_details = comparison_details(hypothesis, dictionary=dictionary, language=resolved)
    b = hypothesis_details["tokens"]
    distances = [list(range(len(b) + 1))]
    for i, ac in enumerate(a, 1):
        row = [i]
        for j, bc in enumerate(b, 1):
            row.append(min(distances[i - 1][j] + 1, row[j - 1] + 1,
                           distances[i - 1][j - 1] + (ac != bc)))
        distances.append(row)
    i, j, edits = len(a), len(b), []
    while i or j:
        if i and j and a[i - 1] == b[j - 1] and distances[i][j] == distances[i - 1][j - 1]:
            i, j = i - 1, j - 1
        elif i and j and distances[i][j] == distances[i - 1][j - 1] + 1:
            edits.append({"kind": "replace", "reference_index": i - 1, "hypothesis_index": j - 1,
                          "reference": a[i - 1], "hypothesis": b[j - 1]})
            i, j = i - 1, j - 1
        elif i and distances[i][j] == distances[i - 1][j] + 1:
            edits.append({"kind": "delete", "reference_index": i - 1,
                          "hypothesis_index": j, "reference": a[i - 1], "hypothesis": ""})
            i -= 1
        else:
            edits.append({"kind": "insert", "reference_index": i,
                          "hypothesis_index": j - 1, "reference": "", "hypothesis": b[j - 1]})
            j -= 1
    return {"error_rate": distances[-1][-1] / max(1, len(a)), "operations": list(reversed(edits)),
            "reference": "".join(a) if unit == "character" else " ".join(a),
            "hypothesis": "".join(b) if unit == "character" else " ".join(b),
            "reference_tokens": a, "hypothesis_tokens": b, "language": resolved,
            "error_metric": "CER" if unit == "character" else "WER" if unit == "word" else "mixed_token_error_rate",
            "alignment_unit": unit, "reference_unit_count": len(a),
            "normalization_version": VERSION,
            "normalization_policy": "bounded_english_numeric_date_equivalence_ambiguous_identifiers_and_abbreviations_unchanged",
            "comparison_normalization": {"reference": reference_details, "hypothesis": hypothesis_details},
            "deletions": sum(e["kind"] == "delete" for e in edits),
            "insertions": sum(e["kind"] == "insert" for e in edits),
            "substitutions": sum(e["kind"] == "replace" for e in edits)}


class QualityEvaluator:
    def __init__(self, options=None, *, transcribe=None, speaker=None, vad=None, store=None):
        from .backends import SenseVoiceBackend, SileroVAD, SpeakerEncoder
        self.options = options or CoreOptions()
        self.transcribe = transcribe or SenseVoiceBackend(getattr(self.options, "asr_model_dir", None))
        self.speaker = speaker or SpeakerEncoder(self.options.speaker_model_dir)
        self.vad = vad or SileroVAD()
        self.store = store
        self.transcripts = {}
        self.embeddings = {}
        self.evaluation_seconds = 0.0
        # 自定义测试／扩展转写器未声明版本时不跨实例复用磁盘结果。
        self._provided_backend_ids = {'asr': uuid.uuid4().hex, 'speaker': uuid.uuid4().hex}

    def backend_identity(self, kind):
        backend = self.transcribe if kind == 'asr' else self.speaker
        if callable(getattr(backend, 'cache_identity', None)):
            return backend.cache_identity()
        return {'kind': 'provided_callable', 'fingerprint': self._provided_backend_ids[kind]}

    def transcript(self, path):
        identity = self.backend_identity('asr')
        audio_digest = _audio_sha256(path)
        digest = fingerprint({"audio": audio_digest,
                              "asr": identity['fingerprint'], "version": "asr-v3-stable-audio"})
        if digest in self.transcripts:
            return self.transcripts[digest]
        cache = self.store.root / "asr" / f"{digest}.json" if self.store else None
        text = None
        if cache and cache.is_file():
            import json
            try:
                value = json.loads(cache.read_text())
                if value['model_fingerprint'] == identity['fingerprint'] and isinstance(value['text'], str) and value['text'].strip():
                    text = value['text'].strip()
            except (ValueError, KeyError, TypeError, OSError):
                pass
        if text is None:
            text = str(self.transcribe(str(path))).strip()
            if not text:
                raise ValueError("转写为空，不能确认内容完整")
            if self.backend_identity('asr')['fingerprint'] != identity['fingerprint']:
                raise RuntimeError('转写期间模型版本变化，本次结果不能缓存或判为通过')
            if _audio_sha256(path) != audio_digest:
                raise RuntimeError('转写期间音频变化，本次结果不能缓存或判为通过')
            if self.store:
                self.store.write_json(f"asr/{digest}.json", {"text": text, 'model_fingerprint': identity['fingerprint']})
        if _audio_sha256(path) != audio_digest:
            raise RuntimeError('转写期间音频变化，本次结果不能缓存或判为通过')
        self.transcripts[digest] = text
        return text

    def embedding(self, path):
        identity = self.backend_identity('speaker')['fingerprint']
        key = (_audio_sha256(path), identity)
        if key not in self.embeddings:
            vector = np.asarray(self.speaker(str(path)), dtype=float).reshape(-1)
            if self.backend_identity('speaker')['fingerprint'] != identity:
                raise RuntimeError('声纹计算期间模型版本变化，请更新完成后重新评估')
            if _audio_sha256(path) != key[0]:
                raise RuntimeError('声纹计算期间音频变化，本次结果不能缓存或采用')
            self.embeddings[key] = vector
        if _audio_sha256(path) != key[0]:
            raise RuntimeError('声纹计算期间音频变化，本次结果不能采用')
        vector = self.embeddings[key]
        if not len(vector) or not np.all(np.isfinite(vector)) or np.linalg.norm(vector) <= 0:
            raise ValueError("声纹向量无效")
        return vector / np.linalg.norm(vector)

    def evaluate_chunk(self, chunk, path, *, anchor=None):
        started = time.perf_counter()
        audio_digest = _audio_sha256(path)
        report = QualityReport(chunk.chunk_id, {"signal": "passed", "content": "incomplete", "consistency": "incomplete"})
        report.metrics['audio_sha256'] = audio_digest
        report.metrics['audio_evidence_version'] = AUDIO_EVIDENCE_VERSION
        report.metrics['evaluation_models'] = {
            kind: self.backend_identity(kind) for kind, enabled in
            (('asr', self.options.enable_asr), ('speaker', self.options.enable_speaker)) if enabled}
        metrics = signal_features(path)
        report.metrics.update(metrics)
        for code, condition in (("empty_audio", metrics["samples"] == 0),
                                ("too_quiet", metrics["peak"] < .003),
                                ("clipping", metrics["clipped_fraction"] > .002)):
            if condition:
                report.issues.append(QualityIssue(code, "signal", chunk.chunk_id, "error", "confirmed"))
                report.dimensions["signal"] = "failed"
        active = min(metrics["duration_seconds"], metrics["active_seconds"])
        if self.options.enable_vad:
            try:
                active = min(metrics["duration_seconds"], max(0, float(self.vad(path))))
                report.metrics["activity_method"] = "silero"
            except Exception as exc:
                report.metrics["vad_unavailable"] = type(exc).__name__
        language = chunk.language if chunk.language != "auto" else self.options.language
        count, language, unit = reading_count(chunk.tts_text, dictionary=self.options.reading_dictionary, language=language)
        rate = count / max(active, .1)
        threshold = self.options.max_english_wpm / 60 if language == "en" else self.options.max_rate
        report.metrics.update(language=language, reading_unit=unit, reading_unit_count=count, reading_count_basis="normalized_reference_not_observed_word_timestamps",
                              articulation_rate_unit="words_per_second" if language == "en" else
                                  "han_characters_per_second" if language == "zh" else "unavailable_mixed_or_unknown",
                              rate_threshold=threshold if language in {"en", "zh"} else None,
                              rate_threshold_kind="uncalibrated_heuristic")
        report.metrics["articulation_rate"] = rate if count >= 5 else None
        report.metrics["overall_rate"] = count / max(metrics["duration_seconds"], .1) if count else None
        if language == "en":
            report.metrics["words_per_minute"] = report.metrics["overall_rate"] * 60 if count else None
        if self.options.enable_asr:
            try:
                transcript = self.transcript(path)
                alignment = align_text(chunk.tts_text, transcript, dictionary=self.options.reading_dictionary, language=language)
                report.metrics["content_alignment"] = alignment
                report.dimensions["content"] = "passed" if not alignment["operations"] else "incomplete"
                if alignment["operations"]:
                    report.issues.append(QualityIssue("asr_mismatch", "content", chunk.chunk_id,
                                                     evidence=alignment))
            except Exception as exc:
                report.metrics["asr_unavailable"] = type(exc).__name__
        else:
            report.metrics["asr_unavailable"] = "disabled"
        # 多读／漏读时，参考字词数不是实际朗读量；保留估算值，停止用它判断语速。
        alignment = report.metrics.get("content_alignment")
        content_mismatch = bool(alignment and alignment["operations"])
        rate_usable = (not content_mismatch and language in {"en", "zh"}
                       and count >= 5 and metrics["duration_seconds"] >= 1)
        report.metrics.update(rate_policy_version=RATE_POLICY_VERSION,
                              rate_estimate_usable_for_heuristics=rate_usable,
                              rate_estimate_status="unreliable_content_mismatch" if content_mismatch else
                                  "insufficient_duration_or_units" if not rate_usable else
                                  "reference_estimate_content_aligned" if alignment else
                                  "reference_estimate_content_unverified")
        if rate_usable and rate > threshold:
            report.issues.append(QualityIssue("too_fast", "consistency", chunk.chunk_id,
                                             evidence={"rate": rate, "threshold": threshold,
                                                       "unit": report.metrics["articulation_rate_unit"],
                                                       "threshold_kind": "heuristic"}))
        if anchor is not None:
            anchor_path, anchor_metrics = anchor
            anchor_digest = _audio_sha256(anchor_path)
            bindings = [anchor_metrics.get(key) for key in ('fixed_reference_sha256', 'audio_sha256')
                        if anchor_metrics.get(key) is not None]
            if any(digest != anchor_digest for digest in bindings):
                raise ValueError('参考音频已变化，不能沿用旧内容、信号或身份核验依据')
            anchor_alignment = anchor_metrics.get('content_alignment')
            checked = (bool(bindings) and isinstance(anchor_alignment, dict)
                       and anchor_alignment.get('operations') == []
                       and anchor_metrics.get('peak', 0) >= .003
                       and anchor_metrics.get('clipped_fraction', 1) <= .002)
            kind = anchor_metrics.get('fixed_reference_kind') or (
                'bootstrap_signal_and_content_checked' if checked else 'external_reference_unverified')
            report.metrics["consistency_reference"] = {"path": str(anchor_path), "kind": kind,
                "sha256": anchor_digest,
                "source_binding": 'matched_recorded_sha256' if bindings else 'observed_at_comparison_only'}
            previous_rate = anchor_metrics.get("articulation_rate")
            same_unit = anchor_metrics.get("articulation_rate_unit", "han_characters_per_second") == report.metrics["articulation_rate_unit"]
            anchor_mismatch = bool((anchor_metrics.get("content_alignment") or {}).get("operations"))
            if content_mismatch:
                report.metrics["rate_reference_unavailable"] = "current_content_mismatch"
            elif anchor_mismatch or anchor_metrics.get("rate_estimate_usable_for_heuristics") is False:
                report.metrics["rate_reference_unavailable"] = "reference_rate_unreliable"
            elif not same_unit:
                report.metrics["rate_reference_unavailable"] = "different_language_or_unit"
            if (rate_usable and not anchor_mismatch
                    and anchor_metrics.get("rate_estimate_usable_for_heuristics") is not False
                    and same_unit and previous_rate and abs(math.log(max(rate, .01) / previous_rate)) > math.log(1.3)):
                report.issues.append(QualityIssue("rate_drift", "consistency", chunk.chunk_id,
                                                 evidence={"ratio": rate / previous_rate}))
            current_pitch = metrics["pitch"]["median_hz"]
            previous_pitch = anchor_metrics.get("pitch", {}).get("median_hz")
            # 大幅偏移仅触发复核；情绪、声调变化可能合理，不能当作确认故障。
            if current_pitch and previous_pitch:
                shift = 12 * math.log2(current_pitch / previous_pitch)
                report.metrics["pitch_shift_semitones"] = shift
                if (abs(shift) > 6 and metrics["pitch"]["voiced_frames"] >= 50
                        and anchor_metrics.get("pitch", {}).get("voiced_frames", 0) >= 50):
                    report.issues.append(QualityIssue("pitch_drift", "consistency", chunk.chunk_id,
                        evidence={"semitones": shift, "threshold": 6, "threshold_kind": "heuristic"}))
            if self.options.enable_speaker:
                try:
                    distance = 1 - float(np.dot(self.embedding(path), self.embedding(anchor_path)))
                    report.metrics["speaker_distance"] = distance
                    report.metrics["speaker_threshold_kind"] = "uncalibrated"
                    if distance > .35:
                        report.issues.append(QualityIssue("speaker_drift", "consistency", chunk.chunk_id,
                            evidence={"distance": distance, "threshold": .35, "threshold_kind": "heuristic"}))
                    # 未标定阈值之前仅呈现距离，不能把该维度自动判为通过。
                except Exception as exc:
                    report.metrics["speaker_unavailable"] = type(exc).__name__
            if _audio_sha256(anchor_path) != anchor_digest:
                raise RuntimeError('比对期间参考音频变化，不能采用本次一致性证据')
        else:
            report.metrics["consistency_reference"] = "not_available"
        if _audio_sha256(path) != audio_digest:
            raise RuntimeError('质量评估期间音频变化，不能采用本次结果')
        report.metrics["evaluation_seconds"] = time.perf_counter() - started
        self.evaluation_seconds += report.metrics["evaluation_seconds"]
        return report

    def evaluate_boundary(self, left, right, left_path, right_path, *, assembled_window=None):
        started = time.perf_counter()
        boundary_id = f"{left.chunk_id}|{right.chunk_id}"
        report = QualityReport(boundary_id, {"stitching": "incomplete", "content": "incomplete"})
        features = boundary_features(left_path, right_path, same_speaker=left.role_id == right.role_id,
                                     planned_pause_ms=left.pause_after_ms)
        report.metrics["features"] = features
        report.metrics["threshold_kind"] = "heuristic"
        from .boundary_model import heuristic_labels
        for label in heuristic_labels(features):
            report.issues.append(QualityIssue(label, "stitching", boundary_id,
                                             evidence={"features": features, "threshold_kind": "heuristic"}))
        if self.options.boundary_model:
            try:
                from .boundary_model import predict_boundary
                prediction = predict_boundary(self.options.boundary_model, features)
                report.metrics["model_prediction"] = prediction
                report.metrics["threshold_kind"] = prediction["threshold_kind"]
                for label in prediction["labels"]:
                    if not any(i.code == label for i in report.issues):
                        report.issues.append(QualityIssue(label, "stitching", boundary_id,
                                                         evidence={"model": prediction}))
                report.metrics["model_screening"] = "complete" if prediction["thresholds_ready"] else "partial"
                # 训练和选阈值不等于通过真实缺陷验收，先导模型只用于筛查。
            except Exception as exc:
                report.metrics["model_unavailable"] = type(exc).__name__
        if assembled_window and self.options.enable_asr:
            try:
                # 输入窗口应对应完整左右片段，不能拿裁剪音频对齐整段文本。
                alignment = align_text(join_reading_texts([left.tts_text, right.tts_text]), self.transcript(assembled_window),
                                       dictionary=self.options.reading_dictionary,
                                       language=left.language if left.language == right.language else "auto")
                report.metrics["content_alignment"] = alignment
                if alignment["operations"]:
                    report.issues.append(QualityIssue("boundary_content_mismatch", "content", boundary_id,
                                                     evidence=alignment))
                else:
                    report.dimensions["content"] = "passed"
            except Exception as exc:
                report.metrics["asr_unavailable"] = type(exc).__name__
        report.metrics["evaluation_seconds"] = time.perf_counter() - started
        self.evaluation_seconds += report.metrics["evaluation_seconds"]
        return report


def report_rank(report):
    """完整性错误优先，其余遵循拼接、一致性、内容、信号的检查顺序。"""
    hard = sum(i.certainty == "confirmed" and i.severity == "error" for i in report.issues)
    counts = tuple(sum(i.dimension == d for i in report.issues)
                   for d in ("stitching", "consistency", "content", "signal"))
    mismatch = report.metrics.get("content_alignment", {}).get("error_rate", 0)
    excess_rate = report.metrics.get("articulation_rate") or 0
    return (hard, *counts, mismatch, excess_rate if any(i.code == "too_fast" for i in report.issues) else 0)
