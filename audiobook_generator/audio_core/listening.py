"""有参考声音的角色辨识先导材料；答案与条件标签不进入公开材料。"""
from __future__ import annotations

import csv
import json
import random
import shutil
import tempfile
from pathlib import Path

from .annotations import _verify_pcm_layout
from .audio import audio_duration
from .repair_review import _read_report, _sha
from .report_sources import resolve_reference_pcm
from .store import fingerprint


TASK = "reference_conditioned_role_identification"
VERSION = "role-listening-v2"


def _voice_identity(item):
    """核对实验中固定的声音档案和实际请求；不以配置一致代替听感一致。"""
    profile = item['chunk'].get('profile')
    request = item.get('voice_reference_request')
    if not profile:
        if request is not None:
            raise ValueError('声音请求缺少对应角色档案')
        return None  # 单场景旧报告兼容，不能用于跨场景身份推断。
    if not isinstance(profile, dict) or (request is not None and not isinstance(request, dict)):
        raise ValueError('声音档案和请求记录必须是对象')
    from audiobook_generator.tts_providers.mimo_voice import MODELS
    mode = profile.get('voice_mode', 'preset')
    if mode not in MODELS:
        raise ValueError('听众材料包含未知声音模式')
    if mode == 'preset':
        if not isinstance(profile.get('voice'), str) or not profile['voice'].strip():
            raise ValueError('内置声音档案缺少voice')
        if request is not None and request.get('voice') != profile['voice']:
            raise ValueError('实际声音请求与内置档案不一致')
    else:
        if (request is None or profile.get('voice') is not None
                or request.get('voice') is not None
                or any(not isinstance(profile.get(k), str) or not profile[k].strip()
                       for k in ('voice_profile_id', 'voice_version', 'voice_language'))
                or any(request.get(k) != profile[k] for k in ('voice_profile_id', 'voice_version'))
                or request.get('language') != profile['voice_language']):
            raise ValueError('描述／克隆声音须有匹配的档案版本、语言和实际请求')
        if mode == 'design' and (not isinstance(profile.get('voice_description'), str)
                                 or not profile['voice_description'].strip()):
            raise ValueError('描述声音档案缺少固定描述')
    if request is not None:
        if request.get('mode') != mode or request.get('model') != MODELS[mode]:
            raise ValueError('实际声音模式或模型与档案不一致')
        for key, route_key in (('voice_profile_id','voice_profile_id'), ('voice_version','voice_version'),
                               ('voice_language','language')):
            if key in profile and request.get(route_key) != profile[key]:
                raise ValueError('实际声音请求与角色档案版本不一致')
    if mode == 'clone':
        from audiobook_generator.tts_providers.mimo_reference import load_clone_reference
        for record in (profile, request):
            load_clone_reference(record.get('reference_audio_path'),record.get('reference_audio_sha256'))
        if profile['reference_audio_sha256'] != request['reference_audio_sha256']:
            raise ValueError('克隆档案和实际请求的参考内容不一致')
    # 参考路径是地址；相同内容的合法副本不应被误认为另一声音。
    identity = {'profile':{k:v for k,v in profile.items() if k != 'reference_audio_path'},
                'request':None if request is None else
                    {k:v for k,v in request.items() if k != 'reference_audio_path'}}
    return fingerprint(identity)


def _listening_source(path):
    source = _read_report(path)
    from .quality_review import validate_adjudicated_source
    source["review_dependencies"] = validate_adjudicated_source(source)
    report = source["report"]
    if report.get("quality_status") not in {"passed", "incomplete"}:
        raise ValueError("已确认失败的音频不能用于角色辨识")
    checks = [c.get("report", {}) for c in report["chunks"]]
    boundaries = report.get("boundaries", [])
    if len(boundaries) != len(report["assembly"]["boundaries"]):
        raise ValueError("缺少接缝质量报告")
    for check in checks + boundaries + [report["final_verification"]]:
        dimensions = check.get("dimensions", {})
        if (check.get("issues") or "failed" in dimensions.values()
                or dimensions.get("content") != "passed"):
            raise ValueError("角色辨识材料存在已检出问题或内容未完成检查，请先复核")
    if any(c.get("dimensions", {}).get("signal") != "passed" for c in checks):
        raise ValueError("角色辨识材料的信号检查未通过")
    metrics = report["final_verification"]["metrics"]
    reference_sha = metrics.get("reference_pcm_sha256")
    pcm = resolve_reference_pcm(report, source["path"], require_hash=True)
    _verify_pcm_layout(pcm, report["assembly"], report["chunks"])
    source["pcm"], source["pcm_sha256"] = pcm, reference_sha
    return source


