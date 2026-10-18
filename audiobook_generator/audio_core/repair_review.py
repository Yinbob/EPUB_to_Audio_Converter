"""修复前后盲听先导材料；只导出既有音频，不预填人工结论。"""
from __future__ import annotations

import csv
import hashlib
import json
import random
import tempfile
from datetime import datetime
from pathlib import Path

import soundfile as sf

from .audio import load_audio

DIMENSIONS = ("stitching", "consistency", "content", "signal")
CHOICES = {"A", "B", "tie", "uncertain", "not_applicable"}


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_report(path):
    path = Path(path).resolve()
    payload = path.read_bytes()
    report = json.loads(payload)
    if report.get("schema_version") != "audio-core-v1" or report.get("provider") != "openai" or report.get("generation_status") != "generated":
        raise ValueError("盲听需要已生成的 MiMo 统一核心报告")
    encoded = report.get("final_verification", {})
    expected = encoded.get("metrics", {}).get("encoded_sha256")
    audio = Path(report["output_file"]).resolve()
    if encoded.get("dimensions", {}).get("encoding") != "passed" or not expected or _sha(audio) != expected:
        raise ValueError("最终音频缺少编码保留检查或已改变，请先离线复评")
    chunks, mapping = report["chunks"], report["assembly"]
    spans, rate = mapping["spans"], mapping["sample_rate"]
    if not chunks or rate <= 0 or len(spans) != len(chunks) or any(
            span["chunk_id"] != chunk["chunk"]["chunk_id"] or not 0 <= span["start_sample"] < span["end_sample"] <= mapping["total_samples"]
            for span, chunk in zip(spans, chunks)):
        raise ValueError("报告正文与时间表不一致")
    if any(left["end_sample"] > right["start_sample"] for left, right in zip(spans, spans[1:])):
        raise ValueError("时间表顺序不一致")
    return {"path": str(path), "report_sha256": hashlib.sha256(payload).hexdigest(),
            "report": report, "audio": audio, "encoded_sha256": expected}


def _identity(report):
    return [(c["chunk"]["chunk_id"], c["chunk"]["role_id"], c["chunk"]["source_text"],
             c["chunk"]["tts_text"], c["chunk"].get("profile", {}), c["chunk"].get("tone")) for c in report["chunks"]]


def prepare_repair_review(pairs, output_dir, *, seed=42):
    """随机 A/B、隐藏方法与机器诊断，使用最终编码的 PCM 试听副本。"""
    if not isinstance(pairs, list) or not pairs:
        raise ValueError("至少指定一组 baseline_report／candidate_report")
    destination = Path(output_dir).resolve()
    if destination.exists():
        raise ValueError("盲听包已存在，拒绝覆盖")
    sources, seen = [], set()
    for pair in pairs:
        before, after = (_read_report(pair[key]) for key in ("baseline_report", "candidate_report"))
        a, b = before["report"], after["report"]
        group = (a["source_group_id"], a["chapter_index"])
        if (group != (b["source_group_id"], b["chapter_index"]) or _identity(a) != _identity(b)):
            raise ValueError("比较版本的正文、角色、声音或分块不一致")
        if group in seen:
            raise ValueError("同一来源章节不能重复作为独立试题")
        seen.add(group)
        sources.append((before, after))
    destination.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    with tempfile.TemporaryDirectory(prefix=".repair-review-", dir=destination.parent) as temporary:
        root = Path(temporary) / "pack"
        public = root / "public"
        (public / "audio").mkdir(parents=True)
        trials, answers, checksums = [], {}, {}
        for index, source_pair in enumerate(sources, 1):
            trial_id = f"T{index:03d}"
            arms = list(zip(("baseline", "candidate"), source_pair))
            rng.shuffle(arms)
            versions, private = {}, {}
            roles = {role: f"角色{number}" for number, role in enumerate(
                dict.fromkeys(c["chunk"]["role_id"] for c in source_pair[0]["report"]["chunks"]), 1)}
            for label, (method, source) in zip(("A", "B"), arms):
                report = source["report"]
                audio, rate = load_audio(source["audio"])
                if not len(audio) or rate != report["assembly"]["sample_rate"] or abs(len(audio) - report["assembly"]["total_samples"]) > round(.15 * rate):
                    raise ValueError("最终音频与记录的时间表不符")
                relative = f"audio/{trial_id}_{label}.wav"
                sf.write(public / relative, audio, rate, subtype="PCM_16")
                if _sha(source["audio"]) != source["encoded_sha256"] or _sha(source["path"]) != source["report_sha256"]:
                    raise ValueError("导出期间来源报告或音频改变")
                checksums[relative] = _sha(public / relative)
                versions[label] = {"audio": relative, "duration_seconds": len(audio) / rate,
                    "segments": [{"role": roles[c["chunk"]["role_id"]], "text": c["chunk"]["source_text"],
                                  "spoken_reference": c["chunk"]["tts_text"],
                                  "start_seconds": span["start_sample"] / rate,
                                  "end_seconds": span["end_sample"] / rate}
                                 for c, span in zip(report["chunks"], report["assembly"]["spans"])],
                    "joins": [{"start_seconds": join["start_sample"] / rate, "end_seconds": join["end_sample"] / rate,
                               "same_speaker": join["same_speaker"]} for join in report["assembly"]["boundaries"]]}
                private[label] = {"method": method, "report_path": source["path"],
                                  "report_sha256": source["report_sha256"], "encoded_sha256": source["encoded_sha256"]}
            trials.append({"trial_id": trial_id, "versions": versions})
            answers[trial_id] = {"source_group_id": source_pair[0]["report"]["source_group_id"], "arms": private}
        rng.shuffle(trials)
        (public / "trials.json").write_text(json.dumps({"task": "blind_repair_comparison_pilot", "trials": trials}, ensure_ascii=False, indent=2))
        with (public / "responses.csv").open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=["participant_id", "trial_id", "review_status", "reviewed_at", *DIMENSIONS, "notes"])
            writer.writeheader()
            writer.writerows({"trial_id": trial["trial_id"], "review_status": "pending"} for trial in trials)
        lines = ["# 修复质量盲听先导", "", "仅向听众分发 public 目录。请先打开 trials.json 查看原文、预期读法、角色区间和各版本拼接位置。", "",
                 "按顺序比较拼接截断／漏音／重叠／停顿、同角色音色音调语速一致性、重复漏读错读、信号听感。正常换角色不算漂移；速度更慢本身不等于更好。", "",
                 "在 responses.csv 的 stitching、consistency、content、signal 中填写较好的版本 A 或 B；相当填 tie，无法判断填 uncertain，不适用填 not_applicable。", "",
                 "填写 participant_id、带时区的 reviewed_at，将 review_status 改为 reviewed。notes 写明版本、秒数、对应文字和原因。每名听众使用独立表格；实验者合并后评分。", "",
                 "音频是各版本最终编码解码后的统一 PCM16 试听副本，未再次变速或归一化。每题 A/B 随机且固定；此包不控制听众重复暴露，正式实验需分组／顺序平衡。", "",
                 "仅做先导偏好统计，不据此推断缺陷修复率、显著性或模型泛化。机器报告及版本对应关系保留在私有答案中。", ""]
        for trial in trials:
            lines += [f"## {trial['trial_id']}", "", f"[试听 A]({trial['versions']['A']['audio']}) · [试听 B]({trial['versions']['B']['audio']})", ""]
            for segment in trial["versions"]["A"]["segments"]:
                lines += [f"{segment['role']}原文：{segment['text']}", "", f"预期读法：{segment['spoken_reference']}", ""]
            for label, version in trial["versions"].items():
                intervals = "；".join(f"{s['role']} {s['start_seconds']:.2f}～{s['end_seconds']:.2f} 秒" for s in version["segments"])
                joins = "；".join(f"{j['start_seconds']:.2f}～{j['end_seconds']:.2f} 秒（{'同角色' if j['same_speaker'] else '换角色'}）" for j in version["joins"]) or "无跨块接缝"
                lines += [f"{label} 角色区间：{intervals}。拼接位置：{joins}。", ""]
        (public / "README.md").write_text("\n".join(lines))
        checksums["trials.json"] = _sha(public / "trials.json")
        (root / "private_key.json").write_text(json.dumps({"task": "blind_repair_comparison_pilot", "seed": seed,
            "answers": answers, "public_sha256": checksums}, ensure_ascii=False, indent=2))
        root.rename(destination)
    return {"output": str(destination), "trials": len(trials), "pending": len(trials), "requests_sent": 0,
            "distribution_note": "只分发 public；private_key.json 留给实验者。"}


