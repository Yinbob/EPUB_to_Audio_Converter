"""离线回填人工边界标注；保留未知状态，不替人工判断。"""
from __future__ import annotations

import csv
import hashlib
import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from .boundary_model import LABELS, feature_vector
from .report_sources import resolve_reference_pcm


MANUAL_FIELDS = {"review_status", "cutoff", "gap", "click", "overlap", "timbre_drift",
                 "pitch_drift", "rate_drift", "omission", "repetition", "misreading",
                 "labels_json", "reviewer", "reviewed_at", "notes"}
ASPECT_LABELS = {"click": "boundary_click_suspected", "cutoff": "cutoff_suspected",
                 "overlap": "overlap", "gap": "unexpected_gap"}
ASPECTS = MANUAL_FIELDS - {"review_status", "labels_json", "reviewer", "reviewed_at", "notes"}
REVIEW_FIELDS = ["sample_id", "sample_type", "chapter", "role_ids", "same_speaker", "audio_path",
                 "full_context_path", "boundary_at_seconds", "source_text", "expected_tts_text",
                 "review_status", "cutoff", "gap", "click", "overlap", "timbre_drift", "pitch_drift",
                 "rate_drift", "omission", "repetition", "misreading", "labels_json", "reviewer",
                 "reviewed_at", "notes", "scope_kind", "parent_chunk_id"]


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _inside(root, path):
    result = (root / path).resolve()
    if not result.is_relative_to(root):
        raise ValueError("标注包路径必须位于包内")
    return result


def _verify_pcm_layout(path, mapping, items):
    """逐块核对当前章节／组合的实际 PCM，防止同长度的错误上下文进入标注。"""
    import numpy as np
    import soundfile as sf
    spans, joins = mapping["spans"], mapping["boundaries"]
    if (len(spans) != len(items) or len(joins) != len(items) - 1
            or [s["chunk_id"] for s in spans] != [item["chunk"]["chunk_id"] for item in items]
            or len({s["chunk_id"] for s in spans}) != len(spans)):
        raise ValueError("PCM 时间表的块数、顺序或编号不一致")
    cursor = 0
    with sf.SoundFile(path) as stream:
        if (stream.subtype != "PCM_16" or stream.frames != mapping["total_samples"]
                or stream.samplerate != mapping["sample_rate"] or stream.channels != mapping["channels"]):
            raise ValueError("PCM 文件与时间表格式不一致")
        for i, (span, item) in enumerate(zip(spans, items)):
            start, end = span.get("start_sample"), span.get("end_sample")
            if type(start) is not int or type(end) is not int or start != cursor or end <= start:
                raise ValueError("PCM 时间表缺少有效的连续样本区间")
            source = Path(item["rendered_path"])
            if _sha(source) != span.get("render_sha256"):
                raise ValueError("分块音频与生成报告校验值不一致")
            with sf.SoundFile(source) as reference:
                if (reference.subtype != "PCM_16" or reference.frames != end - start
                        or reference.samplerate != stream.samplerate or reference.channels != stream.channels):
                    raise ValueError("分块音频与时间表格式不一致")
                while True:
                    expected = reference.read(65536, dtype="int16", always_2d=True)
                    if not len(expected):
                        break
                    actual = stream.read(len(expected), dtype="int16", always_2d=True)
                    if not np.array_equal(actual, expected):
                        raise ValueError("实际 PCM 与选中片段内容不一致，请恢复后再导出")
            cursor = end
            if i < len(joins):
                boundary = joins[i]
                if (boundary["left_chunk_id"] != span["chunk_id"]
                        or boundary["right_chunk_id"] != spans[i + 1]["chunk_id"]
                        or boundary["start_sample"] != cursor
                        or boundary["end_sample"] != spans[i + 1]["start_sample"]
                        or boundary["end_sample"] < cursor):
                    raise ValueError("PCM 边界与相邻片段位置不一致")
                remaining = boundary["end_sample"] - cursor
                while remaining:
                    size = min(65536, remaining)
                    silence = stream.read(size, dtype="int16", always_2d=True)
                    if len(silence) != size or np.any(silence != 0):
                        raise ValueError("计划补充的静音区存在其他音频内容")
                    remaining -= size
                cursor = boundary["end_sample"]
        if cursor != stream.frames:
            raise ValueError("PCM 时间表未覆盖完整文件")


