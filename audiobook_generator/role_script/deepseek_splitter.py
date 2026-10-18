"""使用 DeepSeek 为书籍章节生成 RoleScriptV1 剧本。

模型只负责提出角色和对白分段；最终文本边界始终由本地按原文重新对齐。这样即使模型
返回了轻微改写，也不会污染最终剧本：对齐失败会重试，仍失败则退回 TODO 占位。
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from .errors import ValidationReport
from .models import ChapterScript, RoleDefinition, RoleScriptV1, SegmentScript
from audiobook_generator.tts_providers.voice_catalog import get_role_voice_pools, get_voice_entry
from .normalization import is_semantic_whitespace, normalize_gender
from .validator import validate_role_script
from .narration import request_narration_context, ground_narration_segments

logger = logging.getLogger(__name__)

DEFAULT_PAUSE_AFTER_MS = 250
DEFAULT_CHUNK_CHARS = 6000
MAX_ATTEMPTS_PER_CHUNK = 2
_ROLE_ID_PATTERN = re.compile(r"^[^\s/\\]{1,64}$")

# 角色性别 → 音色池。DeepSeek 会尽量给出角色性别，本地再按名称关键词兜底。
# 同一性别的不同角色在各自音色池内轮转，避免所有角色都是同一把声音。
# 只保留“称谓 / 亲属 / 身份”这类强信号，绝不能用姓名常用字推断性别：
# “贾宝玉 / 林黛玉”都含“玉”，但前者是男性；靠单字会把整本书的角色判成同性别。
_FEMALE_MARKERS = (
    "女", "妈", "母", "娘", "姐", "妹", "婆", "奶", "妃",
    "姑娘", "小姐", "女士", "夫人", "太太", "丫头", "少女", "玫瑰",
    "侍女", "丫鬟", "女巫", "女王", "公主", "女孩",
    "嫂子", "婶", "姨", "姑姑", "姑妈", "姑母", "姑婆",
    "皇后", "太后", "王后", "娘娘", "贵妃", "王妃", "奶妈",
    "mrs", "miss", "queen", "princess", "mother", "sister", "aunt",
    "grandma", "lady", "girl", "woman", "female", "ms",
)
_MALE_MARKERS = (
    "男", "爸", "父", "爷", "哥", "弟", "叔", "伯",
    "帝", "皇", "王子", "少爷", "先生", "公子", "少年", "男孩", "男士",
    "将军", "老爷", "王爷", "和尚", "道士", "侠客", "书生", "秀才", "国王",
    "大王", "首领", "刺客", "勇士", "骑士", "僧", "童",
    "老公", "公公", "外公", "公爵", "侯爷", "皇帝", "帝王", "大帝",
    "父皇", "皇兄", "皇弟", "高僧", "僧人", "圣僧",
    "mr", "sir", "king", "prince", "father", "brother", "uncle",
    "grandpa", "boy", "man", "male", "lord", "duke",
)
_VOICE_POOLS = {
    "openai": {
        "zh": {
            "female": ("茉莉", "冰糖"),
            "male": ("苏打", "白桦"),
            "narrator": "mimo_default",
        },
        # MiMo 中英文音色不能混用：英文书必须显式使用英文音色，否则会出现
        # 中文音色读英文时节奏漂移、发音不准的问题。
        "en": {
            "female": ("Chloe", "Mia"),
            "male": ("Dean", "Milo"),
            "narrator": "Milo",
        },
    },
    "minimax": {
        "zh": {
            # 旁白占用一个稳重男声；角色池先排除它，避免第一个男性角色与旁白同音色。
            "female": ("female-yujie", "female-chengshu", "female-shaonv", "female-tianmei"),
            "male": ("male-qn-badao", "male-qn-qingse", "male-qn-daxuesheng", "male-qn-jingying"),
            "narrator": "male-qn-jingying",
        },
        "en": {
            "female": ("English_Graceful_Lady", "English_Whispering_girl"),
            "male": (
                "English_Trustworthy_Man",
                "English_Diligent_Man",
                "English_Gentle-voiced_man",
                "English_Aussie_Bloke",
            ),
            "narrator": "English_Trustworthy_Man",
        },
    },
}

_CJK_PATTERN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_LATIN_PATTERN = re.compile(r"[A-Za-z]")

ProgressCallback = Optional[Callable[[str], None]]


class DeepSeekSplitError(RuntimeError):
    """DeepSeek 拆分无法产生可用剧本。"""


def _infer_gender(role_id: str, display_name: str) -> Optional[str]:
    """按 role_id / 显示名里的性别关键词兜底推断性别。"""
    haystack = f"{role_id} {display_name}".lower()
    for marker in _FEMALE_MARKERS:
        if marker in haystack:
            return "female"
    for marker in _MALE_MARKERS:
        if marker in haystack:
            return "male"
    return None


def normalize_script_language(value: Any) -> Optional[str]:
    """把 UI/CLI 的语言值归一为脚本层支持的中英文标记。"""
    if not isinstance(value, str):
        return None
    language = value.strip().lower().replace("_", "-")
    if language.startswith("en"):
        return "en"
    if language.startswith("zh"):
        return "zh"
    return None


def detect_text_language(text: str) -> str:
    """按 CJK/拉丁字母占比判断书稿语言；无法判断时沿用中文默认值。"""
    sample = (text or "")[:50000]
    cjk_count = len(_CJK_PATTERN.findall(sample))
    latin_count = len(_LATIN_PATTERN.findall(sample))
    if cjk_count == 0 and latin_count == 0:
        return "zh"
    if cjk_count >= 20 and cjk_count * 2 >= latin_count:
        return "zh"
    if latin_count >= 20 and latin_count >= cjk_count * 4:
        return "en"
    return "zh" if cjk_count >= latin_count else "en"


def detect_role_script_language(script: RoleScriptV1) -> str:
    """从剧本正文检测语言，供旧剧本迁移和试听共用。"""
    return detect_text_language(
        "".join(
            segment.text
            for chapter in script.chapters
            for segment in chapter.segments
        )
    )


def _provider_voice_pools(provider: str, language: str = "zh") -> Dict[str, Any]:
    """合并人工音色目录和内置兜底池，人工音色始终优先。"""
    provider_pools = _VOICE_POOLS.get(provider)
    if provider_pools is None:
        raise ValueError(f"不支持的角色模式 Provider：{provider}")
    language_key = normalize_script_language(language) or "zh"
    fallback = provider_pools.get(language_key) or provider_pools["zh"]
    try:
        catalog_pools = get_role_voice_pools(provider, language_key)
    except Exception as exc:  # 目录损坏不能阻断普通转换
        logger.warning("读取人工音色目录失败，回退到内置音色池：%s", exc)
        catalog_pools = {}

    merged: Dict[str, Any] = {}
    for gender in ("female", "male", "neutral"):
        catalog_voices = tuple(catalog_pools.get(gender) or ())
        fallback_voices = tuple(fallback.get(gender) or ())
        merged[gender] = tuple(dict.fromkeys(catalog_voices + fallback_voices))
    merged["narrator"] = str(
        catalog_pools.get("narrator") or fallback.get("narrator") or ""
    )
    return merged


def _default_provider_params(
    provider: str,
    display_name: str,
    voice: Optional[str] = None,
    *,
    is_narrator: bool = False,
    language: str = "zh",
) -> Dict[str, Any]:
    language_key = normalize_script_language(language) or "zh"
    pools = _provider_voice_pools(provider, language_key)
    if provider == "openai":
        if language_key == "en":
            instructions = (
                "Read in a clear, steady English audiobook narration voice. "
                "Keep a consistent, moderate pace and natural expression; do not overact."
                if is_narrator
                else (
                    "Speak naturally as this character in English. Preserve the original "
                    "tone and keep a consistent, moderate speaking pace."
                )
            )
        else:
            instructions = (
                "用清晰、平稳、有起伏的中文有声书旁白语气朗读，不要表演化。"
                if is_narrator
                else f"以{display_name}的身份自然演绎角色对白，保留原作语气。"
            )
        return {
            "voice": voice or str(pools["narrator" if is_narrator else "male"]),
            "instructions": instructions,
            "speed": 1.0,
        }
    if provider == "minimax":
        return {
            "voice_id": voice or str(pools["narrator" if is_narrator else "male"]),
            "speed": 1.0,
            "pitch": 0.0,
            "volume": 1.0,
        }
    raise ValueError(f"不支持的角色模式 Provider：{provider}")


def _character_voice_pools(provider: str, language: str = "zh") -> Dict[str, Tuple[str, ...]]:
    """角色音色池：排除旁白音色，避免角色与旁白分配成同一把声音。"""
    pools = _provider_voice_pools(provider, language)
    narrator_voice = pools["narrator"]
    return {
        gender: tuple(voice for voice in voices if voice != narrator_voice)
        for gender, voices in pools.items()
        if gender != "narrator"
    }


def _voice_gender_lookup(provider: str, language: str = "zh") -> Dict[str, str]:
    """把音色池反查成 音色 -> 性别，用于检测“性别与音色不匹配”。"""
    pools = _provider_voice_pools(provider, language)
    lookup: Dict[str, str] = {}
    for gender in ("female", "male"):
        for voice in pools.get(gender, ()):  # type: ignore[arg-type]
            lookup[voice] = gender
    narrator_voice = pools.get("narrator")
    if narrator_voice:
        lookup[str(narrator_voice)] = "narrator"
    return lookup


def _voice_matches_script_language(provider: str, voice: str, language: str) -> bool:
    """判断音色是否属于目标语言，优先使用人工目录的语言元数据。"""
    normalized_voice = str(voice or "").strip()
    if not normalized_voice:
        return False
    language_key = normalize_script_language(language) or "zh"
    entry = get_voice_entry(provider, normalized_voice)
    if entry is not None and entry.language not in ("", "unknown"):
        return entry.language == language_key

    if provider == "minimax":
        # 旧目录可能没有语言元数据；MiniMax 英文推荐音色保留 English_ 前缀兜底。
        is_english = normalized_voice.startswith("English_")
        return is_english if language_key == "en" else not is_english

    pools = _provider_voice_pools(provider, language_key)
    valid_voices = {
        str(voice)
        for gender in ("female", "male", "narrator")
        for voice in (
            pools.get(gender, ())
            if gender != "narrator"
            else (pools.get("narrator"),)
        )
        if voice
    }
    return normalized_voice in valid_voices


def _with_language_instructions(
    role_id: str,
    role: RoleDefinition,
    provider: str,
    language: str,
    *,
    force: bool = False,
) -> Tuple[RoleDefinition, bool]:
    """把旧剧本里与正文语言不一致的 MiMo 朗读指令迁移到当前语言。"""
    if provider != "openai":
        return role, False
    params = dict(role.provider_params)
    if params.get('voice_mode') == 'design' or params.get('voice_profile_id'):
        return role, False
    instructions = params.get("instructions")
    has_instruction = isinstance(instructions, str) and bool(instructions.strip())
    has_cjk = bool(
        isinstance(instructions, str) and _CJK_PATTERN.search(instructions)
    )
    language_mismatch = has_instruction and (
        (language == "en" and has_cjk) or (language == "zh" and not has_cjk)
    )
    if not force and not language_mismatch:
        return role, False
    defaults = _default_provider_params(
        provider,
        role.display_name,
        voice=str(params.get("voice") or ""),
        is_narrator=role_id == "narrator",
        language=language,
    )
    default_instructions = defaults.get("instructions")
    if not default_instructions or instructions == default_instructions:
        return role, False
    params["instructions"] = default_instructions
    return replace(role, provider_params=params), True


def _pick_voice(
    pool: Sequence[str],
    start: int,
    used: set,
) -> str:
    """在池中从 start 开始挑一个尚未占用的音色；全被占用时回落到轮转位置。"""
    if not pool:
        return ""
    for offset in range(len(pool)):
        candidate = pool[(start + offset) % len(pool)]
        if candidate not in used:
            return candidate
    return pool[start % len(pool)]


def _build_role_definitions(
    provider: str,
    roles: Dict[str, Dict[str, str]],
    language: str = "zh",
) -> Dict[str, RoleDefinition]:
    """为每个角色分配差异化音色：优先用 DeepSeek 给出的性别，其次按名称关键词推断。"""
    language_key = normalize_script_language(language) or "zh"
    pools = _provider_voice_pools(provider, language_key)
    character_pools = _character_voice_pools(provider, language_key)
    counters = {"female": 0, "male": 0, "neutral": 0}
    definitions: Dict[str, RoleDefinition] = {}
    used_voices: set = set()
    for role_id, meta in roles.items():
        raw_display = meta.get("display_name") if isinstance(meta, dict) else None
        display_name = (raw_display if isinstance(raw_display, str) and raw_display.strip() else role_id)
        display_name = display_name.strip()[:64]
        is_narrator = role_id == "narrator"
        if is_narrator:
            voice = pools["narrator"]
        else:
            raw_gender = meta.get("gender") if isinstance(meta, dict) else None
            gender = normalize_gender(raw_gender) or _infer_gender(role_id, display_name)
            if gender is None:
                # 性别无法判断时在男女声池之间交替，保证不同角色至少听感不同。
                gender = "female" if counters["neutral"] % 2 == 0 else "male"
                counters["neutral"] += 1
            pool = character_pools.get(gender) or character_pools["male"]
            voice = _pick_voice(pool, counters.get(gender, 0), used_voices)
            counters[gender] = counters.get(gender, 0) + 1
            used_voices.add(voice)
        definitions[role_id] = RoleDefinition(
            display_name=display_name,
            provider_params=_default_provider_params(
                provider,
                display_name,
                voice,
                is_narrator=is_narrator,
                language=language_key,
            ),
            gender=None if is_narrator else gender,
        )
    return definitions


def differentiate_role_voices(
    script: RoleScriptV1, language: Optional[str] = None
) -> Tuple[RoleScriptV1, bool]:
    """给重复或缺失音色的角色自动分配差异化音色。

    只改动确实有问题的角色：没有音色、音色与旁白重复、或与同书其它角色重复。
    已经手动配置且互不冲突的音色不会被覆盖；旁白音色始终保留。性别优先按角色名推断，
    无法判断时在男女声池之间交替，避免多个角色听起来是同一把声音。
    """
    if script.provider not in _VOICE_POOLS:
        return script, False
    from .models import RoleScriptV2

    language_key = normalize_script_language(language) or detect_role_script_language(script)
    pools = _provider_voice_pools(script.provider, language_key)

    voice_field = "voice" if script.provider == "openai" else "voice_id"
    character_pools = _character_voice_pools(script.provider, language_key)
    narrator_voice = pools["narrator"]

    def current_voice(role: RoleDefinition) -> str:
        return str(role.provider_params.get(voice_field) or "").strip()

    roles: Dict[str, RoleDefinition] = dict(script.roles)
    changed = False
    narrator_role = roles.get("narrator")
    narrator_locked = isinstance(script, RoleScriptV2) and bool(
        script.entities.get("narrator") and script.entities["narrator"].voice_locked
    )
    if narrator_role is not None and not narrator_locked and not narrator_role.provider_params.get('voice_profile_id'):
        narrator_current = current_voice(narrator_role)
        if not _voice_matches_script_language(
            script.provider, narrator_current, language_key
        ):
            narrator_params = dict(narrator_role.provider_params)
            narrator_params[voice_field] = narrator_voice
            narrator_role = replace(narrator_role, provider_params=narrator_params)
            changed = True
        narrator_role, instruction_changed = _with_language_instructions(
            "narrator", narrator_role, script.provider, language_key
        )
        changed = changed or instruction_changed
        roles["narrator"] = narrator_role
        narrator_voice = current_voice(narrator_role)

    characters = [
        (role_id, role)
        for role_id, role in script.roles.items()
        if role_id != "narrator"
    ]
    if not characters:
        return (replace(script, roles=roles), True) if changed else (script, False)

    voice_counts = Counter(current_voice(role) for _, role in characters)
    voice_genders = _voice_gender_lookup(script.provider, language_key)
    genders: Dict[str, Optional[str]] = {}
    needs_reassign: Dict[str, bool] = {}
    for role_id, role in characters:
        genders[role_id] = normalize_gender(role.gender) or _infer_gender(
            role_id, role.display_name
        )
        voice = current_voice(role)
        known_voice_gender = voice_genders.get(voice)
        gender_mismatch = (
            genders[role_id] is not None
            and known_voice_gender in ("female", "male")
            and known_voice_gender != genders[role_id]
        )
        locked = isinstance(script, RoleScriptV2) and bool(
            script.entities.get(role_id) and script.entities[role_id].voice_locked
        )
        fixed_profile = role.provider_params.get('voice_mode') == 'design' or bool(role.provider_params.get('voice_profile_id'))
        needs_reassign[role_id] = not locked and not fixed_profile and (
            not voice
            or not _voice_matches_script_language(script.provider, voice, language_key)
            or voice == narrator_voice
            or voice_counts[voice] > 1
            or gender_mismatch
        )

    if any(needs_reassign.values()):
        kept_voices = {
            current_voice(role)
            for role_id, role in characters
            if not needs_reassign[role_id]
        }
        kept_voices.discard(narrator_voice)
        counters = {"female": 0, "male": 0, "neutral": 0}
        new_voices: Dict[str, str] = {}
        for role_id, role in characters:
            if not needs_reassign[role_id]:
                continue
            gender = genders[role_id]
            if gender is None:
                gender = "female" if counters["neutral"] % 2 == 0 else "male"
                counters["neutral"] += 1
            pool = character_pools.get(gender) or character_pools["male"]
            used = kept_voices | set(new_voices.values())
            new_voices[role_id] = _pick_voice(pool, counters.get(gender, 0), used)
            counters[gender] = counters.get(gender, 0) + 1

        for role_id, role in characters:
            if role_id not in new_voices:
                continue
            params = dict(role.provider_params)
            params[voice_field] = new_voices[role_id]
            roles[role_id] = RoleDefinition(
                display_name=role.display_name,
                provider_params=params,
                gender=normalize_gender(role.gender),
            )
            changed = True

    for role_id, role in characters:
        current_role, instruction_changed = _with_language_instructions(
            role_id,
            roles[role_id],
            script.provider,
            language_key,
            force=needs_reassign[role_id],
        )
        roles[role_id] = current_role
        changed = changed or instruction_changed

    if not changed:
        return script, False
    return replace(script, roles=roles), True


def _report_progress(progress: ProgressCallback, message: str) -> None:
    if progress is None:
        return
    try:
        progress(message)
    except Exception:
        logger.debug("DeepSeek 拆分进度回调失败", exc_info=True)


def _split_text_chunks(text: str, max_chars: int = DEFAULT_CHUNK_CHARS) -> List[str]:
    """优先在段落、换行和句末标点处切块，避免一次请求超过上下文限制。"""
    if max_chars < 200:
        raise ValueError("max_chars 不能小于 200")
    if len(text) <= max_chars:
        return [text]

    chunks: List[str] = []
    remaining = text
    while len(remaining) > max_chars:
        window = remaining[:max_chars]
        cut = -1
        for marker in ("\n\n", "\n", "。", "！", "？", "；", ". ", "! ", "? ", "; "):
            found = window.rfind(marker)
            if found > cut:
                cut = found + len(marker)
        if cut < max_chars // 2:
            cut = max_chars
        chunks.append(remaining[:cut])
        remaining = remaining[cut:]
    if remaining:
        chunks.append(remaining)
    return chunks


def _normalized_with_source_map(text: str) -> Tuple[str, List[int]]:
    """返回覆盖率规范化文本，以及每个规范化字符对应的原文字符索引。"""
    chars: List[str] = []
    source_map: List[int] = []
    for source_index, source_char in enumerate(text):
        normalized = unicodedata.normalize("NFKC", source_char)
        for char in normalized:
            if is_semantic_whitespace(char):
                continue
            chars.append(char)
            source_map.append(source_index)
    return "".join(chars), source_map


def _has_visible_text(text: str) -> bool:
    """判断文本在覆盖率规范化后是否仍有实际内容。"""
    return bool(_normalized_with_source_map(text)[0])


def _extract_json_object(content: str) -> Dict[str, Any]:
    text = (content or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise DeepSeekSplitError("DeepSeek 未返回可解析的 JSON 对象")
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise DeepSeekSplitError(f"DeepSeek JSON 解析失败：{exc}") from exc
    if not isinstance(parsed, dict):
        raise DeepSeekSplitError("DeepSeek JSON 根节点必须是对象")
    return parsed


def _raw_segments(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    raw_roles = payload.get("roles") or {}
    if not isinstance(raw_roles, dict):
        raise DeepSeekSplitError("DeepSeek 返回的 roles 必须是对象")
    raw_segments = payload.get("segments")
    if raw_segments is None and isinstance(payload.get("chapter"), dict):
        raw_segments = payload["chapter"].get("segments")
    if raw_segments is None and isinstance(payload.get("chapters"), list) and payload["chapters"]:
        first_chapter = payload["chapters"][0]
        if isinstance(first_chapter, dict):
            raw_segments = first_chapter.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        raise DeepSeekSplitError("DeepSeek 返回的 segments 必须是非空数组")
    normalized_segments: List[Dict[str, Any]] = []
    for item in raw_segments:
        if not isinstance(item, dict):
            raise DeepSeekSplitError("segments 中的每一项都必须是对象")
        normalized_segments.append(item)
    return raw_roles, normalized_segments


def _normalize_role_id(role_id: Any, roles: Dict[str, Dict[str, str]], role_hint: Optional[str] = None) -> str:
    if not isinstance(role_id, str) or not role_id.strip():
        raise DeepSeekSplitError("segment.role_id 必须是非空字符串")
    role_id = role_id.strip()
    if role_id.lower() == "narrator":
        role_id = "narrator"
    if not _ROLE_ID_PATTERN.fullmatch(role_id):
        raise DeepSeekSplitError(f"非法 role_id：{role_id!r}")
    if role_id not in roles:
        display = role_hint.strip() if isinstance(role_hint, str) and role_hint.strip() else role_id
        roles[role_id] = {"display_name": display}
    return role_id


def _reconcile_segments(
    source_text: str,
    raw_segments: Sequence[Dict[str, Any]],
    roles: Dict[str, Dict[str, str]],
) -> List[SegmentScript]:
    """把模型返回的文本顺序重新映射回原文边界，确保覆盖率严格一致。"""
    source_normalized, source_map = _normalized_with_source_map(source_text)
    if not source_normalized:
        raise DeepSeekSplitError("章节文本为空")

    entries: List[Tuple[Dict[str, Any], int]] = []
    cursor = 0
    for item in raw_segments:
        text = item.get("text")
        if not isinstance(text, str) or not text:
            raise DeepSeekSplitError("segment.text 必须是非空字符串")
        normalized_text, _ = _normalized_with_source_map(text)
        if not normalized_text:
            # 模型偶尔会返回只有空白（含全角空格、换行）的“占位”段落。这类段落不承载
            # 任何正文，跳过即可；否则整块会因为“规范化后为空”而回退成 narrator，
            # 白白丢掉已经正确拆分的其余段落（历史反馈中的偶发拆分失败即由此触发）。
            continue
        match_at = source_normalized.find(normalized_text, cursor)
        if match_at != cursor:
            raise DeepSeekSplitError(
                f"segment 文本未能按原文顺序精确覆盖：{text[:80]!r}"
            )
        entries.append((item, match_at))
        cursor = match_at + len(normalized_text)
    if cursor != len(source_normalized):
        raise DeepSeekSplitError("segment 文本未覆盖章节全部正文")

    # entries 里保存了“规范化下标”；原文字符可能被 NFKC 展开，也可能夹有空白，
    # 必须通过 source_map 映射回原文下标，否则段首标点会被错误地挪到下一段。
    # 相邻规范化字符之间的空白（换行等）归属前一段，保证拼接后逐字等于原文。
    boundaries = [source_map[start] for _, start in entries] + [len(source_text)]
    reconciled: List[SegmentScript] = []
    for index, (item, _start) in enumerate(entries):
        text = source_text[boundaries[index] : boundaries[index + 1]]
        if text:
            reconciled.append(_segment_from_item(item, roles, text))
    if not reconciled:
        raise DeepSeekSplitError("本地对齐后没有任何 segment")
    return reconciled


def _segment_from_item(item: Dict[str, Any], roles: Dict[str, Dict[str, str]], text: str) -> SegmentScript:
    """把模型返回的单个 segment 转成领域对象，非法 tone/pause 静默丢弃。"""
    role_hint = item.get("display_name") or item.get("role_name")
    role_id = _normalize_role_id(item.get("role_id"), roles, role_hint)
    tone = item.get("tone")
    if tone is not None and (not isinstance(tone, str) or not tone or len(tone) > 200):
        tone = None
    pause = item.get("pause_after_ms")
    if not isinstance(pause, int) or isinstance(pause, bool) or not 0 <= pause <= 60000:
        pause = None
    evidence_candidates = []
    for evidence in item.get("evidence", []) if isinstance(item.get("evidence"), list) else []:
        if not isinstance(evidence, dict):
            continue
        quote = evidence.get("quote")
        kind = evidence.get("kind")
        if isinstance(quote, str) and quote.strip() and isinstance(kind, str) and kind.strip():
            evidence_candidates.append((quote.strip(), kind.strip()))
    return SegmentScript(
        role_id=role_id,
        text=text,
        tone=tone,
        pause_after_ms=pause,
        evidence_candidates=tuple(evidence_candidates[:3]),
        text_kind=item.get('text_kind') if item.get('text_kind') in ('narration', 'dialogue', 'unknown') else None,
    )


def _reconcile_segments_lenient(
    source_text: str,
    raw_segments: Sequence[Dict[str, Any]],
    roles: Dict[str, Dict[str, str]],
) -> List[SegmentScript]:
    """宽松对齐：模型轻微改写导致严格对齐失败时，尽量保住已经拆好的角色分段。

    无法精确对齐的原文区间并入前一段（或首个未对齐区间回退 narrator），保证拼接
    结果始终逐字等于原文。一个 segment 都没对上时返回空列表，由上层决定整块回退。
    """
    source_normalized, source_map = _normalized_with_source_map(source_text)
    if not source_normalized:
        raise DeepSeekSplitError("章节文本为空")

    def source_slice(start_norm: int, end_norm: int) -> str:
        if start_norm >= len(source_map):
            return ""
        start_char = source_map[start_norm]
        end_char = source_map[end_norm] if end_norm < len(source_map) else len(source_text)
        return source_text[start_char:end_char]

    pieces: List[List[Any]] = []  # [item_or_None, start_norm, end_norm]
    matched_any = False
    cursor = 0
    for item in raw_segments:
        text = item.get("text")
        if not isinstance(text, str) or not text:
            continue
        normalized_text, _ = _normalized_with_source_map(text)
        if not normalized_text:
            continue
        match_at = source_normalized.find(normalized_text, cursor)
        match_len = len(normalized_text)
        if match_at < 0:
            for prefix_len in range(min(len(normalized_text), 24), 5, -1):
                match_at = source_normalized.find(normalized_text[:prefix_len], cursor)
                if match_at >= 0:
                    match_len = prefix_len
                    break
            else:
                continue
        if match_at > cursor:
            # 无法对齐的间隙是上一段被模型轻微改写的尾部，并入上一段更贴近原意；
            # 若还没有任何段落，则先用 narrator 占位。
            if pieces:
                pieces[-1][2] = match_at
            else:
                pieces.append([None, cursor, match_at])
        pieces.append([item, match_at, match_at + match_len])
        matched_any = True
        cursor = match_at + match_len

    if not matched_any:
        return []
    if cursor < len(source_normalized):
        pieces[-1][2] = len(source_normalized)

    reconciled: List[SegmentScript] = []
    for item, start, end in pieces:
        text = source_slice(start, end)
        # 宽松抢救同样不能产出“规范化后为空”的段：NFKC 展开字符可能让区间映射
        # 到零长度（左右下标指向同一个原文字符），这类片段必须丢弃而不是送进剧本。
        if not text or not _has_visible_text(text):
            continue
        if item is None:
            reconciled.append(SegmentScript(role_id="narrator", text=text))
        else:
            reconciled.append(_segment_from_item(item, roles, text))
    return reconciled


def _build_prompt(
    chapter_index: int,
    title: str,
    text: str,
    provider: str,
    language: str = "zh",
    narration_context: Optional[Dict[str, Any]] = None,
) -> str:
    provider_name = "MiMo (openai)" if provider == "openai" else "MiniMax"
    language_key = normalize_script_language(language) or "zh"
    if language_key == "en":
        prompt = f"""Split the following chapter from an English book into a multi-role dialogue script. The target TTS provider is {provider_name}.