def prepare_listening(conditions, output_dir, *, seed=42):
    if len(conditions) < 2 or len({c["condition"] for c in conditions}) != len(conditions):
        raise ValueError("至少需要两个不重名的选角条件")
    root = Path(output_dir).resolve()
    if root.exists():
        raise ValueError("试听材料输出目录已存在，避免覆盖既有实验")
    # 先验证全部来源；任何条件失败都不留下可被误分发的半成品。
    sources = []
    for condition in conditions:
        if ('report_path' in condition) == ('report_paths' in condition):
            raise ValueError("每个条件须指定 report_path 或有序 report_paths，不能同时指定")
        paths = condition.get('report_paths', [condition.get('report_path')])
        if (not isinstance(paths, list) or not paths
                or any(not isinstance(p, str) or not p for p in paths)
                or len({str(Path(p).resolve()) for p in paths}) != len(paths)):
            raise ValueError("场景报告须为非空、无重复的有序路径列表")
        sources.append([_listening_source(p) for p in paths])
    root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".role-listening-", dir=root.parent) as temporary:
        stage = Path(temporary) / "pack"
        result = _prepare_validated(conditions, sources, stage, seed=seed)
        stage.rename(root)
    return {**result, "output": str(root)}


def _prepare_validated(conditions, sources, root, *, seed):
    public = root / "public"
    (public / "audio").mkdir(parents=True)
    trials, answers, reference_scenes, roles = [], {}, None, None
    checksums = {}

    def copy_audio(path, expected):
        source = Path(path)
        if _sha(source) != expected:
            raise ValueError("导出期间来源片段发生变化")
        name = fingerprint({"seed": seed, "audio": expected})[:24] + ".wav"
        target = public / "audio" / name
        if not target.exists():
            shutil.copyfile(source, target)
        if _sha(target) != expected:
            raise ValueError("导出音频与报告校验值不一致")
        checksums["audio/" + name] = expected
        return "audio/" + name

    def copy_item(ref):
        return copy_audio(ref['item']['rendered_path'], ref['sha256'])

    def provenance(ref):
        return {'report_path': ref['source']['path'], 'report_sha256': ref['source']['report_sha256'],
                'source_group_id': ref['source']['report']['source_group_id'],
                'chunk_id': ref['item']['chunk']['chunk_id'], 'source_role': ref['item']['chunk']['role_id']}

    for condition, scene_sources in zip(conditions, sources):
        scenes, pool = [], []
        for source_index, source in enumerate(scene_sources):
            report = source['report']
            texts = [(c['chunk']['role_id'], c['chunk']['source_text'], c['chunk']['tts_text'])
                     for c in report['chunks']]
            scenes.append((report['source_group_id'], texts))
            spans = {s['chunk_id']: s for s in report['assembly']['spans']}
            for index, item in enumerate(report['chunks']):
                pool.append({'item': item, 'source': source, 'source_index': source_index, 'index': index,
                             'sha256': spans[item['chunk']['chunk_id']]['render_sha256'],
                             'voice_identity':_voice_identity(item)})
        if reference_scenes is None:
            reference_scenes = scenes
            roles = sorted({r for _, texts in scenes for r, _, _ in texts if r != 'narrator'})
        if scenes != reference_scenes:
            raise ValueError("各选角条件必须使用相同正文、角色、场景与分块顺序")
        if len(roles) < 2:
            raise ValueError("角色辨识至少需要两个非旁白角色")
        by_role = {role: [] for role in roles}
        eligible = []
        for ref in pool:
            role = ref['item']['chunk']['role_id']
            if role in by_role and audio_duration(ref['item']['rendered_path']) >= 3:
                by_role[role].append(ref)
                eligible.append(ref)
        for role in roles:
            if len({ref['sha256'] for ref in by_role[role]}) < 2:
                raise ValueError(f"角色 {role} 缺少至少两个不同的三秒片段，不能静默遗漏该角色")
            identities = {ref['voice_identity'] for ref in pool if ref['item']['chunk']['role_id'] == role}
            if len(identities) != 1 or (len(scene_sources) > 1 and None in identities):
                raise ValueError(f"角色 {role} 的声音档案版本或实际请求缺失／不一致")
        for ref in eligible:
            item, source = ref['item'], ref['source']
            report = source['report']
            role = item['chunk']['role_id']
            target = copy_item(ref)
            cues, reference_sources = {}, {}
            for number, candidate_role in enumerate(roles, 1):
                candidates = [c for c in by_role[candidate_role] if c['sha256'] != ref['sha256']]
                if not candidates:
                    raise ValueError(f"角色 {candidate_role} 没有与目标不同的独立参考音频")
                cues[f"角色{number}"] = copy_item(candidates[0])
                reference_sources[f'角色{number}'] = provenance(candidates[0])
            trial_id = fingerprint({"seed": seed, "condition": condition["condition"],
                                    'source_index': ref['source_index'], "index": ref['index']})[:16]
            trials.append({"trial_id": trial_id, "audio": target, "reference_voices": cues,
                           "question": "请根据参考声音，选择目标音频属于哪位角色。"})
            answers[trial_id] = {"condition": condition["condition"], "correct_role": f"角色{roles.index(role) + 1}",
                "source_role": role, "source_group_id": report['source_group_id'], "chunk_id": item["chunk"]["chunk_id"],
                "quality_status": report["quality_status"], "allowed_roles": list(cues),
                'target_source': provenance(ref), 'reference_sources': reference_sources}
    for source in (s for scenes in sources for s in scenes):
        if (_sha(source["path"]) != source["report_sha256"]
                or _sha(source["audio"]) != source["encoded_sha256"]
                or _sha(source["pcm"]) != source["pcm_sha256"]):
            raise ValueError("导出期间来源报告或章节音频改变")
        if any(_sha(d["path"]) != d["sha256"] for d in source.get("review_dependencies", [])):
            raise ValueError("导出期间人工裁决依据改变")
    represented = {answer["condition"] for answer in answers.values()}
    if len(represented) != len(conditions):
        raise ValueError("每个条件都需要可试听目标和独立参考音频；每位角色至少准备两个不同片段")
    random.Random(seed).shuffle(trials)
    payload = {"task": TASK, "version": VERSION, "seed": seed,
               "human_review_required": True, "trials": trials}
    (public / "trials.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    from .listening_player import render_listening_player
    (public / 'index.html').write_text(render_listening_player(payload),encoding='utf-8')
    with (public / "responses.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["participant_id", "trial_id", "response_role"])
        writer.writerows(["", trial["trial_id"], ""] for trial in trials)
    (public / "README.md").write_text(
        "# 角色辨识先导材料\n\n实验者须先人工核验内容、句尾、音色音调语速和质量可比性。机器无报警不代表人工验收通过。\n\n"
        "试听音频为生成报告选中的 PCM16 分块副本，包含该分块已采用的处理，不另加变速或音量调整；不用于评价完整章节接缝。\n\n"
        "直接打开 index.html，填写参与者编号，试听并选择角色，最后导出回答 CSV。页面无需联网或本地服务；"
        "需要将完整 public 目录连同 audio 子目录一起复制。回答只暂存在当前浏览器会话，关闭前请导出。"
        "也可根据 trials.json 中参考声音选择目标音频角色，在 responses.csv 填写 participant_id 和 response_role。"
        "未回答行保留空白；每名听众填写独立副本。只分发 public 目录。仅做描述性先导统计。\n", encoding="utf-8")
    for name in ("trials.json", "README.md", "index.html"):
        checksums[name] = _sha(public / name)
    source_records = [{"condition": c["condition"], 'scene_index': scene_index, "report_path": s["path"],
                   "report_sha256": s["report_sha256"], "encoded_sha256": s["encoded_sha256"],
                   "reference_pcm_sha256": s["pcm_sha256"],
                   "human_review_dependencies": s.get("review_dependencies", [])}
                   for c, scenes in zip(conditions, sources) for scene_index, s in enumerate(scenes)]
    (root / "private_answer_key.json").write_text(json.dumps({"task": TASK, "version": VERSION,
        "answers": answers, "public_sha256": checksums, "sources": source_records}, ensure_ascii=False, indent=2))
    return {"trials": len(trials), "output": str(root), "human_review_required": True,
            "requests_sent": 0,
            "distribution_note": "只分发 public 目录；答案文件留给实验者，不与材料一起发给听众。"}


def score_listening(key_path, responses_path):
    key_path = Path(key_path).resolve()
    key = json.loads(key_path.read_text())
    if key.get("task") != TASK or key.get("version") != VERSION or not key.get("public_sha256"):
        raise ValueError("试听答案缺少材料绑定，请重新导出试听包")
    public = key_path.parent / "public"
    for name, expected in key["public_sha256"].items():
        path = (public / name).resolve()
        if not path.is_relative_to(public) or not path.is_file() or _sha(path) != expected:
            raise ValueError("试听材料已改变，不能沿用旧答案评分")
    answers = key["answers"]
    seen, summaries = set(), {}
    with Path(responses_path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not {"participant_id", "trial_id", "response_role"} <= set(reader.fieldnames or []):
            raise ValueError("辨识回答表缺少必要列")
        for row in reader:
            participant, trial, response = ((row.get(k) or "").strip() for k in
                                            ("participant_id", "trial_id", "response_role"))
            if trial not in answers:
                raise ValueError("未知角色辨识试题")
            if not participant and not response:
                continue
            if not participant or trial not in answers or (participant, trial) in seen:
                raise ValueError("回答缺少参与者、试题未知或存在重复回答")
            seen.add((participant, trial))
            answer = answers[trial]
            if response not in answer["allowed_roles"]:
                raise ValueError("回答角色不在允许选项中")
            result = summaries.setdefault(answer["condition"], {"correct": 0, "total": 0, "confusion": {}, "participants": set()})
            result["total"] += 1
            result["correct"] += int(response == answer["correct_role"])
            result["participants"].add(participant)
            cell = answer["correct_role"] + " → " + response
            result["confusion"][cell] = result["confusion"].get(cell, 0) + 1
    for result in summaries.values():
        result["accuracy"] = result["correct"] / result["total"]
        result["participants"] = len(result["participants"])
    return {"conditions": summaries, "analysis_kind": "descriptive_pilot",
            "note": "未做重复测量或场景聚类推断；不据此声称显著改善。"}
