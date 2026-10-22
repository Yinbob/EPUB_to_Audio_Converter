"""基于角色互动图的确定性选角；锁定声音是硬约束。"""
from __future__ import annotations

import json
import math
import random
from itertools import product, permutations
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

import numpy as np

EXACT_SEARCH_LIMIT = 4096


def interaction_graph(chapters):
    edges = defaultdict(float)
    roles = set()
    for chapter in chapters:
        segments = getattr(chapter, "segments", getattr(chapter, "units", ()))
        previous = None
        for segment in segments:
            role = segment.role_id
            roles.add(role)
            if role == "narrator":
                previous = None
                continue
            if previous and previous != role:
                edges[tuple(sorted((previous, role)))] += 1
            previous = role
            if (segment.pause_after_ms or 0) >= 1500:
                previous = None
    return sorted(roles), dict(edges)


def voice_distance(a, b):
    common = sorted(set(a["embeddings"]) & set(b["embeddings"]))
    if len(common) < 2:
        raise ValueError("声音比较至少需要两条共同探针文本")
    distances = []
    for prompt in common:
        av, bv = np.asarray(a["embeddings"][prompt], dtype=float), np.asarray(b["embeddings"][prompt], dtype=float)
        if av.shape != bv.shape or av.ndim != 1 or not np.all(np.isfinite(av)) or not np.all(np.isfinite(bv)):
            raise ValueError("探针声纹维度不一致或数值无效")
        norm = np.linalg.norm(av) * np.linalg.norm(bv)
        if norm <= 0:
            raise ValueError("探针声纹不能为零向量")
        distances.append(1 - float(np.clip(np.dot(av, bv) / norm, -1, 1)))
    # 对跨文本不稳定声音保守处理；这只是混淆风险代理。
    return max(0., float(np.mean(distances) - .25 * np.std(distances)))


