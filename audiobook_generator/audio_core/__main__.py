"""研究与离线评估入口：python -m audiobook_generator.audio_core --help。"""
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

from .models import CoreOptions, ReadingChunk, ResourceLimits
from .store import ArtifactStore, fingerprint


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    from audiobook_generator.tts_providers.segment_synthesis import atomic_write_bytes
    atomic_write_bytes(str(path), json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode())


def preflight(args):
    import platform
    from audiobook_generator.role_script.audio_pipeline import require_ffmpeg_tools
    try:
        ffmpeg, ffprobe = require_ffmpeg_tools()
    except RuntimeError:
        ffmpeg = ffprobe = None
    return {"provider_scope": "mimo_only", "python": platform.python_version(),
            "ffmpeg": ffmpeg, "ffprobe": ffprobe,
            "packages": {name: importlib.util.find_spec(name) is not None
                         for name in ("numpy", "soundfile", "scipy", "funasr", "speechbrain", "silero_vad")},
            "asr_model_configured": bool(args.asr_model and Path(args.asr_model).is_dir()),
            "speaker_model_configured": bool(args.speaker_model and Path(args.speaker_model, "hyperparams.yaml").is_file()),
            "boundary_model_configured": bool(args.boundary_model and Path(args.boundary_model).is_file()),
            "automatic_downloads": False, "requests_sent": 0}


def create_plan(args):
    from audiobook_generator.role_script.models import SynthesisUnit, VoiceProfile, SourceSpan
    from .reading import VERSION, build_reading_plan, load_reading_dictionary
    text = Path(args.text).read_text(encoding="utf-8")
    profile = VoiceProfile("narrator", "旁白", {"voice": args.voice, "speed": 1.0})
    unit = SynthesisUnit("1:1:narrator", 1, "正文", 1, 1, "narrator", "旁白", text, profile,
                         source_span=SourceSpan(1, 0, len(text)))
    dictionary = load_reading_dictionary(args.reading_dictionary)
    chunks = build_reading_plan([unit], chunk_chars=args.chunk_chars, dictionary=dictionary, language=args.language)
    result = {"provider": "openai", "chunks": [asdict(c) for c in chunks], "requests_sent": 0,
              "normalization_version": VERSION, "reading_dictionary": dictionary, "language": args.language}
    from .reading import pronunciation_review
    result["pronunciation_review"] = pronunciation_review(chunks)
    write_json(args.output, result)
    return {"output": str(Path(args.output).resolve()), "chunks": len(chunks), "requests_sent": 0}


def probe(args):
    from audiobook_generator.config.general_config import GeneralConfig
    from audiobook_generator.role_script.models import VoiceProfile
    from audiobook_generator.tts_providers.openai_tts_provider import OpenAITTSProvider, get_openai_supported_voices
    from .language import normalize_language
    language = normalize_language(args.language)
    voices = args.voices or (["Mia", "Chloe", "Milo", "Dean"] if language == "en" else ["冰糖", "茉莉", "苏打", "白桦"])
    if len(voices) * args.prompt_count > args.max_requests:
        raise ValueError("请求上限不足以完成共同探针；请减少声音数或 prompt-count")
    if len(set(voices)) != len(voices) or set(voices) - set(get_openai_supported_voices()):
        raise ValueError("试听声音必须唯一且属于当前 MiMo 目录")
    config = GeneralConfig(None)
    config.tts, config.language, config.voice_name, config.output_format = "openai", args.language, voices[0], "wav"
    config.speed, config.stream = 1.0, False
    provider = OpenAITTSProvider(config)
    store = ArtifactStore(args.output)
    run = store.start_run(ResourceLimits(max_requests=args.max_requests, max_seconds=args.max_seconds))
    texts = ["清晨的阳光穿过窗户，落在安静的书桌上，他轻轻打开了那本旧书。",
             "你还记得昨天约定的时间吗？我们应该在什么地方见面呢？",
             "二零二六年十月十五日，这份报告显示增长了百分之三点五。",
             "别着急，先把事情说清楚，我们一起想办法解决眼前的问题。"]
    if language == "en":
        texts = ["Morning sunlight fell across the quiet desk. She opened the old book and began to read.",
                 "Do you remember where we agreed to meet? Please wait beside the bridge until I arrive.",
                 "The report showed an increase of three point five percent. He checked every number carefully.",
                 "Take your time and tell me what happened. We can work through the problem together."]
    texts = texts[:args.prompt_count]
    records = []
    for voice in voices:
        for index, text in enumerate(texts):
            path = provider.synthesize_observed_chunk(text, VoiceProfile(voice, voice, {"voice": voice}), store, run)
            records.append({"voice": voice, "prompt_id": f"prompt_{index + 1}", "text": text,
                            "path": path, "verified": False, "language": language})
    manifest = {"provider": "openai", "model": config.model_name, "run_id": run,
                "probes": records, "language": language, "resources": store.summary(run)}
    write_json(Path(args.output) / "probes.json", manifest)
    return {"manifest": str((Path(args.output) / "probes.json").resolve()),
            "probes": len(records), "review_required": True, "resources": store.summary(run)}


