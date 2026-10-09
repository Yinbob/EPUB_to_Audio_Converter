"""独立获取 TTS 官方英文音色并写入本地音色目录。

该模块只由根目录的 ``fetch_english_voices.py`` 显式调用，不会接入 WebUI 或
普通转换路径。所有来源都使用官方页面/官方 API；下载或解析失败时返回错误，
由调用方决定是否继续，模块本身不会用空结果覆盖已有目录。
"""
from __future__ import annotations

import argparse
import html as html_lib
import json
import logging
import re
import warnings
from dataclasses import dataclass, replace
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import urljoin, urlparse

import requests

# BeautifulSoup 把 soupsieve 作为可选 CSS 选择器依赖；本脚本只解析 HTML 表格，
# 不需要 CSS 选择器，缺少 soupsieve 时不应向用户打印无关警告。
with warnings.catch_warnings():
    warnings.filterwarnings("ignore", message="The soupsieve package is not installed")
    from bs4 import BeautifulSoup

from audiobook_generator.tts_providers.voice_catalog import (
    VoiceCatalogEntry,
    builtin_voice_entries,
    get_voice_catalog_path,
    import_voice_catalog_document,
    load_voice_catalog,
    normalize_catalog_provider,
    save_user_voice_entries,
)
from audiobook_generator.utils.minimax_config import get_minimax_credentials

logger = logging.getLogger(__name__)

