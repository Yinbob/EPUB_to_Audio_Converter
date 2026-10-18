"""从已核验正常的真实边界制作扰动，保留来源与原始划分。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import soundfile as sf

from .audio import boundary_features, load_audio
from .store import fingerprint


def augment_boundaries(rows, output_dir):
    destination = Path(output_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    result = []
    for row in rows:
        if (row.get("reviewed_normal") is not True or row.get("labels") != []
                or row.get("origin") not in {"real", "real_reviewed"}):
            raise ValueError("只允许从人工确认正常的真实边界生成扰动")
        if row.get("split") not in {"train", "dev"} or not row.get("group_id"):
            raise ValueError("先划分 train/dev；测试集保留真实样本，不自动加入扰动")
        left, rate = load_audio(row["left_path"])
        right, right_rate = load_audio(row["right_path"])
        if rate != right_rate or len(left) < rate // 2 or not len(right):
            raise ValueError("扰动需要同采样率且左侧至少半秒的非空音频")
        variants = {
            "cutoff": (left[:-max(1, round(.08 * rate))], "cutoff_suspected"),
            "gap": (np.concatenate([left, np.zeros((2 * rate, left.shape[1]), dtype=np.float32)]), "unexpected_gap"),
        }
        clicked = left.copy()
        clicked[-1] = .9
        variants["click"] = clicked, "boundary_click_suspected"
        for kind, (samples, label) in variants.items():
            key = fingerprint({"group": row["group_id"], "boundary": row["boundary_id"],
                               "left": hashlib.sha256(left.tobytes()).hexdigest(), "kind": kind, "version": 1})
            path = destination / f"{key}.wav"
            sf.write(path, samples, rate, subtype="PCM_16")
            features = boundary_features(path, row["right_path"],
                same_speaker=bool(row["features"]["same_speaker"]),
                planned_pause_ms=row["features"]["planned_pause_seconds"] * 1000)
            result.append({**row, "origin": "synthetic", "reviewed_normal": False,
                "labels": None, "suggested_labels": [label], "augmentation": kind,
                "parent_boundary_id": row["boundary_id"], "boundary_id": f'{row["boundary_id"]}:{kind}',
                "left_path": str(path), "features": features})
    return result


def write_jsonl(path, rows):
    from audiobook_generator.tts_providers.segment_synthesis import atomic_write_bytes
    atomic_write_bytes(str(path), ("\n".join(json.dumps(row, ensure_ascii=False, allow_nan=False)
                                          for row in rows) + "\n").encode())
