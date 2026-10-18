"""首轮 MiMo 可观测执行链；未来本地引擎实现同样的块级适配接口即可接入。"""
from __future__ import annotations

import hashlib
import logging
import os
import json
import time
from dataclasses import asdict
from pathlib import Path

from audiobook_generator.role_script.models import VoiceProfile
from .audio import assemble_pcm, load_audio, render_pcm, render_safe_boundary
from .models import CoreOptions, ReadingChunk, QualityIssue
from .model_identity import local_model_identity, runtime_version
from .quality import RATE_POLICY_VERSION, QualityEvaluator, attach_composition_report, inspect_composition, report_rank
from .reading import VERSION, PLAN_VERSION, build_reading_plan, nonspoken_source_units, pronunciation_review
from .repair import CONTENT_PROMPT_VERSION, content_repair_profile, propose_actions, split_repair_chunk
from .store import ArtifactStore, ResourceExhausted, fingerprint
from .tail_repeat import VERSION as TAIL_REPEAT_VERSION, inspect_tail_repeat, render_checked_prefix

logger = logging.getLogger(__name__)


def _profile(chunk):
    return VoiceProfile(chunk.role_id, chunk.role_id, dict(chunk.profile), tone=chunk.tone)


def run_chapter(plan, provider, output_file, tags, project_root, *, options=None,
                run_id=None, evaluator=None, progress=None):
    options = options or CoreOptions()
    store = ArtifactStore(project_root)
    run_id = run_id or store.start_run(options.limits)
    try:
        return _run_chapter(plan, provider, output_file, tags, project_root, options=options,
                            run_id=run_id, evaluator=evaluator, progress=progress)
    except Exception as exc:
        prefix = f"reports/{run_id}/chapter_{plan.chapter_index:06d}"
        result = {"schema_version": "audio-core-v1", "provider": plan.provider, "run_id": run_id,
                  "chapter_index": plan.chapter_index, "output_file": str(Path(output_file).resolve()),
                  "generation_status": "failed", "quality_status": "incomplete",
                  "reading_configuration": {"normalization_version": VERSION, "language": options.language,
                                            "max_english_wpm": options.max_english_wpm,
                                            "reading_dictionary": options.reading_dictionary},
                  "reading_plan_version": PLAN_VERSION,
                  "nonspoken_source_units": nonspoken_source_units(plan.units),
                  "error_type": type(exc).__name__, "chunks": [], "boundaries": [],
                  "assembly": {"spans": [], "boundaries": []}, "repair_attempts": [],
                  "resource_summary": store.summary(run_id),
                  "resource_limits": asdict(store.run_limits(run_id)),
                  "resource_provenance": store.resource_provenance(run_id, []),
                  "limits_reached": [str(exc)] if isinstance(exc, ResourceExhausted) else [],
                  "recovery_note": "原始样本与朗读计划保留在项目目录，可修正配置后复用缓存重跑。",
                  "source_group_id": fingerprint("".join(unit.text for unit in plan.units))}
        report_path = store.write_json(prefix + "/quality.json", result)
        store.write_json(f"latest/chapter_{plan.chapter_index:06d}.json", {"report_path": report_path})
        raise