You must follow these rules exactly:
1. Only segment the source text. Never rewrite, polish, omit, expand, reorder, or merge the original text.
2. Every segment's text must be a contiguous verbatim excerpt from the source. Concatenating all segments in order must reproduce the source exactly.
3. Separate text_kind (narration/dialogue/unknown) from role_id (voice identity). First-person memories, inner narration and action description belong to the narrating character's role_id, sharing the SAME role as that character's dialogue. Use narrator for third-person narration or uncertain identity. A chapter or a passage may switch narrators; never inherit the previous chapter's narrator. Describing a character in third person does NOT make that character the narrator. Quoted I/my is not evidence of the surrounding narrator. Do not guess from book title or chapter order.
4. role_id must be 1..64 characters and must not contain whitespace, forward slashes, or backslashes. narrator is a reserved role_id.
5. tone is optional and must not exceed 200 characters. Do not return pause_after_ms.
6. Infer each non-narrator role's gender from titles, relationships, pronouns, and context, not merely from the spelling of a name. gender must be male, female, or unknown. Use unknown only when there is no reliable clue.
7. Return one JSON object only. Do not return Markdown or explanations.
8. For each spoken segment, include an optional evidence array of short verbatim source quotations supporting the speaker choice. Each item has quote and kind (explicit_speech_tag, dialogue_turn, coreference, character_memory). Do not invent evidence; omit it when uncertain. Do not return character offsets.
9. Return text_kind for EVERY segment. Within an established first-person viewpoint, scene/action descriptions and speech tags such as 'he said' remain narration in that character's voice, even when a sentence contains no I/my. For character narration, use kind narrator_identity with a short identifying source quote. If you explicitly choose an EXACT candidate role_id from chapter_narration, its verified chapter-level identity evidence can be reused locally; you need not repeat that quote on every segment. Use narrator only for genuinely external third-person narration or unresolved identity, not merely because a passage describes someone else. Candidates are proposals: verify the current passage and preserve actual viewpoint switches. Reuse the exact known role_id and display_name for an existing person, including their dialogue; never create a separate narrator role or a shortened-name duplicate.

