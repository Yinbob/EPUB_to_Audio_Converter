"""MiniMax 上传/克隆工作流；中断后的不确定远端写入不自动重发。"""
import hashlib
import re
from pathlib import Path

import requests

from .common import atomic_json, read_json

BASE_URL = 'https://api.minimaxi.com'


def validate_reference(path, voice_id):
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{6,254}[A-Za-z0-9]', voice_id):
        raise ValueError('MiniMax 音色 ID 需为 8～256 位，以字母开头，仅含字母、数字、_、-，末尾不能是 _ 或 -')
    path = Path(path)
    if path.suffix.lower() not in ('.wav', '.mp3', '.m4a') or not 0 < path.stat().st_size <= 20 * 1024 * 1024:
        raise ValueError('MiniMax 参考音需为 WAV/MP3/M4A，大小不超过 20 MB')
    from pydub.utils import mediainfo
    duration = float(mediainfo(str(path)).get('duration') or 0)
    if not 10 <= duration <= 300:
        raise ValueError('MiniMax 参考音长度需为 10 秒～5 分钟')


def clone(path, voice_id, *, api_key, root, log, session=None):
    validate_reference(path, voice_id)
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    # 远端声音属于账号；换凭据不得复用另一账号的 file_id/voice_id。
    account = hashlib.sha256(api_key.encode()).hexdigest()
    key = hashlib.sha256((BASE_URL + account + voice_id + digest).encode()).hexdigest()
    target = Path(root) / '.studio' / 'minimax_clones' / (key + '.json')
    state = read_json(target, {'voice_id': voice_id, 'reference_sha256': digest})
    if state.get('phase') in ('uploading', 'cloning'):
        raise ValueError('上次 MiniMax 写入已中断，远端结果尚不确定。请在提供商控制台核对音色 ID，确认后使用现有音色试听，或换新 ID；系统不会自动重复克隆。')
    if state.get('phase') == 'cloned':
        log.info('复用已完成的 MiniMax 克隆：%s', voice_id)
        return voice_id
    http = session or requests.Session()
    headers = {'Authorization': 'Bearer ' + api_key}

    def response_json(response):
        response.raise_for_status()
        value = response.json()
        if value.get('base_resp', {}).get('status_code') != 0:
            raise ValueError('MiniMax 拒绝请求：' + str(value.get('base_resp', {}).get('status_msg', '未知错误')))
        return value

    if not state.get('file_id'):
        state['phase'] = 'uploading'
        atomic_json(target, state)
        log.info('上传 MiniMax 克隆参考音（%s 字节）', Path(path).stat().st_size)
        with Path(path).open('rb') as source:
            value = response_json(http.post(BASE_URL + '/v1/files/upload', headers=headers,
                data={'purpose': 'voice_clone'}, files={'file': (Path(path).name, source)}, timeout=(15, 120)))
        state.update(file_id=value['file']['file_id'], phase='uploaded')
        atomic_json(target, state)
    state['phase'] = 'cloning'
    atomic_json(target, state)
    log.info('创建 MiniMax 克隆音色：%s', voice_id)
    value = response_json(http.post(BASE_URL + '/v1/voice_clone', headers=headers,
        json={'file_id': state['file_id'], 'voice_id': voice_id,
              'need_noise_reduction': False, 'need_volume_normalization': False}, timeout=(15, 120)))
    if value.get('input_sensitive'):
        raise ValueError('MiniMax 未接受此参考音，请更换音频')
    state['phase'] = 'cloned'
    atomic_json(target, state)
    return voice_id