def build_bank(args):
    from .audio import signal_features
    from .backends import SpeakerEncoder
    from .reading import VERSION, reading_count
    from .language import resolve_language
    import hashlib
    import re
    manifest_bytes = Path(args.manifest).read_bytes()
    source = json.loads(manifest_bytes)
    if source.get("provider") != "openai":
        raise ValueError("首轮仅支持 MiMo 探针")
    encoder, voices = SpeakerEncoder(args.speaker_model), {}
    speaker_identity = encoder.cache_identity()
    languages = set()
    if source.get("human_review_path"):
        if hashlib.sha256(Path(source["human_review_path"]).read_bytes()).hexdigest() != source.get("human_review_sha256"):
            raise ValueError("人工复核文件指纹变化，请重新核对探针清单")
    for record in source["probes"]:
        if record.get("verified") is not True:
            raise ValueError("请先试听核验探针并在清单中标记 verified=true")
        audio_sha256 = hashlib.sha256(Path(record['path']).read_bytes()).hexdigest()
        if record.get("audio_sha256") and record["audio_sha256"] != audio_sha256:
            raise ValueError("探针音频与人工核验的指纹不符")
        language = resolve_language(record["text"], record.get("language", source.get("language", "auto")))
        if language not in {"en", "zh"}:
            raise ValueError("声音库需要按中文、英文分别建库；混合文本不能代替单语言核验")
        languages.add(language)
        if len(languages) > 1:
            raise ValueError("中文与英文探针请分别建库，不能共用已核验语言声明")
        metrics = signal_features(record["path"])
        if metrics["peak"] < .003 or metrics["clipped_fraction"] > .002:
            raise ValueError("探针存在静音或削波，不能建声音库")
        voice = voices.setdefault(record["voice"], {"verified": True, "embeddings": {}, "texts": {}, 'probes': {}})
        prompt_id = record["prompt_id"]
        if prompt_id in voice["embeddings"]:
            raise ValueError("同声音探针编号重复")
        voice["embeddings"][prompt_id] = encoder(record["path"]).tolist()
        if hashlib.sha256(Path(record['path']).read_bytes()).hexdigest() != audio_sha256:
            raise ValueError('建库期间探针音频发生变化，请固定音频后重新构建声音库')
        voice["texts"][prompt_id] = record["text"]
        count, _, unit = reading_count(record['text'], language=language)
        metrics['overall_rate'] = count / max(metrics['duration_seconds'], .1) if count else None
        metrics['articulation_rate'] = count / max(metrics['active_seconds'], .1) if count >= 5 else None
        metrics['articulation_rate_unit'] = 'words_per_second' if language == 'en' else 'han_characters_per_second'
        if language == 'en':
            metrics['words_per_minute'] = metrics['overall_rate'] * 60 if count else None
        voice['probes'][prompt_id] = {'path': str(Path(record['path']).resolve()),
            'audio_sha256': audio_sha256,
            'metrics': metrics, 'language': language,
            'reading_unit_kind': 'english_normalized_reading_words' if language == 'en' else 'normalized_han_characters',
            'activity_method': 'rms_20ms_threshold_0.003', 'human_verified_declaration': True}
    if not voices:
        raise ValueError("探针清单为空")
    for a in voices.values():
        for b in voices.values():
            common = set(a["texts"]) & set(b["texts"])
            if len(common) < 2 or any(a["texts"][key] != b["texts"][key] for key in common):
                raise ValueError("各声音必须使用至少两条内容一致的共同探针")
    if encoder.cache_identity()['fingerprint'] != speaker_identity['fingerprint']:
        raise ValueError('建库期间声纹模型版本变化，请固定模型后重新构建声音库')
    if Path(args.manifest).read_bytes() != manifest_bytes:
        raise ValueError('建库期间探针清单发生变化，请固定清单后重新构建声音库')
    bank = {"provider": "openai", "model": source.get("model"), "speaker_model": args.speaker_model,
            "voices": voices, "languages": sorted(languages), "reading_normalization_version": VERSION, "verification_origin": "caller_supplied_manifest",
            'speaker_model_identity': speaker_identity,
            'probe_manifest_sha256': hashlib.sha256(manifest_bytes).hexdigest()}
    write_json(args.output, bank)
    return {"voices": len(voices), "output": str(Path(args.output).resolve())}


