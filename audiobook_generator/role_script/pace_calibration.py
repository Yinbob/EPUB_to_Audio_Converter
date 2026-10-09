"""用同一段试听文本测量音色的基础语速，不改动正文或角色语气。"""
from __future__ import annotations

import math
from typing import Mapping


def calibrated_speeds(durations_ms: Mapping[str, int], baseline_role: str, baseline_speed: float):
    """使各音色的试听时长接近基准角色；返回倍率和超出支持范围的角色。"""
    if not math.isfinite(baseline_speed) or not 0.25 <= baseline_speed <= 4.0:
        raise ValueError("基准角色语速必须在 0.25～4.0 之间")
    if baseline_role not in durations_ms:
        raise ValueError("缺少基准角色的试听时长")
    if any(not math.isfinite(duration) or duration <= 0 for duration in durations_ms.values()):
        raise ValueError("试听音频为空或时长无效，请重试")
    target_duration = durations_ms[baseline_role] / baseline_speed
    result, limited = {}, []
    for role_id, duration in durations_ms.items():
        speed = duration / target_duration
        if not 0.25 <= speed <= 4.0:
            limited.append(role_id)
        result[role_id] = round(max(0.25, min(4.0, speed)), 3)
    return result, limited
