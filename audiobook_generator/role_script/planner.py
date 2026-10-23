"""把已验证剧本转换成可 pickle 的章节合成计划。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence, Tuple

from .deepseek_splitter import differentiate_role_voices
from .errors import ValidationReport
from .models import ChapterSynthesisPlan, RoleScriptV1, SynthesisUnit, VoiceProfile
from .validator import validate_role_script

FINAL_OUTPUT_FORMATS = ("mp3", "wav", "flac")


@dataclass
class PlanningResult:
    plans: Tuple[ChapterSynthesisPlan, ...]
    report: ValidationReport

    @property
    def ok(self) -> bool:
        return self.report.ok


def build_default_provider_params(provider: str, config: Any) -> Dict[str, Any]:
    """从普通模式配置构造 fallback 的全局默认角色参数。"""
    if getattr(config, '_portable_params', None):
        return dict(config._portable_params)
    if provider == "openai":
        if getattr(config, 'model_name', None) == 'mimo-v2.5-tts-voicedesign':
            import hashlib
            import json
            description = str(getattr(config, 'instructions', '') or '').strip()
            if not description or len(description) > 1500:
                raise ValueError('VoiceDesign 请在朗读要求中填写 1～1500 字声音描述')
            params = {'voice_mode': 'design', 'voice_description': description,
                'voice_language': 'en' if str(getattr(config, 'language', '')).lower().startswith('en') else 'zh',
                'speed': float(getattr(config, 'speed', None) or 1.0), 'voice_profile_id': 'global_narrator'}
            params['voice_version'] = hashlib.sha256(json.dumps(params, sort_keys=True,
                ensure_ascii=False).encode()).hexdigest()
            return params
        return {
            "voice": getattr(config, "voice_name", None) or "mimo_default",
            "instructions": getattr(config, "instructions", None),
            "speed": float(getattr(config, "speed", None) or 1.0),
        }
    if provider == "minimax":
        return {
            "voice_id": getattr(config, "voice_name", None) or "male-qn-qingse",
            "speed": float(getattr(config, "speed", None) or 1.0),
            "pitch": 0.0,
            "volume": 1.0,
        }
    raise ValueError(f"不支持的角色模式 Provider：{provider}")


def _global_fallback_profile(profile: Dict[str, Any]) -> VoiceProfile:
    return VoiceProfile(
        role_id="__global_default__",
        display_name="全局默认音色",
        provider_params=dict(profile),
    )


def build_synthesis_plans(
    script: RoleScriptV1,
    chapters: Sequence[Tuple[str, str]],
    *,
    expected_book_sha256: str,
    provider: str,
    chapter_start: int,
    chapter_end: int,
    output_format: str,
    allow_text_override: bool = False,
    allow_title_mismatch: bool = False,
    allow_fallback: bool = False,
    fallback_profile: Optional[Dict[str, Any]] = None,
) -> PlanningResult:
    report = ValidationReport()
    if provider != script.provider:
        report.error(
            "provider_mismatch",
            "$.provider",
            f"角色剧本 provider={script.provider!r}，当前 TTS provider={provider!r}",
            script_provider=script.provider,
            tts_provider=provider,
        )
        return PlanningResult((), report)
    if output_format not in FINAL_OUTPUT_FORMATS:
        report.error(
            "unsupported_role_output_format",
            "$.output_format",
            "角色模式最终格式只支持 mp3/wav/flac",
            actual=output_format,
        )
        return PlanningResult((), report)

    # 旧版英文剧本可能是用 MiMo 中文音色和中文朗读指令生成的。中文音色读英文时
    # 容易出现节奏漂移和发音不准，因此无论从 WebUI 还是 CLI 进入合成计划，都按正文
    # 语言统一纠正音色池与 MiMo 指令；中文剧本和已经正确的英文配置保持不变。
    localized_script, voice_localized = differentiate_role_voices(script)
    if voice_localized:
        script = localized_script
        report.warn(
            "role_voice_localized",
            "$.roles",
            "检测到角色音色或 MiMo 朗读指令与正文语言不匹配，已自动切换为匹配语言的音色池。",
        )

    validation = validate_role_script(
        script,
        expected_book_sha256=expected_book_sha256,
        chapters=chapters,
        chapter_start=chapter_start,
        chapter_end=chapter_end,
        allow_text_override=allow_text_override,
        allow_title_mismatch=allow_title_mismatch,
        allow_fallback=allow_fallback,
        fallback_profile=fallback_profile,
    )
    report.extend(validation.report)
    if not validation.ok or validation.script is None:
        return PlanningResult((), report)
    normalized = validation.script
    by_index = {chapter.chapter_index: chapter for chapter in normalized.chapters}

    plans = []
    for chapter_index in range(chapter_start, chapter_end + 1):
        chapter = by_index[chapter_index]
        title = chapters[chapter_index - 1][0]
        units = []
        count = len(chapter.segments)
        for offset, segment in enumerate(chapter.segments):
            is_last = offset == count - 1
            if segment.role_id in normalized.roles:
                role = normalized.roles[segment.role_id]
                profile = VoiceProfile(
                    role_id=segment.role_id,
                    display_name=role.display_name,
                    provider_params=dict(role.provider_params),
                    tone=segment.tone,
                )
                is_fallback = False
            else:
                narrator = normalized.roles.get("narrator")
                if narrator is not None:
                    profile = VoiceProfile(
                        role_id=segment.role_id,
                        display_name=narrator.display_name,
                        provider_params=dict(narrator.provider_params),
                        tone=segment.tone,
                    )
                else:
                    fallback = _global_fallback_profile(fallback_profile or {})
                    profile = VoiceProfile(
                        role_id=segment.role_id,
                        display_name=fallback.display_name,
                        provider_params=dict(fallback.provider_params),
                        tone=segment.tone,
                    )
                is_fallback = True
            pause = 0 if is_last else (
                segment.pause_after_ms
                if segment.pause_after_ms is not None
                else normalized.default_pause_after_ms
            )
            units.append(
                SynthesisUnit(
                    unit_id=f"{chapter_index}:{offset + 1}:{segment.role_id}",
                    chapter_index=chapter_index,
                    chapter_title=title,
                    segment_index=offset + 1,
                    segment_count=count,
                    role_id=segment.role_id,
                    display_name=profile.display_name,
                    text=segment.text,
                    profile=profile,
                    tone=segment.tone,
                    pause_after_ms=pause,
                    is_fallback=is_fallback,
                    source_span=segment.source_span,
                    segment_id=segment.segment_id,
                )
            )
        plans.append(
            ChapterSynthesisPlan(
                chapter_index=chapter_index,
                title=title,
                units=tuple(units),
                output_format=output_format,
                provider=script.provider,
            )
        )
    return PlanningResult(tuple(plans), report)


def render_proofing_text(plan: ChapterSynthesisPlan) -> str:
    """导出带角色显示名的校对文本；音频路径不会使用该渲染结果。"""
    lines = []
    for unit in plan.units:
        lines.append(f"【{unit.display_name}】{unit.text}")
    return "\n".join(lines)