def score_repair_review(key_path, responses_path):
    key_path = Path(key_path).resolve()
    key = json.loads(key_path.read_text())
    if key.get("task") != "blind_repair_comparison_pilot":
        raise ValueError("盲听答案版本不匹配")
    public = key_path.parent / "public"
    for name, expected in key["public_sha256"].items():
        path = (public / name).resolve()
        if not path.is_relative_to(public) or _sha(path) != expected:
            raise ValueError("试听材料已改变，不能沿用旧答案评分")
    seen, reviewed, skipped, participants, groups = set(), 0, 0, set(), set()
    counts = {dimension: {choice: 0 for choice in ("baseline", "candidate", "tie", "uncertain", "not_applicable")} for dimension in DIMENSIONS}
    with Path(responses_path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"participant_id", "trial_id", "review_status", "reviewed_at", *DIMENSIONS}
        if not required <= set(reader.fieldnames or []):
            raise ValueError("盲听表缺少必要列")
        for row in reader:
            trial = row["trial_id"].strip()
            if trial not in key["answers"]:
                raise ValueError("未知盲听试题")
            status = row["review_status"].strip()
            if status in {"pending", "needs_review"}:
                skipped += 1
                continue
            participant = row["participant_id"].strip()
            if status != "reviewed" or not participant or (participant, trial) in seen:
                raise ValueError("核验状态、参与者或重复回答不合规")
            stamp = datetime.fromisoformat(row["reviewed_at"].strip().replace("Z", "+00:00"))
            if stamp.utcoffset() is None:
                raise ValueError("人工核验时间必须带时区")
            for dimension in DIMENSIONS:
                choice = row[dimension].strip()
                if choice not in CHOICES:
                    raise ValueError("四维评价须明确填写 A/B/tie/uncertain/not_applicable")
                method = key["answers"][trial]["arms"][choice]["method"] if choice in {"A", "B"} else choice
                counts[dimension][method] += 1
            seen.add((participant, trial))
            reviewed += 1
            participants.add(participant)
            groups.add(key["answers"][trial]["source_group_id"])
    return {"analysis_kind": "descriptive_blind_repair_pilot", "reviewed": reviewed, "skipped": skipped,
            "participants": len(participants), "source_groups": len(groups), "dimension_preferences": counts,
            "status": "awaiting_human_review" if not reviewed else "descriptive_only", "requests_sent": 0,
            "note": "偏好票数不是缺陷修复率；未做重复测量或来源聚类推断，不据此声称显著改善。"}
