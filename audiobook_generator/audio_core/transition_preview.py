"""已知接缝的受控试听候选；不接入自动修复，不覆盖或重合成来源。"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from .audio import edge_silence, load_audio
from .quality import align_text
from .language import join_reading_texts
from .repair_review import _read_report, _sha


def prepare_transition_preview(report_path, boundary_id, output_dir, *, extra_pause_ms=150,
                               onset_gain=.8, ramp_ms=(200, 400), evaluator=None):
    """保留同一最终编码副本；局部正增益仅供人工比较，不能据此自动判为安全。"""
    if type(extra_pause_ms) is not int or not 1 <= extra_pause_ms <= 1000:
        raise ValueError("试听追加停顿必须为 1～1000 毫秒整数")
    if isinstance(onset_gain, bool) or not np.isfinite(onset_gain) or not .4 <= onset_gain < 1:
        raise ValueError("试听起始增益必须在 0.4（含）到 1（不含）之间")
    if not ramp_ms or len(set(ramp_ms)) != len(ramp_ms) or any(type(n) is not int or not 1 <= n <= 500 for n in ramp_ms):
        raise ValueError("试听增益恢复长度必须为不同的 1～500 毫秒整数")
    output = Path(output_dir).resolve()
    if output.exists():
        raise ValueError("试听候选目录已存在，拒绝覆盖")
    source = _read_report(report_path)
    report = source["report"]
    mapping = report["assembly"]
    selected = [b for b in mapping["boundaries"] if b["boundary_id"] == boundary_id]
    if len(selected) != 1:
        raise ValueError("必须指定报告中唯一存在的边界编号")
    boundary = selected[0]
    spans = mapping["spans"]
    indices = [i for i, s in enumerate(spans[:-1]) if s["chunk_id"] == boundary["left_chunk_id"]
               and spans[i + 1]["chunk_id"] == boundary["right_chunk_id"]]
    if len(indices) != 1:
        raise ValueError("接缝左右块必须在时间表中相邻")
    index = indices[0]
    left, right = spans[index:index + 2]
    if left["end_sample"] != boundary["start_sample"] or right["start_sample"] != boundary["end_sample"]:
        raise ValueError("接缝与分块实际样本位置不符")
    samples, rate = load_audio(source["audio"])
    if rate != mapping["sample_rate"] or len(samples) != mapping["total_samples"]:
        raise ValueError("此试听入口要求编码解码样本数与时间表严格一致")
    left_quiet = edge_silence(samples[left["start_sample"]:left["end_sample"]], rate, leading=False)
    right_quiet = edge_silence(samples[right["start_sample"]:right["end_sample"]], rate, leading=True)
    onset = right["start_sample"] + round(right_quiet * rate)
    if any(onset + round(n / 1000 * rate) > right["end_sample"] for n in ramp_ms):
        raise ValueError("右侧片段不足以容纳指定增益恢复窗口")
    model = evaluator.backend_identity("asr") if evaluator else None
    reference = join_reading_texts(c["chunk"]["tts_text"] for c in report["chunks"])
    dictionary = report.get("reading_configuration", {}).get("reading_dictionary", {})
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".transition-preview-", dir=output.parent) as temporary:
        root = Path(temporary) / "pack"
        (root / "audio").mkdir(parents=True)
        baseline = root / "audio/original.wav"
        sf.write(baseline, samples, rate, subtype="PCM_16")
        pcm, _ = sf.read(baseline, dtype="int16", always_2d=True)
        pause_frames = round(extra_pause_ms / 1000 * rate)
        insertion = right["start_sample"]
        variants = [("original", pcm, {"kind": "reference", "added_samples": 0}),
                    (f"pause_plus_{extra_pause_ms}ms", np.concatenate([pcm[:insertion],
                         np.zeros((pause_frames, pcm.shape[1]), dtype=np.int16), pcm[insertion:]]),
                     {"kind": "extra_pause", "added_samples": pause_frames, "insert_at_sample": insertion})]
        for duration in ramp_ms:
            end = onset + round(duration / 1000 * rate)
            modified = pcm.copy()
            gain = np.linspace(onset_gain, 1., end - onset)[:, None]
            modified[onset:end] = np.rint(pcm[onset:end].astype(float) * gain).astype(np.int16)
            variants.append((f"onset_gain_{duration}ms", modified,
                {"kind": "nonzero_onset_gain", "added_samples": 0, "start_sample": onset,
                 "end_sample": end, "initial_gain": onset_gain, "final_gain": 1.,
                 "onset_kind": "low_energy_estimate_not_phoneme_alignment"}))
        results = []
        for name, candidate, operation in variants:
            full = root / f"audio/{name}.wav"
            sf.write(full, candidate, rate, subtype="PCM_16")
            actual, _ = sf.read(full, dtype="int16", always_2d=True)
            if not np.array_equal(actual, candidate):
                raise ValueError("试听文件与计划 PCM 不一致")
            if operation["kind"] == "extra_pause":
                preserves = np.array_equal(actual[:insertion], pcm[:insertion]) and np.array_equal(actual[insertion + pause_frames:], pcm[insertion:])
                preserves &= not np.any(actual[insertion:insertion + pause_frames])
            elif operation["kind"] == "nonzero_onset_gain":
                start, end = operation["start_sample"], operation["end_sample"]
                preserves = np.array_equal(actual[:start], pcm[:start]) and np.array_equal(actual[end:], pcm[end:])
                preserves &= bool(np.all(np.abs(actual[start:end].astype(np.int32)) <= np.abs(pcm[start:end].astype(np.int32))))
            else:
                preserves = np.array_equal(actual, pcm)
            if not preserves or len(actual) != len(pcm) + operation["added_samples"]:
                raise ValueError("修改范围之外的 PCM 或样本长度检查失败")
            preview_start = max(0, boundary["start_sample"] - 2 * rate)
            preview_end = min(len(candidate), boundary["end_sample"] + operation["added_samples"] + 3 * rate)
            excerpt = root / f"audio/{name}_window.wav"
            sf.write(excerpt, actual[preview_start:preview_end], rate, subtype="PCM_16")
            item = {"name": name, "full_audio": str(full.relative_to(root)),
                    "window_audio": str(excerpt.relative_to(root)), "operation": operation,
                    "sample_rate": rate, "samples": len(actual), "duration_seconds": len(actual) / rate,
                    "outside_operation_pcm_unchanged": True, "sha256": _sha(full),
                    "window_sha256": _sha(excerpt),
                    "boundary_in_window_seconds": (boundary["start_sample"] - preview_start) / rate,
                    "content_check": {"status": "not_assessed"}}
            if evaluator:
                try:
                    alignment = align_text(reference, evaluator.transcript(full), dictionary=dictionary,
                                           language=report.get("reading_configuration", {}).get("language", "auto"))
                    item["content_check"] = {"status": "no_asr_difference" if not alignment["operations"] else "asr_difference",
                                             "alignment": alignment}
                except Exception as exc:
                    item["content_check"] = {"status": "incomplete", "error_type": type(exc).__name__}
            results.append(item)
        if _sha(source["audio"]) != source["encoded_sha256"] or _sha(source["path"]) != source["report_sha256"]:
            raise ValueError("生成试听候选期间来源文件发生改变")
        if evaluator and evaluator.backend_identity("asr") != model:
            raise ValueError("本组试听候选评估期间 ASR 模型改变")
        manifest = {"version": "transition-preview-v1", "mode": "manual_experiment_only",
                    "source_report": source["path"], "source_report_sha256": source["report_sha256"],
                    "encoded_source_sha256": source["encoded_sha256"], "source_group_id": report["source_group_id"],
                    "boundary_id": boundary_id, "sample_rate": rate, "original_samples": len(pcm),
                    "low_energy_estimate_seconds": {"left_tail": left_quiet, "right_head": right_quiet,
                        "existing_inserted_gap": (boundary["end_sample"] - boundary["start_sample"]) / rate,
                        "note": "RMS threshold estimate; not verified silence or missing-pause diagnosis"},
                    "asr_model": model, "candidates": results, "additional_tts_requests": 0,
                    "human_preference": None, "automatically_applied": False,
                    "limitations": "ASR equality does not prove audibility or naturalness; gain windows alter speech amplitude intentionally for manual comparison."}
        (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        lines = ["# 第一章接缝候选试听", "", "本包只有一个来源接缝。以下是受控试听候选，未应用到生成默认配置，原始文件保留。", "",
                 "先听局部窗口，再用完整音频核对语境。窗口中约第 2 秒为拼接位置；追加停顿版右段延后。", "",
                 "比较衔接是否自然、第二段首字是否清楚、停顿是否拖沓。无需重填之前的六行标注或两道 A/B 表。", "",
                 f"音量候选的波形幅度从 {onset_gain:.0%} 恢复到 100%，没有从零淡入；恢复起点由低能量规则估计，不是已验证的字音边界。", "",
                 "低能量区不等于已确认静音。增加停顿或调整音量都未证明更好，ASR 一致也不证明听感合格。", ""]
        for item in results:
            lines += [f"- **{item['name']}**：[局部试听]({item['window_audio']}) · [完整音频]({item['full_audio']})；内容筛查：`{item['content_check']['status']}`。"]
        (root / "README.md").write_text("\n".join(lines) + "\n")
        root.rename(output)
    return {"output": str(output), "candidates": len(results), "additional_tts_requests": 0,
            "human_review_required": True, "automatically_applied": False,
            "content_checks": {item["name"]: item["content_check"]["status"] for item in results}}