def _run_chapter(plan, provider, output_file, tags, project_root, *, options=None,
                run_id=None, evaluator=None, progress=None):
    started = time.perf_counter()
    if plan.provider != "openai" or getattr(provider, "provider_id", None) != "openai":
        raise ValueError("统一质量核心首轮仅支持 MiMo（openai），尚未适配其他引擎")
    if not callable(getattr(provider, "synthesize_observed_chunk", None)):
        raise TypeError("Provider 未实现可观测块级合成接口")
    options = options or CoreOptions()
    store = ArtifactStore(project_root)
    run_id = run_id or store.start_run(options.limits)
    evaluator = evaluator or QualityEvaluator(options, store=store)
    chunks = build_reading_plan(plan.units, chunk_chars=options.chunk_chars, dictionary=options.reading_dictionary, language=options.language)
    if not chunks:
        raise ValueError("朗读计划为空")
    source_group_id = fingerprint("".join(unit.text for unit in plan.units))
    configured_joins = set(options.transition_boundaries)
    matching_joins = [f"{left.chunk_id}|{right.chunk_id}" for left, right in zip(chunks, chunks[1:])
                      if f"{left.chunk_id}|{right.chunk_id}" in configured_joins]
    if matching_joins and options.transition_source_group != source_group_id:
        raise ValueError("起读处理接缝编号匹配，但章节原文指纹不符；请核对来源报告，尚未发起合成")
    prefix = f"reports/{run_id}/chapter_{plan.chapter_index:06d}"
    store.write_json(prefix + "/reading_plan.json", {"normalization_version": VERSION, "language": options.language,
                                                    "reading_plan_version": PLAN_VERSION,
                                                    "nonspoken_source_units": nonspoken_source_units(plan.units),
                                                    "reading_dictionary": options.reading_dictionary,
                                                    "pronunciation_review": pronunciation_review(chunks),
                                                    "chunks": [asdict(c) for c in chunks]})
    paths, raw_paths, reports, attempts, limits_hit = [], [], [], [], []
    artifact_hashes = {}
    repair_counts = dict.fromkeys((c.chunk_id for c in chunks), 0)
    local_counts = dict.fromkeys(repair_counts, 0)
    render_operations = [[] for _ in chunks]
    source_parts = [[] for _ in chunks]
    request_histories = [set() for _ in chunks]
    history_incomplete = [False for _ in chunks]
    compositions = [None for _ in chunks]
    anchors, anchor_indices = {}, {}
    anchor_keys = {}
    reference_requests = {}
    conditioning_references = {}
    selection_keys = {}
    provider_config = getattr(provider, "config", None)
    evaluation_models = {kind: local_model_identity(kind, path) for kind, path, enabled in
        (('asr', options.asr_model_dir, options.enable_asr),
         ('speaker', options.speaker_model_dir, options.enable_speaker)) if enabled}
    for chunk in chunks:
        effective_route = provider.resolve_voice(chunk.profile) if callable(getattr(provider, 'resolve_voice', None)) else None
        reference_requests[chunk.chunk_id] = effective_route
        key = fingerprint({"role": chunk.role_id, "profile": chunk.profile,
            "model": effective_route or getattr(provider_config, "model_name", None),
            "global_instructions": getattr(provider_config, "instructions", None),
            "endpoint": str(getattr(getattr(provider, "client", None), "base_url", "")),
            "asr": options.asr_model_dir, "speaker": options.speaker_model_dir,
            "enable_asr": options.enable_asr, "max_rate": options.max_rate,
            "rate_policy": RATE_POLICY_VERSION,
            "language": chunk.language, "max_english_wpm": options.max_english_wpm,
            "evaluation_models": evaluation_models, 'enable_vad': options.enable_vad,
            'vad_runtime': runtime_version('silero-vad') if options.enable_vad else None,
            "normalization": VERSION, "reading_dictionary": options.reading_dictionary,
            "version": "bootstrap-anchor-v1"})
        anchor_keys[chunk.chunk_id] = key
        selection_keys[chunk.chunk_id] = fingerprint({"chunk": asdict(chunk), "context": key,
            "language": getattr(provider_config, "language", None), "stream": getattr(provider_config, "stream", None),
            "format": getattr(provider_config, "output_format", None), "prompt_version": CONTENT_PROMPT_VERSION,
            "tail_repeat_mode": options.tail_repeat_mode, 'tail_repeat_policy': TAIL_REPEAT_VERSION,
            "version": "render-selection-v1"})
        saved = None
        if options.role_references and chunk.profile.get('voice_profile_id'):
            from .role_references import load_reference
            saved = load_reference(options.role_references, chunk.role_id, chunk.profile, chunk.language, effective_route)
        if saved is None and chunk.profile.get('voice_mode') == 'clone':
            from .role_references import clone_conditioning_reference
            reference_identity = (chunk.profile.get('reference_audio_path'),
                                  chunk.profile.get('reference_audio_sha256'))
            if reference_identity not in conditioning_references:
                conditioning_references[reference_identity] = clone_conditioning_reference(chunk.profile)
            saved = conditioning_references[reference_identity]
        if saved is None and chunk.profile.get('voice_mode') not in {'design', 'clone'}:
            saved = store.load_anchor(key)
        if saved:
            anchors.setdefault(chunk.role_id, saved)
    sample_rate, channels = None, None

    def rendered(raw, speed):
        key = fingerprint({"raw": hashlib.sha256(Path(raw).read_bytes()).hexdigest(), "speed": speed,
                           "sample_rate": sample_rate, "channels": channels, "renderer": "pcm-v1"})
        destination = store.root / "rendered" / f"{key}.wav"
        checksum = destination.with_suffix(".json")
        valid = False
        if destination.is_file() and checksum.is_file():
            try:
                valid = hashlib.sha256(destination.read_bytes()).hexdigest() == json.loads(checksum.read_text())["sha256"]
            except (ValueError, KeyError):
                pass
        if not valid:
            render_pcm(raw, destination, speed=speed, sample_rate=sample_rate, channels=channels)
            store.write_json(str(checksum.relative_to(store.root)),
                             {"sha256": hashlib.sha256(destination.read_bytes()).hexdigest()})
        return str(destination)

    def observed_synthesis(index, text, profile, **kwargs):
        before = {event["id"] for event in store.request_events(run_id=run_id)}
        try:
            raw = provider.synthesize_observed_chunk(text, profile, store, run_id, **kwargs)
            origin = store.sample_provenance(raw)
            request_histories[index].update(origin["origin_request_ids"])
            if origin["origin_status"] == "unknown":
                history_incomplete[index] = True
            return raw
        finally:
            observed = {event["id"] for event in store.request_events(run_id=run_id)} - before
            request_histories[index].update(observed)
            # 旧缓存可能是历史策略选出的结果；只有原始生成事件不能证明全部历史尝试。
            if not kwargs.get("repair") and not observed:
                history_incomplete[index] = True

    def compose_parts(parts):
        part_chunks, part_paths = [], []
        for part in parts:
            part_chunk = ReadingChunk(**part["chunk"])
            path = rendered(part["raw_path"], part["base_speed"])
            part["rendered_path"] = path
            part_chunks.append(part_chunk)
            part_paths.append(path)
        if len(parts) == 1:
            return part_paths[0], None
        key = fingerprint({"parts": [{"chunk": asdict(c), "sha256": hashlib.sha256(Path(p).read_bytes()).hexdigest()}
                                     for c, p in zip(part_chunks, part_paths)], "version": "repair-compose-v1"})
        target = store.root / "rendered" / f"composition-{key}.wav"
        mapping = assemble_pcm(part_chunks, part_paths, target)
        anchor = anchors.get(part_chunks[0].role_id)
        if anchor and anchor[0] == str(target):
            anchor = None
        return str(target), inspect_composition(parts, target, mapping, evaluator,
                                                anchor=anchor)

    def rebuild_selection(value):
        path, composition = compose_parts(value["parts"])
        for op in value["render_operations"]:
            if op["kind"] == "local_speed":
                path = rendered(path, op["speed_factor"])
            elif op["kind"] in {"local_trim_silence", "local_edge_fade"}:
                key = fingerprint({"input": hashlib.sha256(Path(path).read_bytes()).hexdigest(), "operation": op,
                                   "version": "restored-local-v1"})
                target = str(store.root / "rendered" / f"{key}.wav")
                render_safe_boundary(path, target, kind=op["kind"], edge=op["edge"],
                                     keep_silence_ms=op.get("retained_silence_samples", 0) / sample_rate * 1000)
                path = target
            elif op['kind'] == 'local_tail_repeat':
                key = fingerprint({'operation':op,'version':TAIL_REPEAT_VERSION})
                target = store.root / 'rendered' / f'tail-repeat-restored-{key}.wav'
                render_checked_prefix(path,target,end_sample=op['end_sample'],expected_sha256=op['input_sha256'])
                if hashlib.sha256(target.read_bytes()).hexdigest() != op['output_sha256']:
                    raise ValueError('恢复的尾部裁切与选中候选不符')
                path = str(target)
            else:
                raise ValueError("无法恢复未知的本地操作")
        return path, composition

    def evaluate(index, path, composition):
        chunk = chunks[index]
        anchor = anchors.get(chunk.role_id)
        # 不拿自身作唯一参考来证明声音一致。
        if anchor and (anchor[0] == path or anchor_indices.get(chunk.role_id) == index):
            anchor = None
        report = evaluator.evaluate_chunk(chunk, path, anchor=anchor)
        return attach_composition_report(report, composition)

    speeds = []
    for index, chunk in enumerate(chunks):
        if store.remaining_seconds(run_id) <= 0:
            raise ResourceExhausted("合成前已达到运行时限")
        if progress:
            progress(f"chapter-{plan.chapter_index}_{plan.title}_chunk_{index + 1}_of_{len(chunks)}")
        saved = store.load_render_selection(selection_keys[chunk.chunk_id])
        if saved:
            request_histories[index].update(saved.get("generation_request_ids", []))
            history_incomplete[index] = saved.get("generation_history_incomplete", True)
            raw = saved["parts"][0]["raw_path"]
        else:
            raw = observed_synthesis(index, chunk.tts_text, _profile(chunk))
        if sample_rate is None:
            samples, sample_rate = load_audio(raw)
            channels = samples.shape[1]
            if saved:
                sample_rate, channels = saved["sample_rate"], saved["channels"]
            if channels not in (1, 2):
                raise ValueError("统一核心支持单声道／双声道音频")
        speed = saved["speed"] if saved else float(chunk.profile.get("speed") or 1.0)
        if saved:
            source_parts[index] = saved["parts"]
            render_operations[index] = saved["render_operations"]
            # 重算内部接缝证据，不能把旧质量结果当作新模型的验收。
            if len(saved["parts"]) > 1 or not saved["render_valid"]:
                path, compositions[index] = rebuild_selection(saved)
            else:
                path = saved["rendered_path"]
        else:
            path = rendered(raw, speed)
            source_parts[index] = [{"chunk": asdict(chunk), "raw_path": raw, "base_speed": speed,
                                    "rendered_path": path, "strategy": "initial"}]
        report = evaluate(index, path, compositions[index])
        paths.append(path)
        artifact_hashes[chunk.chunk_id] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        raw_paths.append(raw)
        reports.append(report)
        speeds.append(speed)
        if (chunk.profile.get("voice_mode") not in {"design", "clone"} and not report.issues
                and report.dimensions.get("content") == "passed" and chunk.role_id not in anchors):
            anchors[chunk.role_id] = (path, report.metrics)
            anchor_indices[chunk.role_id] = index

    tail_repeat_checks, tail_candidates, deferred_tail = [], {}, set()
    if options.enable_asr and options.tail_repeat_mode != 'off':
        for index,chunk in enumerate(chunks):
            if compositions[index] or not any(i.code == 'asr_mismatch' for i in reports[index].issues):
                continue
            if store.remaining_seconds(run_id) <= 0:
                limits_hit.append('尾部重复检查达到运行时限'); break
            try:
                check = inspect_tail_repeat(chunk,paths[index],reports[index],evaluator,
                    store.root / prefix / 'tail_repeat' / f'chunk_{index+1:06d}',
                    deadline=time.perf_counter()+store.remaining_seconds(run_id))
                tail_repeat_checks.append(check)
                if check['status'] == 'candidate_pending_review':
                    tail_candidates[index] = check
                    deferred_tail.add(index)
                    reports[index].metrics['tail_repeat'] = check
                    reports[index].issues.append(QualityIssue('tail_repeat_suspected','content',chunk.chunk_id,
                        evidence={'candidate_path':check['candidate_path'],
                                  'auto_eligible':check['auto_eligible'],'policy':TAIL_REPEAT_VERSION}))
            except Exception as exc:
                tail_repeat_checks.append({'chunk_id':chunk.chunk_id,'status':'evaluation_unavailable',
                    'error_type':type(exc).__name__,'original_kept':True})

    def refresh_anchor(index):
        """参考块改变后重算同角色依赖，避免继续引用被淘汰音频。"""
        role = chunks[index].role_id
        if chunks[index].profile.get('voice_mode') in {'design', 'clone'}:
            return
        if role in anchors and anchor_indices.get(role) != index:
            return
        anchors.pop(role, None)
        anchor_indices.pop(role, None)
        for i, chunk in enumerate(chunks):
            if chunk.role_id != role:
                continue
            standalone = attach_composition_report(evaluator.evaluate_chunk(chunk, paths[i]), compositions[i])
            if not standalone.issues and standalone.dimensions.get("content") == "passed":
                anchors[role], anchor_indices[role] = (paths[i], standalone.metrics), i
                break
        for i, chunk in enumerate(chunks):
            if chunk.role_id == role:
                if compositions[i]:
                    compositions[i] = inspect_composition(source_parts[i], paths[i],
                        compositions[i]["base_assembly"], evaluator,
                        anchor=anchors.get(role) if anchor_indices.get(role) != i else None)
                reports[i] = evaluate(i, paths[i], compositions[i])

    def candidate_for(index, action):
        chunk = chunks[index]
        if store.remaining_seconds(run_id) <= 0:
            raise ResourceExhausted("修复前已达到运行时限")
        if action.kind in {"local_speed", "local_trim_silence", "local_edge_fade", 'local_tail_repeat'}:
            if compositions[index]:
                raise ValueError("首轮不对已重分块组合再做局部变换，以保持内部时间表和检查有效")
            if local_counts[chunk.chunk_id] >= 2:
                raise ResourceExhausted("该分块已达到两次本地修复限制")
            local_counts[chunk.chunk_id] += 1
            if action.kind == 'local_tail_repeat':
                check = tail_candidates[index]
                if options.tail_repeat_mode != 'auto' or not check['auto_eligible']:
                    raise ValueError('存在文本歧义的尾部重复只能人工复核')
                operation = check['operation']
                path = check['candidate_path']; speed = speeds[index]
                render_checked_prefix(paths[index],path,end_sample=operation['end_sample'],
                    expected_sha256=operation['input_sha256'])
            elif action.kind == "local_speed":
                speed = max(.25, min(4.0, speeds[index] * action.speed_factor))
                factor = speed / speeds[index]
                path = rendered(paths[index], factor)
                operation = {"kind": "local_speed", "speed_factor": factor,
                             "input_sha256": hashlib.sha256(Path(paths[index]).read_bytes()).hexdigest()}
            else:
                speed = speeds[index]
                key = fingerprint({"input": hashlib.sha256(Path(paths[index]).read_bytes()).hexdigest(),
                                   "action": asdict(action), "version": "safe-boundary-v1"})
                path = str(store.root / "rendered" / f"{key}.wav")
                operation = render_safe_boundary(paths[index], path, kind=action.kind, edge=action.edge,
                                                   keep_silence_ms=action.keep_silence_ms)
            return raw_paths[index], path, speed, operation, source_parts[index], compositions[index]
        if action.kind not in {"resample", "content_repair"}:
            raise ValueError("未知修复动作不得转为合成请求")
        if repair_counts[chunk.chunk_id] >= options.limits.per_chunk_repairs:
            raise ResourceExhausted("该分块已达到质量重试次数限制")
        remaining_chars = store.remaining_repair_characters(run_id)
        if remaining_chars is not None and remaining_chars < len(chunk.tts_text):
            raise ResourceExhausted("剩余修复正文字符额度不足以完成该分块")
        if action.kind == "content_repair":
            split = split_repair_chunk(chunk, dictionary=options.reading_dictionary)
            available = min(options.limits.per_chunk_repairs - repair_counts[chunk.chunk_id], store.remaining_requests(run_id))
            if available <= 0:
                raise ResourceExhausted("内容修复没有剩余请求额度")
            candidates = split if split and available >= 2 else (chunk,)
            store.write_json(prefix + f"/repair_plan_{index + 1}_{len(attempts) + 1}.json",
                {"parent_chunk_id": chunk.chunk_id, "prompt_version": CONTENT_PROMPT_VERSION,
                 "parts": [asdict(c) for c in candidates]})
            parts = []
            for child in candidates:
                if repair_counts[chunk.chunk_id] >= options.limits.per_chunk_repairs:
                    raise ResourceExhausted("该原始分块已达到质量重试次数限制")
                repair_counts[chunk.chunk_id] += 1
                profile = content_repair_profile(child, getattr(provider_config, "instructions", None))
                raw = observed_synthesis(index, child.tts_text, profile, resample=True, repair=True)
                parts.append({"chunk": asdict(child), "raw_path": raw, "base_speed": speeds[index],
                              "request_profile": profile.provider_params, "prompt_version": CONTENT_PROMPT_VERSION,
                              "strategy": "resegment" if len(candidates) > 1 else "content_prompt"})
            path, composition = compose_parts(parts)
            return parts[0]["raw_path"], path, speeds[index], {"kind": "content_repair",
                "mode": parts[0]["strategy"], "prompt_version": CONTENT_PROMPT_VERSION}, parts, composition
        repair_counts[chunk.chunk_id] += 1
        raw = observed_synthesis(index, chunk.tts_text, _profile(chunk), resample=True, repair=True)
        path = rendered(raw, speeds[index])
        return raw, path, speeds[index], None, [{"chunk": asdict(chunk), "raw_path": raw,
            "base_speed": speeds[index], "rendered_path": path, "strategy": "resample"}], None

    def boundary_report(index):
        left, right = chunks[index:index + 2]
        pair_key = fingerprint({"left": hashlib.sha256(Path(paths[index]).read_bytes()).hexdigest(),
                                "right": hashlib.sha256(Path(paths[index + 1]).read_bytes()).hexdigest(),
                                "pause": left.pause_after_ms, "version": "pair-v2"})
        pair = store.root / "rendered" / f"pair-{pair_key}.wav"
        checksum = pair.with_suffix(".json")
        valid = False
        if pair.is_file() and checksum.is_file():
            try:
                valid = hashlib.sha256(pair.read_bytes()).hexdigest() == json.loads(checksum.read_text())["sha256"]
            except (ValueError, KeyError):
                pass
        if not valid:
            assemble_pcm([left, right], paths[index:index + 2], pair)
            store.write_json(str(checksum.relative_to(store.root)), {"sha256": hashlib.sha256(pair.read_bytes()).hexdigest()})
        report = evaluator.evaluate_boundary(left, right, paths[index], paths[index + 1], assembled_window=str(pair))
        report.metrics["preview_path"] = str(pair)
        return report

    boundary_reports = [boundary_report(i) for i in range(len(chunks) - 1)]

    def preserves_checks(before, after):
        hard = lambda r: {i.code for i in r.issues if i.certainty == "confirmed" and i.severity == "error"}
        old_alignment = before.metrics.get("content_alignment")
        new_alignment = after.metrics.get("content_alignment")
        return (hard(after) <= hard(before)
                and all(after.dimensions.get(dimension) == "passed" for dimension, status in before.dimensions.items()
                        if status == "passed")
                and (old_alignment is None or (new_alignment is not None
                     and new_alignment["error_rate"] <= old_alignment["error_rate"])))

    def attempt_repair(index, action, boundary_id=None):
        old_path, old_report = paths[index], reports[index]
        affected = list(range(max(0, index - 1), min(len(boundary_reports), index + 1)))
        previous = {i: boundary_reports[i] for i in affected}
        record = {"chunk_id": chunks[index].chunk_id, "action": asdict(action),
                  "before": old_report.to_dict(), "selected": False,
                  "before_boundaries": {str(i): report.to_dict() for i, report in previous.items()}}
        if boundary_id:
            record["boundary_id"] = boundary_id
        try:
            raw, path, speed, operation, parts, composition = candidate_for(index, action)
            record["candidate_sources"] = parts
            record["candidate_composition"] = composition
            candidate = evaluate(index, path, composition)
            paths[index] = path
            updated = {i: boundary_report(i) for i in affected}

            def combined_rank(chunk_report, boundaries):
                ranks = [report_rank(r) for r in [chunk_report, *boundaries.values()]]
                return tuple(sum(rank[k] for rank in ranks) for k in range(len(ranks[0])))

            acceptable = (preserves_checks(old_report, candidate)
                          and all(preserves_checks(previous[i], updated[i]) for i in affected))
            if composition:
                acceptable &= not any(issue["dimension"] in {"stitching", "content", "signal"}
                                      or issue["code"] != "too_fast"
                                      for inner in composition["internal_reports"] for issue in inner["issues"])
                acceptable &= all(inner["dimensions"].get("content") == "passed"
                                  and inner["dimensions"].get("signal", "passed") == "passed"
                                  for inner in composition["internal_reports"])
            if acceptable and combined_rank(candidate, updated) < combined_rank(old_report, previous):
                raw_paths[index], speeds[index], reports[index] = raw, speed, candidate
                for i, report in updated.items():
                    boundary_reports[i] = report
                record["selected"] = True
                record["decision_reason"] = "improved_priority_without_regressions"
                source_parts[index], compositions[index] = parts, composition
                render_operations[index] = render_operations[index] + [operation] if action.kind.startswith("local_") else []
                record["render_operation"] = operation
                artifact_hashes[chunks[index].chunk_id] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
                refresh_anchor(index)
            else:
                record["decision_reason"] = "regressed_check" if not acceptable else "no_priority_gain"
            record["after"] = candidate.to_dict()
            record["after_boundaries"] = {str(i): r.to_dict() for i, r in updated.items()}
            record["candidate_path"] = path
        except ResourceExhausted as exc:
            limits_hit.append(str(exc))
            record["stopped"] = str(exc)
            record["decision_reason"] = "resource_limit"
        except Exception as exc:
            record["error_type"] = type(exc).__name__
            record["decision_reason"] = "no_safe_edit" if action.kind in {
                "local_trim_silence", "local_edge_fade"} and isinstance(exc, ValueError) else "evaluation_or_generation_error"
        finally:
            if not record["selected"]:
                paths[index] = old_path
        attempts.append(record)
        return record["selected"]

    if options.auto_repair:
        # 可本地保留完整正文时，先尝试尾部裁切，避免先为相邻ASR差异发起重生成。
        from .repair import RepairAction
        for index,check in tail_candidates.items():
            if options.tail_repeat_mode == 'auto' and check['auto_eligible']:
                check['selected'] = attempt_repair(index,RepairAction('local_tail_repeat','tail_repeat_suspected'))
                if check['selected']:
                    deferred_tail.discard(index)
        # 先处理拼接，再处理块级问题；右侧有问题时也能在额度内尝试右块。
        for index in range(len(boundary_reports)):
            if index in deferred_tail or index+1 in deferred_tail:
                # 重复尾段尚待核验时，不能把该接缝的连带ASR差异转为邻句重生成。
                continue
            for target, edge in ((index, "tail"), (index + 1, "head")):
                for action in propose_actions(boundary_reports[index], edge=edge):
                    if action.kind in {"local_trim_silence", "local_edge_fade"}:
                        attempt_repair(target, action, boundary_reports[index].scope_id)
            for target in (index, index + 1):
                if target in deferred_tail:
                    continue
                actions = [a for a in propose_actions(boundary_reports[index]) if a.kind == "resample"]
                if not actions:
                    break
                attempt_repair(target, actions[0], boundary_reports[index].scope_id)
        order = sorted(range(len(chunks)), key=lambda i: report_rank(reports[i]), reverse=True)
        for index in order:
            if index in deferred_tail:
                continue
            for local_round in range(2):
                local_selected = False
                for action in propose_actions(reports[index], max_rate=options.max_rate):
                    if action.kind not in {a.kind for a in propose_actions(reports[index], max_rate=options.max_rate)}:
                        continue
                    if local_round and action.kind != "local_speed":
                        continue
                    if action.kind == "local_speed" and local_counts[chunks[index].chunk_id] >= 2:
                        continue
                    selected = attempt_repair(index, action)
                    local_selected |= selected and action.kind == "local_speed"
                if not local_selected:
                    break
            while (any(i.code == "asr_mismatch" for i in reports[index].issues)
                   and repair_counts[chunks[index].chunk_id] < options.limits.per_chunk_repairs
                   and store.remaining_requests(run_id) > 0):
                from .repair import RepairAction
                before_count = repair_counts[chunks[index].chunk_id]
                attempt_repair(index, RepairAction("content_repair", "asr_mismatch"))
                if repair_counts[chunks[index].chunk_id] == before_count:
                    break

    # 输出音量方案独立于修复选择缓存：恢复或切换开关时不能重复叠加。
    selection_paths = list(paths)
    output_conditioning = []
    if options.transition_boundaries:
        from .transition import PRESET, render_onset_transition
        for index in range(len(chunks) - 1):
            boundary_id = f"{chunks[index].chunk_id}|{chunks[index + 1].chunk_id}"
            if boundary_id not in options.transition_boundaries:
                continue
            target = index + 1
            record = {"boundary_id": boundary_id, "chunk_id": chunks[target].chunk_id,
                      "preset": PRESET, "selected": False,
                      "selection_basis": "explicit_boundary_configuration_not_detector",
                      "before": reports[target].to_dict()}
            output_conditioning.append(record)
            if compositions[target]:
                record["decision_reason"] = "compound_chunk_requires_separate_review"
                continue
            old_path = paths[target]
            affected = list(range(max(0, target - 1), min(len(boundary_reports), target + 1)))
            before_boundaries = {i: boundary_reports[i] for i in affected}
            try:
                if hashlib.sha256(Path(old_path).read_bytes()).hexdigest() != artifact_hashes[chunks[target].chunk_id]:
                    raise ValueError("起读处理前来源音频校验失败")
                path = str(store.root / prefix / "transitions" / f"chunk_{target + 1:06d}.wav")
                operation = render_onset_transition(old_path, path)
                record["operation"] = operation
                candidate = evaluate(target, path, None)
                paths[target] = path
                updated = {i: boundary_report(i) for i in affected}
                acceptable = (preserves_checks(reports[target], candidate)
                              and all(preserves_checks(before_boundaries[i], updated[i]) for i in affected))
                record.update(after=candidate.to_dict(),
                              after_boundaries={str(i): r.to_dict() for i, r in updated.items()})
                if acceptable:
                    reports[target] = candidate
                    for i, report in updated.items():
                        boundary_reports[i] = report
                    artifact_hashes[chunks[target].chunk_id] = operation["output_sha256"]
                    record.update(selected=True, decision_reason="requested_policy_without_detected_regression")
                else:
                    record["decision_reason"] = "regressed_check_keep_original"
            except Exception as exc:
                record.update(decision_reason="processing_or_evaluation_failed_keep_original", error_type=type(exc).__name__)
            finally:
                if not record["selected"]:
                    paths[target] = old_path

    final_pcm = store.root / prefix / "chapter.wav"
    mapping = assemble_pcm(chunks, paths, final_pcm, expected_artifacts=artifact_hashes)
    # 所有诊断位置映射到最终时间表，修复改变时长后不会沿用旧时间戳。
    for span, report in zip(mapping["spans"], reports):
        report.metrics["start_seconds"] = span["start_sample"] / sample_rate
        report.metrics["end_seconds"] = span["end_sample"] / sample_rate
    for span, report in zip(mapping["boundaries"], boundary_reports):
        report.metrics["start_seconds"] = span["start_sample"] / sample_rate
        report.metrics["end_seconds"] = span["end_sample"] / sample_rate

    from audiobook_generator.role_script.audio_pipeline import _concat_file_line, _final_encode, require_ffmpeg_tools
    from audiobook_generator.utils.utils import set_audio_tags
    ffmpeg, _ = require_ffmpeg_tools()
    playlist = final_pcm.with_suffix(".concat.txt")
    playlist.write_text(_concat_file_line(str(final_pcm.resolve())))
    temporary_output = final_pcm.with_name(f"encoded.{plan.output_format}")
    _final_encode(str(playlist), str(temporary_output), plan.output_format, ffmpeg)
    from .audio import audio_duration
    expected_duration = mapping["total_samples"] / sample_rate
    if abs(audio_duration(temporary_output) - expected_duration) > max(.15, expected_duration * .01):
        raise RuntimeError("最终编码音频时长与 PCM 组装计划不一致")
    set_audio_tags(str(temporary_output), tags, output_format=plan.output_format)
    from .encoding import verify_encoded_audio
    encoded_report = verify_encoded_audio(temporary_output, final_pcm, chunks, mapping,
        store.root / prefix / "encoded_checks", evaluator, enable_asr=options.enable_asr,
        dictionary=options.reading_dictionary)
    Path(output_file).parent.mkdir(parents=True, exist_ok=True)
    os.replace(temporary_output, output_file)
    for index, chunk in enumerate(chunks):
        for part in source_parts[index]:
            store.select_sample(part["raw_path"])
            request_histories[index].update(store.sample_provenance(part["raw_path"])["origin_request_ids"])
        store.save_render_selection(selection_keys[chunk.chunk_id], {"parts": source_parts[index],
            "rendered_path": selection_paths[index], "speed": speeds[index], "render_operations": render_operations[index],
            "sample_rate": sample_rate, "channels": channels,
            "generation_request_ids": sorted(request_histories[index]),
            "generation_history_incomplete": history_incomplete[index]})
    for role, index in anchor_indices.items():
        anchor_path, anchor_metrics = anchors[role]
        store.save_anchor(anchor_keys[chunks[index].chunk_id], anchor_path, anchor_metrics)
    all_reports = reports + boundary_reports + [encoded_report]
    status = "failed" if any(r.status == "failed" for r in all_reports) else (
        "incomplete" if any(r.status == "incomplete" for r in all_reports) else "passed")
    result = {"schema_version": "audio-core-v1", "provider": "openai", "run_id": run_id,
              "reading_plan_version": PLAN_VERSION,
              "nonspoken_source_units": nonspoken_source_units(plan.units),
              "chapter_index": plan.chapter_index, "output_file": str(Path(output_file).resolve()),
              "generation_status": "generated", "quality_status": status,
              "reading_configuration": {"normalization_version": VERSION, "language": options.language,
                                        'tail_repeat_mode':options.tail_repeat_mode,
                                        "role_references": options.role_references,
                                            "max_english_wpm": options.max_english_wpm,
                                        "reading_dictionary": options.reading_dictionary},
              "output_conditioning": {"configured_boundaries": options.transition_boundaries,
                                      "configured_source_group": options.transition_source_group,
                                      "source_group_matches": options.transition_source_group == source_group_id,
                                      "matching_boundaries": matching_joins,
                                      "operations": output_conditioning,
                                      "scope": "explicitly_selected_joins_only",
                                      "note": "50% is waveform amplitude; a single-boundary preference is not a universal quality guarantee."},
              "pronunciation_review": pronunciation_review(chunks),
              "chunks": [{"chunk": asdict(c), "raw_path": raw, "rendered_path": path,
                          "voice_reference_request": reference_requests[c.chunk_id],
                          "selected_rendered_path": selection_path,
                          "speed": speed, "render_operations": operations, "synthesis_parts": parts,
                          "composition": composition, "report": report.to_dict()}
                         for c, raw, path, selection_path, speed, operations, parts, composition, report in
                         zip(chunks, raw_paths, paths, selection_paths, speeds, render_operations, source_parts, compositions, reports)],
              "boundaries": [r.to_dict() for r in boundary_reports], "assembly": mapping,
              'tail_repeat_checks':tail_repeat_checks,
              "final_verification": encoded_report.to_dict(),
              "repair_attempts": attempts, "resource_summary": store.summary(run_id),
              "resource_limits": asdict(store.run_limits(run_id)),
              "resource_provenance": store.resource_provenance(run_id,
                  [part["raw_path"] for parts in source_parts for part in parts],
                  [{"chunk_id": chunk.chunk_id, "request_ids": sorted(request_histories[index]),
                    "history_incomplete": history_incomplete[index]} for index, chunk in enumerate(chunks)]),
              "limits_reached": limits_hit,
              "source_group_id": source_group_id}
    elapsed = time.perf_counter() - started
    result["performance"] = {"runtime_seconds": elapsed,
                             "evaluation_seconds": getattr(evaluator, "evaluation_seconds", None),
                             "runtime_rtf": elapsed / max(expected_duration, .001),
                             "duration_seconds": expected_duration}
    report_path = store.write_json(prefix + "/quality.json", result)
    store.write_json(f"latest/chapter_{plan.chapter_index:06d}.json", {"report_path": report_path})
    logger.info("第 %s 章统一质检：%s；报告：%s", plan.chapter_index, status, report_path)
    return result
