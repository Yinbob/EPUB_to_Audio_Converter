"""角色模式的 ffmpeg/ffprobe 音频管线。

每段合成结果先探测实际格式，再解码为统一的 PCM WAV；只在最后把整章编码一次。
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from audiobook_generator.core.audio_tags import AudioTags
from audiobook_generator.utils.utils import set_audio_tags

from .models import AudioArtifact, ChapterSynthesisPlan

logger = logging.getLogger(__name__)

FINAL_OUTPUT_FORMATS = ("mp3", "wav", "flac")


def resolve_ffmpeg_binary(name: str) -> Optional[str]:
    env_name = "FFMPEG_PATH" if name == "ffmpeg" else "FFPROBE_PATH"
    env_path = os.environ.get(env_name)
    if env_path and os.path.isfile(env_path):
        return env_path
    found = shutil.which(name)
    if found:
        return found
    for candidate in (f"/opt/homebrew/bin/{name}", f"/usr/local/bin/{name}", f"/usr/bin/{name}"):
        if os.path.isfile(candidate):
            return candidate
    return None


def require_ffmpeg_tools() -> tuple[str, str]:
    ffmpeg = resolve_ffmpeg_binary("ffmpeg")
    ffprobe = resolve_ffmpeg_binary("ffprobe")
    if not ffmpeg or not ffprobe:
        missing = "ffmpeg" if not ffmpeg else "ffprobe"
        raise RuntimeError(f"角色模式需要 {missing}；请安装 ffmpeg 后重试")
    return ffmpeg, ffprobe


def _run(command: Sequence[str]) -> subprocess.CompletedProcess:
    logger.debug("运行音频命令: %s", " ".join(command))
    try:
        return subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        detail = stderr or (exc.stdout or "").strip() or "ffmpeg/ffprobe 未返回错误详情"
        raise RuntimeError(
            f"音频命令执行失败（退出码 {exc.returncode}）：{detail}"
        ) from exc


def _normalize_format(format_name: str, codec_name: str, path: str) -> str:
    value = f"{format_name},{codec_name}".lower()
    if "flac" in value:
        return "flac"
    if "mp3" in value or "mpeg" in value:
        return "mp3"
    if "wav" in value or "pcm" in value:
        return "wav"
    suffix = Path(path).suffix.lower().lstrip(".")
    return suffix or "unknown"


def probe_audio(path: str, ffprobe_path: Optional[str] = None) -> Dict[str, Any]:
    ffprobe = ffprobe_path or resolve_ffmpeg_binary("ffprobe")
    if not ffprobe:
        raise RuntimeError("角色模式需要 ffprobe；请安装 ffmpeg 后重试")
    proc = _run([
        ffprobe,
        "-v",
        "error",
        "-show_streams",
        "-show_format",
        "-of",
        "json",
        path,
    ])
    payload = json.loads(proc.stdout or "{}")
    streams = payload.get("streams") or []
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    if audio is None:
        raise ValueError(f"未检测到音频流：{path}")
    duration = payload.get("format", {}).get("duration") or audio.get("duration") or 0
    return {
        "format": _normalize_format(
            payload.get("format", {}).get("format_name", ""),
            audio.get("codec_name", ""),
            path,
        ),
        "sample_rate": int(audio.get("sample_rate") or 0),
        "channels": int(audio.get("channels") or 0),
        "duration_ms": int(float(duration) * 1000) if duration else 0,
    }


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_audio_artifact(path: str, cache_key: str = "", ffprobe_path: Optional[str] = None) -> AudioArtifact:
    metadata = probe_audio(path, ffprobe_path)
    return AudioArtifact(
        path=str(path),
        format=metadata["format"],
        sample_rate=metadata["sample_rate"],
        channels=metadata["channels"],
        duration_ms=metadata["duration_ms"],
        sha256=_sha256_file(path),
        cache_key=cache_key,
    )


def atempo_chain(speed: float) -> list[str]:
    """把任意正速度拆成 ffmpeg atempo 支持的 0.5..2.0 串联参数。"""
    if not math.isfinite(speed) or speed <= 0:
        raise ValueError("atempo 速度必须是大于 0 的有限数字")
    filters = []
    remaining = float(speed)
    while remaining > 2.0:
        filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        filters.append("atempo=0.5")
        remaining /= 0.5
    if abs(remaining - 1.0) > 1e-9:
        filters.append(f"atempo={remaining:.8f}")
    return filters


def _channel_layout(channels: int) -> str:
    if channels == 1:
        return "mono"
    if channels == 2:
        return "stereo"
    raise ValueError(f"角色音频管线只支持单声道或双声道，实际为 {channels}")


def _decode_normalized(
    artifact: AudioArtifact,
    output_wav: str,
    sample_rate: int,
    channels: int,
    speed: Optional[float],
    ffmpeg_path: str,
) -> None:
    filters = []
    if speed is not None and abs(speed - 1.0) > 1e-9:
        filters.extend(atempo_chain(speed))
    command = [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        artifact.path,
        "-vn",
        "-ar",
        str(sample_rate),
        "-ac",
        str(channels),
    ]
    if filters:
        command += ["-filter:a", ",".join(filters)]
    command += ["-c:a", "pcm_s16le", output_wav]
    _run(command)


def render_role_preview(artifact: AudioArtifact, profile, provider: str, output_wav: str) -> AudioArtifact:
    """试听和整章使用同一条变速管线；MiniMax 已在服务端应用 speed。"""
    ffmpeg, ffprobe = require_ffmpeg_tools()
    speed = float(profile.provider_params.get("speed", 1.0)) if provider == "openai" else None
    _decode_normalized(
        artifact, output_wav, artifact.sample_rate or 24000,
        artifact.channels or 1, speed, ffmpeg,
    )
    return build_audio_artifact(output_wav, ffprobe_path=ffprobe)


def _write_silence(output_wav: str, duration_ms: int, sample_rate: int, channels: int, ffmpeg_path: str) -> None:
    if duration_ms <= 0:
        raise ValueError("静音时长必须大于 0")
    _run([
        ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"anullsrc=r={sample_rate}:cl={_channel_layout(channels)}",
        "-t",
        f"{duration_ms / 1000:.3f}",
        "-c:a",
        "pcm_s16le",
        output_wav,
    ])


def _concat_file_line(path: str) -> str:
    # concat demuxer 会把列表中的相对路径相对于 concat.txt 所在目录解析。
    # 角色模式传入的 work_dir 可能是相对路径，因此这里必须写绝对路径，
    # 否则 ffmpeg 会在章节临时目录下再次拼接路径并返回 254。
    absolute_path = os.path.abspath(os.fspath(path))
    escaped = absolute_path.replace("'", "'\\''")
    return f"file '{escaped}'\n"


def _final_encode(concat_list: str, output_file: str, output_format: str, ffmpeg_path: str) -> None:
    codec_args = {
        "mp3": ["-c:a", "libmp3lame", "-q:a", "2"],
        "wav": ["-c:a", "pcm_s16le"],
        "flac": ["-c:a", "flac"],
    }.get(output_format)
    if codec_args is None:
        raise ValueError(f"不支持的角色模式输出格式：{output_format}")
    _run([
        ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        concat_list,
        "-vn",
        "-map_metadata",
        "-1",
        *codec_args,
        output_file,
    ])


def assemble_chapter_audio(
    plan: ChapterSynthesisPlan,
    artifacts: Sequence[AudioArtifact],
    output_file: str,
    audio_tags: AudioTags,
    work_dir: str,
    ffmpeg_path: Optional[str] = None,
) -> AudioArtifact:
    """按顺序合并章节，原子替换输出并写入格式对应的标签。"""
    if plan.output_format not in FINAL_OUTPUT_FORMATS:
        raise ValueError(f"不支持的角色模式输出格式：{plan.output_format}")
    if len(artifacts) != len(plan.units):
        raise ValueError(f"章节 {plan.chapter_index} 的 artifact 数量与 segment 数量不一致")
    if not artifacts:
        raise ValueError("章节没有可合并的音频")
    for artifact in artifacts:
        if not os.path.isfile(artifact.path):
            raise FileNotFoundError(f"segment 音频不存在：{artifact.path}")
    required_ffmpeg, required_ffprobe = require_ffmpeg_tools()
    ffmpeg = ffmpeg_path or required_ffmpeg
    ffprobe = required_ffprobe
    Path(work_dir).mkdir(parents=True, exist_ok=True)
    normalized_dir = os.path.join(work_dir, "normalized")
    os.makedirs(normalized_dir, exist_ok=True)

    base_probe = probe_audio(artifacts[0].path, ffprobe)
    sample_rate = base_probe["sample_rate"] or 32000
    channels = base_probe["channels"] or 1
    if channels not in (1, 2):
        raise ValueError(f"角色音频管线只支持单声道或双声道，实际为 {channels}")

    normalized_paths = []
    timeline, sample_cursor = [], 0
    for index, artifact in enumerate(artifacts):
        unit = plan.units[index]
        speed = None
        if plan.provider == "openai":
            speed = float(unit.profile.provider_params.get("speed", 1.0))
        target = os.path.join(normalized_dir, f"segment_{index + 1:04d}.wav")
        _decode_normalized(artifact, target, sample_rate, channels, speed, ffmpeg)
        import wave
        with wave.open(target, 'rb') as normalized:
            frames = normalized.getnframes()
        from dataclasses import asdict
        timeline.append({'chunk_id': unit.unit_id, 'role_id': unit.role_id, 'start_sample': sample_cursor,
            'end_sample': sample_cursor + frames, 'source_span': asdict(unit.source_span) if unit.source_span else None})
        sample_cursor += frames
        normalized_paths.append(target)
        if index < len(artifacts) - 1 and unit.pause_after_ms > 0:
            silence = os.path.join(normalized_dir, f"pause_{index + 1:04d}.wav")
            _write_silence(silence, unit.pause_after_ms, sample_rate, channels, ffmpeg)
            normalized_paths.append(silence)
            with wave.open(silence, 'rb') as pause:
                sample_cursor += pause.getnframes()

    concat_list = os.path.abspath(os.path.join(work_dir, "concat.txt"))
    with open(concat_list, "w", encoding="utf-8") as file_obj:
        for path in normalized_paths:
            file_obj.write(_concat_file_line(path))

    output_dir = os.path.dirname(os.path.abspath(output_file)) or "."
    os.makedirs(output_dir, exist_ok=True)
    temp_output = os.path.join(work_dir, f"chapter_final.{plan.output_format}")
    try:
        _final_encode(concat_list, temp_output, plan.output_format, ffmpeg)
    except Exception:
        try:
            os.remove(temp_output)
        except OSError:
            pass
        raise
    os.replace(temp_output, output_file)
    try:
        set_audio_tags(output_file, audio_tags, output_format=plan.output_format)
    except Exception:
        try:
            os.remove(output_file)
        except OSError:
            pass
        raise
    from audiobook_generator.services.provenance import write_timeline
    write_timeline(output_file, plan.chapter_index, timeline, sample_rate=sample_rate)
    return build_audio_artifact(
        output_file,
        cache_key=f"chapter:{plan.chapter_index}",
        ffprobe_path=ffprobe,
    )
