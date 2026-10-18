"""保守的中英朗读规范化；保留每个输出字符的原文映射。"""
from __future__ import annotations

import re
from .models import ReadingChunk
from .language import resolve_language, split_positions

VERSION = "bilingual-reading-v6"
PLAN_VERSION = "source-preserving-reading-plan-v2"
PRONUNCIATION_REVIEW_VERSION = "polyphone-review-v1"
# 非穷尽人工复核表，不根据字符推断实际读音，也不将出现这些字判为合成缺陷。
_POLYPHONE_REVIEW_CHARS = frozenset("行重长乐还得着藏调薄解差")
_DIGITS = "零一二三四五六七八九"
_QUANTITY_UNITS = ("平方厘米", "平方毫米", "平方米", "平方千米", "立方厘米", "立方米", "摄氏度",
                   "毫秒", "分钟", "小时", "千克", "公斤", "毫克", "毫米", "厘米", "千米", "公里",
                   "毫升", "公升", "万元", "美元", "米", "克", "升", "秒", "元")


def _term_pattern(term):
    # 拉丁词条不命中较长编号／单词内部；中文词组按用户给定的原文精确匹配。
    left = r"(?<![A-Za-z0-9_])" if re.match(r"[A-Za-z0-9_]", term[0]) else ""
    right = r"(?![A-Za-z0-9_])" if re.match(r"[A-Za-z0-9_]", term[-1]) else ""
    return left + re.escape(term) + right


def validate_reading_dictionary(value):
    """词典只给出实际朗读文本，不接受控制语法或会级联的替换。"""
    import unicodedata
    if not isinstance(value, dict) or len(value) > 256:
        raise ValueError("朗读词典必须是至多 256 项的原文→读法对象")
    result = {}
    for before, after in value.items():
        if (not isinstance(before, str) or not isinstance(after, str) or not 1 <= len(before) <= 64
                or not 1 <= len(after) <= 256 or before.strip() != before or after.strip() != after
                or any(unicodedata.category(c) in {"Cc", "Cf"} for c in before + after)
                or any(c in after for c in "<>[]{}")):
            raise ValueError("词典词条须为非空纯文本，禁止控制标签；原文至多 64 字、读法至多 256 字")
        if before != after:
            result[before] = after
    if result:
        keys = re.compile("|".join(_term_pattern(key) for key in sorted(result, key=lambda key: (-len(key), key))))
        if any(keys.search(after) for after in result.values()):
            raise ValueError("词典读法不能再次命中词条；请直接填写最终读法，避免循环或级联替换")
    return result


def load_reading_dictionary(value):
    if value is None:
        return {}
    if isinstance(value, str):
        import json
        from pathlib import Path
        value = json.loads(Path(value).read_text(encoding="utf-8"))
    return validate_reading_dictionary(value)


def chinese_number(value: str) -> str:
    if "." in value:
        integer, fraction = value.split(".", 1)
        return chinese_number(integer) + "点" + "".join(_DIGITS[int(c)] for c in fraction)
    if len(value) > 4 or (len(value) > 1 and value.startswith("0")):
        return "".join(_DIGITS[int(c)] for c in value)
    n = int(value)
    if n == 0:
        return "零"
    result, zero = "", False
    for divisor, unit in ((1000, "千"), (100, "百"), (10, "十"), (1, "")):
        digit, n = divmod(n, divisor)
        if digit:
            if zero:
                result += "零"
            result += ("" if digit == 1 and divisor == 10 and not result else _DIGITS[digit]) + unit
            zero = False
        elif result and n:
            zero = True
    return result