def cast(args):
    from audiobook_generator.role_script.loader import load_role_script
    from .casting import interaction_graph, locked_voices_from_script, optimize_casting
    script, report = load_role_script(args.script)
    if not report.ok or script is None or script.provider != "openai":
        raise ValueError("需要校验通过的 MiMo 角色剧本")
    from .language import normalize_language, resolve_language
    required = {resolve_language(segment.text, args.language) for chapter in script.chapters for segment in chapter.segments}
    if required - {normalize_language(args.language)}:
        raise ValueError("选角目标语言与剧本正文不一致；中英文须分别核验，混合正文暂不自动选角")
    roles, edges = interaction_graph(script.chapters)
    initial = {role: definition.provider_params.get("voice") for role, definition in script.roles.items()}
    result = optimize_casting(roles, edges, read_json(args.bank), locked=locked_voices_from_script(script),
                              initial=initial, strategy=args.strategy, seed=args.seed,
                              fit_penalties=read_json(args.fit_penalties) if args.fit_penalties else None,
                              narrator_exclusive=args.narrator_exclusive, language=args.language)
    write_json(args.output, result)
    return result


def evaluate(args):
    from .audio import assemble_pcm
    from .annotations import _verify_pcm_layout
    from .quality import QualityEvaluator, attach_composition_report, inspect_composition
    from .reading import VERSION
    from .report_sources import resolve_reference_pcm
    source = read_json(args.manifest)
    if source.get("provider") != "openai":
        raise ValueError("首轮评估清单必须来自 MiMo")
    if source.get("generation_status") == "failed" or not source.get("chunks"):
        raise ValueError("失败或空章节没有可重新评估的音频")
    reference = resolve_reference_pcm(source, args.manifest)
    _verify_pcm_layout(reference, source["assembly"], source["chunks"])
    options = CoreOptions(asr_model_dir=args.asr_model, speaker_model_dir=args.speaker_model,
                          role_references=getattr(args, 'role_references', None) or source.get('reading_configuration', {}).get('role_references'),
                          language=source.get("reading_configuration", {}).get("language", "auto"),
                          max_english_wpm=source.get("reading_configuration", {}).get("max_english_wpm", 300),
                          boundary_model=args.boundary_model, enable_asr=not args.no_asr,
                          enable_speaker=not args.no_speaker, enable_vad=args.vad,
                          reading_dictionary=source.get("reading_configuration", {}).get("reading_dictionary", {}))
    store = ArtifactStore(Path(args.output).parent / ".evaluation_cache")
    evaluation_dir = store.root / "reports" / fingerprint({"source": source,
        "output": str(Path(args.output).resolve()), "options": asdict(options), "normalization": VERSION})
    evaluator = QualityEvaluator(options, store=store)
    started = time.perf_counter()
    chunks, paths, reports, anchors = [], [], [], {}
    for item in source["chunks"]:
        chunk, path = ReadingChunk(**item["chunk"]), item["rendered_path"]
        if options.role_references and chunk.profile.get('voice_profile_id'):
            from .role_references import load_reference
            route = item.get('voice_reference_request')
            if route is None:
                raise ValueError('复评固定参考需要来源中实际声音请求元数据，不能猜测全局指令')
            fixed = load_reference(options.role_references, chunk.role_id, chunk.profile, chunk.language, route)
            if fixed:
                anchors[chunk.role_id] = fixed
        report = evaluator.evaluate_chunk(chunk, path, anchor=anchors.get(chunk.role_id))
        if item.get("composition"):
            item["composition"] = inspect_composition(item["synthesis_parts"], path,
                item["composition"]["base_assembly"], evaluator, anchor=anchors.get(chunk.role_id),
                expected_sha256=item["composition"].get("render_sha256"))
            attach_composition_report(report, item["composition"])
        if (chunk.profile.get('voice_mode') not in {'design', 'clone'} and not report.issues
                and report.dimensions.get("content") == "passed" and chunk.role_id not in anchors):
            anchors[chunk.role_id] = (path, report.metrics)
        chunks.append(chunk)
        paths.append(path)
        report.metrics.update({key: item["report"].get("metrics", {}).get(key) for key in
                               ("start_seconds", "end_seconds") if key in item["report"].get("metrics", {})})
        reports.append(report.to_dict())
    boundaries = []
    for i in range(len(chunks) - 1):
        pair = evaluation_dir / f"pair_{i}.wav"
        assemble_pcm(chunks[i:i + 2], paths[i:i + 2], pair)
        report = evaluator.evaluate_boundary(chunks[i], chunks[i + 1], paths[i], paths[i + 1], assembled_window=str(pair))
        report.metrics["preview_path"] = str(pair)
        report.metrics.update({key: source["boundaries"][i].get("metrics", {}).get(key) for key in
                               ("start_seconds", "end_seconds") if key in source["boundaries"][i].get("metrics", {})})
        boundaries.append(report.to_dict())
    from .encoding import verify_encoded_audio
    final_check = verify_encoded_audio(source["output_file"], reference, chunks, source["assembly"],
        evaluation_dir / "encoded_checks", evaluator, enable_asr=options.enable_asr,
        dictionary=options.reading_dictionary).to_dict()
    statuses = [r["status"] for r in reports + boundaries + [final_check]]
    status = "failed" if "failed" in statuses else "incomplete" if "incomplete" in statuses else "passed"
    result = {**source, "chunks": [{**item, "report": report} for item, report in zip(source["chunks"], reports)],
              "boundaries": boundaries, "quality_status": status, "final_verification": final_check,
              "reevaluation": {"requests_sent": 0, "seconds": time.perf_counter() - started,
                               "normalization_version": VERSION,
                               "asr_model": args.asr_model, "speaker_model": args.speaker_model,
                               "boundary_model": args.boundary_model, "vad": args.vad,
                               "reading_dictionary": options.reading_dictionary}}
    from .reading import pronunciation_review
    result["pronunciation_review"] = pronunciation_review(chunks)
    if source.get("experiment_conditioning"):
        result["experiment_conditioning"] = {**source["experiment_conditioning"],
                                             "quality_pending_reevaluation": False}
    write_json(args.output, result)
    return {"output": str(Path(args.output).resolve()), "chunks": len(reports), "boundaries": len(boundaries),
            "requests_sent": 0}


