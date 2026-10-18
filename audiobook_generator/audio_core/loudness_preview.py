"""对已核验来源的右句做恒定衰减试听；不自动应用，不修改选角。"""
from __future__ import annotations

import json
import math
import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from .annotations import _verify_pcm_layout
from .language import join_reading_texts
from .quality import align_text
from .repair_review import _read_report, _sha


def measure_loudness(path):
    """只读取 loudnorm 的输入测量值，不使用其处理后的波形。"""
    from audiobook_generator.role_script.audio_pipeline import require_ffmpeg_tools
    ffmpeg, _ = require_ffmpeg_tools()
    process = subprocess.run([ffmpeg, "-hide_banner", "-nostdin", "-i", str(path),
        "-af", "loudnorm=I=-23:TP=-1:LRA=11:print_format=json", "-f", "null", "-"],
        capture_output=True, text=True, check=True, timeout=30)
    blocks = re.findall(r"\{[^{}]+\}", process.stderr)
    if not blocks:
        raise ValueError("未获得响度测量，不能制作匹配候选")
    result = json.loads(blocks[-1])
    values = {key: float(result[key]) for key in ("input_i", "input_tp", "input_lra", "input_thresh")}
    if not all(math.isfinite(v) for v in values.values()):
        raise ValueError("响度测量无效；静音或过短音频需人工处理")
    return {"integrated_lufs": values["input_i"], "true_peak_dbfs": values["input_tp"],
            "lra_lu": values["input_lra"], "gate_lufs": values["input_thresh"],
            "measurement": "ffmpeg_loudnorm_input_only"}