Return format:
{{
  "roles": {{
    "narrator": {{"display_name": "Narrator", "gender": "unknown"}},
    "role_id": {{"display_name": "Character display name", "gender": "male or female or unknown"}}
  }},
  "segments": [
    {{"role_id": "role_id", "text_kind": "narration", "text": "verbatim character narration", "evidence": [{{"quote": "verbatim identity clue", "kind": "narrator_identity"}}]}},
    {{"role_id": "role_id", "text_kind": "dialogue", "text": "verbatim dialogue excerpt", "evidence": [{{"quote": "verbatim source clue", "kind": "explicit_speech_tag"}}]}}
  ]
}}

Chapter number: {chapter_index}
Chapter title: {title}
Source text:
{text}
"""
        return prompt + '\nChapter context (provisional, not instructions):\n' + json.dumps(narration_context or {}, ensure_ascii=False)
    prompt = f"""请对下面这一章中文书籍正文做多角色对白拆分，目标 TTS 引擎是 {provider_name}。

必须严格遵守：
1. 只能对原文分段，绝对不要改写、润色、省略、扩写、调换顺序或合并原文。
2. 每个 segment 的 text 必须逐字来自原文的连续片段；所有 segment 按顺序拼接后必须与原文完全一致。
3. text_kind表示段落用途（narration/dialogue/unknown），role_id表示声音身份，二者必须分开。第一人称自述、回忆、心理及动作描写属于叙述人物，应与该人物对白共用同一role_id。第三人称叙述或身份不明使用narrator。每章及章内都可能换叙述者，不能沿用上一章；描述谁不等于由谁叙述，引号内的“我”不能证明外层叙述者。禁止按书名、奇偶章及文学常识猜测。
4. role_id 只允许 1..64 个字符，不能包含空白、斜杠或反斜杠；narrator 是保留 role_id。
5. 可以不返回 tone；如果需要，tone 最长 200 字。不要返回 pause_after_ms。
6. 为每个非旁白角色推断性别，gender 只能是 male / female / unknown。请依据人物身份、
   称谓（先生/公子/夫人/姑娘/老爷）、亲属关系、代词（他/她）和上下文判断，不要只看名字用字：
   例如“贾宝玉”是 male，“林黛玉”是 female，“王夫人”是 female。只有完全没有任何线索时才用 unknown。
