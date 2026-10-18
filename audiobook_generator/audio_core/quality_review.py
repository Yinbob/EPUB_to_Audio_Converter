"""人工裁决另存派生报告；精确绑定原报告及问题，不改写机器证据。"""
from __future__ import annotations

import copy
import json
from datetime import datetime
from pathlib import Path

from .annotations import _verify_pcm_layout
from .repair_review import _read_report, _sha
from .report_sources import resolve_reference_pcm
from .store import fingerprint

VERSION = "audio-quality-human-review-v1"
ALLOWED = {"boundary_content_mismatch": "false_positive", "rate_drift": "acceptable_variation",
           "asr_mismatch": "false_positive"}


def adjudicate_quality(report_path, review_path):
    source = _read_report(report_path)
    original = source["report"]
    if original.get("human_adjudication"):
        raise ValueError("请对原始机器报告复核，不叠加派生裁决")
    review_path = Path(review_path).resolve()
    review_hash = _sha(review_path)
    review = json.loads(review_path.read_text())
    if (review.get("version") != VERSION or review.get("source_report_sha256") != source["report_sha256"]
            or review.get("source_audio_sha256") != source["encoded_sha256"]):
        raise ValueError("人工复核与当前报告／音频不匹配")
    if not isinstance(review.get("reviewer"), str) or not review["reviewer"].strip():
        raise ValueError("人工复核缺少标注人")
    try:
        stamp = datetime.fromisoformat(review["reviewed_at"].replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            raise ValueError("缺少时区")
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise ValueError("人工复核需要带时区的时间") from exc
    decisions, observations = review.get("decisions", []), review.get("additional_issues", [])
    if not isinstance(decisions, list) or not isinstance(observations, list) or not (decisions or observations):
        raise ValueError("人工复核需要逐项裁决或已知问题")
    pcm = resolve_reference_pcm(original, source["path"], require_hash=True)
    _verify_pcm_layout(pcm, original["assembly"], original["chunks"])
    result = copy.deepcopy(original)
    # 派生报告可能另存到其他目录；旧报告的相对发现结果必须显式绑定。
    result["final_verification"]["metrics"]["reference_pcm_path"] = str(pcm)
    modified, seen = {}, set()

    def select(entry):
        scope, index = entry.get("scope"), entry.get("index")
        if scope not in {"chunk", "boundary"} or type(index) is not int or index < 0:
            raise ValueError("人工复核须指定分块／接缝及非负整数索引")
        items = result["chunks"] if scope == "chunk" else result["boundaries"]
        if index >= len(items):
            raise ValueError("人工复核位置超出报告范围")
        check = items[index]["report"] if scope == "chunk" else items[index]
        key = scope, index
        if key not in modified:
            modified[key] = (check, copy.deepcopy(check))
        return check, key

    for decision in decisions:
        check, key = select(decision)
        issue_hash = decision.get("issue_sha256")
        if not isinstance(issue_hash, str) or (key, issue_hash) in seen:
            raise ValueError("人工裁决问题重复或缺少指纹")
        seen.add((key, issue_hash))
        matches = [i for i in check.get("issues", []) if fingerprint(i) == issue_hash]
        if len(matches) != 1:
            raise ValueError("人工裁决未指向唯一的原机器问题")
        issue = matches[0]
        if (issue.get("code") not in ALLOWED or decision.get("resolution") != ALLOWED[issue["code"]]
                or issue.get("severity", "warning") == "error"
                or not isinstance(decision.get("reason"), str) or not decision["reason"].strip()):
            raise ValueError("不支持此裁决；不能消除未复核、严重或其他类型问题")
        if issue['code'] == 'asr_mismatch':
            # 文字识别误报须明确核验整块读法，不用局部听感消除漏读／多读提示。
            expected = result['chunks'][key[1]]['chunk']['tts_text'] if key[0] == 'chunk' else None
            if (key[0] != 'chunk' or not expected
                    or decision.get('verified_tts_text') != expected
                    or decision.get('content_complete') is not True
                    or decision.get('no_additions') is not True
                    or issue.get('dimension') != 'content'
                    or check.get('dimensions', {}).get('content') == 'failed'):
                raise ValueError('ASR误报须核验当前整块朗读文本、正文完整及无多读，不能解除已失败内容')
        check["issues"].remove(issue)
        check.setdefault("human_decisions", []).append(copy.deepcopy(decision))
        if issue["code"] in {"boundary_content_mismatch", "asr_mismatch"} and not any(
                i.get("dimension") == "content" for i in check["issues"]):
            check["dimensions"]["content"] = "passed"
            check.setdefault("metrics", {})["content_verification_method"] = "human_adjudicated_exact_issue"
    for observation in observations:
        check, _ = select(observation)
        issue = observation.get("issue", {})
        if (not isinstance(issue.get("code"), str) or not issue["code"].startswith("human_")
                or issue.get("dimension") not in {"stitching", "consistency", "content", "signal"}
                or not isinstance(issue.get("evidence"), dict) or not issue["evidence"]):
            raise ValueError("人工新增问题需有独立编号、维度和证据")
        check.setdefault("issues", []).append({**copy.deepcopy(issue), "certainty": "confirmed"})
    for check, machine in modified.values():
        check["machine_evidence"] = machine
        check["status"] = ("failed" if "failed" in check["dimensions"].values()
            or any(i.get("certainty") == "confirmed" and i.get("severity") == "error" for i in check["issues"])
            else "incomplete" if check["issues"] or "incomplete" in check["dimensions"].values() else "passed")
    checks = [c["report"] for c in result["chunks"]] + result["boundaries"] + [result["final_verification"]]
    statuses = [c.get("status", "incomplete") for c in checks]
    result["quality_status"] = "failed" if "failed" in statuses else "incomplete" if "incomplete" in statuses else "passed"
    result["human_adjudication"] = {"version": VERSION, "source_report": source["path"],
        "source_report_sha256": source["report_sha256"], "source_audio_sha256": source["encoded_sha256"],
        "review_path": str(review_path), "review_sha256": review_hash, "reviewer": review["reviewer"],
        "reviewed_at": stamp.isoformat(), "decisions": len(decisions), "additional_issues": len(observations),
        "full_chapter_human_verified": False, "requests_sent": 0}
    if (_sha(source["path"]) != source["report_sha256"] or _sha(source["audio"]) != source["encoded_sha256"]
            or _sha(review_path) != review_hash):
        raise ValueError("裁决期间来源或人工记录发生变化")
    return result


def validate_adjudicated_source(source):
    """材料导出时重建裁决结果；人工记录及原报告变化均使裁决失效。"""
    metadata = source["report"].get("human_adjudication")
    if not metadata:
        return []
    if metadata.get("version") != VERSION:
        raise ValueError("未知人工裁决格式")
    for path_key, hash_key in (("source_report", "source_report_sha256"), ("review_path", "review_sha256")):
        if _sha(metadata[path_key]) != metadata[hash_key]:
            raise ValueError("人工裁决来源已改变，请重新复核")
    expected = adjudicate_quality(metadata["source_report"], metadata["review_path"])
    if expected != source["report"]:
        raise ValueError("派生裁决报告与来源／人工记录不一致")
    return [{"path": metadata[k], "sha256": metadata[h]} for k, h in
            (("source_report", "source_report_sha256"), ("review_path", "review_sha256"))]