def export_review_pack(reports, output):
    """从生成报告导出完整片段与真实 PCM 接缝；不导入机器结论。"""
    import soundfile as sf
    from .store import fingerprint
    destination = Path(output).resolve()
    if destination.exists():
        raise ValueError("标注包目录已存在，请使用新路径以保留人工填写结果")
    destination.parent.mkdir(parents=True, exist_ok=True)
    rows, boundaries, files, sections, chapters = [], [], [], [], set()
    with tempfile.TemporaryDirectory(prefix=".review-export-", dir=destination.parent) as folder:
        stage = Path(folder) / "pack"
        (stage / "audio").mkdir(parents=True)

        def record(path, source):
            info = sf.info(path)
            files.append({"path": str(path.relative_to(stage)), "sha256": _sha(path),
                          "sample_rate": info.samplerate, "channels": info.channels, "frames": info.frames,
                          "source_path": str(source)})

        def copy(source, name):
            path = stage / "audio" / name
            shutil.copyfile(source, path)
            if _sha(path) != _sha(Path(source)):
                raise ValueError("导出音频校验失败")
            record(path, source)
            return path

        def add_row(**fields):
            row = {key: "" for key in REVIEW_FIELDS}
            row.update(fields, review_status="pending")
            rows.append(row)

        for report_file in reports:
            report_path = Path(report_file).resolve()
            report = json.loads(report_path.read_text(encoding="utf-8"))
            if (report.get("schema_version") != "audio-core-v1" or report.get("provider") != "openai"
                    or report.get("generation_status") != "generated" or not report.get("chunks")):
                raise ValueError("只导出已有音频的 MiMo 生成报告；生成成功不等于质量通过")
            chapter = report["chapter_index"]
            if type(chapter) is not int or chapter < 1 or chapter in chapters:
                raise ValueError("一个标注包中每章只能选一个版本，章节编号必须是正整数")
            chapters.add(chapter)
            original = resolve_reference_pcm(report, report_path)
            assembly = report["assembly"]
            info = sf.info(original)
            if (info.frames != assembly["total_samples"] or info.samplerate != assembly["sample_rate"]
                    or info.channels != assembly["channels"]):
                raise ValueError("章节 PCM 与报告的时间表不一致")
            _verify_pcm_layout(original, assembly, report["chunks"])
            full = copy(original, f"chapter_{chapter:06d}_full.wav")
            full_rel = str(full.relative_to(stage))
            full_final = str(destination / full_rel)
            group = report.get("source_group_id") or fingerprint("".join(c["chunk"]["source_text"] for c in report["chunks"]))
            chunk_map, exported, internal_jobs = {}, {}, []
            spans = {span["chunk_id"]: span for span in assembly["spans"]}
            for i, item in enumerate(report["chunks"], 1):
                chunk = item["chunk"]
                cid = chunk["chunk_id"]
                if cid in chunk_map or cid not in spans:
                    raise ValueError("分块清单重复或缺少时间映射")
                chunk_map[cid] = chunk
                expected_sha = spans[cid].get("render_sha256")
                if expected_sha and _sha(Path(item["rendered_path"])) != expected_sha:
                    raise ValueError("分块音频与生成报告校验值不一致")
                sid = f"C{chapter:06d}_{i:03d}"
                path = copy(item["rendered_path"], sid + ".wav")
                rel = str(path.relative_to(stage))
                exported[cid] = str(destination / rel)
                add_row(sample_id=sid, sample_type="chunk", chapter=str(chapter), role_ids=chunk["role_id"],
                        audio_path=rel, full_context_path=full_rel, source_text=chunk["source_text"],
                        expected_tts_text=chunk["tts_text"], scope_kind="parent_chunk")
                sections.append(f"### {sid} · 完整片段 · {chunk['role_id']}\n\n[试听]({rel})\n\n"
                                f"原文：{chunk['source_text']}\n\n预期读法：{chunk['tts_text']}\n")
                composition = item.get("composition")
                if not composition:
                    continue
                # 只采用实际选中组合的样本位置；过时的变换前时间表不能映射到最终章节。
                parts = item.get("synthesis_parts", [])
                internal = composition.get("base_assembly", {})
                if (composition.get("coordinate_scope") != "parent_rendered_pcm" or len(parts) != 2
                        or composition.get("render_sha256") != expected_sha
                        or len(internal.get("spans", [])) != 2 or len(internal.get("boundaries", [])) != 1
                        or internal.get("sample_rate") != assembly["sample_rate"]
                        or internal.get("channels") != assembly["channels"]
                        or spans[cid].get("end_sample", 0) - spans[cid].get("start_sample", 0) != internal.get("total_samples")
                        or "".join(p["chunk"]["tts_text"] for p in parts) != chunk["tts_text"]
                        or "".join(p["chunk"]["source_text"] for p in parts) != chunk["source_text"]):
                    raise ValueError("内部组合来源或时间表不对应当前选中音频")
                children, child_paths = {}, {}
                _verify_pcm_layout(item["rendered_path"], internal, parts)
                for j, (part, span) in enumerate(zip(parts, internal["spans"]), 1):
                    child = part["chunk"]
                    pid = child["chunk_id"]
                    if (pid in children or pid != span["chunk_id"] or child["role_id"] != chunk["role_id"]
                            or _sha(Path(part["rendered_path"])) != span.get("render_sha256")):
                        raise ValueError("内部子块缺失、重复或音频校验值不一致")
                    child_info = sf.info(part["rendered_path"])
                    if (child_info.frames != span["end_sample"] - span["start_sample"]
                            or child_info.samplerate != internal["sample_rate"] or child_info.channels != internal["channels"]):
                        raise ValueError("内部子块音频与样本时间表不一致")
                    child_sid = f"P{chapter:06d}_{i:03d}_{j:03d}"
                    child_path = copy(part["rendered_path"], child_sid + ".wav")
                    child_rel = str(child_path.relative_to(stage))
                    children[pid], child_paths[pid] = child, str(destination / child_rel)
                    add_row(sample_id=child_sid, sample_type="chunk", chapter=str(chapter), role_ids=child["role_id"],
                            audio_path=child_rel, full_context_path=full_rel, source_text=child["source_text"],
                            expected_tts_text=child["tts_text"], scope_kind="repair_part", parent_chunk_id=cid)
                    sections.append(f"### {child_sid} · 修复子块（父块 {sid}）\n\n[试听]({child_rel})\n\n"
                                    f"原文：{child['source_text']}\n\n预期读法：{child['tts_text']}\n")
                boundary = internal["boundaries"][0]
                if (boundary["left_chunk_id"] != parts[0]["chunk"]["chunk_id"]
                        or boundary["right_chunk_id"] != parts[1]["chunk"]["chunk_id"]
                        or internal["spans"][0]["start_sample"] != 0
                        or internal["spans"][0]["end_sample"] != boundary["start_sample"]
                        or internal["spans"][1]["start_sample"] != boundary["end_sample"]
                        or internal["spans"][1]["end_sample"] != internal["total_samples"]):
                    raise ValueError("内部子块顺序或边界样本位置不一致")
                evidence = [r for r in composition.get("internal_reports", []) if r["scope_id"] == boundary["boundary_id"]]
                if len(evidence) != 1:
                    raise ValueError("内部接缝缺少唯一的质量证据，请先离线复评")
                feature_vector(evidence[0]["metrics"]["features"])
                offset = spans[cid]["start_sample"]
                positioned = {**boundary, "start_sample": offset + boundary["start_sample"],
                              "end_sample": offset + boundary["end_sample"]}
                internal_jobs.append((positioned, evidence[0], children, child_paths,
                                      f"I{chapter:06d}_{i:03d}_001", "internal_resegment", cid))
            if set(spans) != set(chunk_map) or len(report["boundaries"]) != len(assembly["boundaries"]):
                raise ValueError("报告的片段或边界数量不一致")
            with sf.SoundFile(full) as stream:
                rate = stream.samplerate
                jobs = [(boundary, evidence, chunk_map, exported, f"B{chapter:06d}_{i:03d}", "original_boundary", "")
                        for i, (boundary, evidence) in enumerate(zip(assembly["boundaries"], report["boundaries"]), 1)]
                for boundary, evidence, members, sources, sid, kind, parent_id in jobs + internal_jobs:
                    if boundary["boundary_id"] != evidence["scope_id"]:
                        raise ValueError("边界顺序或编号不一致")
                    start = max(0, boundary["start_sample"] - 2 * rate)
                    end = min(len(stream), boundary["end_sample"] + 2 * rate)
                    if not 0 <= start <= boundary["start_sample"] <= boundary["end_sample"] < end:
                        raise ValueError("边界样本位置越界")
                    stream.seek(start)
                    samples = stream.read(end - start, dtype="int16", always_2d=True)
                    path = stage / "audio" / (sid + ".wav")
                    sf.write(path, samples, rate, subtype="PCM_16")
                    record(path, original)
                    rel = str(path.relative_to(stage))
                    left, right = (members[boundary[key]] for key in ("left_chunk_id", "right_chunk_id"))
                    same = boundary["same_speaker"]
                    join = (boundary["start_sample"] - start) / rate
                    text = left["source_text"] + " ｜ " + right["source_text"]
                    spoken = left["tts_text"] + " ｜ " + right["tts_text"]
                    roles = left["role_id"] + " → " + right["role_id"]
                    add_row(sample_id=sid, sample_type="boundary", chapter=str(chapter), role_ids=roles,
                            same_speaker=str(same).lower(), audio_path=rel, full_context_path=full_rel,
                            boundary_at_seconds=str(join), source_text=text, expected_tts_text=spoken,
                            scope_kind=kind, parent_chunk_id=parent_id)
                    boundaries.append({"sample_id": sid, "group_id": group, "split": "unassigned", "labels": None,
                        "origin": "real_unlabelled", "reviewed_normal": False, "boundary_id": evidence["scope_id"],
                        "features": evidence["metrics"]["features"], "left_path": sources[left["chunk_id"]],
                        "right_path": sources[right["chunk_id"]], "preview_path": str(destination / rel),
                        "full_context_path": full_final, "source_text": text, "expected_tts_text": spoken,
                        "same_speaker": same, "boundary_at_preview_seconds": join,
                        "source_report_path": str(report_path), "review_status": "pending",
                        "scope_kind": kind, "parent_chunk_id": parent_id,
                        "boundary_at_chapter_sample": boundary["start_sample"]})
                    label = "同一角色" if same else "角色切换，正常换声音不算漂移"
                    if parent_id:
                        label += " · 修复新增内部接缝"
                    sections.append(f"### {sid} · {label}\n\n[接缝试听]({rel}) · [完整上下文]({full_rel})\n\n"
                                    f"接缝在试听文件第 {join:.2f} 秒；短窗口两端是人工裁切边缘，不作为缺陷。\n\n"
                                    f"原文：{text}\n\n预期读法：{spoken}\n")
        if not rows:
            raise ValueError("至少提供一份含音频的报告")
        with (stage / "annotation.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=REVIEW_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        data = stage / "pending_boundaries.jsonl"
        data.write_text("".join(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n" for row in boundaries), encoding="utf-8")
        manifest = {"schema": "audio-quality-human-review-v1", "provider": "mimo", "sample_count": len(rows),
                    "chunk_count": len(rows) - len(boundaries), "boundary_count": len(boundaries),
                    "human_reviewed_count": 0, "requests_sent": 0, "audio_files": files,
                    "boundary_data_sha256": _sha(data),
                    "review_records": [{k: v for k, v in row.items() if k not in MANUAL_FIELDS} for row in rows]}
        (stage / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        guide = ("# 待人工标注的 MiMo 样本\n\n"
                 "编辑 [annotation.csv](annotation.csv)，按拼接、一致性、内容完整性的顺序试听。所有判断初始为空；"
                 "填写 yes/no/uncertain/not_applicable，空白表示未检查。正常角色切换不算音色漂移；"
                 "缺少同角色参考时填 uncertain 或 not_applicable，不凭单段判断跨段一致性。\n\n"
                 "review_status 使用 pending/reviewed/needs_review。已完成需填写 reviewer 和含时区的 ISO reviewed_at，"
                 "例如 2026-10-16T12:00:00+08:00；notes 记录问题秒数和文字。\n\n"
                 "边界四列 click/cutoff/overlap/gap 全部明确判断后才能标 reviewed；"
                 "labels_json 用 JSON 数组，对应 boundary_click_suspected/cutoff_suspected/overlap/unexpected_gap。"
                 "只有四项都 no 才填 []。有疑点保持 needs_review，不把未知当正常。完整片段的 labels_json 留空。\n\n"
                 "人工结果用 import-review 导入，未标注记录不会进入训练；导出不自动划分 train/dev/test。"
                 "相同 group_id 的所有变体应保留在同一划分。本包只提供材料，不证明检测或修复效果；"
                 "章节、父块、修复子块、窗口音频相互重叠，不能按文件数统计独立样本。"
                 "scope_kind 与 parent_chunk_id 标明修复子块及新增内部接缝；这些受保护字段不要修改。\n\n")
        (stage / "README.md").write_text(guide + "\n".join(sections), encoding="utf-8")
        if destination.exists():
            raise ValueError("输出目录已出现，停止以免覆盖")
        stage.rename(destination)
    return {"output": str(destination), "sample_count": len(rows), "boundary_count": len(boundaries),
            "audio_files": len(files), "requests_sent": 0, "annotation_required": True}


def read_review_pack(pack, reviews, *, splits=None):
    """先校验整个包和表格，再返回可用标签；不写文件、不调用模型。"""
    root = Path(pack).resolve()
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != "audio-quality-human-review-v1":
        raise ValueError("不支持的人工标注包版本")
    records = manifest.get("review_records")
    if not isinstance(records, list) or not records:
        raise ValueError("标注包缺少原始记录快照，无法校验表格是否改错样本")
    original = {r["sample_id"]: r for r in records}
    if len(original) != len(records):
        raise ValueError("原始快照有重复样本编号")
    files = manifest.get("audio_files", [])
    if not files:
        raise ValueError("标注包缺少音频校验清单")
    audio_paths = set()
    for item in files:
        path = _inside(root, item["path"])
        if not path.is_file() or _sha(path) != item["sha256"]:
            raise ValueError(f"音频缺失或内容改变：{item['path']}")
        audio_paths.add(path)
    data_path = root / "pending_boundaries.jsonl"
    if _sha(data_path) != manifest.get("boundary_data_sha256"):
        raise ValueError("原始边界数据已改变，请重新核验来源")
    source_rows = [json.loads(line) for line in data_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    boundaries = {r["sample_id"]: r for r in source_rows}
    if len(boundaries) != len(source_rows) or set(boundaries) != {
            key for key, value in original.items() if value["sample_type"] == "boundary"}:
        raise ValueError("边界数据与原始样本清单不一致")
    for source in source_rows:
        feature_vector(source["features"])
        for name in ("left_path", "right_path", "preview_path", "full_context_path"):
            if _inside(root, source[name]) not in audio_paths:
                raise ValueError("边界引用的音频不在已核验清单中")
    with Path(reviews).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames or []
        if len(fields) != len(set(fields)) or not MANUAL_FIELDS.issubset(fields):
            raise ValueError("人工表格缺少必要列或包含重复列")
        human_rows = list(reader)
    seen, accepted, skipped = set(), [], []
    splits = {} if splits is None else splits
    groups = {row["group_id"] for row in source_rows}
    if (not isinstance(splits, dict) or set(splits) - groups
            or any(value not in {"train", "dev", "test"} for value in splits.values())):
        raise ValueError("划分文件必须是本包 group_id 到 train/dev/test 的映射")
    for row in human_rows:
        if any(not isinstance(key, str) or not isinstance(value, str) for key, value in row.items()):
            raise ValueError("人工表格行的列数不一致或包含空列名")
        sid = row.get("sample_id")
        if sid in seen or sid not in original:
            raise ValueError("表格存在重复或未知样本编号")
        seen.add(sid)
        if any(row.get(key) != value for key, value in original[sid].items()):
            raise ValueError(f"{sid} 的原文、角色或音频定位等受保护字段已改变")
        status = row["review_status"].strip()
        if status not in {"pending", "reviewed", "needs_review"}:
            raise ValueError(f"{sid} 的 review_status 无效")
        for aspect in ASPECTS:
            if row[aspect].strip() not in {"", "yes", "no", "uncertain", "not_applicable"}:
                raise ValueError(f"{sid} 的 {aspect} 必须使用约定的判断值")
        if status != "reviewed":
            skipped.append({"sample_id": sid, "reason": status})
            continue
        if not row["reviewer"].strip():
            raise ValueError(f"{sid} 缺少标注人")
        try:
            stamp = datetime.fromisoformat(row["reviewed_at"].strip().replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                raise ValueError("缺少时区")
        except ValueError as exc:
            raise ValueError(f"{sid} 需要包含时区的 ISO 标注时间") from exc
        if sid not in boundaries:
            if row["labels_json"].strip():
                raise ValueError("完整片段不使用边界四类标签")
            continue
        if any(row[key].strip() not in {"yes", "no"} for key in ASPECT_LABELS):
            raise ValueError(f"{sid} 四类边界检查未完成或仍不确定，请标为 needs_review")
        try:
            labels = json.loads(row["labels_json"])
        except (ValueError, TypeError) as exc:
            raise ValueError(f"{sid} 缺少有效的 labels_json 数组") from exc
        if (not isinstance(labels, list) or any(not isinstance(label, str) for label in labels)
                or len(labels) != len(set(labels)) or set(labels) - set(LABELS)):
            raise ValueError(f"{sid} 边界标签无效或重复")
        expected = {label for aspect, label in ASPECT_LABELS.items() if row[aspect].strip() == "yes"}
        if set(labels) != expected:
            raise ValueError(f"{sid} 的边界标签与逐项人工判断矛盾")
        source = boundaries[sid]
        accepted.append({**source, "labels": labels, "origin": "real_reviewed",
                         "reviewed_normal": not labels, "review_status": "reviewed",
                         "split": splits.get(source["group_id"], "unassigned"),
                         "reviewer": row["reviewer"].strip(), "reviewed_at": stamp.isoformat(),
                         "notes": row["notes"],
                         "human_checks": {key: row[key].strip() for key in sorted(ASPECTS)}})
    if seen != set(original):
        raise ValueError("人工表格缺少样本行；未标注样本应保留 pending")
    return {"boundaries": accepted, "human_records": human_rows, "skipped": skipped,
            "reviewed_boundaries": len(accepted), "total_samples": len(human_rows),
            "split_required": any(r["split"] == "unassigned" for r in accepted),
            "all_accepted_splits_assigned": bool(accepted) and all(r["split"] != "unassigned" for r in accepted),
            "training_sufficiency": "not_assessed", "requests_sent": 0}
