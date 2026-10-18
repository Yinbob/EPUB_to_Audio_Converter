"""MiMo克隆参考：只在请求前编码，日志及缓存配置只保存路径和指纹。"""
from __future__ import annotations

import base64
import hashlib
import io
import re
from pathlib import Path

import soundfile as sf

MAX_ENCODED_REFERENCE_BYTES = 10_000_000


def load_clone_reference(path, digest):
    if (not isinstance(path, str) or not Path(path).is_absolute()
            or not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest)):
        raise ValueError('克隆参考需要本地绝对路径及64位小写SHA256')
    source = Path(path).resolve()
    if not source.is_file() or source.suffix.lower() != '.wav':
        raise ValueError('首轮MiMo克隆仅接受已有本地PCM16 WAV参考')
    size = source.stat().st_size
    if 4 * ((size + 2) // 3) > MAX_ENCODED_REFERENCE_BYTES:
        raise ValueError('克隆参考Base64编码后不能超过10MB')
    raw = source.read_bytes()
    if 4 * ((len(raw) + 2) // 3) > MAX_ENCODED_REFERENCE_BYTES:
        raise ValueError('克隆参考Base64编码后不能超过10MB')
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('克隆参考音频指纹不符；请核验新文件并更新声音版本')
    try:
        info = sf.info(io.BytesIO(raw))
    except (RuntimeError, sf.LibsndfileError) as exc:
        raise ValueError('克隆参考不是有效WAV音频') from exc
    if info.format != 'WAV' or info.subtype != 'PCM_16' or info.frames <= 0 or info.channels not in (1, 2):
        raise ValueError('克隆参考必须是非空、单或双声道PCM16 WAV')
    return raw, {'reference_audio_path': str(source), 'reference_audio_sha256': digest}


def clone_reference_data_uri(route):
    raw, _ = load_clone_reference(route['reference_audio_path'], route['reference_audio_sha256'])
    return 'data:audio/wav;base64,' + base64.b64encode(raw).decode('ascii')