def prepare_labels(args):
    source = read_json(args.report)
    group = source.get("source_group_id") or fingerprint([c["chunk"]["source_text"] for c in source["chunks"]])
    paths = {c["chunk"]["chunk_id"]: c["rendered_path"] for c in source["chunks"]}
    rows = []
    for report, boundary in zip(source["boundaries"], source["assembly"]["boundaries"]):
        rows.append({"group_id": group, "split": "unassigned", "labels": None,
                     "origin": "real_unlabelled", "boundary_id": report["scope_id"],
                     "features": report["metrics"]["features"], "reviewed_normal": False,
                     "left_path": paths[boundary["left_chunk_id"]], "right_path": paths[boundary["right_chunk_id"]]})
    from audiobook_generator.tts_providers.segment_synthesis import atomic_write_bytes
    atomic_write_bytes(args.output, ("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n").encode())
    return {"rows": len(rows), "output": args.output, "annotation_required": True}


def train(args):
    from .boundary_model import train_boundary
    rows = [json.loads(line) for line in Path(args.data).read_text().splitlines() if line.strip()]
    model = train_boundary(rows, steps=args.steps, seed=args.seed)
    write_json(args.output, model)
    return {"output": str(Path(args.output).resolve()), "confidence_kind": model["confidence_kind"],
            "threshold_kind": model["threshold_kind"],
            "label_support": model["label_support"], "source_group_counts": model["source_group_counts"],
            "heldout_metrics": model["heldout_metrics"], "note": "训练完成不代表真实缺陷泛化已通过验证"}


def import_review(args):
    from .annotations import read_review_pack
    from .dataset import write_jsonl
    result = read_review_pack(args.pack, args.reviews,
                              splits=read_json(args.splits) if args.splits else None)
    output = Path(args.output).resolve()
    audit = output.with_name(output.name + ".review.json")
    if not args.check_only:
        if output.exists() or audit.exists():
            raise ValueError("标注导入不覆盖既有文件，请指定新输出路径")
        write_jsonl(output, result["boundaries"])
        write_json(audit, result)
    return {key: value for key, value in result.items() if key not in {"boundaries", "human_records"}} | {
        "check_only": args.check_only, "output": str(output) if not args.check_only else None}


def prepare_review(args):
    from .annotations import export_review_pack
    return export_review_pack(args.reports, args.output)


def augment(args):
    from .dataset import augment_boundaries, write_jsonl
    rows = [json.loads(line) for line in Path(args.data).read_text().splitlines() if line.strip()]
    variants = augment_boundaries(rows, Path(args.output).parent / "augmented_audio")
    write_jsonl(args.output, variants)
    return {"output": args.output, "variants": len(variants), "annotation_required": True,
            "requests_sent": 0}


def listening(args):
    from .listening import prepare_listening
    return prepare_listening(read_json(args.conditions), args.output, seed=args.seed)


def score(args):
    from .listening import score_listening
    result = score_listening(args.key, args.responses)
    write_json(args.output, result)
    return result


def smoke(args):
    from .validation import live_smoke
    return live_smoke(args.output, max_requests=args.max_requests, max_seconds=args.max_seconds)


def repair_review(args):
    from .repair_review import prepare_repair_review
    return prepare_repair_review(read_json(args.pairs), args.output, seed=args.seed)


def repair_review_score(args):
    from .repair_review import score_repair_review
    result = score_repair_review(args.key, args.responses)
    write_json(args.output, result)
    return result


def transition_preview(args):
    from .transition_preview import prepare_transition_preview
    evaluator = None
    if args.asr_model:
        from .models import CoreOptions
        from .quality import QualityEvaluator
        evaluator = QualityEvaluator(CoreOptions(enable_speaker=False, asr_model_dir=args.asr_model))
    return prepare_transition_preview(args.report, args.boundary, args.output,
                                      onset_gain=args.onset_gain, ramp_ms=args.ramp_ms, evaluator=evaluator)