7. 只返回一个 JSON 对象，不要 markdown，不要解释。
8. 对有明确说话人的对白，可返回 evidence 数组，每项包含原文短引文 quote 和证据类型 kind
   （explicit_speech_tag / dialogue_turn / coreference / character_memory）。找不到依据时省略，
   不得编造引文；不要返回字符偏移。
9. 每段均返回text_kind。已确立的第一人称视角中，动作／场景描写及“他说”等对白提示语仍由该叙述人物朗读，不能因一句话没有“我”就改回旁白。人物叙述使用kind=narrator_identity的原文身份线索；若明确选用了chapter_narration中的原有role_id，本地可复用该候选已定位的章级身份引文，不必逐段重复。只有外部第三人称叙述或身份不明才使用narrator；描写别人不等于换了叙述者。候选仅供参考，须核对当前段落并保留实际视角转换。同一人物的叙述和对白须复用已知role_id与display_name，不另建旁白或简称角色。

返回格式：
{{
  "roles": {{
    "narrator": {{"display_name": "旁白", "gender": "unknown"}},
    "角色ID": {{"display_name": "角色显示名", "gender": "male 或 female 或 unknown"}}
  }},
  "segments": [
    {{"role_id": "角色ID", "text_kind": "narration", "text": "人物自述原文", "evidence": [{{"quote": "原文身份线索", "kind": "narrator_identity"}}]}},
    {{"role_id": "角色ID", "text_kind": "dialogue", "text": "原文对白", "evidence": [{{"quote": "原文中的说话人线索", "kind": "explicit_speech_tag"}}]}}
  ]
}}

