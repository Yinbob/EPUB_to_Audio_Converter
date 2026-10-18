"""选角先导的统一恒定增益副本；保留时间表，必须另行复评和试听。"""
from __future__ import annotations

import copy
import json
import math
import shutil
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from .annotations import _verify_pcm_layout
from .repair_review import _read_report, _sha
from .store import fingerprint


def prepare_casting_gain(conditions, gains_db, output_dir):
    """所有条件共用显式声音增益表；仅支持 PCM16 和不放大的固定增益。"""
    destination = Path(output_dir).resolve()
    if destination.exists():
        raise ValueError("统一增益目录已存在，拒绝覆盖")
    if (not isinstance(conditions, list) or len(conditions) < 2
            or any(not isinstance(c.get("condition"), str) or not c["condition"].strip() for c in conditions)
            or len({c["condition"] for c in conditions}) != len(conditions)):
        raise ValueError("至少需要两个不重名的选角条件")
    if (not isinstance(gains_db, dict) or not gains_db
            or any(not isinstance(k, str) or not k for k in gains_db)
            or any(isinstance(v, bool) or not isinstance(v, (int, float))
                   or not math.isfinite(v) or not -12 <= v <= 0 for v in gains_db.values())):
        raise ValueError("声音增益必须为 -12～0 dB 的完整有限数值表")
    protocol = {"version": "casting-fixed-voice-gain-v1", "gains_db": dict(gains_db),
                "scope": "pilot_development_not_global_default", "sample_positions_preserved": True,
                "content_speed_pitch_unchanged_by_design": True, "human_verified": False}
    protocol_sha = fingerprint(protocol)
    sources, voices, seen = [], set(), set()
    reference_scenes = None
    for condition in conditions:
        paths = condition.get("report_paths")
        if not isinstance(paths, list) or not paths:
            raise ValueError("每个条件需有序非空 report_paths")
        group, scenes, role_voices = [], [], {}
        for path in paths:
            source = _read_report(path)
            if source["path"] in seen:
                raise ValueError("选角报告不能重复使用")
            seen.add(source["path"])
            report = source["report"]
            if report.get("experiment_conditioning") or report.get("human_adjudication"):
                raise ValueError("须从原报告制作增益副本，不能叠加或迁移人工裁决")
            info = sf.info(source["audio"])
            if info.format != "WAV" or info.subtype != "PCM_16":
                raise ValueError("统一增益仅支持原生 PCM16 WAV")
            _verify_pcm_layout(source["audio"], report["assembly"], report["chunks"])
            scenes.append((report["source_group_id"], [(i["chunk"]["role_id"], i["chunk"]["source_text"],
                           i["chunk"]["tts_text"]) for i in report["chunks"]]))
            for item in report["chunks"]:
                if item.get("composition"):
                    raise ValueError("本先导增益入口暂不支持复合分块")
                role, voice = item["chunk"]["role_id"], item["chunk"]["profile"]["voice"]
                if role in role_voices and role_voices[role] != voice:
                    raise ValueError("同一条件中的角色声音不一致")
                role_voices[role] = voice
                voices.add(voice)
            group.append(source)
        if reference_scenes is not None and scenes != reference_scenes:
            raise ValueError("各条件的正文、角色及场景顺序必须相同")
        reference_scenes = scenes
        sources.append(group)
    if voices != set(gains_db):
        raise ValueError("增益表必须精确覆盖全部候选声音，不允许隐式默认")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".casting-gain-", dir=destination.parent) as folder:
        root = Path(folder)/"pack"
        root.mkdir()
        derived_conditions, lineage, files = [], [], []
        for ci, (condition, group) in enumerate(zip(conditions, sources), 1):
            paths = []
            for si, source in enumerate(group, 1):
                report = copy.deepcopy(source["report"])
                relative = Path(f"condition_{ci:02d}/scene_{si:02d}")
                chapter = root/relative
                chapter.mkdir(parents=True)
                samples, rate = sf.read(source["audio"], dtype="int16", always_2d=True)
                modified = samples.copy()
                staging_items = copy.deepcopy(report["chunks"])
                operations = []
                for index, (item, staging, span) in enumerate(zip(report["chunks"], staging_items,
                                                               report["assembly"]["spans"]), 1):
                    original_path = item["rendered_path"]
                    voice = item["chunk"]["profile"]["voice"]
                    gain_db = float(gains_db[voice])
                    gain = 10 ** (gain_db/20)
                    start, end = span["start_sample"], span["end_sample"]
                    modified[start:end] = np.rint(samples[start:end].astype(np.float64)*gain).astype(np.int16)
                    chunk_rel = relative/f"chunk_{index:02d}.wav"
                    sf.write(root/chunk_rel, modified[start:end], rate, subtype="PCM_16")
                    span["render_sha256"] = _sha(root/chunk_rel)
                    item["rendered_path"] = item["selected_rendered_path"] = str(destination/chunk_rel)
                    staging["rendered_path"] = str(root/chunk_rel)
                    operation = {"kind": "experiment_constant_voice_gain", "voice": voice,
                                 "gain_db": gain_db, "gain": gain, "start_sample": start,
                                 "end_sample": end, "input_path": original_path,
                                 "input_sha256": source["report"]["assembly"]["spans"][index-1]["render_sha256"],
                                 "output_sha256": span["render_sha256"], "protocol_sha256": protocol_sha}
                    item["render_operations"] = item.get("render_operations", [])+[operation]
                    item["report"] = {"scope_id": item["chunk"]["chunk_id"], "status": "incomplete",
                        "dimensions": {k: "incomplete" for k in ("signal", "content", "consistency")},
                        "issues": [], "metrics": {"start_seconds": start/rate, "end_seconds": end/rate}}
                    operations.append(operation)
                full_rel = relative/"chapter.wav"
                sf.write(root/full_rel, modified, rate, subtype="PCM_16")
                _verify_pcm_layout(root/full_rel, report["assembly"], staging_items)
                report["output_file"] = str(destination/full_rel)
                report["quality_status"] = "incomplete"
                report["boundaries"] = [{"scope_id": b["boundary_id"], "status": "incomplete",
                    "dimensions": {"content": "incomplete", "stitching": "incomplete"}, "issues": [],
                    "metrics": {"start_seconds": b["start_sample"]/rate, "end_seconds": b["end_sample"]/rate}}
                    for b in report["assembly"]["boundaries"]]
                # 此处只声明新 PCM 的身份；编码、内容等结论必须由 evaluate 重建。
                report["final_verification"] = {"scope_id": "final_encoding", "status": "incomplete",
                    "dimensions": {"encoding": "incomplete", "content": "incomplete"}, "issues": [],
                    "metrics": {"reference_pcm_path": str(destination/full_rel),
                                "reference_pcm_sha256": _sha(root/full_rel)}}
                report["experiment_conditioning"] = {**protocol, "protocol_sha256": protocol_sha,
                    "source_report": source["path"], "source_report_sha256": source["report_sha256"],
                    "source_audio_sha256": source["encoded_sha256"], "operations": operations,
                    "requests_sent": 0, "quality_pending_reevaluation": True}
                descriptor_rel = relative/"descriptor.json"
                (root/descriptor_rel).write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
                paths.append(str(destination/descriptor_rel))
                lineage.append({"condition": condition["condition"], "scene": si,
                    "source_report": source["path"], "source_sha256": source["report_sha256"],
                    "source_audio": str(source["audio"]), "source_audio_sha256": source["encoded_sha256"],
                    "descriptor": str(destination/descriptor_rel)})
            derived_conditions.append({"condition": condition["condition"], "report_paths": paths})
        for group in sources:
            for source in group:
                if (_sha(source["path"]) != source["report_sha256"]
                        or _sha(source["audio"]) != source["encoded_sha256"]):
                    raise ValueError("增益处理期间来源变化，拒绝发布")
                _verify_pcm_layout(source["audio"], source["report"]["assembly"], source["report"]["chunks"])
        (root/"conditions.json").write_text(json.dumps(derived_conditions, ensure_ascii=False, indent=2)+"\n")
        for path in sorted(root.rglob("*")):
            if path.is_file():
                files.append({"path": str(path.relative_to(root)), "sha256": _sha(path)})
        (root/"manifest.json").write_text(json.dumps({"protocol": protocol, "protocol_sha256": protocol_sha,
            "sources": lineage, "files": files, "requests_sent": 0,
            "human_verified": False, "ready_for_listeners": False}, ensure_ascii=False, indent=2)+"\n")
        root.rename(destination)
    return {"output": str(destination), "conditions": len(conditions), "chapters": len(lineage),
            "protocol_sha256": protocol_sha, "requests_sent": 0, "quality_pending_reevaluation": True}