def loudness_preview(args):
    from .loudness_preview import prepare_loudness_preview
    evaluator = None
    if args.asr_model:
        from .quality import QualityEvaluator
        evaluator = QualityEvaluator(CoreOptions(asr_model_dir=args.asr_model, enable_speaker=False))
    return prepare_loudness_preview(args.report, args.boundary, args.output,
                                   max_attenuation_db=args.max_attenuation_db, evaluator=evaluator)


def adjudicate(args):
    from .quality_review import adjudicate_quality
    output = Path(args.output).resolve()
    if output.exists():
        raise ValueError("人工裁决输出已存在，拒绝覆盖")
    result = adjudicate_quality(args.manifest, args.review)
    write_json(output, result)
    return {"output": str(output), "quality_status": result["quality_status"],
            "human_adjudication": result["human_adjudication"], "requests_sent": 0}


def review_queue(args):
    from .review_queue import build_review_queue
    output = Path(args.output).resolve()
    if output.exists():
        raise ValueError('集中复核清单已存在，拒绝覆盖')
    result = build_review_queue(args.report,max_window_seconds=args.max_window_seconds)
    write_json(output,result)
    return {'output':str(output),**result['summary'],'requests_sent':0}


def summarize(args):
    results, resources, snapshots, generation_events = [], {}, {}, {}
    history_incomplete = False
    for path in args.reports:
        report = read_json(path)
        results.append({"report": path, "chapter": report["chapter_index"], "quality_status": report["quality_status"],
                        "chunk_issues": sum(len(c["report"]["issues"]) for c in report["chunks"]),
                        "boundary_issues": sum(len(b["issues"]) for b in report["boundaries"]),
                        "selected_repairs": sum(a["selected"] for a in report["repair_attempts"])})
        # 章节报告的资源数是同一 run 的累计值，不能简单相加。
        run = report["run_id"]
        snapshot = (sum(c["requests"] for c in report["resource_summary"].values()),
                    Path(path).stat().st_mtime_ns)
        if snapshot >= snapshots.get(run, (-1, -1)):
            snapshots[run] = snapshot
            resources[run] = report["resource_summary"]
        provenance = report.get("resource_provenance", {})
        lineage = provenance.get("recorded_generation", {})
        history_incomplete |= lineage.get("history_incomplete", True)
        for event in lineage.get("request_events", []):
            key = (provenance["project_database"], event["id"])
            previous = generation_events.get(key)
            if previous and any(previous[name] != event[name] for name in ("request_key", "run_id", "characters", "repair")):
                raise ValueError("同一请求的生成来源记录矛盾")
            if previous is None or (event["finished"] or 0) >= (previous["finished"] or 0):
                generation_events[key] = event
    generation_summary = {}
    for event in generation_events.values():
        item = generation_summary.setdefault(event["status"], {"requests": 0, "characters": 0, "repair_requests": 0})
        item["requests"] += 1
        item["characters"] += event["characters"]
        item["repair_requests"] += event["repair"]
    return {"chapters": results, "resources_by_run": resources,
            "recorded_generation": {"scope": "deduplicated_selected_sources_and_observed_candidate_lineage",
                "summary": generation_summary, "history_incomplete": history_incomplete,
                "request_count": len(generation_events),
                "note": "生成来源与本次运行请求可能重叠，不能相加；未知历史不记为零。"}}


def hybrid_command(args):
    from audiobook_generator.role_script.loader import load_role_script
    from audiobook_generator.role_script.deepseek_splitter import role_script_to_dict
    from .hybrid_casting import role_usage, hybrid_casting, apply_hybrid, generate_voice_cards
    script, report = load_role_script(args.script)
    if not report.ok or script is None:
        raise ValueError('需要可加载的角色剧本')
    if args.command == 'hybrid-usage':
        result = role_usage(script, language=args.language, full_book=args.full_book)
    elif args.command == 'cast-hybrid':
        result = hybrid_casting(script, read_json(args.bank), language=args.language,
            full_book=args.full_book, reserve_narrator=not args.no_reserve_narrator,
            locked=read_json(args.locks) if args.locks else None,
            fit_penalties=read_json(args.fit_penalties) if args.fit_penalties else None)
        write_json(Path(args.output).with_name('role_usage.json'), result['usage'])
    elif args.command == 'describe-hybrid':
        from openai import OpenAI
        from audiobook_generator.utils.deepseek_config import get_deepseek_credentials
        key, url, model = get_deepseek_credentials()
        if not key:
            raise ValueError('未配置 DeepSeek，声音卡尚未生成')
        result, receipt = generate_voice_cards(script, read_json(args.casting),
            client=OpenAI(api_key=key, base_url=url, max_retries=0), model=model)
        write_json(Path(args.output).with_name('voice_card_generation.json'), receipt)
    else:
        result = role_script_to_dict(apply_hybrid(script, read_json(args.casting), read_json(args.cards)))
    write_json(args.output, result)
    return {'output': str(Path(args.output).resolve()), 'command': args.command,
            'tts_requests': 0, 'requires_audio_review': args.command != 'hybrid-usage'}


