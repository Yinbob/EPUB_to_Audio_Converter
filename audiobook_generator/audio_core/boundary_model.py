"""无需深度学习运行时的边界多标签小模型，可用真实标注训练与验证。"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

FEATURES = ("sample_jump", "rms_jump_db", "spectral_distance", "left_speech_edge",
            "right_speech_edge", "left_tail_silence", "right_head_silence",
            "planned_pause_seconds", "same_speaker")
LABELS = ("boundary_click_suspected", "cutoff_suspected", "overlap", "unexpected_gap")


def feature_vector(features):
    values = np.asarray([float(features[name]) for name in FEATURES], dtype=float)
    if not np.all(np.isfinite(values)):
        raise ValueError("边界特征必须为有限数值")
    return values


def _sigmoid(x):
    return 1 / (1 + np.exp(-np.clip(x, -30, 30)))


def validate_rows(rows):
    groups = {}
    for row in rows:
        if not row.get("group_id") or row.get("split") not in {"train", "dev", "test"}:
            raise ValueError("每条标注必须包含原始音频 group_id 和 train/dev/test 划分")
        group, split = row["group_id"], row["split"]
        if group in groups and groups[group] != split:
            raise ValueError("同一原始音频及其变体不能跨数据划分")
        groups[group] = split
        feature_vector(row["features"])
        if not isinstance(row.get("labels"), list) or set(row["labels"]) - set(LABELS):
            raise ValueError("边界标签不在允许列表中")


def train_boundary(rows, *, steps=1000, learning_rate=.05, seed=42):
    """训练集拟合参数，开发集选阈值，测试集只报告固定模型效果。"""
    validate_rows(rows)
    if type(steps) is not int or steps <= 0 or not np.isfinite(learning_rate) or learning_rate <= 0:
        raise ValueError("训练步数和学习率必须为正")
    train = [r for r in rows if r["split"] == "train"]
    dev = [r for r in rows if r["split"] == "dev"]
    if len(train) < 4 or not dev:
        raise ValueError("至少需要四条训练标注及独立开发集；不足时继续使用规则")
    support = {split: {label: {
        "positive": sum(label in r["labels"] for r in rows if r["split"] == split),
        "negative": sum(label not in r["labels"] for r in rows if r["split"] == split),
    } for label in LABELS} for split in ("train", "dev", "test")}
    ready_labels = [all(support[split][label][kind] > 0
                        for split in ("train", "dev") for kind in ("positive", "negative"))
                    for label in LABELS]
    if not any(ready_labels):
        raise ValueError("没有可训练类别：至少一类需在训练集和独立开发集各有正常与异常标注；不足时继续使用规则")
    x = np.stack([feature_vector(r["features"]) for r in train])
    y = np.asarray([[label in r["labels"] for label in LABELS] for r in train], dtype=float)
    mean, scale = x.mean(0), x.std(0)
    scale = np.where(scale < 1e-6, 1, scale)
    x = np.c_[(x - mean) / scale, np.ones(len(x))]
    weights = np.random.default_rng(seed).normal(0, .01, (x.shape[1], len(LABELS)))
    for _ in range(steps):
        weights -= learning_rate * (x.T @ (_sigmoid(x @ weights) - y) / len(x) + .001 * weights)
    dev_x = np.stack([feature_vector(r["features"]) for r in dev])
    probabilities = _sigmoid(np.c_[(dev_x - mean) / scale, np.ones(len(dev_x))] @ weights)
    thresholds, available = [], []
    for column, label in enumerate(LABELS):
        truth = np.asarray([label in r["labels"] for r in dev])
        valid = ready_labels[column]
        available.append(valid)
        if not valid:
            thresholds.append(1.1)
            continue
        # 先满足开发集最多 5% 误报的候选，再最大化召回；这不是泛化保证。
        candidates = []
        for threshold in np.unique(np.r_[0, probabilities[:, column], 1.001]):
            pred = probabilities[:, column] >= threshold
            fp_rate = float(np.mean(pred[~truth]))
            recall = float(np.mean(pred[truth]))
            if fp_rate <= .05:
                candidates.append((recall, -fp_rate, float(threshold)))
        thresholds.append(max(candidates)[2])
    model = {"version": "boundary-logistic-v1", "features": list(FEATURES), "labels": list(LABELS),
             "mean": mean.tolist(), "scale": scale.tolist(), "weights": weights.tolist(),
             "thresholds": thresholds, "threshold_ready_labels": available, "seed": seed,
             "training_rows": len(train), "development_rows": len(dev),
             "label_support": support,
             "source_group_counts": {split: len({r["group_id"] for r in rows if r["split"] == split})
                                     for split in ("train", "dev", "test")},
             "confidence_kind": "uncalibrated_scores",
             "threshold_kind": "dev_selected" if all(available) else "partially_dev_selected",
             "thresholds_ready": all(available)}
    model["heldout_metrics"] = evaluate_model(model, [r for r in rows if r["split"] == "test"])
    real_test = [r for r in rows if r["split"] == "test" and r.get("origin") in {"real", "real_reviewed"}]
    model["real_heldout_metrics"] = evaluate_model(model, real_test)
    model["real_rule_baseline"] = evaluate_model(model, real_test, use_rules=True)
    model["data_origin_counts"] = {split: {
        origin: sum(r["split"] == split and r.get("origin", "unspecified") == origin for r in rows)
        for origin in sorted({r.get("origin", "unspecified") for r in rows})}
        for split in ("train", "dev", "test")}
    model["real_validation_status"] = "requires_human_review" if real_test else "no_real_test_data"
    return model


def predict_model(model, features):
    if (model.get("version") != "boundary-logistic-v1" or model.get("features") != list(FEATURES)
            or model.get("labels") != list(LABELS)):
        raise ValueError("边界模型版本或特征顺序不匹配")
    mean, scale, weights, thresholds = (np.asarray(model[k], dtype=float)
                                       for k in ("mean", "scale", "weights", "thresholds"))
    if (mean.shape != (len(FEATURES),) or scale.shape != mean.shape
            or weights.shape != (len(FEATURES) + 1, len(LABELS)) or thresholds.shape != (len(LABELS),)
            or any(not np.all(np.isfinite(value)) for value in (mean, scale, weights, thresholds))
            or np.any(scale <= 0) or np.any(thresholds < 0)):
        raise ValueError("边界模型参数尺寸或数值无效")
    vector = (feature_vector(features) - mean) / scale
    probabilities = _sigmoid(np.r_[vector, 1] @ weights)
    if probabilities.shape != (len(LABELS),) or not np.all(np.isfinite(probabilities)):
        raise ValueError("边界模型输出无效")
    return {"probabilities": dict(zip(LABELS, probabilities.tolist())),
            "labels": [label for label, p, t in zip(LABELS, probabilities, model["thresholds"]) if p >= t],
            "confidence_kind": model["confidence_kind"], "model_version": model["version"],
            "threshold_kind": model["threshold_kind"], "thresholds_ready": model["thresholds_ready"]}


def predict_boundary(path, features):
    return predict_model(json.loads(Path(path).read_text()), features)


def heuristic_labels(features):
    result = []
    if features["sample_jump"] > .15:
        result.append("boundary_click_suspected")
    if features["left_tail_silence"] + features["right_head_silence"] > max(1.5, features["planned_pause_seconds"] + .8):
        result.append("unexpected_gap")
    return result


def evaluate_model(model, rows, *, use_rules=False):
    results = {}
    for label in LABELS:
        tp = fp = fn = tn = 0
        for row in rows:
            truth = label in row["labels"]
            labels = heuristic_labels(row["features"]) if use_rules else predict_model(model, row["features"])["labels"]
            predicted = label in labels
            tp += int(truth and predicted)
            fp += int(not truth and predicted)
            fn += int(truth and not predicted)
            tn += int(not truth and not predicted)
        results[label] = {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
                          "precision": tp / (tp + fp) if tp + fp else None,
                          "recall": tp / (tp + fn) if tp + fn else None,
                          "false_positive_rate": fp / (fp + tn) if fp + tn else None}
    return {"rows": len(rows), "by_label": results}
