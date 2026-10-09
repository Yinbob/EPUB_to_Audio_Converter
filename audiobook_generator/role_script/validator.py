"""RoleScriptV1 语义、参数和章节覆盖率校验。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional, Sequence, Tuple

from .errors import ValidationReport
from .models import ChapterScript, RoleDefinition, RoleScriptV1, SegmentScript
from .normalization import (
    is_known_gender_value,
    normalize_coverage_text,
    normalize_gender,
)

SUPPORTED_PROVIDERS = ("openai", "minimax")
PARAM_RULES = {
    "openai": {
        "allowed": {"voice", "instructions", "speed"},
        "required": {"voice"},
        "speed": (0.25, 4.0),
    },
    "minimax": {
        "allowed": {"voice_id", "speed", "pitch", "volume"},
        "required": {"voice_id"},
        "speed": (0.5, 2.0),
        "pitch": (-12, 12),
        "volume": (0, 10),
    },
}
_ROLE_ID_PATTERN = re.compile(r"^[^\s/\\]{1,64}$")
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass
class ValidationResult:
    script: Optional[RoleScriptV1]
    report: ValidationReport

    @property
    def ok(self) -> bool:
        return self.report.ok and self.script is not None


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _normalize_params(role_id: str, params: Dict[str, Any], provider: str, report: ValidationReport) -> Dict[str, Any]:
    rules = PARAM_RULES.get(provider)
    if rules is None:
        return dict(params)
    allowed = rules["allowed"]
    role_path = f"$.roles.{role_id}.provider_params"
    normalized: Dict[str, Any] = {}
    for key, value in params.items():
        if key not in allowed:
            report.error("unknown_provider_param", f"{role_path}.{key}", f"{provider} 不支持参数：{key}")
            continue
        if key in {"voice", "voice_id", "instructions"}:
            if not isinstance(value, str) or (key != "instructions" and not value.strip()):
                report.error("invalid_provider_param", f"{role_path}.{key}", f"{key} 必须是非空字符串")
                continue
            normalized[key] = value.strip() if key != "instructions" else value
            continue
        if not _is_number(value):
            report.error("invalid_provider_param", f"{role_path}.{key}", f"{key} 必须是数字")
            continue
        numeric = float(value)
        if not numeric == numeric or numeric in (float("inf"), float("-inf")):
            report.error("invalid_provider_param", f"{role_path}.{key}", f"{key} 必须是有限数字")
            continue
        if key in rules:
            low, high = rules[key]
            if numeric < low or numeric > high:
                report.error(
                    "provider_param_out_of_range",
                    f"{role_path}.{key}",
                    f"{key} 必须在 {low} 到 {high} 之间",
                    minimum=low,
                    maximum=high,
                    actual=numeric,
                )
                continue
        normalized[key] = numeric
    for required in rules["required"]:
        if required not in normalized:
            report.error("missing_provider_param", f"{role_path}.{required}", f"缺少必填参数：{required}")
    return normalized


def _normalize_roles(script: RoleScriptV1, report: ValidationReport) -> Dict[str, RoleDefinition]:
    roles: Dict[str, RoleDefinition] = {}
    for role_id, role in script.roles.items():
        path = f"$.roles.{role_id}"
        if not _ROLE_ID_PATTERN.fullmatch(role_id):
            report.error("invalid_role_id", path, "role_id 不能包含空白、斜杠或反斜杠，长度须为 1..64")
            continue
        if not role.display_name or len(role.display_name) > 64:
            report.error("invalid_display_name", f"{path}.display_name", "display_name 长度须为 1..64")
            continue
        if not is_known_gender_value(role.gender):
            report.error(
                "invalid_role_gender",
                f"{path}.gender",
                "gender 只允许 male/female/unknown 或对应的中文别名",
                actual=role.gender,
            )
            continue
        params = _normalize_params(role_id, role.provider_params, script.provider, report)
        roles[role_id] = RoleDefinition(
            display_name=role.display_name,
            provider_params=params,
            gender=normalize_gender(role.gender),
        )
    return roles


def _normalize_chapters(script: RoleScriptV1, report: ValidationReport) -> Tuple[ChapterScript, ...]:
    seen = set()
    chapters = []
    for chapter_pos, chapter in enumerate(script.chapters):
        path = f"$.chapters[{chapter_pos}]"
        if chapter.chapter_index in seen:
            report.error("duplicate_chapter", path, f"章节 {chapter.chapter_index} 重复定义")
            continue
        seen.add(chapter.chapter_index)
        if not chapter.segments:
            report.error("empty_segments", f"{path}.segments", "章节至少需要一个 segment")
            continue
        normalized_segments = []
        for segment_pos, segment in enumerate(chapter.segments):
            segment_path = f"{path}.segments[{segment_pos}]"
            if not segment.text:
                report.error("empty_segment_text", f"{segment_path}.text", "segment text 不能为空")
                continue
            if segment.tone is not None and len(segment.tone) > 200:
                report.error("invalid_tone", f"{segment_path}.tone", "tone 最长 200 字符")
                continue
            if segment.pause_after_ms is not None and not (0 <= segment.pause_after_ms <= 60000):
                report.error(
                    "pause_out_of_range",
                    f"{segment_path}.pause_after_ms",
                    "pause_after_ms 必须在 0 到 60000 之间",
                )
                continue
            normalized_segments.append(segment)
        if normalized_segments:
            chapters.append(ChapterScript(chapter.chapter_index, chapter.title, tuple(normalized_segments)))
    return tuple(sorted(chapters, key=lambda item: item.chapter_index))


def _chapter_range(chapters: Sequence[Tuple[str, str]], chapter_start: Optional[int], chapter_end: Optional[int]):
    count = len(chapters)
    start = 1 if chapter_start is None else chapter_start
    end = count if chapter_end in (None, -1) else chapter_end
    return start, end


def _validate_book_alignment(
    script: RoleScriptV1,
    chapters: Sequence[Tuple[str, str]],
    chapter_start: Optional[int],
    chapter_end: Optional[int],
    allow_text_override: bool,
    allow_title_mismatch: bool,
    allow_fallback: bool,
    fallback_profile: Optional[Dict[str, Any]],
    report: ValidationReport,
) -> None:
    by_index = {
        chapter.chapter_index: (chapter_pos, chapter)
        for chapter_pos, chapter in enumerate(script.chapters)
    }
    start, end = _chapter_range(chapters, chapter_start, chapter_end)
    if start < 1 or end < 1 or start > end or end > len(chapters):
        report.error(
            "invalid_chapter_range",
            "$.chapters",
            "章节范围无效",
            chapter_start=start,
            chapter_end=end,
            chapter_count=len(chapters),
        )
        return

    for index in range(start, end + 1):
        chapter_entry = by_index.get(index)
        if chapter_entry is None:
            report.error("missing_chapter", f"$.chapters[{index}]", f"缺少第 {index} 章剧本")
            continue
        chapter_pos, chapter = chapter_entry
        chapter_path = f"$.chapters[{chapter_pos}]"
        parser_title = chapters[index - 1][0]
        if chapter.title != parser_title:
            if allow_title_mismatch:
                report.warn(
                    "title_mismatch_override",
                    f"{chapter_path}.title",
                    f"标题不匹配，已按 override 跳过：剧本={chapter.title!r}，书籍={parser_title!r}",
                )
            else:
                report.error(
                    "title_mismatch",
                    f"{chapter_path}.title",
                    f"标题不匹配：剧本={chapter.title!r}，书籍={parser_title!r}",
                )
        if not allow_text_override:
            script_text = "".join(segment.text for segment in chapter.segments)
            expected_text = chapters[index - 1][1]
            if normalize_coverage_text(script_text) != normalize_coverage_text(expected_text):
                report.error(
                    "text_coverage_mismatch",
                    f"{chapter_path}.segments",
                    f"第 {index} 章 segment 文本与书籍正文不一致",
                    chapter_index=index,
                )
        else:
            report.warn("text_override", f"{chapter_path}.segments", f"已跳过第 {index} 章文本覆盖率检查")

        for segment_pos, segment in enumerate(chapter.segments):
            if segment.role_id in script.roles:
                continue
            path = f"{chapter_path}.segments[{segment_pos}].role_id"
            if not allow_fallback:
                report.error("missing_role", path, f"角色 {segment.role_id!r} 未定义")
                continue
            fallback_role_id = "narrator" if "narrator" in script.roles else None
            if fallback_role_id is None and fallback_profile is None:
                report.error(
                    "missing_fallback_profile",
                    path,
                    f"角色 {segment.role_id!r} 未定义，且没有 narrator 或全局默认配置可回退",
                )
            else:
                report.warn(
                    "role_fallback",
                    path,
                    f"角色 {segment.role_id!r} 未定义，已回退到 {'narrator' if fallback_role_id else '全局默认配置'}",
                    role_id=segment.role_id,
                )


def validate_role_script(
    script: RoleScriptV1,
    *,
    expected_book_sha256: Optional[str] = None,
    chapters: Optional[Sequence[Tuple[str, str]]] = None,
    chapter_start: Optional[int] = None,
    chapter_end: Optional[int] = None,
    allow_text_override: bool = False,
    allow_title_mismatch: bool = False,
    allow_fallback: bool = False,
    fallback_profile: Optional[Dict[str, Any]] = None,
) -> ValidationResult:
    """校验并返回规范化后的剧本。章节对齐只在提供 chapters 时执行。"""
    report = ValidationReport(schema_version=script.schema_version)
    if script.schema_version != 1:
        report.error("unsupported_schema_version", "$.schema_version", "仅支持 schema_version=1")
    if script.provider not in SUPPORTED_PROVIDERS:
        report.error("unsupported_provider", "$.provider", f"不支持的 provider：{script.provider}")
    if not _SHA256_PATTERN.fullmatch(script.book_sha256 or ""):
        report.error("invalid_book_sha256", "$.book_sha256", "book_sha256 必须是 64 位小写十六进制 SHA-256")
    if not isinstance(script.default_pause_after_ms, int) or isinstance(script.default_pause_after_ms, bool):
        report.error("invalid_default_pause", "$.default_pause_after_ms", "default_pause_after_ms 必须是整数")
    elif not 0 <= script.default_pause_after_ms <= 60000:
        report.error("pause_out_of_range", "$.default_pause_after_ms", "default_pause_after_ms 必须在 0 到 60000 之间")
    if expected_book_sha256 is not None and script.book_sha256 != expected_book_sha256:
        report.error(
            "book_sha256_mismatch",
            "$.book_sha256",
            "剧本绑定的书指纹与输入文件不一致",
            expected=expected_book_sha256,
            actual=script.book_sha256,
        )

    roles = _normalize_roles(script, report)
    normalized_chapters = _normalize_chapters(script, report)
    normalized = RoleScriptV1(
        schema_version=script.schema_version,
        provider=script.provider,
        book_sha256=script.book_sha256,
        default_pause_after_ms=script.default_pause_after_ms,
        roles=roles,
        chapters=normalized_chapters,
    )

    if chapters is not None:
        _validate_book_alignment(
            normalized,
            chapters=chapters,
            chapter_start=chapter_start,
            chapter_end=chapter_end,
            allow_text_override=allow_text_override,
            allow_title_mismatch=allow_title_mismatch,
            allow_fallback=allow_fallback,
            fallback_profile=fallback_profile,
            report=report,
        )

    return ValidationResult(normalized if not report.errors else None, report)