def normalize_reading_text(text: str, *, dictionary=None, language="auto"):
    """返回朗读文本、字符映射及变换记录；歧义编号不改写。"""
    dictionary = validate_reading_dictionary({} if dictionary is None else dictionary)
    user = "|".join(_term_pattern(key) for key in sorted(dictionary, key=lambda key: (-len(key), key)))
    units = "|".join(_QUANTITY_UNITS)
    pattern = re.compile((f"(?P<user>{user})|" if user else "") +
        r"(?<![\w.])(?P<date>(?:19|20)\d{2}年(?:0?[1-9]|1[0-2])月(?:0?[1-9]|[12]\d|3[01])日)"
        r"|(?<![\w.])(?P<year>(?:19|20)\d{2})(?=年)"
        r"|(?<![\d.\w])(?P<percent>\d{1,4}(?:\.\d{1,4})?)[%％]"
        r"|(?<![A-Za-z0-9_.+,，−\-])(?P<quantity>(?:0|[1-9][0-9]{0,3})\.[0-9]{1,4})"
        rf"(?=[ \t]*(?P<unit>{units})(?![A-Za-z0-9_.]))"
    )
    # 中文属于 \w：数字左侧只排除拉丁字母／数字，不能排除普通中文。
    pattern = re.compile(pattern.pattern.replace("[\\w.]", "[A-Za-z0-9_.]").replace(
        "[\\d.\\w]", "[A-Za-z0-9_.+,，−\\-]"))
    # 英文不自动改成中文数字读法；混合文本仅处理明确的中文上下文。
    if resolve_language(text, language) not in {"zh", "mixed"}:
        pattern = re.compile(f"(?P<user>{user})") if user else re.compile(r"(?!)")
    out, mapping, edits, cursor, length = [], [], [], 0, 0
    for match in pattern.finditer(text):
        if (not (user and match.group("user")) and match.group("percent")
                and resolve_language(text, language) == "mixed"
                and not re.search(r"[\u3400-\u9fff][ \t]*$", text[:match.start()])):
            continue
        prefix = text[cursor:match.start()]
        out.append(prefix)
        mapping.extend((i, i + 1) for i in range(cursor, match.start()))
        length += len(prefix)
        if user and match.group("user"):
            rendered, kind = dictionary[match.group()], "user_dictionary"
        elif match.group("date"):
            year, month, day = re.findall(r"\d+", match.group())
            from datetime import date
            try:
                date(int(year), int(month), int(day))
            except ValueError:
                original = match.group()
                out.append(original)
                mapping.extend((i, i + 1) for i in range(match.start(), match.end()))
                length += len(original)
                cursor = match.end()
                continue
            rendered = "".join(_DIGITS[int(c)] for c in year) + "年" + chinese_number(str(int(month))) + "月" + chinese_number(str(int(day))) + "日"
            kind = "date"
        elif match.group("year"):
            rendered = "".join(_DIGITS[int(c)] for c in match.group())
            kind = "year"
        elif match.group("percent"):
            rendered, kind = "百分之" + chinese_number(match.group("percent")), "percentage"
        else:
            rendered, kind = chinese_number(match.group("quantity")), "quantity_decimal"
        out.append(rendered)
        mapping.extend([(match.start(), match.end())] * len(rendered))
        edits.append({"kind": kind, "source_start": match.start(), "source_end": match.end(),
                      "tts_start": length, "tts_end": length + len(rendered),
                      "before": match.group(), "after": rendered, "version": VERSION,
                      **({"confirmation": "user_configured"} if kind == "user_dictionary" else {}),
                      **({"unit": match.group("unit")} if kind == "quantity_decimal" else {})})
        length += len(rendered)
        cursor = match.end()
    out.append(text[cursor:])
    mapping.extend((i, i + 1) for i in range(cursor, len(text)))
    return "".join(out), mapping, tuple(edits)


def comparison_text(text: str, *, dictionary=None, language="auto") -> str:
    import unicodedata
    spoken, _, _ = normalize_reading_text(unicodedata.normalize("NFKC", text), dictionary=dictionary, language=language)
    # 用户指定的最终读法仍可能含数字；只做内置数值等价，不递归应用用户词典。
    spoken, _, _ = normalize_reading_text(spoken, language=language)
    return "".join(c.casefold() for c in spoken if unicodedata.category(c)[0] in {"L", "N"})


def comparison_details(text, *, dictionary=None, language="auto"):
    """英文按词，中文按字符；词界、否定词与缩略词内部撇号不丢弃。"""
    import unicodedata
    text = unicodedata.normalize("NFKC", text).replace("’", "'").replace("‘", "'")
    spoken, _, _ = normalize_reading_text(text, dictionary=dictionary, language=language)
    spoken, _, _ = normalize_reading_text(spoken, language=language)
    resolved = resolve_language(spoken, language)
    if resolved == "zh":
        return {"tokens": list(comparison_text(spoken, language="zh")), "language": resolved,
                "unit": "character", "english_events": []}
    events = []
    if resolved == "en":
        from .english_reading import comparison_reading
        spoken, events = comparison_reading(spoken)
    spoken = spoken.replace("%", " percent ").replace("&", " and ")
    spoken = re.sub(r"(?<![A-Za-z0-9])[-−](?=\d)", " minus ", spoken)
    spoken = re.sub(r"(?<![A-Za-z0-9])[+](?=\d)", " plus ", spoken)
    tokens = re.findall(r"[^\W\d_\u3400-\u9fff]+(?:'[^\W\d_\u3400-\u9fff]+)*|[0-9]+(?:[.,][0-9]+)*|[\u3400-\u9fff]|[$£€/@]", spoken.casefold())
    return {"tokens": tokens, "language": resolved, "unit": "word" if resolved == "en" else "mixed_token",
            "english_events": events, "event_coordinate_scope": "NFKC_and_explicit_dictionary_comparison_input"}


def comparison_units(text, *, dictionary=None, language="auto"):
    details = comparison_details(text, dictionary=dictionary, language=language)
    return details["tokens"], details["language"], details["unit"]