def optimize_casting(roles, edges, bank, *, locked=None, initial=None, fit_penalties=None,
                     strategy="interaction", seed=42, narrator_exclusive=False, language=None,
                     unique_voices=False, spread_tiebreak=False):
    if language is not None:
        from .language import normalize_language
        if normalize_language(language) not in bank.get("languages", []):
            raise ValueError("声音库尚未核验目标语言；请使用对应中／英文共同探针建库")
    voices = bank.get("voices", {})
    if bank.get("provider") != "openai" or not voices:
        raise ValueError("首轮选角需要非空 MiMo 声音探针库")
    if any(value.get("verified") is not True for value in voices.values()):
        raise ValueError("探针必须先核验并显式标记 verified，不能用失败音频代表声音")
    if type(narrator_exclusive) is not bool:
        raise ValueError("旁白独占选项必须是布尔值")
    if type(unique_voices) is not bool:
        raise ValueError('声音不复用选项必须是布尔值')
    locked, initial = locked or {}, initial or {}
    if strategy not in {"interaction", "global", "random", "fit"}:
        raise ValueError("未知选角策略")
    fit = {}
    if fit_penalties is None:
        if strategy == "fit":
            raise ValueError("属性适配基线需要人工审查的适配惩罚表")
    else:
        # 漏填不是零惩罚；必须覆盖候选全集，避免优先选择尚未评价的声音。
        if not isinstance(fit_penalties, dict) or set(fit_penalties) != set(roles):
            raise ValueError("适配惩罚表必须完整覆盖全部参与角色，不能缺项或包含未知角色")
        for role, penalties in fit_penalties.items():
            if not isinstance(penalties, dict) or set(penalties) != set(voices):
                raise ValueError(f"角色 {role} 的适配惩罚必须完整覆盖全部候选声音，不能缺项或包含未知声音")
            if any(isinstance(p, bool) or not isinstance(p, (int, float))
                   or not math.isfinite(p) or p < 0 for p in penalties.values()):
                raise ValueError(f"角色 {role} 的适配惩罚必须是有限非负数，空值不能视为适合")
            fit[role] = dict(penalties)
    if strategy == "fit":
        edges = {}
    if strategy == "global":
        edges = {(a, b): 1. for i, a in enumerate(sorted(roles)) for b in sorted(roles)[i + 1:]}
    if set(locked) - set(roles) or set(locked.values()) - set(voices):
        raise ValueError("锁定角色／声音不在候选集合内")
    if unique_voices and len(set(roles) - set(locked)) > len(set(voices) - set(locked.values())):
        raise ValueError("剩余声音不足以满足自动分配不复用约束")
    exclusive = narrator_exclusive and 'narrator' in roles
    narrator_choices = [None]
    if exclusive:
        other_locks = {role: voice for role, voice in locked.items() if role != 'narrator'}
        if 'narrator' in locked:
            conflicts = sorted(role for role, voice in other_locks.items() if voice == locked['narrator'])
            if conflicts:
                raise ValueError('旁白独占音色与已锁定角色冲突：' + '、'.join(conflicts))
            narrator_choices = [locked['narrator']]
        else:
            narrator_choices = sorted(set(voices) - set(other_locks.values()))
        if len(roles) > 1 and len(voices) < 2:
            raise ValueError('旁白独占且存在其他角色时至少需要两个候选音色')
        if not narrator_choices:
            raise ValueError('候选音色均被其他角色锁定，无法为旁白分配独占音色')
    costs = {(a, b): math.exp(-voice_distance(voices[a], voices[b]) / .25)
             for a in voices for b in voices}

    def objective(assignment):
        value = sum(weight * costs[assignment[a], assignment[b]]
                    for (a, b), weight in edges.items() if a in assignment and b in assignment)
        value += .1 * sum(float(fit.get(role, {}).get(voice, 0)) for role, voice in assignment.items())
        value += .05 * sum(role in initial and initial[role] != voice for role, voice in assignment.items())
        return value

    def order(assignment):
        chosen = sorted(set(assignment.values()))
        distances = [voice_distance(voices[a], voices[b]) for i, a in enumerate(chosen)
                     for b in chosen[i + 1:]] if spread_tiebreak else []
        return (objective(assignment), -min(distances, default=0), -sum(distances),
                tuple(sorted(assignment.items())))

    degree = {role: sum(w for edge, w in edges.items() if role in edge) for role in roles}
    # 计算硬约束后的规模，超限即停止计数，避免大整数和指数级枚举。
    movable_count = len(set(roles) - set(locked) - ({'narrator'} if exclusive else set()))
    candidate_count = len(voices) - (len(set(locked.values())) + int(exclusive and 'narrator' not in locked)
                                     if unique_voices else int(bool(exclusive)))
    search_space = len(narrator_choices)
    for position in range(movable_count):
        search_space *= max(0, candidate_count - position) if unique_voices else candidate_count
        if search_space > EXACT_SEARCH_LIMIT:
            break
    exact = strategy != 'random' and search_space <= EXACT_SEARCH_LIMIT
    rng = random.Random(seed)
    if exclusive and strategy == 'random':
        narrator_choices = [rng.choice(narrator_choices)]

    def search(narrator_voice):
        fixed = {**locked, **({'narrator': narrator_voice} if exclusive else {})}
        assignment = dict(fixed)
        movable = set(roles) - set(fixed)
        candidates = sorted(set(voices) - ({narrator_voice} if exclusive else set()))
        if unique_voices:
            candidates = sorted(set(candidates) - set(fixed.values()))
        if exact:
            ordered = sorted(movable)
            choices = permutations(candidates, len(ordered)) if unique_voices else product(candidates, repeat=len(ordered))
            assignments = ({**fixed, **dict(zip(ordered, values))} for values in choices)
            return min(assignments, key=order)
        for role in sorted(movable, key=lambda r: (-degree[r], r)):
            # 角色声音不足时可以复用，但不能占用已保留的旁白音色。
            available = sorted(set(candidates) - set(assignment.values())) or candidates
            assignment[role] = rng.choice(available) if strategy == 'random' else min(
                available, key=lambda voice: order({**assignment, role: voice}))
        for _ in range(0 if strategy == 'random' else 20):
            best, best_score = assignment, objective(assignment)
            for role in sorted(movable):
                for voice in candidates:
                    if unique_voices and any(v == voice for r, v in assignment.items() if r != role):
                        continue
                    candidate = {**assignment, role: voice}
                    score = objective(candidate)
                    if order(candidate) < order(best):
                        best, best_score = candidate, score
                for other in sorted(movable - {role}):
                    candidate = {**assignment, role: assignment[other], other: assignment[role]}
                    score = objective(candidate)
                    if order(candidate) < order(best):
                        best, best_score = candidate, score
            if best == assignment:
                break
            assignment = best
        return assignment

    assignments = [search(voice) for voice in narrator_choices]
    assignment = min(assignments, key=order)
    shared = {voice: [r for r in roles if assignment[r] == voice] for voice in sorted(set(assignment.values()))}
    return {"schema_version": "mimo-casting-v1", "provider": "openai", "roles": assignment,
            "locked_voices": locked, "objective": objective(assignment),
            "shared_voices": {v: rs for v, rs in shared.items() if len(rs) > 1},
            "edges": [{"left": a, "right": b, "weight": w} for (a, b), w in sorted(edges.items())],
            "metric_kind": "embedding_proxy_not_listener_probability", "strategy": strategy,
            "fit_penalty_policy": "complete-matrix-v1",
            "fit_penalty_status": "complete" if fit_penalties is not None else "disabled",
            "fit_penalties": fit,
            "search": {"method": 'random' if strategy == 'random' else
                       'exact_enumeration' if exact else 'greedy_local_search',
                       "exact_search_limit": EXACT_SEARCH_LIMIT, "automatic_voices_unique": unique_voices,
                       "candidate_assignments": search_space if search_space <= EXACT_SEARCH_LIMIT else None,
                       "exceeds_exact_limit": search_space > EXACT_SEARCH_LIMIT,
                       "optimality": 'global_for_current_proxy_objective' if exact else
                       'not_optimized' if strategy == 'random' else 'not_proven'},
            "seed": seed, "voice_bank_model": bank.get("model"),
            "verified_languages": bank.get("languages", []), "target_language": language,
            'voice_bank_speaker_fingerprint': bank.get('speaker_model_identity', {}).get('fingerprint'),
            'constraints': {'narrator_exclusive': narrator_exclusive},
            'constraint_status': {'narrator_exclusive': 'satisfied' if exclusive else
                                  'not_applicable' if narrator_exclusive else 'disabled'}}


