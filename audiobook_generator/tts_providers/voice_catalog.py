"""人工音色目录：把官网音色说明转成角色模式可调用的统一数据。

这个模块刻意不导入任何 TTS Provider，避免凭证、网络客户端或可选依赖影响目录读取。
Provider 层只通过公开函数追加自定义音色；角色拆分器通过 ``get_role_voice_pools``
获取按语言和性别过滤后的候选池。
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import unicodedata
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

_PROVIDER_ALIASES = {
    "openai": "openai",
    "mimo": "openai",
    "mi-mo": "openai",
    "小米mimo": "openai",
    "minimax": "minimax",
    "mini-max": "minimax",
}

_LANGUAGE_ALIASES = {
    "en": "en",
    "eng": "en",
    "english": "en",
    "en-us": "en",
    "en-gb": "en",
    "英语": "en",
    "英文": "en",
    "zh": "zh",
    "chi": "zh",
    "chs": "zh",
    "cht": "zh",
    "chinese": "zh",
    "mandarin": "zh",
    "zh-cn": "zh",
    "zh-tw": "zh",
    "中文": "zh",
    "普通话": "zh",
    "国语": "zh",
    "yue": "yue",
    "cantonese": "yue",
    "粤语": "yue",
    "广东话": "yue",
    "ja": "ja",
    "jp": "ja",
    "japanese": "ja",
    "日语": "ja",
    "日文": "ja",
    "ko": "ko",
    "kr": "ko",
    "korean": "ko",
    "韩语": "ko",
    "韩文": "ko",
}

_GENDER_ALIASES = {
    "male": "male",
    "m": "male",
    "man": "male",
    "男": "male",
    "男性": "male",
    "男生": "male",
    "female": "female",
    "f": "female",
    "woman": "female",
    "女": "female",
    "女性": "female",
    "女生": "female",
    "neutral": "neutral",
    "unknown": "neutral",
    "neutralvoice": "neutral",
    "中性": "neutral",
    "未知": "neutral",
}

@dataclass(frozen=True)
class VoiceCatalogEntry:
    """一条可持久化的音色说明。"""

    provider: str
    voice_id: str
    display_name: str
    language: str = ""
    gender: str = "neutral"
    description: str = ""
    verified: bool = False
    source: str = "uploaded"
    recommended: bool = False
    tags: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["tags"] = list(self.tags)
        return payload


_BUILTIN_ENTRIES: Tuple["VoiceCatalogEntry", ...]
_POSITIONAL_FIELDS = (
    "voice_id",
    "display_name",
    "language",
    "gender",
    "description",
)


def _pack(
    provider: str,
    voice_id: str,
    display_name: str,
    language: str,
    gender: str,
    description: str = "",
    *,
    verified: bool = True,
    recommended: bool = False,
    tags: Sequence[str] = (),
) -> "VoiceCatalogEntry":
    return VoiceCatalogEntry(
        provider=provider,
        voice_id=voice_id,
        display_name=display_name or voice_id,
        language=language,
        gender=gender,
        description=description,
        verified=verified,
        source="builtin",
        recommended=recommended,
        tags=tuple(tags),
    )


_BUILTIN_ENTRIES = (
    # MiMo：保留现有角色模式的候选顺序，同时补全语言和性别元数据。
    _pack("openai", "mimo_default", "MiMo 默认", "zh", "neutral", "中文默认音色", recommended=True, tags=("narrator",)),
    _pack("openai", "茉莉", "茉莉", "zh", "female", "自然温和的中文女声"),
    _pack("openai", "冰糖", "冰糖", "zh", "female", "清晰甜润的中文女声"),
    _pack("openai", "苏打", "苏打", "zh", "male", "清朗自然的中文男声"),
    _pack("openai", "白桦", "白桦", "zh", "male", "沉稳的中文男声"),
    _pack("openai", "Chloe", "Chloe", "en", "female", "English female voice"),
    _pack("openai", "Mia", "Mia", "en", "female", "English female voice"),
    _pack("openai", "Dean", "Dean", "en", "male", "English male voice"),
    _pack("openai", "Milo", "Milo", "en", "male", "English male narration voice", recommended=True, tags=("narrator",)),
    # MiniMax：基础中文角色池。
    _pack("minimax", "male-qn-jingying", "精英青年音色", "zh", "male", "稳重清晰的中文男声", recommended=True, tags=("narrator",)),
    _pack("minimax", "female-yujie", "御姐音色", "zh", "female", "成熟的中文女声"),
    _pack("minimax", "female-chengshu", "成熟女性音色", "zh", "female", "成熟自然的中文女声"),
    _pack("minimax", "female-shaonv", "少女音色", "zh", "female", "年轻的中文女声"),
    _pack("minimax", "female-tianmei", "甜美女性音色", "zh", "female", "甜美的中文女声"),
    _pack("minimax", "male-qn-badao", "霸道青年音色", "zh", "male", "低沉有力的中文男声"),
    _pack("minimax", "male-qn-qingse", "青涩青年音色", "zh", "male", "年轻的中文男声"),
    _pack("minimax", "male-qn-daxuesheng", "青年大学生音色", "zh", "male", "青年学生风格的中文男声"),
    # MiniMax：英文音色。前四项与现有英文角色池保持一致，后面是可扩展项。
    _pack("minimax", "English_Trustworthy_Man", "Trustworthy Man", "en", "male", "可靠的英文男声", recommended=True, tags=("narrator",)),
    _pack("minimax", "English_Graceful_Lady", "Graceful Lady", "en", "female", "优雅的英文女声"),
    _pack("minimax", "English_Whispering_girl", "Whispering girl", "en", "female", "轻柔低语的英文女声"),
    _pack("minimax", "English_Diligent_Man", "Diligent Man", "en", "male", "勤奋稳重的英文男声"),
    _pack("minimax", "English_Gentle-voiced_man", "Gentle-voiced man", "en", "male", "温和的英文男声"),
    _pack("minimax", "English_Aussie_Bloke", "Aussie Bloke", "en", "male", "澳大利亚口音英文男声"),
    _pack("minimax", "Charming_Lady", "Charming Lady", "en", "female", "有魅力的英文女声"),
    _pack("minimax", "Sweet_Girl", "Sweet Girl", "en", "female", "甜美的英文女声"),
    _pack("minimax", "Attractive_Girl", "Attractive Girl", "en", "female", "有吸引力的英文女声"),
    _pack("minimax", "Serene_Woman", "Serene Woman", "en", "female", "平静的英文女声"),
    _pack("minimax", "Santa_Claus", "Santa Claus", "en", "male", "Santa Claus English voice"),
    _pack("minimax", "Grinch", "Grinch", "en", "male", "Grinch English voice"),
    _pack("minimax", "Rudolph", "Rudolph", "en", "male", "Rudolph English voice"),
    _pack("minimax", "Arnold", "Arnold", "en", "male", "Arnold English voice"),
    _pack("minimax", "Charming_Santa", "Charming Santa", "en", "male", "English male voice"),
    _pack("minimax", "Cute_Elf", "Cute Elf", "en", "neutral", "English neutral voice"),
)


@dataclass(frozen=True)
class VoiceCatalogImportResult:
    """文档解析结果；preview 阶段不会写盘。"""

    entries: Tuple[VoiceCatalogEntry, ...] = ()
    errors: Tuple[str, ...] = ()
    warnings: Tuple[str, ...] = ()
    source_name: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.entries) and not self.errors

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "source_name": self.source_name,
            "entries": [entry.to_dict() for entry in self.entries],
            "errors": list(self.errors),
            "warnings": list(self.warnings),
        }


def normalize_catalog_provider(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = unicodedata.normalize("NFKC", str(value)).strip().lower()
    compact = re.sub(r"[\s_\-/]+", "", text)
    return _PROVIDER_ALIASES.get(text) or _PROVIDER_ALIASES.get(compact)


def normalize_voice_language(value: Any, *, voice_id: str = "", display_name: str = "", description: str = "") -> str:
    """把中英文、locale 和官网描述归一为角色模式使用的语言键。"""
    explicit = unicodedata.normalize("NFKC", str(value or "")).strip().lower().replace("_", "-")
    explicit_compact = re.sub(r"[\s_\-/]+", "", explicit)
    language = _LANGUAGE_ALIASES.get(explicit) or _LANGUAGE_ALIASES.get(explicit_compact)
    if language:
        return language

    haystack = " ".join((str(value or ""), voice_id, display_name, description)).lower()
    for marker, mapped in (
        ("english", "en"), ("en-us", "en"), ("en-gb", "en"),
        ("mandarin", "zh"), ("chinese", "zh"), ("普通话", "zh"), ("中文", "zh"),
        ("cantonese", "yue"), ("粤语", "yue"), ("日本語", "ja"),
        ("japanese", "ja"), ("한국", "ko"), ("korean", "ko"),
    ):
        if marker in haystack:
            return mapped

    normalized_voice = unicodedata.normalize("NFKC", voice_id or "")
    if re.match(r"(?i)^english[_\s-]", normalized_voice):
        return "en"
    if re.match(r"(?i)^(chinese|mandarin)[_\s-]", normalized_voice):
        return "zh"
    if re.match(r"(?i)^cantonese[_\s-]", normalized_voice):
        return "yue"
    if re.search(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", f"{voice_id} {display_name} {description}"):
        return "zh"
    return "unknown"


def normalize_catalog_gender(value: Any, *, voice_id: str = "", display_name: str = "", description: str = "") -> str:
    explicit = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    explicit_compact = re.sub(r"[\s_\-/]+", "", explicit)
    gender = _GENDER_ALIASES.get(explicit) or _GENDER_ALIASES.get(explicit_compact)
    if gender:
        return gender

    haystack = f"{voice_id} {display_name} {description}".lower()
    if re.search(r"(female|woman|girl|lady|woman|女声|女性|女生|御姐|少女|甜美)", haystack):
        return "female"
    if re.search(r"(male|man|boy|gentleman|男声|男性|男生|青年|大叔|大爷)", haystack):
        return "male"
    return "neutral"


def get_voice_catalog_path() -> Path:
    override = os.environ.get("TTS_VOICE_CATALOG_PATH")
    if override:
        return Path(override).expanduser().resolve()
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / ".tts_voice_catalog.json"


def _entry_from_mapping(
    payload: Mapping[str, Any],
    *,
    provider: Optional[str],
    default_language: str = "",
    source_name: str = "",
    row_number: Optional[int] = None,
) -> Tuple[Optional[VoiceCatalogEntry], List[str]]:
    """把一行官网表/JSON 对象转成目录项。"""
    warnings: List[str] = []
    normalized_payload: Dict[str, Any] = {}
    for key, value in payload.items():
        canonical = _canonical_field(str(key))
        if canonical and canonical not in normalized_payload:
            normalized_payload[canonical] = value

    voice_id = _clean(payload.get("voice_id") if "voice_id" in payload else normalized_payload.get("voice_id"))
    if not voice_id:
        # 允许 JSON 顶层使用 voice_id 之外的常见命名。
        for alias in ("voice_id", "voiceId", "voice", "id", "short_name", "shortName", "name"):
            voice_id = _clean(_mapping_value(payload, alias))
            if voice_id:
                break
    if not voice_id:
        row_text = f"第 {row_number} 行" if row_number else "文档"
        warnings.append(f"{row_text}没有识别到 voice_id，已跳过。")
        return None, warnings

    provider_value = (
        normalize_catalog_provider(payload.get("provider"))
        or normalize_catalog_provider(_mapping_value(payload, "provider_id"))
        or provider
    )
    if not provider_value:
        warnings.append(f"音色 {voice_id!r} 未提供 provider，已跳过；请在导入时选择 MiMo 或 MiniMax。")
        return None, warnings

    display_name = _clean(
        normalized_payload.get("display_name")
        or _mapping_value(payload, "display_name")
        or _mapping_value(payload, "voice_name")
        or _mapping_value(payload, "name")
    ) or voice_id
    language_value = (
        normalized_payload.get("language")
        or _mapping_value(payload, "locale")
        or default_language
        or ""
    )
    description = _clean(
        normalized_payload.get("description")
        or _mapping_value(payload, "description")
        or _mapping_value(payload, "desc")
        or _mapping_value(payload, "备注")
    )
    gender_value = (
        normalized_payload.get("gender")
        or _mapping_value(payload, "gender")
        or ""
    )
    language = normalize_voice_language(
        language_value,
        voice_id=voice_id,
        display_name=display_name,
        description=description,
    )
    gender = normalize_catalog_gender(
        gender_value,
        voice_id=voice_id,
        display_name=display_name,
        description=description,
    )
    tags = ["manual-import"]
    text_haystack = f"{display_name} {description}".lower()
    recommended = any(marker in text_haystack for marker in ("narrator", "narration", "旁白", "推荐"))
    if recommended:
        tags.append("narrator")
    verified_value = _mapping_value(payload, "verified")
    verified = _as_bool(verified_value, default=False)
    return VoiceCatalogEntry(
        provider=provider_value,
        voice_id=voice_id,
        display_name=display_name,
        language=language,
        gender=gender,
        description=description,
        verified=verified,
        source="uploaded",
        recommended=recommended,
        tags=tuple(tags),
    ), warnings


def _mapping_value(payload: Mapping[str, Any], key: str) -> Any:
    if key in payload:
        return payload.get(key)
    canonical = _canonical_field(key)
    for actual_key, value in payload.items():
        if _canonical_field(str(actual_key)) == canonical:
            return value
    return None


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return unicodedata.normalize("NFKC", str(value)).strip().strip('"“”\'')


def _as_bool(value: Any, *, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "是", "已验证", "推荐"}:
        return True
    if text in {"0", "false", "no", "n", "否", "未验证"}:
        return False
    return default


def _canonical_field(key: str) -> Optional[str]:
    compact = re.sub(r"[\s_\-/（）()]+", "", unicodedata.normalize("NFKC", key).lower())
    aliases = {
        "voice_id": {
            "voiceid", "voiceidentifier", "voicecode", "shortname", "id",
            "音色id", "音色标识", "音色代码", "短名称", "voice",
        },
        "display_name": {
            "displayname", "voicename", "name", "label", "名称", "音色名称", "中文名", "展示名",
        },
        "language": {"language", "lang", "locale", "语言", "语种", "地区"},
        "gender": {"gender", "sex", "性别", "音色性别"},
        "description": {"description", "desc", "detail", "备注", "说明", "描述", "特点", "音色特点"},
        "provider": {"provider", "modelprovider", "引擎", "提供商", "服务商"},
        "verified": {"verified", "官方验证", "已验证"},
    }
    for canonical, names in aliases.items():
        if compact in names:
            return canonical
    return None


def _iter_active_lines(text: str) -> Iterable[str]:
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line in {"|", "---"}:
            continue
        yield line


def _split_table_line(line: str) -> Optional[List[str]]:
    stripped = line.strip().strip("|").strip()
    if not stripped:
        return None
    if "|" in line:
        return [cell.strip() for cell in stripped.split("|")]
    if "\t" in line:
        return [cell.strip() for cell in stripped.split("\t")]
    return None


def _parse_text_records(text: str) -> List[Dict[str, str]]:
    records: List[Dict[str, str]] = []
    header_fields: Optional[List[str]] = None
    for line in _iter_active_lines(text):
        cells = _split_table_line(line)
        if not cells:
            continue
        if all(re.fullmatch(r"[-: ]+", cell or "") for cell in cells):
            continue
        if header_fields is None:
            canonical = [_canonical_field(cell) for cell in cells]
            if sum(field is not None for field in canonical) >= 2:
                header_fields = [field or "" for field in canonical]
                continue
            if len(cells) >= 2:
                # 无表头时按官网常见顺序解析。
                records.append(dict(zip(_POSITIONAL_FIELDS, cells)))
                continue
        mapping: Dict[str, str] = {}
        for index, cell in enumerate(cells):
            field = header_fields[index] if header_fields and index < len(header_fields) else None
            if not field and index < len(_POSITIONAL_FIELDS):
                field = _POSITIONAL_FIELDS[index]
            if field:
                mapping[field] = cell
        if mapping:
            records.append(mapping)
    return records


def _parse_loose_voice_lines(text: str) -> List[Dict[str, str]]:
    """兜底解析 ``voice_id | 名称 | en | female | 说明`` 形式的文本。"""
    records: List[Dict[str, str]] = []
    for line in _iter_active_lines(text):
        if line.startswith("#") or line.startswith("```"):
            continue
        parts = [part.strip() for part in re.split(r"\t+|\s*\|+\s*", line) if part.strip()]
        if len(parts) < 2:
            continue
        voice_id = parts[0]
        if len(voice_id) < 2 or len(voice_id) > 120:
            continue
        if not re.search(r"[A-Za-z]", voice_id):
            continue
        mapping = dict(zip(_POSITIONAL_FIELDS, parts))
        records.append(mapping)
    return records


def _html_to_text(text: str) -> str:
    """优先保留表格行，避免 BeautifulSoup get_text 把多列压成一行。"""
    try:
        from bs4 import BeautifulSoup  # type: ignore

        soup = BeautifulSoup(text, "html.parser")
        lines: List[str] = []
        for row in soup.find_all("tr"):
            cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
            if cells:
                lines.append(" | ".join(cells))
        if lines:
            return "\n".join(lines)
        return soup.get_text("\n", strip=True)
    except Exception:
        return re.sub(r"<[^>]+>", " ", text)


def _read_document_text(file_path: Optional[str], pasted_text: str) -> str:
    if pasted_text and pasted_text.strip():
        return pasted_text
    if not file_path:
        return ""
    path = Path(file_path)
    suffix = path.suffix.lower()
    if suffix == ".docx":
        try:
            from docx import Document  # type: ignore

            document = Document(str(path))
            lines = [paragraph.text for paragraph in document.paragraphs]
            for table in document.tables:
                for row in table.rows:
                    lines.append(" | ".join(cell.text.strip() for cell in row.cells))
            return "\n".join(lines)
        except Exception as exc:
            raise ValueError(f"无法读取 DOCX：{exc}") from exc
    if suffix == ".pdf":
        try:
            from PyPDF2 import PdfReader  # type: ignore

            reader = PdfReader(str(path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception:
            try:
                import fitz  # type: ignore

                document = fitz.open(str(path))
                return "\n".join(page.get_text() for page in document)
            except Exception as exc:
                raise ValueError("无法读取 PDF；请安装 pypdf/PyPDF2 或复制文档文字后粘贴。") from exc
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "big5"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"无法按 UTF-8/GB18030 解码文档：{path.name}")
    if suffix in {".html", ".htm"}:
        return _html_to_text(text)
    return text


def _parse_json_payload(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("voices", "voice_list", "items", "data", "result"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    if any(_canonical_field(str(key)) == "voice_id" for key in payload):
        return [payload]
    records: List[Dict[str, Any]] = []
    for voice_id, value in payload.items():
        if isinstance(value, str):
            records.append({"voice_id": str(voice_id), "display_name": value})
        elif isinstance(value, dict):
            record = dict(value)
            record.setdefault("voice_id", str(voice_id))
            records.append(record)
    return records


def _parse_delimited(text: str, delimiter: str) -> List[Dict[str, str]]:
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    rows = [[_clean(cell) for cell in row] for row in reader if any(_clean(cell) for cell in row)]
    if not rows:
        return []
    header = [_canonical_field(cell) for cell in rows[0]]
    recognized = sum(field is not None for field in header)
    records: List[Dict[str, str]] = []
    start = 0
    if recognized >= 2:
        start = 1
    for row in rows[start:]:
        mapping: Dict[str, str] = {}
        for index, cell in enumerate(row):
            field = header[index] if start == 1 and index < len(header) else None
            if not field and index < len(_POSITIONAL_FIELDS):
                field = _POSITIONAL_FIELDS[index]
            if field:
                mapping[field] = cell
        if mapping:
            records.append(mapping)
    return records


def _parse_pasted_delimited_records(text: str) -> List[Dict[str, str]]:
    """识别直接粘贴的 CSV/TSV 表头，避免只支持 Markdown 管道表格。"""
    for delimiter in (",", "\t", ";"):
        first_line = next(_iter_active_lines(text), "")
        if not first_line:
            continue
        try:
            cells = next(csv.reader(io.StringIO(first_line), delimiter=delimiter))
        except (csv.Error, StopIteration):
            continue
        recognized = sum(_canonical_field(cell) is not None for cell in cells)
        if recognized < 2:
            continue
        records = _parse_delimited(text, delimiter)
        if records:
            return records
    return []


def _entries_from_records(
    records: Sequence[Mapping[str, Any]],
    *,
    provider: Optional[str],
    default_language: str,
    source_name: str,
) -> VoiceCatalogImportResult:
    entries: List[VoiceCatalogEntry] = []
    warnings: List[str] = []
    errors: List[str] = []
    seen: Dict[Tuple[str, str], int] = {}
    for index, record in enumerate(records, 1):
        entry, row_warnings = _entry_from_mapping(
            record,
            provider=provider,
            default_language=default_language,
            source_name=source_name,
            row_number=index,
        )
        warnings.extend(row_warnings)
        if entry is None:
            continue
        key = (entry.provider, entry.voice_id)
        if key in seen:
            old_index = seen[key]
            entries[old_index] = entry
            warnings.append(f"重复音色 {entry.voice_id!r}，已保留文档中后面的定义。")
        else:
            seen[key] = len(entries)
            entries.append(entry)
    if not entries and not errors:
        errors.append("没有解析到任何有效音色；请确认文档包含 voice_id/音色 ID 和语言/性别等列。")
    return VoiceCatalogImportResult(
        entries=tuple(entries),
        errors=tuple(errors),
        warnings=tuple(warnings),
        source_name=source_name,
    )


def import_voice_catalog_document(
    file_path: Optional[str] = None,
    *,
    text: str = "",
    provider: Optional[str] = None,
    default_language: str = "",
) -> VoiceCatalogImportResult:
    """解析人工上传或粘贴的官网音色说明，不写入磁盘。"""
    provider_id = normalize_catalog_provider(provider)
    if provider and provider_id is None:
        return VoiceCatalogImportResult(errors=(f"不支持的 provider：{provider}",))
    language = normalize_voice_language(default_language) if default_language else ""
    if language == "unknown":
        language = ""
    try:
        raw = _read_document_text(file_path, text)
    except Exception as exc:
        return VoiceCatalogImportResult(errors=(str(exc),), source_name=Path(file_path).name if file_path else "粘贴内容")
    if not raw or not raw.strip():
        return VoiceCatalogImportResult(errors=("没有可解析的文档内容。",), source_name=Path(file_path).name if file_path else "粘贴内容")

    suffix = Path(file_path).suffix.lower() if file_path else ""
    stripped = raw.lstrip()
    records: List[Mapping[str, Any]] = []
    try:
        if suffix == ".json" or stripped.startswith("{") or stripped.startswith("["):
            records = _parse_json_payload(json.loads(raw))
        elif suffix == ".csv":
            records = _parse_delimited(raw, ",")
        elif suffix == ".tsv":
            records = _parse_delimited(raw, "\t")
        else:
            # 用户往往直接从官网复制 CSV/TSV 表格，粘贴内容没有文件后缀，
            # 因此先依据表头嗅探逗号、制表符和分号，再回退到 Markdown/自由文本。
            records = _parse_pasted_delimited_records(raw)
            if not records:
                records = _parse_text_records(raw)
            if not records:
                records = _parse_loose_voice_lines(raw)
    except Exception as exc:
        return VoiceCatalogImportResult(
            errors=(f"文档解析失败：{exc}",),
            source_name=Path(file_path).name if file_path else "粘贴内容",
        )
    return _entries_from_records(
        records,
        provider=provider_id,
        default_language=language,
        source_name=Path(file_path).name if file_path else "粘贴内容",
    )


def builtin_voice_entries() -> Tuple[VoiceCatalogEntry, ...]:
    return _BUILTIN_ENTRIES


def _load_user_entries() -> List[VoiceCatalogEntry]:
    path = get_voice_catalog_path()
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    raw_entries = payload.get("voices") if isinstance(payload, dict) else payload
    if not isinstance(raw_entries, list):
        return []
    entries: List[VoiceCatalogEntry] = []
    for item in raw_entries:
        if not isinstance(item, dict):
            continue
        provider = normalize_catalog_provider(item.get("provider"))
        voice_id = _clean(item.get("voice_id"))
        if provider is None or not voice_id:
            continue
        entries.append(
            VoiceCatalogEntry(
                provider=provider,
                voice_id=voice_id,
                display_name=_clean(item.get("display_name")) or voice_id,
                language=normalize_voice_language(
                    item.get("language"),
                    voice_id=voice_id,
                    display_name=_clean(item.get("display_name")),
                    description=_clean(item.get("description")),
                ),
                gender=normalize_catalog_gender(
                    item.get("gender"),
                    voice_id=voice_id,
                    display_name=_clean(item.get("display_name")),
                    description=_clean(item.get("description")),
                ),
                description=_clean(item.get("description")),
                verified=bool(item.get("verified", False)),
                source="uploaded",
                recommended=bool(item.get("recommended", False)),
                tags=tuple(str(tag) for tag in item.get("tags", ()) if tag),
            )
        )
    return entries


def load_voice_catalog(*, include_builtin: bool = True) -> Tuple[VoiceCatalogEntry, ...]:
    """返回“人工目录覆盖内置目录”的合并结果。"""
    merged: Dict[Tuple[str, str], VoiceCatalogEntry] = {}
    # 人工项先插入，保证自定义英文音色能进入角色池的前排候选。
    if include_builtin:
        for entry in _load_user_entries():
            merged[(entry.provider, entry.voice_id)] = entry
    else:
        for entry in _load_user_entries():
            merged[(entry.provider, entry.voice_id)] = entry
    if include_builtin:
        for entry in _BUILTIN_ENTRIES:
            merged.setdefault((entry.provider, entry.voice_id), entry)
    return tuple(merged.values())


def list_catalog_entries(
    provider: Optional[str] = None,
    *,
    language: Optional[str] = None,
    gender: Optional[str] = None,
    include_builtin: bool = True,
) -> Tuple[VoiceCatalogEntry, ...]:
    provider_id = normalize_catalog_provider(provider) if provider else None
    language_id = normalize_voice_language(language) if language else None
    gender_id = normalize_catalog_gender(gender) if gender else None
    entries = load_voice_catalog(include_builtin=include_builtin)
    result = []
    for entry in entries:
        if provider_id and entry.provider != provider_id:
            continue
        if language_id and language_id != "unknown" and entry.language != language_id:
            continue
        if gender_id and entry.gender != gender_id:
            continue
        result.append(entry)
    return tuple(result)


def get_voice_entry(provider: str, voice_id: str) -> Optional[VoiceCatalogEntry]:
    provider_id = normalize_catalog_provider(provider)
    normalized_voice = _clean(voice_id)
    if provider_id is None or not normalized_voice:
        return None
    for entry in load_voice_catalog(include_builtin=True):
        if entry.provider == provider_id and entry.voice_id == normalized_voice:
            return entry
    return None


def list_provider_voices(provider: str) -> Tuple[VoiceCatalogEntry, ...]:
    return list_catalog_entries(provider, include_builtin=True)


def get_role_voice_pools(provider: str, language: str = "zh") -> Dict[str, Any]:
    """生成角色拆分器使用的 female/male/narrator 池。"""
    provider_id = normalize_catalog_provider(provider)
    language_id = normalize_voice_language(language)
    if provider_id is None or language_id == "unknown":
        return {}
    entries = list_catalog_entries(provider_id, language=language_id)
    female: List[str] = []
    male: List[str] = []
    neutral: List[str] = []
    narrator = ""
    for entry in entries:
        # 用户目录排在前面；第一个推荐音色作为旁白，避免后续内置项覆盖用户选择。
        if entry.recommended and not narrator:
            narrator = entry.voice_id
        if entry.gender == "female":
            female.append(entry.voice_id)
        elif entry.gender == "male":
            male.append(entry.voice_id)
        else:
            neutral.append(entry.voice_id)
    if not narrator:
        narrator = next((voice for voice in male + female + neutral if voice), "")
    if not female and neutral:
        female = list(neutral)
    if not male and neutral:
        male = list(neutral)
    return {
        "female": tuple(dict.fromkeys(female)),
        "male": tuple(dict.fromkeys(male)),
        "neutral": tuple(dict.fromkeys(neutral)),
        "narrator": narrator,
    }


def save_user_voice_entries(
    entries: Sequence[VoiceCatalogEntry | Mapping[str, Any]],
    *,
    replace_existing: bool = False,
) -> Tuple[VoiceCatalogEntry, ...]:
    """保存人工目录；默认按 provider+voice_id 合并，重复项以后写为准。"""
    normalized: List[VoiceCatalogEntry] = []
    for item in entries:
        if isinstance(item, VoiceCatalogEntry):
            entry = replace(item, source="uploaded")
        elif isinstance(item, Mapping):
            entry, _ = _entry_from_mapping(
                item,
                provider=normalize_catalog_provider(item.get("provider")),
                default_language=_clean(item.get("language")),
            )
        else:
            continue
        if entry is not None:
            normalized.append(entry)

    merged: Dict[Tuple[str, str], VoiceCatalogEntry] = {}
    if not replace_existing:
        for entry in _load_user_entries():
            merged[(entry.provider, entry.voice_id)] = entry
    for entry in normalized:
        merged[(entry.provider, entry.voice_id)] = entry

    path = get_voice_catalog_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": 1, "voices": [entry.to_dict() for entry in merged.values()]}
    temp_path = path.with_name(path.name + f".tmp.{os.getpid()}")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp_path, path)
    return tuple(merged.values())


def clear_user_voice_entries() -> None:
    path = get_voice_catalog_path()
    try:
        path.unlink()
    except FileNotFoundError:
        return


__all__ = [
    "VoiceCatalogEntry",
    "VoiceCatalogImportResult",
    "builtin_voice_entries",
    "clear_user_voice_entries",
    "get_role_voice_pools",
    "get_voice_catalog_path",
    "get_voice_entry",
    "import_voice_catalog_document",
    "list_catalog_entries",
    "list_provider_voices",
    "load_voice_catalog",
    "normalize_catalog_gender",
    "normalize_catalog_provider",
    "normalize_voice_language",
    "save_user_voice_entries",
]
