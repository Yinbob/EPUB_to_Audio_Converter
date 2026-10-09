"""RoleScriptV1 JSON 读取与结构解析。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .errors import ValidationReport
from .models import ChapterScript, RoleDefinition, RoleScriptV1, SegmentScript
from .normalization import is_known_gender_value, normalize_gender

_TOP_LEVEL_FIELDS = {
    "schema_version",
    "provider",
    "book_sha256",
    "default_pause_after_ms",
    "roles",
    "chapters",
}
_ROLE_FIELDS = {"display_name", "provider_params", "gender"}
_CHAPTER_FIELDS = {"chapter_index", "title", "segments"}
_SEGMENT_FIELDS = {"role_id", "text", "tone", "pause_after_ms"}


def _format_json_path(path: Tuple[Any, ...]) -> str:
    rendered = "$"
    for part in path:
        if isinstance(part, int):
            rendered += f"[{part}]"
        else:
            rendered += f".{part}"
    return rendered


class _TrackedDict(dict):
    """保留同一对象内重复 key 的信息，解析完成后再还原精确路径。"""

    def __init__(self, pairs=()):
        super().__init__()
        self.duplicate_keys = []
        for key, value in pairs:
            if key in self:
                self.duplicate_keys.append(key)
            else:
                super().__setitem__(key, value)


class DuplicateKeyError(ValueError):
    def __init__(self, key: str, path: Tuple[Any, ...]):
        self.key = key
        self.path = path + (key,)
        rendered = _format_json_path(self.path)
        super().__init__(f"重复键: {rendered}")


def _object_pairs_hook(pairs):
    return _TrackedDict(pairs)


def _find_duplicate(node: Any, path: Tuple[Any, ...] = ()) -> Optional[Tuple[str, Tuple[Any, ...]]]:
    """按 JSON 文档顺序查找第一个重复 key，返回 (key, 父路径)。"""
    if isinstance(node, _TrackedDict):
        if node.duplicate_keys:
            return node.duplicate_keys[0], path
        for key, value in node.items():
            found = _find_duplicate(value, path + (key,))
            if found is not None:
                return found
    elif isinstance(node, list):
        for pos, value in enumerate(node):
            found = _find_duplicate(value, path + (pos,))
            if found is not None:
                return found
    return None


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _unknown_fields(value: Dict[str, Any], allowed: set[str], path: str, report: ValidationReport) -> None:
    for key in value:
        if key not in allowed:
            report.error("unknown_field", f"{path}.{key}", f"未知字段：{key}")


def parse_role_script(raw: Any, report: Optional[ValidationReport] = None) -> Optional[RoleScriptV1]:
    """把已反序列化的 JSON 对象解析为领域模型，同时收集结构错误。"""
    report = report or ValidationReport()
    if not isinstance(raw, dict):
        report.error("invalid_root", "$", "剧本根节点必须是 JSON 对象")
        return None
    if raw.get("schema_version") == 2:
        from .v2_io import parse_role_script_v2

        return parse_role_script_v2(raw, report)

    _unknown_fields(raw, _TOP_LEVEL_FIELDS, "$", report)

    for required in ("schema_version", "provider", "book_sha256", "default_pause_after_ms", "roles", "chapters"):
        if required not in raw:
            report.error("missing_field", f"$.{required}", f"缺少必填字段：{required}")

    schema_version = raw.get("schema_version")
    if not _is_int(schema_version):
        report.error("invalid_type", "$.schema_version", "schema_version 必须是整数")
        schema_version_value = None
    else:
        schema_version_value = schema_version
        report.schema_version = schema_version
        if schema_version != 1:
            report.error("unsupported_schema_version", "$.schema_version", "仅支持 schema_version=1", actual=schema_version)

    provider = raw.get("provider")
    if not isinstance(provider, str):
        report.error("invalid_type", "$.provider", "provider 必须是字符串")

    book_sha256 = raw.get("book_sha256")
    if not isinstance(book_sha256, str):
        report.error("invalid_type", "$.book_sha256", "book_sha256 必须是字符串")

    default_pause = raw.get("default_pause_after_ms")
    if not _is_int(default_pause):
        report.error("invalid_type", "$.default_pause_after_ms", "default_pause_after_ms 必须是整数")

    roles: Dict[str, RoleDefinition] = {}
    raw_roles = raw.get("roles")
    if not isinstance(raw_roles, dict):
        report.error("invalid_type", "$.roles", "roles 必须是对象")
    else:
        if not raw_roles:
            report.error("empty_roles", "$.roles", "roles 不能为空")
        for role_id, role_raw in raw_roles.items():
            role_path = f"$.roles.{role_id}"
            if not isinstance(role_id, str):
                report.error("invalid_role_id", role_path, "role_id 必须是字符串")
                continue
            if not isinstance(role_raw, dict):
                report.error("invalid_role", role_path, "角色定义必须是对象")
                continue
            _unknown_fields(role_raw, _ROLE_FIELDS, role_path, report)
            display_name = role_raw.get("display_name")
            if not isinstance(display_name, str) or not display_name.strip():
                report.error("invalid_display_name", f"{role_path}.display_name", "display_name 必须是非空字符串")
            raw_gender = role_raw.get("gender")
            gender_valid = is_known_gender_value(raw_gender)
            if not gender_valid:
                report.error(
                    "invalid_role_gender",
                    f"{role_path}.gender",
                    "gender 只允许 male/female/unknown 或对应的中文别名",
                    actual=raw_gender,
                )
            params = role_raw.get("provider_params")
            if not isinstance(params, dict):
                report.error("invalid_provider_params", f"{role_path}.provider_params", "provider_params 必须是对象")
                params = {}
            else:
                for key, value in params.items():
                    if not isinstance(key, str):
                        report.error("invalid_provider_param", f"{role_path}.provider_params", "参数名必须是字符串")
                    elif not isinstance(value, (str, int, float)) or isinstance(value, bool):
                        report.error(
                            "invalid_provider_param_type",
                            f"{role_path}.provider_params.{key}",
                            "参数值必须是字符串或数字",
                        )
            if (
                isinstance(display_name, str)
                and display_name.strip()
                and gender_valid
                and isinstance(params, dict)
            ):
                roles[role_id] = RoleDefinition(
                    display_name=display_name.strip(),
                    provider_params=dict(params),
                    gender=normalize_gender(raw_gender),
                )

    chapters = []
    raw_chapters = raw.get("chapters")
    if not isinstance(raw_chapters, list):
        report.error("invalid_type", "$.chapters", "chapters 必须是数组")
    else:
        if not raw_chapters:
            report.error("empty_chapters", "$.chapters", "chapters 不能为空")
        for chapter_pos, chapter_raw in enumerate(raw_chapters):
            chapter_path = f"$.chapters[{chapter_pos}]"
            if not isinstance(chapter_raw, dict):
                report.error("invalid_chapter", chapter_path, "章节必须是对象")
                continue
            _unknown_fields(chapter_raw, _CHAPTER_FIELDS, chapter_path, report)
            chapter_index = chapter_raw.get("chapter_index")
            title = chapter_raw.get("title")
            segments_raw = chapter_raw.get("segments")
            if not _is_int(chapter_index) or chapter_index < 1:
                report.error("invalid_chapter_index", f"{chapter_path}.chapter_index", "chapter_index 必须是从 1 开始的整数")
            if not isinstance(title, str) or not title:
                report.error("invalid_chapter_title", f"{chapter_path}.title", "title 必须是非空字符串")
            segments = []
            if not isinstance(segments_raw, list):
                report.error("invalid_segments", f"{chapter_path}.segments", "segments 必须是数组")
            else:
                if not segments_raw:
                    report.error("empty_segments", f"{chapter_path}.segments", "章节至少需要一个 segment")
                for segment_pos, segment_raw in enumerate(segments_raw):
                    segment_path = f"{chapter_path}.segments[{segment_pos}]"
                    if not isinstance(segment_raw, dict):
                        report.error("invalid_segment", segment_path, "segment 必须是对象")
                        continue
                    _unknown_fields(segment_raw, _SEGMENT_FIELDS, segment_path, report)
                    role_id = segment_raw.get("role_id")
                    text = segment_raw.get("text")
                    tone = segment_raw.get("tone")
                    pause = segment_raw.get("pause_after_ms")
                    if not isinstance(role_id, str) or not role_id:
                        report.error("invalid_segment_role", f"{segment_path}.role_id", "role_id 必须是非空字符串")
                    if not isinstance(text, str) or not text:
                        report.error("empty_segment_text", f"{segment_path}.text", "segment text 必须是非空字符串")
                    if tone is not None and (not isinstance(tone, str) or not tone):
                        report.error("invalid_tone", f"{segment_path}.tone", "tone 必须是非空字符串或省略")
                    if pause is not None and not _is_int(pause):
                        report.error("invalid_pause", f"{segment_path}.pause_after_ms", "pause_after_ms 必须是整数或省略")
                    if (
                        isinstance(role_id, str)
                        and role_id
                        and isinstance(text, str)
                        and text
                        and (tone is None or (isinstance(tone, str) and tone))
                        and (pause is None or _is_int(pause))
                    ):
                        segments.append(
                            SegmentScript(
                                role_id=role_id,
                                text=text,
                                tone=tone,
                                pause_after_ms=pause,
                            )
                        )
            if (
                _is_int(chapter_index)
                and chapter_index >= 1
                and isinstance(title, str)
                and title
                and isinstance(segments_raw, list)
            ):
                chapters.append(
                    ChapterScript(
                        chapter_index=chapter_index,
                        title=title,
                        segments=tuple(segments),
                    )
                )

    if report.errors:
        return None
    return RoleScriptV1(
        schema_version=schema_version_value,
        provider=provider,
        book_sha256=book_sha256,
        default_pause_after_ms=default_pause,
        roles=roles,
        chapters=tuple(chapters),
    )


def load_role_script(path: str | Path, report: Optional[ValidationReport] = None) -> Tuple[Optional[RoleScriptV1], ValidationReport]:
    """读取 JSON；重复键不会被静默覆盖，而是生成稳定错误。"""
    report = report or ValidationReport()
    try:
        raw_text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        report.error("read_error", "$", f"无法读取剧本文件：{exc}")
        return None, report
    try:
        raw = json.loads(raw_text, object_pairs_hook=_object_pairs_hook)
    except json.JSONDecodeError as exc:
        report.error(
            "invalid_json",
            "$",
            f"JSON 语法错误：第 {exc.lineno} 行第 {exc.colno} 列 {exc.msg}",
            line=exc.lineno,
            column=exc.colno,
        )
        return None, report
    duplicate = _find_duplicate(raw)
    if duplicate is not None:
        key, parent_path = duplicate
        exc = DuplicateKeyError(key, parent_path)
        report.error("duplicate_key", _format_json_path(exc.path), str(exc), key=key)
        return None, report
    return parse_role_script(raw, report), report