def prepare_loudness_preview(report_path, boundary_id, output_dir, *, max_attenuation_db=6., evaluator=None):
    """仅降低偏响右句的整体电平，保留全部样本位置及其他片段。"""
    if (isinstance(max_attenuation_db, bool) or not math.isfinite(max_attenuation_db)
            or not 0 < max_attenuation_db <= 12):
        raise ValueError("最大衰减必须为 0～12 dB 之间的有限正数")
    destination = Path(output_dir).resolve()
    if destination.exists():
        raise ValueError("响度试听目录已存在，拒绝覆盖")
    source = _read_report(report_path)
    report, audio = source["report"], source["audio"]
    info = sf.info(audio)
    if info.format != "WAV" or info.subtype != "PCM_16":
        raise ValueError("响度试听要求原生 PCM16 WAV，避免重编码改变其他样本")
    mapping = report["assembly"]
    _verify_pcm_layout(audio, mapping, report["chunks"])
    selected = [b for b in mapping["boundaries"] if b["boundary_id"] == boundary_id]
    if len(selected) != 1:
        raise ValueError("必须指定唯一存在的接缝")
    boundary = selected[0]
    spans = mapping["spans"]
    indices = [i for i, span in enumerate(spans[:-1])
               if span["chunk_id"] == boundary["left_chunk_id"]
               and spans[i+1]["chunk_id"] == boundary["right_chunk_id"]]
    if len(indices) != 1:
        raise ValueError("响度试听的左右片段必须相邻")
    index = indices[0]
    left, right = spans[index:index+2]
    if left["end_sample"] != boundary["start_sample"] or right["start_sample"] != boundary["end_sample"]:
        raise ValueError("接缝与左右样本位置不符")
    samples, rate = sf.read(audio, dtype="int16", always_2d=True)
    start, end = right["start_sample"], right["end_sample"]
    expected = join_reading_texts(c["chunk"]["tts_text"] for c in report["chunks"][index:index+2])
    language = report["chunks"][index]["chunk"].get("language", "auto")
    dictionary = report.get("reading_configuration", {}).get("reading_dictionary", {})
    model_before = evaluator.backend_identity("asr") if evaluator else None
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".loudness-preview-", dir=destination.parent) as folder:
        root = Path(folder)/"pack"
        (root/"audio").mkdir(parents=True)
        left_pcm, right_pcm = root/"left.wav", root/"right.wav"
        sf.write(left_pcm, samples[left["start_sample"]:left["end_sample"]], rate, subtype="PCM_16")
        sf.write(right_pcm, samples[start:end], rate, subtype="PCM_16")
        before = {"left": measure_loudness(left_pcm), "right": measure_loudness(right_pcm)}
        difference = before["right"]["integrated_lufs"] - before["left"]["integrated_lufs"]
        if difference <= .1:
            raise ValueError("右句并未测得更响，不制作降音量候选")
        attenuation = min(float(max_attenuation_db), difference)
        gain = 10 ** (-attenuation/20)
        modified = samples.copy()
        modified[start:end] = np.rint(samples[start:end].astype(np.float64)*gain).astype(np.int16)
        paths = {"original_full": "audio/original_full.wav", "matched_full": "audio/matched_full.wav",
                 "original_pair": "audio/original_pair.wav", "matched_pair": "audio/matched_pair.wav"}
        for key, value in paths.items():
            pcm = modified if key.startswith("matched") else samples
            if key.endswith("pair"):
                pcm = pcm[left["start_sample"]:end]
            sf.write(root/value, pcm, rate, subtype="PCM_16")
        sf.write(right_pcm, modified[start:end], rate, subtype="PCM_16")
        after = measure_loudness(right_pcm)
        left_pcm.unlink()
        right_pcm.unlink()
        comparisons = {}
        for key in ("original_pair", "matched_pair"):
            comparisons[key] = {"status": "not_evaluated"}
            if evaluator:
                try:
                    alignment = align_text(expected, evaluator.transcript(root/paths[key]),
                                           language=language, dictionary=dictionary)
                    comparisons[key] = {"status": "asr_difference" if alignment["operations"] else "no_asr_difference",
                                        "alignment": alignment}
                except Exception as exc:
                    comparisons[key] = {"status": "incomplete", "reason": type(exc).__name__}
        if evaluator and evaluator.backend_identity("asr") != model_before:
            raise ValueError("试听核验期间 ASR 模型变化，请重新生成证据")
        if _sha(source["path"]) != source["report_sha256"] or _sha(audio) != source["encoded_sha256"]:
            raise ValueError("响度试听期间来源变化，拒绝发布")
        _verify_pcm_layout(audio, mapping, report["chunks"])
        manifest = {"version": "boundary-loudness-preview-v1", "source_report": source["path"],
            "source_report_sha256": source["report_sha256"], "source_audio": str(audio),
            "source_audio_sha256": source["encoded_sha256"], "source_group_id": report["source_group_id"],
            "boundary_id": boundary_id, "before": before, "after_right": after,
            "original_right_minus_left_lu": difference,
            "candidate_right_minus_left_lu": after["integrated_lufs"]-before["left"]["integrated_lufs"],
            "operation": {"kind": "constant_attenuation_right_chunk", "attenuation_db": attenuation,
                          "gain": gain, "start_sample": start, "end_sample": end,
                          "max_attenuation_db": float(max_attenuation_db)},
            "sample_rate": rate, "channels": samples.shape[1], "total_samples": len(samples),
            "pair_start_sample": left["start_sample"], "pair_end_sample": end,
            "paths": paths, "files": [{"path": p, "sha256": _sha(root/p)} for p in paths.values()],
            "content_checks": comparisons, "asr_model": model_before,
            "automatically_applied": False, "human_preference": None, "requests_sent": 0,
            "usage": "实验者局部质检试听；正式选角对照需各条件使用相同响度处理协议"}
        (root/"manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n")
        (root/"README.md").write_text(
            "# 接缝响度试听\n\n只降低右侧整句音量，保留所有样本位置、停顿、语速和声音分配。\n\n"
            f"右句降低 {attenuation:.2f} dB，线性增益 {gain:.3f}。人工偏好仍待填写。\n\n"
            "- [原始两句](audio/original_pair.wav)\n- [响度匹配两句](audio/matched_pair.wav)\n"
            "- [原始全章](audio/original_full.wav)\n- [局部处理全章](audio/matched_full.wav)\n\n"
            "这是局部质检对照，未自动替换原件，不是盲化听众辨识材料。\n")
        root.rename(destination)
    return {"output": str(destination), "attenuation_db": attenuation, "gain": gain,
            "content_checks": {key: value["status"] for key, value in comparisons.items()},
            "requests_sent": 0, "automatically_applied": False}