MIMO_DOCUMENT_URL = "https://mimo.mi.com/docs/models/mimo-v2-5-tts"
MIMO_ROUTE_SUFFIX = "quick-start/usage-guide/audio/speech-synthesis-v2.5"
MINIMAX_GET_VOICE_URL = "https://api.minimaxi.com/v1/get_voice"
DEFAULT_TIMEOUT_SECONDS = 20.0
_DOC_REQUEST_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/javascript,text/javascript,*/*;q=0.8",
    "User-Agent": "EPUB-to-Audio-VoiceCatalogFetcher/1.0",
}
_MINIMAX_API_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "User-Agent": "EPUB-to-Audio-VoiceCatalogFetcher/1.0",
}


class VoiceFetchError(RuntimeError):
    """官方音色来源下载或解析失败。"""


@dataclass(frozen=True)
class ProviderFetchResult:
    """单个 Provider 的英文音色获取结果。"""

    provider: str
    source_url: str
    entries: Tuple[VoiceCatalogEntry, ...] = ()
    warnings: Tuple[str, ...] = ()
    errors: Tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return bool(self.entries) and not self.errors

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "source_url": self.source_url,
            "ok": self.ok,
            "entries": [entry.to_dict() for entry in self.entries],
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


def _provider_label(provider: str) -> str:
    return {"openai": "MiMo", "minimax": "MiniMax"}.get(provider, provider)


def _new_session() -> requests.Session:
    return requests.Session()


def _request(
    session: Any,
    method: str,
    url: str,
    *,
    timeout: float,
    headers: Optional[Mapping[str, str]] = None,
    **kwargs: Any,
) -> Any:
    """执行 HTTP 请求，并把底层异常统一成可展示的错误。"""
    try:
        if method.upper() == "GET":
            response = session.get(url, headers=headers, timeout=timeout, **kwargs)
        else:
            response = session.post(url, headers=headers, timeout=timeout, **kwargs)
    except requests.RequestException as exc:
        host = urlparse(url).netloc or url
        raise VoiceFetchError(f"请求 {host} 失败：{exc}") from exc

    status_code = int(getattr(response, "status_code", 0) or 0)
    if not 200 <= status_code < 300:
        host = urlparse(url).netloc or url
        raise VoiceFetchError(f"{host} 返回 HTTP {status_code}")
    return response


def _get_text(session: Any, url: str, *, timeout: float) -> str:
    response = _request(
        session,
        "GET",
        url,
        timeout=timeout,
        headers=_DOC_REQUEST_HEADERS,
    )
    text = getattr(response, "text", "")
    if not isinstance(text, str) or not text.strip():
        raise VoiceFetchError(f"{urlparse(url).netloc or url} 返回空内容")
    return text


def _post_json(
    session: Any,
    url: str,
    *,
    timeout: float,
    headers: Mapping[str, str],
    payload: Mapping[str, Any],
) -> Any:
    return _request(
        session,
        "POST",
        url,
        timeout=timeout,
        headers=headers,
        json=dict(payload),
    )


def _decode_js_escaped_markup(text: str) -> str:
    """还原文档 chunk 中常见的 JS 字符串转义，保留其中的 HTML 表格。"""
    return (
        text.replace("\\r\\n", "\n")
        .replace("\\n", "\n")
        .replace("\\r", "\r")
        .replace("\\t", "\t")
        .replace('\\"', '"')
        .replace("\\/", "/")
    )


def _table_markup_to_pipe_text(table: Any) -> str:
    rows: List[str] = []
    for row in table.find_all("tr"):
        cells = [
            cell.get_text(" ", strip=True).replace("\n", " ").strip()
            for cell in row.find_all(["th", "td"])
        ]
        if cells:
            rows.append(" | ".join(cells))
    return "\n".join(rows)


def _extract_voice_table_markup(text: str) -> Tuple[str, ...]:
    """从 HTML/JS 文档中提取带有 Voice ID 的音色表。"""
    normalized = _decode_js_escaped_markup(text)
    try:
        soup = BeautifulSoup(normalized, "html.parser")
    except Exception as exc:
        raise VoiceFetchError(f"无法解析官方文档 HTML：{exc}") from exc

    tables: List[str] = []
    for table in soup.find_all("table"):
        header_cells = [
            cell.get_text(" ", strip=True)
            for cell in table.find_all("th")
        ]
        header_text = " ".join(header_cells).lower()
        header_compact = re.sub(r"[\s_\-/]+", "", header_text)
        if "voiceid" not in header_compact and "音色id" not in header_compact:
            continue
        if "language" not in header_text and "语言" not in header_text:
            continue
        markup = _table_markup_to_pipe_text(table)
        if markup:
            tables.append(markup)
    return tuple(tables)


def parse_mimo_voice_document(text: str, *, provider: str = "openai") -> ProviderFetchResult:
    """解析 MiMo 官方语音文档，只保留语言明确为英文的音色。"""
    provider_id = normalize_catalog_provider(provider) or "openai"
    source_url = MIMO_DOCUMENT_URL
    tables = _extract_voice_table_markup(text)
    if not tables:
        return ProviderFetchResult(
            provider=provider_id,
            source_url=source_url,
            errors=("未从 MiMo 官方文档中找到包含 Voice ID / Language 的音色表；文档结构可能已更新。",),
        )

    merged: Dict[Tuple[str, str], VoiceCatalogEntry] = {}
    warnings: List[str] = []
    table_errors: List[str] = []
    for table in tables:
        parsed = import_voice_catalog_document(text=table, provider=provider_id)
        warnings.extend(parsed.warnings)
        if parsed.errors:
            table_errors.extend(parsed.errors)
        for entry in parsed.entries:
            if entry.voice_id == "mimo_default":
                warnings.append("已跳过集群相关默认音色 mimo_default（中国集群与海外集群默认音色不同）。")
                continue
            if entry.language != "en":
                continue
            merged[(entry.provider, entry.voice_id)] = entry

    entries = tuple(merged.values())
    if not entries:
        details = "；".join(dict.fromkeys(table_errors)) or "没有解析到 Language=English 的音色。"
        return ProviderFetchResult(
            provider=provider_id,
            source_url=source_url,
            warnings=tuple(dict.fromkeys(warnings)),
            errors=(f"MiMo 官方文档未返回可用英文音色：{details}",),
        )
    if table_errors:
        warnings.extend(f"部分音色表解析失败：{error}" for error in table_errors)
    return ProviderFetchResult(
        provider=provider_id,
        source_url=source_url,
        entries=entries,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _extract_main_js_url(shell_html: str, source_url: str) -> str:
    patterns = (
        r'<link[^>]+href=["\']([^"\']+\.chunk\.js(?:\?[^"\']*)?)["\']',
        r'<script[^>]+src=["\']([^"\']+\.chunk\.js(?:\?[^"\']*)?)["\']',
    )
    candidates = [
        html_lib.unescape(match.group(1))
        for pattern in patterns
        for match in re.finditer(pattern, shell_html, flags=re.IGNORECASE)
    ]
    if not candidates:
        raise VoiceFetchError("MiMo 文档页中未找到主脚本 URL；页面结构可能已更新。")
    # 页面可能同时引用多个异步 chunk；优先挑选 basename 为 main*.chunk.js 的入口。
    main_candidate = next(
        (
            candidate
            for candidate in candidates
            if re.search(r"(^|/)main[^/]*\.chunk\.js$", urlparse(candidate).path, re.IGNORECASE)
        ),
        None,
    )
    return urljoin(source_url, main_candidate or candidates[0])


def _extract_chunk_hashes(shell_html: str) -> Dict[int, str]:
    return {
        int(chunk_id): chunk_hash
        for chunk_id, chunk_hash in re.findall(r'(\d+):"([0-9a-f]{8,})"', shell_html)
    }


def discover_mimo_document_chunk_url(
    session: Any,
    *,
    source_url: str = MIMO_DOCUMENT_URL,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    shell_html: Optional[str] = None,
) -> str:
    """从 MiMo 文档页动态解析当前版本的语音文档 chunk URL。"""
    shell = shell_html if shell_html is not None else _get_text(session, source_url, timeout=timeout)
    main_url = _extract_main_js_url(shell, source_url)
    main_js = _get_text(session, main_url, timeout=timeout)
    route_pattern = re.compile(
        r'path:"(?P<locale>[A-Za-z]{2}-[A-Za-z]{2})/'
        + re.escape(MIMO_ROUTE_SUFFIX)
        + r'",importFn:\(\)=>Promise\.all\(\[(?P<chunks>[^\]]+)\]\)'
    )
    route_matches = list(route_pattern.finditer(main_js))
    if not route_matches:
        raise VoiceFetchError("MiMo 主脚本中未找到语音合成文档路由；页面结构可能已更新。")

    selected = None
    for locale in ("en-US", "zh-CN"):
        selected = next(
            (match for match in route_matches if match.group("locale").lower() == locale.lower()),
            None,
        )
        if selected is not None:
            break
    if selected is None:
        selected = route_matches[0]

    chunk_ids = [int(value) for value in re.findall(r"\.e\((\d+)\)", selected.group("chunks"))]
    if not chunk_ids:
        raise VoiceFetchError("MiMo 语音文档路由没有关联到可下载的 chunk。")
    chunk_id = chunk_ids[-1]
    chunk_hashes = _extract_chunk_hashes(shell)
    chunk_hash = chunk_hashes.get(chunk_id)
    if not chunk_hash:
        raise VoiceFetchError(f"MiMo 文档页缺少 chunk {chunk_id} 的版本哈希。")
    return urljoin(main_url, f"/static/{chunk_id}.{chunk_hash}.chunk.js")


def _looks_like_voice_table(text: str) -> bool:
    try:
        return bool(_extract_voice_table_markup(text))
    except VoiceFetchError:
        return False


def fetch_mimo_english_voices(
    session: Any,
    *,
    source_url: str = MIMO_DOCUMENT_URL,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> ProviderFetchResult:
    """下载 MiMo 官方文档并返回英文音色。"""
    actual_url = source_url
    try:
        document = _get_text(session, source_url, timeout=timeout)
        if not _looks_like_voice_table(document):
            actual_url = discover_mimo_document_chunk_url(
                session,
                source_url=source_url,
                timeout=timeout,
                shell_html=document,
            )
            document = _get_text(session, actual_url, timeout=timeout)
        result = parse_mimo_voice_document(document)
        return replace(result, source_url=actual_url)
    except VoiceFetchError as exc:
        return ProviderFetchResult(
            provider="openai",
            source_url=actual_url,
            errors=(str(exc),),
        )
    except Exception as exc:
        logger.exception("解析 MiMo 官方音色文档时发生意外错误")
        return ProviderFetchResult(
            provider="openai",
            source_url=actual_url,
            errors=(f"解析 MiMo 官方音色文档失败：{exc}",),
        )


def _looks_like_voice_record(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    keys = {re.sub(r"[\s_\-/]+", "", str(key).lower()) for key in value}
    return bool(keys & {"voiceid", "voiceidentifier", "shortname", "voice"}) and "baseresp" not in keys


def _extract_voice_records(payload: Any, *, depth: int = 0) -> List[Mapping[str, Any]]:
    if depth > 6:
        return []
    if isinstance(payload, list):
        dict_items = [item for item in payload if isinstance(item, Mapping)]
        if any(_looks_like_voice_record(item) for item in dict_items):
            return dict_items
        for item in payload:
            found = _extract_voice_records(item, depth=depth + 1)
            if found:
                return found
        return []
    if not isinstance(payload, Mapping):
        return []
    if _looks_like_voice_record(payload):
        return [payload]
    for key in ("voice_list", "voices", "items", "data", "result"):
        if key in payload:
            found = _extract_voice_records(payload[key], depth=depth + 1)
            if found:
                return found
    for value in payload.values():
        found = _extract_voice_records(value, depth=depth + 1)
        if found:
            return found
    return []


def _known_minimax_english_ids() -> frozenset[str]:
    return frozenset(
        entry.voice_id
        for entry in builtin_voice_entries()
        if entry.provider == "minimax" and entry.language == "en"
    )


def _is_confirmed_minimax_english(entry: VoiceCatalogEntry) -> bool:
    if entry.language == "en":
        return True
    if entry.voice_id.startswith("English_"):
        return True
    if entry.voice_id in _known_minimax_english_ids():
        return True
    haystack = f"{entry.voice_id} {entry.display_name} {entry.description}".lower()
    return bool(re.search(r"\benglish\b|英文|英语", haystack))


def parse_minimax_voice_payload(payload: Any, *, provider: str = "minimax") -> ProviderFetchResult:
    """把 MiniMax get_voice 响应转换为本地目录条目，只保留可确认的英文音色。"""
    provider_id = normalize_catalog_provider(provider) or "minimax"
    if not isinstance(payload, Mapping):
        return ProviderFetchResult(
            provider=provider_id,
            source_url=MINIMAX_GET_VOICE_URL,
            errors=("MiniMax get_voice 响应不是 JSON 对象。",),
        )

    base_resp = payload.get("base_resp")
    if isinstance(base_resp, Mapping):
        status_code = base_resp.get("status_code")
        if status_code not in (None, 0, "0"):
            message = str(base_resp.get("status_msg") or "未知错误")
            return ProviderFetchResult(
                provider=provider_id,
                source_url=MINIMAX_GET_VOICE_URL,
                errors=(f"MiniMax API 返回错误 {status_code}：{message}",),
            )

    records = _extract_voice_records(payload)
    if not records:
        return ProviderFetchResult(
            provider=provider_id,
            source_url=MINIMAX_GET_VOICE_URL,
            errors=("MiniMax get_voice 响应中没有找到 voice_list / voices 音色列表。",),
        )

    serialized = json.dumps({"voices": records}, ensure_ascii=False)
    parsed = import_voice_catalog_document(text=serialized, provider=provider_id)
    if parsed.errors and not parsed.entries:
        return ProviderFetchResult(
            provider=provider_id,
            source_url=MINIMAX_GET_VOICE_URL,
            warnings=parsed.warnings,
            errors=parsed.errors,
        )

    english_entries: List[VoiceCatalogEntry] = []
    skipped = 0
    for entry in parsed.entries:
        if _is_confirmed_minimax_english(entry):
            if entry.language != "en":
                entry = replace(entry, language="en")
            english_entries.append(entry)
        else:
            skipped += 1

    warnings = list(parsed.warnings)
    if skipped:
        warnings.append(
            f"已跳过 {skipped} 个无法确认语言的 MiniMax 音色；如确认属于英文，可在 WebUI 手动导入。"
        )
    if not english_entries:
        return ProviderFetchResult(
            provider=provider_id,
            source_url=MINIMAX_GET_VOICE_URL,
            warnings=tuple(warnings),
            errors=("MiniMax get_voice 已返回音色，但没有可确认的英文音色。",),
        )
    return ProviderFetchResult(
        provider=provider_id,
        source_url=MINIMAX_GET_VOICE_URL,
        entries=tuple(english_entries),
        warnings=tuple(warnings),
    )


def fetch_minimax_english_voices(
    session: Any,
    *,
    api_url: str = MINIMAX_GET_VOICE_URL,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> ProviderFetchResult:
    """调用 MiniMax 官方 get_voice 接口并返回英文音色。"""
    try:
        api_key = get_minimax_credentials()
    except RuntimeError as exc:
        return ProviderFetchResult(
            provider="minimax",
            source_url=api_url,
            errors=(f"未找到 MiniMax 凭证，无法获取官方音色列表：{exc}",),
        )
    except Exception as exc:
        logger.exception("读取 MiniMax 凭证失败")
        return ProviderFetchResult(
            provider="minimax",
            source_url=api_url,
            errors=(f"读取 MiniMax 凭证失败：{exc}",),
        )

    try:
        response = _post_json(
            session,
            api_url,
            timeout=timeout,
            headers={**_MINIMAX_API_HEADERS, "Authorization": f"Bearer {api_key}"},
            payload={"voice_type": "all"},
        )
        payload = response.json()
    except VoiceFetchError as exc:
        return ProviderFetchResult(provider="minimax", source_url=api_url, errors=(str(exc),))
    except (ValueError, json.JSONDecodeError) as exc:
        return ProviderFetchResult(
            provider="minimax",
            source_url=api_url,
            errors=(f"MiniMax get_voice 响应不是有效 JSON：{exc}",),
        )

    result = parse_minimax_voice_payload(payload)
    return replace(result, source_url=api_url)


def fetch_english_voices(
    provider: str = "all",
    *,
    source_url: Optional[str] = None,
    minimax_api_url: str = MINIMAX_GET_VOICE_URL,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    session: Any = None,
) -> Tuple[ProviderFetchResult, ...]:
    """按 Provider 获取英文音色；默认同时尝试 MiMo 和 MiniMax。"""
    provider_id = str(provider or "all").strip().lower()
    if provider_id in {"mimo", "openai"}:
        selected = ("openai",)
    elif provider_id == "minimax":
        selected = ("minimax",)
    elif provider_id == "all":
        selected = ("openai", "minimax")
    else:
        raise ValueError(f"不支持的 provider：{provider}")

    own_session = session is None
    active_session = session if session is not None else _new_session()
    try:
        results: List[ProviderFetchResult] = []
        for item in selected:
            if item == "openai":
                results.append(
                    fetch_mimo_english_voices(
                        active_session,
                        source_url=source_url or MIMO_DOCUMENT_URL,
                        timeout=timeout,
                    )
                )
            else:
                results.append(
                    fetch_minimax_english_voices(
                        active_session,
                        api_url=minimax_api_url,
                        timeout=timeout,
                    )
                )
        return tuple(results)
    finally:
        if own_session and hasattr(active_session, "close"):
            active_session.close()


def save_fetched_entries(
    results: Sequence[ProviderFetchResult],
    *,
    replace_existing: bool = False,
) -> int:
    """保存成功的英文音色；为空、失败或异常时绝不写入。"""
    successful = [result for result in results if result.entries and not result.errors]
    entries = [entry for result in successful for entry in result.entries]
    if not entries:
        return 0

    if not replace_existing:
        save_user_voice_entries(entries)
        return len(entries)

    providers = {result.provider for result in successful}
    preserved = [
        entry
        for entry in load_voice_catalog(include_builtin=False)
        if not (entry.provider in providers and entry.language == "en")
    ]
    save_user_voice_entries((*preserved, *entries), replace_existing=True)
    return len(entries)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="从官方来源获取 MiMo / MiniMax 英文音色，并写入 .tts_voice_catalog.json。",
    )
    parser.add_argument(
        "--provider",
        choices=("mimo", "minimax", "all"),
        default="all",
        help="要获取的 Provider（默认 all）。",
    )
    parser.add_argument(
        "--source-url",
        default=None,
        help="MiMo 文档页或直接音色 chunk URL；默认使用官方 v2.5 文档。",
    )
    parser.add_argument(
        "--minimax-api-url",
        default=MINIMAX_GET_VOICE_URL,
        help=f"MiniMax get_voice 接口地址（默认 {MINIMAX_GET_VOICE_URL}）。",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"单次 HTTP 请求超时秒数（默认 {DEFAULT_TIMEOUT_SECONDS:g}）。",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只显示获取结果，不写入用户音色目录。",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="仅替换本次成功 Provider 的英文条目，保留其他 Provider 和非英文条目。",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="以 JSON 输出结果，便于脚本调用。",
    )
    return parser


def _print_text_results(results: Sequence[ProviderFetchResult], *, dry_run: bool, saved_count: int) -> None:
    print(f"用户音色目录：{get_voice_catalog_path()}")
    for result in results:
        label = _provider_label(result.provider)
        if result.errors:
            print(f"\n❌ {label}：获取失败")
            for error in result.errors:
                print(f"  - {error}")
        else:
            print(f"\n✅ {label}：{len(result.entries)} 个英文音色")
            print(f"  来源：{result.source_url}")
            for entry in result.entries:
                gender = f" / {entry.gender}" if entry.gender and entry.gender != "neutral" else ""
                print(f"  - {entry.voice_id}  {entry.display_name}{gender}")
        for warning in result.warnings:
            print(f"  ⚠️ {warning}")
    if dry_run:
        print("\n未写入用户音色目录（--dry-run）。")
    elif saved_count:
        print(f"\n已保存 {saved_count} 个英文音色到用户音色目录。")
    else:
        print("\n没有成功的英文音色结果，未修改用户音色目录。")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        results = fetch_english_voices(
            args.provider,
            source_url=args.source_url,
            minimax_api_url=args.minimax_api_url,
            timeout=args.timeout,
        )
    except ValueError as exc:
        parser.error(str(exc))
        return 2

    saved_count = 0
    if not args.dry_run:
        try:
            saved_count = save_fetched_entries(results, replace_existing=args.replace)
        except Exception as exc:
            logger.exception("保存自动获取的英文音色失败")
            print(f"❌ 保存用户音色目录失败：{exc}")
            return 2

    if args.json_output:
        print(
            json.dumps(
                {
                    "ok": all(result.ok for result in results),
                    "dry_run": bool(args.dry_run),
                    "saved_count": saved_count,
                    "catalog_path": str(get_voice_catalog_path()),
                    "results": [result.to_dict() for result in results],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        _print_text_results(results, dry_run=args.dry_run, saved_count=saved_count)

    return 0 if results and all(result.ok for result in results) else 1


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "MINIMAX_GET_VOICE_URL",
    "MIMO_DOCUMENT_URL",
    "ProviderFetchResult",
    "VoiceFetchError",
    "build_arg_parser",
    "discover_mimo_document_chunk_url",
    "fetch_english_voices",
    "fetch_minimax_english_voices",
    "fetch_mimo_english_voices",
    "main",
    "parse_minimax_voice_payload",
    "parse_mimo_voice_document",
    "save_fetched_entries",
]
