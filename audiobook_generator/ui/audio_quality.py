"""统一质量设置与报告读取；纯数据层，便于离线检验。"""
import json
from pathlib import Path


def apply_quality_settings(config, path=None):
    if path:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        names = {"chunk_chars", "max_requests", "max_repairs", "max_seconds", "no_asr", "no_speaker",
                 "vad", "asr_model", "speaker_model", "boundary_model", "reading_dictionary", "max_repair_characters",
                 "transition_boundaries", "transition_source_group", "max_english_wpm", "role_references", "tail_repeat_mode"}
        if not isinstance(value, dict) or set(value) - names:
            raise ValueError("质量设置包含未知字段")
        for name, setting in value.items():
            if name in {"no_asr", "no_speaker", "vad"} and not isinstance(setting, bool):
                raise ValueError(f"{name} 必须是布尔值")
            if name in {"chunk_chars", "max_requests", "max_repairs"} and (isinstance(setting, bool) or not isinstance(setting, int)):
                raise ValueError(f"{name} 必须是整数")
            if name == "max_repair_characters" and setting is not None and (type(setting) is not int or setting < 0):
                raise ValueError("max_repair_characters 必须为空或非负整数")
            if name.endswith("model") and setting is not None and not isinstance(setting, str):
                raise ValueError(f"{name} 必须是本地路径")
            if name == "reading_dictionary" and not isinstance(setting, dict):
                raise ValueError("reading_dictionary 必须是原文→实际读法对象")
            setattr(config, "audio_core_" + name, setting)
    from audiobook_generator.audio_core.models import CoreOptions
    return CoreOptions.from_config(config)


def find_quality_reports(output_dir):
    root = Path(output_dir or "audiobook_output").expanduser().resolve() / ".audio_projects"
    if not root.is_dir():
        return []
    return [str(p) for p in sorted(root.glob("*/reports/*/chapter_*/quality.json"),
                                  key=lambda p: p.stat().st_mtime, reverse=True)]


def resource_summary_text(report):
    summary = report.get("resource_summary", {})
    actual = sum(item["requests"] for item in summary.values())
    repairs = sum(item["repair_requests"] for item in summary.values())
    text = f"本次运行累计 {actual} 次合成请求（修复 {repairs} 次）。"
    lineage = report.get("resource_provenance", {}).get("recorded_generation", {})
    if not lineage:
        return text + "历史生成请求数未知。"
    count = sum(item["requests"] for item in lineage["summary"].values())
    text += f"生成来源与候选历史已记录 {count} 次请求。"
    if lineage["history_incomplete"]:
        text += "历史记录不全，未知部分未计作零。"
    return text + "两项可能重叠，不相加。"


def load_quality_report(path):
    source = Path(path).resolve()
    project = next((parent for parent in source.parents if (parent / "project.sqlite").is_file()), None)
    if project is None:
        raise ValueError("报告不属于统一质量项目目录")
    value = json.loads(source.read_text(encoding="utf-8"))
    if value.get("schema_version") != "audio-core-v1":
        raise ValueError("不支持的质量报告版本")
    rows, previews = [], {}
    if value.get("generation_status") == "failed":
        rows.append(["章节", "生成", value.get("error_type", "未知错误"), "failed", "—"])
    reports = [(c["report"], c["rendered_path"]) for c in value["chunks"]]
    for chunk in value["chunks"]:
        for inner in (chunk.get("composition") or {}).get("internal_reports", []):
            reports.append((inner, inner.get("metrics", {}).get("preview_path")))
    reports += [(b, b.get("metrics", {}).get("preview_path")) for b in value["boundaries"]]
    encoded = value.get("final_verification")
    if encoded:
        reports.append((encoded, encoded.get("metrics", {}).get("decoded_path")))
        for check in encoded.get("metrics", {}).get("checks", []):
            audio = check.get("path")
            if audio and Path(audio).resolve().is_relative_to(project) and Path(audio).is_file():
                previews[check["scope_id"]] = audio
    for report, audio in reports:
        if audio and Path(audio).resolve().is_relative_to(project) and Path(audio).is_file():
            previews[report["scope_id"]] = audio
        time_text = f'{report.get("metrics", {}).get("start_seconds", 0):.2f}'
        for issue in report["issues"]:
            at = issue.get("start_seconds")
            rows.append([issue.get("scope_id", report["scope_id"]), issue["dimension"], issue["code"],
                         issue["certainty"], f"{at:.2f}" if at is not None else time_text])
        if not report["issues"] and report["status"] == "incomplete":
            rows.append([report["scope_id"], "未完成检查", "请查看模型／参考与阈值配置", "incomplete", time_text])
    for hint in value.get("pronunciation_review", {}).get("hints", []):
        note = "已声明词典读法，仍需试听" if hint["reading_override_declared"] else "待试听确认读音"
        rows.append([hint["chunk_id"], "读音复核", f'「{hint["character"]}」：{hint["context"]}（{note}）',
                     "pending", "原文位置 " + str(hint["unit_start"])])
    for check in value.get('tail_repeat_checks', []):
        audio = Path(check.get('candidate_path','')).resolve()
        if (audio.is_file() and audio.is_relative_to(project) and check.get('candidate_sha256')):
            import hashlib
            if hashlib.sha256(audio.read_bytes()).hexdigest() == check['candidate_sha256']:
                scope = 'tail_repeat:' + check['chunk_id']
                previews[scope] = str(audio)
                rows.append([scope,'尾部重复候选','已自动选用' if check.get('selected') else '请核对完整性与结束听感',
                             'machine_selected' if check.get('selected') else 'pending','片段内'])
    return value, rows, previews


def preview_quality_issue(path, scope):
    _, _, previews = load_quality_report(path)
    return previews.get(scope)


def apply_local_quality_defaults(config, root=None):
    """仅发现已安装模型，不下载模型，不覆盖用户的高级配置。"""
    root = Path(root) if root is not None else Path(__file__).resolve().parents[2]
    candidates = {'asr': root / '.audio_quality_models' / 'SenseVoiceSmall',
                  'speaker': root / '.audio_quality_models' / 'ecapa'}
    for kind, path in candidates.items():
        if path.is_dir() and any(path.iterdir()):
            setattr(config, 'audio_core_' + kind + '_model', str(path.resolve()))


def local_quality_status():
    from types import SimpleNamespace
    config = SimpleNamespace()
    apply_local_quality_defaults(config)
    available = []
    if getattr(config, 'audio_core_asr_model', None):
        available.append('内容转写')
    if getattr(config, 'audio_core_speaker_model', None):
        available.append('声纹')
    return '本地模型：' + '、'.join(available) if available else '本地检查模型：尚未发现'