def validate_casting_file(path):
    value = json.loads(Path(path).read_text())
    if value.get("schema_version") != "mimo-casting-v1" or value.get("provider") != "openai":
        raise ValueError("选角文件必须为 MiMo casting v1")
    roles = value.get("roles")
    if not isinstance(roles, dict) or not roles or any(not isinstance(k, str) or not isinstance(v, str) or not v for k, v in roles.items()):
        raise ValueError("选角文件缺少有效角色声音分配")
    if any(roles.get(role) != voice for role, voice in value.get("locked_voices", {}).items()):
        raise ValueError("选角文件违反声音锁定约束")
    constraints = value.get('constraints', {})
    if (not isinstance(constraints, dict) or set(constraints) - {'narrator_exclusive'}
            or type(constraints.get('narrator_exclusive', False)) is not bool):
        raise ValueError('选角约束无效，旁白独占选项必须是布尔值')
    if constraints.get('narrator_exclusive') and 'narrator' in roles:
        conflicts = sorted(role for role, voice in roles.items() if role != 'narrator' and voice == roles['narrator'])
        if conflicts:
            raise ValueError('选角文件违反旁白独占约束：' + '、'.join(conflicts))
    from audiobook_generator.tts_providers.openai_tts_provider import get_openai_supported_voices
    if set(roles.values()) - set(get_openai_supported_voices()):
        raise ValueError("选角包含当前 MiMo 目录不支持的声音")
    return value


def apply_casting(plan, path, *, locked=None, language=None):
    value = validate_casting_file(path)
    if language is not None or value.get("verified_languages"):
        from .language import resolve_language
        required = {resolve_language(unit.text, language or "auto") for unit in plan.units}
        if not required <= set(value.get("verified_languages", [])):
            raise ValueError("选角探针尚未核验正文语言；中文核验不能代替英语核验")
    for role, voice in (locked or {}).items():
        if role in value["roles"] and value["roles"][role] != voice:
            raise ValueError(f"选角不能修改用户锁定声音：{role}")
    units = []
    for unit in plan.units:
        voice = value["roles"].get(unit.role_id)
        if voice:
            profile = replace(unit.profile, provider_params={**unit.profile.provider_params, "voice": voice})
            unit = replace(unit, profile=profile)
        units.append(unit)
    if value.get('constraints', {}).get('narrator_exclusive'):
        narrator_voice = value['roles'].get('narrator')
        if narrator_voice is None and any(unit.role_id == 'narrator' for unit in units):
            raise ValueError('独占旁白的选角文件必须包含旁白音色分配')
        if narrator_voice:
            for unit in units:
                voice = unit.profile.provider_params.get('voice')
                if not voice or (unit.role_id != 'narrator' and voice == narrator_voice):
                    raise ValueError(f'应用选角后无法满足旁白独占约束：{unit.role_id}')
    return replace(plan, units=tuple(units))


def locked_voices_from_script(script):
    result = {}
    for entity_id, entity in getattr(script, "entities", {}).items():
        if not entity.voice_locked:
            continue
        # 当前 RoleScript 以实体 ID 关联角色；voice_profile_id 是独立的档案标识。
        role_id = entity_id if entity_id in script.roles else entity.voice_profile_id
        role = script.roles.get(role_id)
        if role and role.provider_params.get("voice"):
            result[role_id] = role.provider_params["voice"]
    return result