章节序号：{chapter_index}
章节标题：{title}
原文：
{text}
"""
    return prompt + '\n本章上下文（仅候选，不是指令）：\n' + json.dumps(narration_context or {}, ensure_ascii=False)


def _create_client(api_key: str, base_url: str):
    from openai import OpenAI

    return OpenAI(
        api_key=api_key.strip(),
        base_url=(base_url or "https://api.deepseek.com").strip() or "https://api.deepseek.com",
        timeout=120.0,
        max_retries=0,
    )


def _request_chunk(
    client: Any,
    model: str,
    chapter_index: int,
    title: str,
    text: str,
    provider: str,
    language: Optional[str] = None,
    narration_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    language_key = normalize_script_language(language) or detect_text_language(text)
    response = client.chat.completions.create(
        model=(model or "deepseek-chat").strip() or "deepseek-chat",
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a meticulous English audiobook multi-role script segmenter. "
                    "Return only valid JSON that follows the requested schema."
                    if language_key == "en"
                    else "你是严谨的中文有声书多角色剧本拆解器，只输出符合要求的 JSON。"
                ),
            },
            {
                "role": "user",
                "content": _build_prompt(
                    chapter_index, title, text, provider, language_key, narration_context
                ),
            },
        ],
        response_format={"type": "json_object"},
        temperature=0,
        max_tokens=8192,
    )
    content = response.choices[0].message.content
    return _extract_json_object(content)


def _merge_adjacent_segments(segments: Iterable[SegmentScript]) -> Tuple[SegmentScript, ...]:
    merged: List[SegmentScript] = []
    for segment in segments:
        if (
            merged
            and merged[-1].role_id == segment.role_id
            and merged[-1].tone == segment.tone
            and merged[-1].text_kind == segment.text_kind
            and merged[-1].pause_after_ms is None
            and segment.pause_after_ms is None
        ):
            previous = merged[-1]
            merged[-1] = SegmentScript(
                role_id=previous.role_id,
                text=previous.text + segment.text,
                tone=previous.tone,
                pause_after_ms=None,
                evidence_candidates=previous.evidence_candidates + segment.evidence_candidates,
                text_kind=previous.text_kind,
            )
        else:
            merged.append(segment)
    return tuple(merged)


def _format_validation_error(report: ValidationReport) -> str:
    details = "；".join(f"[{item.code}] {item.path}: {item.message}" for item in report.errors)
    return details or "未知校验错误"


def split_chapters_with_deepseek(
    chapters: List[Tuple[str, str]],
    chapter_start: int,
    chapter_end: int,
    provider: str,
    book_sha256: str,
    api_key: str,
    base_url: str,
    model: str,
    progress: ProgressCallback = None,
    *,
    report: Optional[ValidationReport] = None,
    chunk_chars: int = DEFAULT_CHUNK_CHARS,
    language: Optional[str] = None,
    analyze_narration: bool = False,
    known_characters: Optional[List[Dict[str, Any]]] = None,
) -> RoleScriptV1:
    """把指定章节范围拆成可编辑、可校验的 RoleScriptV1。

    该函数只会返回覆盖率严格一致的剧本；DeepSeek 单块失败时该块退回 narrator，
    并通过 report.warnings 和 progress 暴露，不会静默返回错位文本。
    """
    if not api_key or not api_key.strip():
        raise DeepSeekSplitError("请先在设置中填写 DeepSeek API Key")
    if provider not in {"openai", "minimax"}:
        raise DeepSeekSplitError(f"不支持的角色模式 Provider：{provider}")
    if chapter_start < 1 or chapter_end < chapter_start or chapter_end > len(chapters):
        raise DeepSeekSplitError("章节范围无效")

    requested_language = normalize_script_language(language)
    selected = list(range(chapter_start, chapter_end + 1))
    detected_language = requested_language or detect_text_language(
        "\n".join(chapters[index - 1][1] for index in selected)
    )
    reports = report if report is not None else ValidationReport(schema_version=1)
    roles: Dict[str, Dict[str, str]] = {
        "narrator": {
            "display_name": "Narrator" if detected_language == "en" else "旁白"
        }
    }
    generated_chapters: List[ChapterScript] = []
    client = _create_client(api_key, base_url)

    for relative_index, chapter_index in enumerate(selected, 1):
        title, source_text = chapters[chapter_index - 1]
        if not _has_visible_text(source_text):
            raise DeepSeekSplitError(f"第 {chapter_index} 章正文为空，无法拆分")
        _report_progress(
            progress,
            f"DeepSeek 正在拆分第 {chapter_index} 章（{relative_index}/{len(selected)}）",
        )
        chapter_parts = _split_text_chunks(source_text, chunk_chars)
        # 超长前导空白可能被切成“只有空白”的块。这类块没有任何正文，直接跳过，
        # 不能送入 DeepSeek，也不能在失败回退时生成规范化后为空的 segment。
        chapter_parts = [part for part in chapter_parts if _has_visible_text(part)]
        if not chapter_parts:
            raise DeepSeekSplitError(f"第 {chapter_index} 章正文为空，无法拆分")
        chapter_segments: List[SegmentScript] = []
        # 每章独立分析，禁止沿用上章的第一人称身份；候选不直接覆盖任何段落。
        narration_context = {'known_characters': known_characters or []}
        if analyze_narration:
            _report_progress(progress, f"DeepSeek 正在识别第 {chapter_index} 章的叙述者")
            try:
                narration_context['chapter_narration'] = request_narration_context(
                    client, model, chapter_index, title, source_text, known_characters or [])
            except Exception as exc:
                reports.warn('narrator_analysis_failed', f'$.chapters[{chapter_index}]',
                             f'本章叙述者预分析失败，继续逐段识别并保留默认旁白待复核：{exc}')
                _report_progress(progress, f"第 {chapter_index} 章叙述者预分析失败，继续逐段识别")
        for part_index, part_text in enumerate(chapter_parts, 1):
            # 分块可能带着首尾空白（尤其是 6000 字边界处）。DeepSeek 只需要可见正文，
            # 本地对齐也必须从第一个可见字符开始；否则模型返回正文时无法精确覆盖，
            # 会被误判为 chunk 拆分失败并回退成 narrator。
            normalized_part, source_map = _normalized_with_source_map(part_text)
            if not normalized_part:
                continue
            part_text = part_text[source_map[0]:source_map[-1] + 1]
            last_error: Optional[Exception] = None
            reconciled: Optional[List[SegmentScript]] = None
            last_raw_segments: Optional[List[Dict[str, Any]]] = None
            for attempt in range(1, MAX_ATTEMPTS_PER_CHUNK + 1):
                try:
                    payload = _request_chunk(
                        client,
                        model,
                        chapter_index,
                        title,
                        part_text,
                        provider,
                        detected_language,
                        **({'narration_context': narration_context} if analyze_narration else {}),
                    )
                    raw_roles, raw_segments = _raw_segments(payload)
                    if analyze_narration:
                        # 模型引用了上下文人物 ID 却漏写 roles 时，仍保留其真实名称。
                        hints = list(known_characters or []) + narration_context.get('chapter_narration', {}).get('narrators', [])
                        used_ids = [item.get('role_id') for item in raw_segments]
                        raw_roles = dict(raw_roles)
                        for hint in hints:
                            if hint.get('role_id') in used_ids:
                                raw_roles.setdefault(hint['role_id'], hint)
                    last_raw_segments = raw_segments
                    for role_id, role_meta in raw_roles.items():
                        if not isinstance(role_id, str):
                            continue
                        normalized_role_id = role_id.strip()
                        if normalized_role_id.lower() == "narrator":
                            normalized_role_id = "narrator"
                        if not _ROLE_ID_PATTERN.fullmatch(normalized_role_id):
                            continue
                        display_name = None
                        gender = None
                        if isinstance(role_meta, dict):
                            display_name = role_meta.get("display_name")
                            gender = normalize_gender(role_meta.get("gender"))
                        merged_display = (
                            display_name.strip()
                            if isinstance(display_name, str) and display_name.strip()
                            else None
                        )
                        existing = roles.get(normalized_role_id) or {}
                        # 同一角色会跨多个 chunk 出现，后续 chunk 若把 gender 写成
                        # unknown/空，不能覆盖前面已经拿到的有效性别。
                        roles[normalized_role_id] = {
                            "display_name": (
                                merged_display
                                or existing.get("display_name")
                                or normalized_role_id
                            )[:64],
                            "gender": gender or existing.get("gender") or "",
                        }
                    if analyze_narration and any(
                        item.get('text_kind') not in ('narration', 'dialogue', 'unknown')
                        and isinstance(item.get('text'), str) and _has_visible_text(item['text'])
                        for item in raw_segments
                    ):
                        raise DeepSeekSplitError('存在缺失或无效的text_kind，需要明确叙述／对白／未知类型')
                    reconciled = _reconcile_segments(part_text, raw_segments, roles)
                    break
                except Exception as exc:
                    last_error = exc
                    if attempt < MAX_ATTEMPTS_PER_CHUNK:
                        logger.warning(
                            "DeepSeek 第 %s 章第 %s/%s 块未满足剧本校验，准备重试：%s",
                            chapter_index,
                            part_index,
                            len(chapter_parts),
                            exc,
                        )
            if reconciled is None and last_raw_segments is not None:
                try:
                    salvaged = _reconcile_segments_lenient(part_text, last_raw_segments, roles)
                except Exception:
                    salvaged = []
                if salvaged:
                    reason = str(last_error or "未知错误")
                    reports.warn(
                        "deepseek_chunk_partial",
                        f"$.chapters[{chapter_index}].chunk_{part_index}",
                        f"DeepSeek 对第 {chapter_index} 章第 {part_index} 块未能逐字对齐，"
                        f"已按可对齐范围保留角色分段，其余回退为 narrator：{reason}",
                        chapter_index=chapter_index,
                        chunk_index=part_index,
                    )
                    reconciled = salvaged
            if reconciled is None:
                reason = str(last_error or "未知错误")
                reports.warn(
                    "deepseek_chunk_fallback",
                    f"$.chapters[{chapter_index}].chunk_{part_index}",
                    f"DeepSeek 对第 {chapter_index} 章第 {part_index} 块拆分失败，已回退为该块 narrator：{reason}",
                    chapter_index=chapter_index,
                    chunk_index=part_index,
                )
                _report_progress(
                    progress,
                    f"第 {chapter_index} 章第 {part_index} 块拆分失败，已安全回退为旁白",
                )
                if not _has_visible_text(part_text):
                    # 语义空白块不承载任何正文，跳过它不会影响覆盖率校验。
                    # 这里必须“跳过”而不是抛错：抛错会让整本书的自动拆分直接失败，
                    # 而这个块本身没有任何可朗读内容需要保留。
                    continue
                reconciled = [SegmentScript(role_id="narrator", text=part_text)]
            if analyze_narration:
                reconciled = [replace(segment, text_kind=segment.text_kind or 'unknown') for segment in reconciled]
                from .narration import complete_narration_evidence
                reconciled = complete_narration_evidence(reconciled, source_text, narration_context)
            chapter_segments.extend(ground_narration_segments(reconciled, source_text))
        generated_chapters.append(
            ChapterScript(
                chapter_index=chapter_index,
                title=title,
                segments=_merge_adjacent_segments(chapter_segments),
            )
        )

    role_definitions = _build_role_definitions(
        provider, roles, language=detected_language
    )

    script = RoleScriptV1(
        schema_version=1,
        provider=provider,
        book_sha256=book_sha256,
        default_pause_after_ms=DEFAULT_PAUSE_AFTER_MS,
        roles=role_definitions,
        chapters=tuple(generated_chapters),
    )
    validation = validate_role_script(
        script,
        expected_book_sha256=book_sha256,
        chapters=chapters,
        chapter_start=chapter_start,
        chapter_end=chapter_end,
    )
    if not validation.ok or validation.script is None:
        raise DeepSeekSplitError(f"DeepSeek 剧本校验失败：{_format_validation_error(validation.report)}")
    reports.warnings.extend(validation.report.warnings)
    return validation.script


def role_script_to_dict(script: RoleScriptV1) -> Dict[str, Any]:
    """把领域模型转回 RoleScriptV1 JSON 对象。"""
    from .models import RoleScriptV2

    if isinstance(script, RoleScriptV2):
        from .v2_io import role_script_v2_to_dict

        return role_script_v2_to_dict(script)
    return {
        "schema_version": script.schema_version,
        "provider": script.provider,
        "book_sha256": script.book_sha256,
        "default_pause_after_ms": script.default_pause_after_ms,
        "roles": {
            role_id: {
                "display_name": role.display_name,
                "provider_params": dict(role.provider_params),
                **({"gender": role.gender} if role.gender is not None else {}),
            }
            for role_id, role in script.roles.items()
        },
        "chapters": [
            {
                "chapter_index": chapter.chapter_index,
                "title": chapter.title,
                "segments": [
                    {
                        "role_id": segment.role_id,
                        "text": segment.text,
                        **({'text_kind': segment.text_kind} if segment.text_kind is not None else {}),
                        **({"tone": segment.tone} if segment.tone is not None else {}),
                        **(
                            {"pause_after_ms": segment.pause_after_ms}
                            if segment.pause_after_ms is not None
                            else {}
                        ),
                    }
                    for segment in chapter.segments
                ],
            }
            for chapter in script.chapters
        ],
    }


def write_role_script(script: RoleScriptV1, path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(
        json.dumps(role_script_to_dict(script), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(destination)
    return destination