def reading_count(text, *, dictionary=None, language="auto"):
    tokens, resolved, unit = comparison_units(text, dictionary=dictionary, language=language)
    if resolved == "zh":
        count = sum(bool(re.fullmatch(r"[\u3400-\u9fff]", token)) for token in tokens)
    elif resolved == "en":
        count = len(tokens)
    else:
        count = 0
    return count, resolved, unit


def pronunciation_review(chunks):
    """输出原文定位与词典声明；和声学质量判定、自动修复调度分开。"""
    hints = []
    for chunk in chunks:
        for offset, char in enumerate(chunk.source_text):
            if char not in _POLYPHONE_REVIEW_CHARS:
                continue
            source_offset = chunk.source_start + offset
            overrides = [edit for edit in chunk.edits if edit["kind"] == "user_dictionary"
                         and edit["source_start"] <= source_offset < edit["source_end"]]
            hints.append({"chunk_id": chunk.chunk_id, "character": char,
                "context": chunk.source_text[max(0, offset - 8):offset + 9],
                "unit_id": chunk.unit_id, "unit_start": source_offset, "unit_end": source_offset + 1,
                "source_scope": chunk.source_scope,
                "source_span": {**chunk.source_span, "start": chunk.source_span["start"] + offset,
                                "end": chunk.source_span["start"] + offset + 1} if chunk.source_span else None,
                "reading_override_declared": bool(overrides),
                "declared_readings": [{"before": e["before"], "after": e["after"]} for e in overrides],
                "review_status": "pending"})
    return {"version": PRONUNCIATION_REVIEW_VERSION,
            "status": "needs_review" if hints else "not_flagged_by_rules",
            "scope": "non_exhaustive_text_hints_only", "audio_pronunciation_verified": False,
            "hints": hints}


def nonspoken_source_units(units):
    """纯空白只作为原文结构留存，不提交给语音接口；标点和短词仍需朗读。"""
    from dataclasses import asdict
    return [{"unit_id": unit.unit_id, "segment_id": unit.segment_id,
             "role_id": unit.role_id, "source_text": unit.text,
             "source_span": asdict(unit.source_span) if unit.source_span else None,
             "source_scope": "chapter" if unit.source_span else "unit",
             "pause_after_ms": unit.pause_after_ms, "reason": "whitespace_only"}
            for unit in units if not unit.text.strip()]


def build_reading_plan(units, *, chunk_chars=300, dictionary=None, language="auto"):
    """从已验证的 SynthesisUnit 建计划，不重写上游剧本或覆盖率标准。"""
    if chunk_chars < 20 or chunk_chars > 1500:
        raise ValueError("分块长度必须在 20～1500 字符之间")
    result = []
    for unit in units:
        if not unit.text.strip():
            continue
        text, mapping, edits = normalize_reading_text(unit.text, dictionary=dictionary, language=language)
        start, index = 0, 0
        while start < len(text):
            end = min(len(text), start + chunk_chars)
            if end < len(text):
                candidates = [p for p in split_positions(text) if start < p <= end]
                if candidates:
                    end = candidates[-1]
                elif end > start and re.match(r"[A-Za-z0-9'’.,-]", text[end - 1]) and re.match(r"[A-Za-z0-9'’.,-]", text[end]):
                    spaces = [m.end() + start for m in re.finditer(r"\s+", text[start:end])]
                    if spaces:
                        end = spaces[-1]
                    else:
                        while end < len(text) and re.match(r"[A-Za-z0-9'’.-]", text[end]):
                            end += 1
                # 不从一个数字读法内部切开，避免两块映射重复覆盖变换。
                while end < len(text) and mapping[end - 1] == mapping[end]:
                    end += 1
            index += 1
            source_start, source_end = mapping[start][0], mapping[end - 1][1]
            last = end == len(text)
            span = getattr(unit, "source_span", None)
            result.append(ReadingChunk(
                chunk_id=f"{unit.unit_id}:chunk:{index}", unit_id=unit.unit_id, role_id=unit.role_id,
                source_text=unit.text[source_start:source_end], tts_text=text[start:end],
                source_start=source_start, source_end=source_end,
                profile=dict(unit.profile.provider_params), tone=unit.tone,
                pause_after_ms=unit.pause_after_ms if last else 0,
                boundary_kind="unit_end" if last else "continuation",
                edits=tuple(e for e in edits if e["tts_start"] < end and e["tts_end"] > start),
                source_span={"chapter_index": span.chapter_index, "start": span.start + source_start,
                             "end": span.start + source_end} if span else None,
                source_scope="chapter" if span else "unit",
                sequence_index=len(result) + 1, language=resolve_language(unit.text, language),
            ))
            start = end
    return tuple(result)
