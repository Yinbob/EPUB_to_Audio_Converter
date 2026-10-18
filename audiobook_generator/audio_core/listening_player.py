"""离线盲化试听页：只接收公开题目，不能读取私有答案。"""
import json
from pathlib import Path

from .store import fingerprint


def render_listening_player(payload):
    # 白名单避免今后公开数据扩展时将内部字段意外嵌入页面。
    trials = [{'trial_id':t['trial_id'], 'audio':t['audio'],
               'reference_voices':dict(t['reference_voices'])} for t in payload['trials']]
    data = {'trials':trials, 'pack_id':fingerprint(trials)}
    encoded = json.dumps(data, ensure_ascii=False).replace('&','\\u0026').replace('<','\\u003c').replace('>','\\u003e')
    encoded = encoded.replace('\u2028','\\u2028').replace('\u2029','\\u2029')
    template = Path(__file__).with_suffix('.html').read_text(encoding='utf-8')
    return template.replace('__LISTENING_PAYLOAD__',encoded)