def hybrid_probe_command(args):
    from .hybrid_probe import run_probe, evaluate_probe
    if args.command == 'evaluate-hybrid-probe':
        result = evaluate_probe(args.manifest, args.output, args.review_dir,
            asr_model=args.asr_model, speaker_model=args.speaker_model, bank_path=args.bank)
        return {'output': args.output, 'samples': len(result['probes']), 'human_review_status': 'pending', 'tts_requests': 0}
    from audiobook_generator.role_script.loader import load_role_script
    from audiobook_generator.config.general_config import GeneralConfig
    from audiobook_generator.tts_providers.openai_tts_provider import OpenAITTSProvider
    from audiobook_generator.role_script.validator import validate_role_script
    script, report = load_role_script(args.script)
    if script is None or not report.ok or not validate_role_script(script).ok:
        raise ValueError('需要通过校验的混合声音剧本')
    config = GeneralConfig(None)
    config.tts, config.language, config.output_format = 'openai', 'en-US', 'wav'
    config.stream = False
    manifest = run_probe(script, OpenAITTSProvider(config), args.output, args.roles)
    return {'manifest': str((Path(args.output) / 'probes.json').resolve()),
            'samples': len(manifest['probes']), 'resources': manifest['resources']}


def confirm_hybrid_references(args):
    from .role_references import make_reference
    quality = read_json(args.quality)
    reviews = read_json(args.reviews)
    if not isinstance(reviews, list) or not reviews:
        raise ValueError('需要非空的逐条人工核验清单')
    samples = {s['sample_id']: s for s in quality['probes']}
    refs = {}
    for review in reviews:
        sample = samples.get(review.get('sample_id'))
        if sample is None:
            raise ValueError('核验条目不属于当前先导')
        key, record = make_reference(sample['role_id'], sample['profile'], sample['profile']['voice_language'], sample['request'],
            sample['path'], sample['report']['metrics'], review)
        if key in refs:
            raise ValueError('同角色只能确认一个固定身份锚点；请在清单中选择一条')
        refs[key] = record
    write_json(args.output, {'schema_version': 'mimo-role-references-v1', 'references': refs})
    return {'output': args.output, 'confirmed_references': len(refs), 'tts_requests': 0}


def hybrid_scenes_command(args):
    from .hybrid_scenes import run_scenes
    from audiobook_generator.role_script.loader import load_role_script
    from audiobook_generator.config.general_config import GeneralConfig
    from audiobook_generator.tts_providers.openai_tts_provider import OpenAITTSProvider
    script, report = load_role_script(args.script)
    if script is None or not report.ok:
        raise ValueError('混合场景剧本加载失败')
    config = GeneralConfig(None)
    config.tts, config.language, config.output_format, config.stream = 'openai', 'en-US', 'wav', False
    result = run_scenes(script, OpenAITTSProvider(config), args.references, args.output,
        asr_model=args.asr_model, speaker_model=args.speaker_model)
    return {'output': str(Path(args.output).resolve()), 'chapters': len(result['chapters']), 'resources': result['resources']}


def main(argv=None):
    parser = argparse.ArgumentParser(description="MiMo 统一质量核心研究工具（无计费逻辑）")
    commands = parser.add_subparsers(dest="command", required=True)
    def models(p):
        p.add_argument("--asr-model")
        p.add_argument("--speaker-model")
        p.add_argument("--boundary-model")
    p = commands.add_parser("preflight", help="离线检查依赖和模型配置，不读取凭证、不发请求")
    models(p)
    p.set_defaults(func=preflight)
    p = commands.add_parser("plan", help="从文本生成可追踪朗读计划，不合成")
    p.add_argument("--text", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--voice", default="mimo_default")
    p.add_argument("--language", default="en-US", choices=["en-US", "en", "zh-CN", "zh", "auto"])
    p.add_argument("--chunk-chars", type=int, default=300)
    p.add_argument("--reading-dictionary", help="原文→实际读法的纯文本词典 JSON")
    p.set_defaults(func=create_plan)
    p = commands.add_parser("probe", help="实际调用 MiMo 生成共同试听文本；单独执行才发请求")
    p.add_argument("--voices", nargs="+")
    p.add_argument("--language", default="en-US", choices=["en-US", "en", "zh-CN", "zh"])
    p.add_argument("--prompt-count", type=int, choices=[2, 3, 4], default=4)
    p.add_argument("--output", required=True)
    p.add_argument("--max-requests", type=int, default=16)
    p.add_argument("--max-seconds", type=float, default=600)
    p.set_defaults(func=probe)
    p = commands.add_parser("build-bank", help="从已核验探针构建声音库")
    p.add_argument("--manifest", required=True)
    p.add_argument("--speaker-model", required=True)
    p.add_argument("--output", required=True)
    p.set_defaults(func=build_bank)
    p = commands.add_parser("cast", help="生成尊重声音锁定的 MiMo 选角文件")
    p.add_argument("--script", required=True)
    p.add_argument("--bank", required=True)
    p.add_argument("--language", default="en", choices=["en", "zh"], help="目标语言须已在探针库中核验")
    p.add_argument("--strategy", choices=["interaction", "global", "random", "fit"], default="interaction")
    p.add_argument("--fit-penalties", help="人工审查的角色→声音→非负适配惩罚 JSON")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument('--narrator-exclusive', action='store_true', help='旁白独占一个候选音色，其他角色不能复用')
    p.add_argument("--output", required=True)
    p.set_defaults(func=cast)
    for name, help_text in [('hybrid-usage', '导出角色对白统计，默认局部范围'),
                            ('cast-hybrid', '按全书对白量生成内置／描述混合选角'),
                            ('describe-hybrid', '实际调用一次 DeepSeek 生成固定声音卡，不合成'),
                            ('apply-hybrid', '将来源绑定的混合选角和声音卡应用到剧本，不改正文')]:
        p = commands.add_parser(name, help=help_text)
        p.add_argument('--script', required=True)
        p.add_argument('--output', required=True)
        if name in {'hybrid-usage', 'cast-hybrid'}:
            p.add_argument('--language', choices=['en', 'zh'], default='en')
            p.add_argument('--full-book', action='store_true', help='明确声明输入为全书预分析，局部剧本不能启用')
        if name == 'cast-hybrid':
            p.add_argument('--bank', required=True)
            p.add_argument('--locks')
            p.add_argument('--fit-penalties')
            p.add_argument('--no-reserve-narrator', action='store_true')
        if name in {'describe-hybrid', 'apply-hybrid'}:
            p.add_argument('--casting', required=True)
        if name == 'apply-hybrid':
            p.add_argument('--cards', required=True)
        p.set_defaults(func=hybrid_command)
    p = commands.add_parser('probe-hybrid', help='实际运行两角色×两共同文本＋独立重复，共6次VoiceDesign请求，无重试')
    p.add_argument('--script', required=True)
    p.add_argument('--roles', nargs=2, required=True)
    p.add_argument('--output', required=True)
    p.set_defaults(func=hybrid_probe_command)
    p = commands.add_parser('evaluate-hybrid-probe', help='离线检查六条描述声音探针并导出试听页')
    p.add_argument('--manifest', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--review-dir', required=True)
    p.add_argument('--asr-model', required=True)
    p.add_argument('--speaker-model', required=True)
    p.add_argument('--bank', help='复用同文本且同声纹模型版本的已核验英语内置探针，不额外合成')
    p.set_defaults(func=hybrid_probe_command)
    p = commands.add_parser('confirm-hybrid-references', help='导入人工核验，按角色固定身份锚点')
    p.add_argument('--quality', required=True)
    p.add_argument('--reviews', required=True)
    p.add_argument('--output', required=True)
    p.set_defaults(func=confirm_hybrid_references)
    p = commands.add_parser('run-hybrid-scenes', help='在描述角色参考经人工确认后运行最多三个自编混合场景')
    p.add_argument('--script', required=True)
    p.add_argument('--references', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--asr-model', required=True)
    p.add_argument('--speaker-model', required=True)
    p.set_defaults(func=hybrid_scenes_command)
    p = commands.add_parser('prepare-hybrid-loudness', help='按新混合场景实测响度制作整句衰减副本，不合成，处理后需复评')
    p.add_argument('--manifest', required=True)
    p.add_argument('--output', required=True)
    def hybrid_loudness_command(args):
        from .hybrid_loudness import prepare_hybrid_loudness
        result = prepare_hybrid_loudness(args.manifest, args.output)
        return {'output': args.output, 'chapters': len(result['report_paths']), 'requests_sent': 0,
                'target_lufs': result['protocol']['target_lufs']}
    p.set_defaults(func=hybrid_loudness_command)
    p = commands.add_parser("evaluate", help="对现有生成报告内的音频重新离线评估")
    p.add_argument('--role-references', help='沿用经人工核验且绑定实际请求的角色参考')
    p.add_argument("--manifest", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--no-asr", action="store_true")
    p.add_argument("--no-speaker", action="store_true")
    p.add_argument("--vad", action="store_true")
    models(p)
    p.set_defaults(func=evaluate)
    p = commands.add_parser("prepare-labels", help="导出待人工标注的真实边界，不伪造标注")
    p.add_argument("--report", required=True)
    p.add_argument("--output", required=True)
    p.set_defaults(func=prepare_labels)
    p = commands.add_parser("prepare-review", help="导出含音频、文本、校验清单与空白人工表格的标注包")
    p.add_argument("--reports", nargs="+", required=True)
    p.add_argument("--output", required=True)
    p.set_defaults(func=prepare_review)
    p = commands.add_parser("import-review", help="校验人工标注包并回填已明确核验的边界；不自动划分数据")
    p.add_argument("--pack", required=True)
    p.add_argument("--reviews", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--splits", help="人工指定 group_id 到 train/dev/test 的 JSON 映射，可稍后填写")
    p.add_argument("--check-only", action="store_true", help="仅核验，不创建或修改任何标注文件")
    p.set_defaults(func=import_review)
    p = commands.add_parser("augment", help="对已核验正常的训练／开发边界注入扰动，标签仍需人工复核")
    p.add_argument("--data", required=True)
    p.add_argument("--output", required=True)
    p.set_defaults(func=augment)
    p = commands.add_parser("train-boundary", help="训练轻量边界分类器并报告独立测试集结果")
    p.add_argument("--data", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--steps", type=int, default=1000)
    p.add_argument("--seed", type=int, default=42)
    p.set_defaults(func=train)
    p = commands.add_parser("summarize", help="汇总章节问题和去重的运行资源记录")
    p.add_argument("reports", nargs="+")
    p.set_defaults(func=summarize)
    p = commands.add_parser("prepare-listening", help="从不同选角条件的同一正文生成待人工审查的辨识先导材料")
    p.add_argument("--conditions", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--seed", type=int, default=42)
    p.set_defaults(func=listening)
    p = commands.add_parser("score-listening", help="汇总已收集的先导辨识回答，不做显著性推断")
    p.add_argument("--key", required=True)
    p.add_argument("--responses", required=True)
    p.add_argument("--output", required=True)
    p.set_defaults(func=score)
    p = commands.add_parser("prepare-repair-review", help="用既有最终音频导出修复前后 A/B 盲听包，不发 TTS 请求")
    p.add_argument("--pairs", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--seed", type=int, default=42)
    p.set_defaults(func=repair_review)
    p = commands.add_parser("score-repair-review", help="校验材料并汇总人工四维偏好，仅作描述性先导统计")
    p.add_argument("--key", required=True)
    p.add_argument("--responses", required=True)
    p.add_argument("--output", required=True)
    p.set_defaults(func=repair_review_score)
    p = commands.add_parser("preview-transition", help="为已知接缝制作停顿／非零增益试听候选，不自动应用，不发 TTS 请求")
    p.add_argument("--report", required=True)
    p.add_argument("--boundary", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--asr-model", help="本地 SenseVoice 目录；不传则明确标记内容未评估")
    p.add_argument("--onset-gain", type=float, default=.8, help="起读波形幅度比例，0.4（含）～1（不含）；默认 0.8")
    p.add_argument("--ramp-ms", type=int, nargs="+", default=[200, 400], help="增益恢复时间，1～500 毫秒；默认 200 400")
    p.set_defaults(func=transition_preview)
    p = commands.add_parser("preview-loudness", help="为偏响的右句制作恒定衰减试听，不自动应用，不发 TTS 请求")
    p.add_argument("--report", required=True)
    p.add_argument("--boundary", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--max-attenuation-db", type=float, default=6., help="最大衰减 0～12 dB（不含0），默认6")
    p.add_argument("--asr-model", help="本地 SenseVoice 目录；不传则标记内容未评估")
    p.set_defaults(func=loudness_preview)
    p = commands.add_parser("prepare-casting-gain", help="各选角条件使用相同的声音增益表，保留时间表，另存待复评副本")
    p.add_argument("--conditions", required=True)
    p.add_argument("--gains", required=True, help="声音→dB 的完整 JSON；仅允许 -12～0")
    p.add_argument("--output", required=True)
    def casting_gain(args):
        from .experiment_loudness import prepare_casting_gain
        return prepare_casting_gain(read_json(args.conditions), read_json(args.gains), args.output)
    p.set_defaults(func=casting_gain)
    p = commands.add_parser('prepare-review-queue',help='合并当前章节的重叠复核范围，保留全部未解决诊断，不发请求')
    p.add_argument('--report',required=True)
    p.add_argument('--output',required=True)
    p.add_argument('--max-window-seconds',type=float,default=45)
    p.set_defaults(func=review_queue)
    p = commands.add_parser("adjudicate-quality", help="另存来源绑定的逐项人工裁决，保留机器证据，不发 TTS 请求")
    p.add_argument("--manifest", required=True)
    p.add_argument("--review", required=True)
    p.add_argument("--output", required=True)
    p.set_defaults(func=adjudicate)
    p = commands.add_parser("smoke", help="实际调用 MiMo：固定自编文本检查流式／非流式及 MP3 编码，不自动运行")
    p.add_argument("--output", required=True)
    p.add_argument("--max-requests", type=int, default=4)
    p.add_argument("--max-seconds", type=float, default=240)
    p.set_defaults(func=smoke)
    args = parser.parse_args(argv)
    try:
        # 第三方模型可能直接 print 进度；stdout 保留为单个可解析 JSON。
        with contextlib.redirect_stdout(sys.stderr):
            result = args.func(args)
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
