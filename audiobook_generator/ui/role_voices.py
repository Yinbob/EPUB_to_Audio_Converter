"""网页角色声音档案：固定身份参数，并持久保存克隆参考。"""
from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path

MIMO_PROFILE_FIELDS = frozenset({
    'voice_mode', 'voice_description', 'voice_profile_id', 'voice_version',
    'voice_language', 'reference_audio_path', 'reference_audio_sha256',
})

# 已人工确认的项目音色；只在本地选择，试听／生成时复用克隆请求链路。
SAVED_ROLE_VOICES = {
    'saved_bryce_young_en': {
        'label': '青年男声 · Bryce（英语）',
        'path': Path(__file__).resolve().parents[2] / 'voices' / 'bryce_young_en.wav',
        'sha256': '0ef58edb31d5bb0f3a5111f1d36e6afb9ba9da022627ce11f446072bed912a14',
    },
}


def role_voice_choices():
    from audiobook_generator.tts_providers.openai_tts_provider import get_openai_supported_voices
    return ([(item['label'], key) for key, item in SAVED_ROLE_VOICES.items()]
            + [(voice, voice) for voice in get_openai_supported_voices()])


def saved_role_voice_key(params):
    if params.get('voice_mode') == 'clone':
        for key, item in SAVED_ROLE_VOICES.items():
            if params.get('reference_audio_sha256') == item['sha256']:
                return key
    return None


def review_voice_identity(script, role_id):
    """按声音来源分组，忽略人物ID、语速等表演参数；不推断实际音频声纹。"""
    params = script.roles[role_id].provider_params
    mode = params.get('voice_mode') or 'preset'
    if mode == 'clone':
        reference = params.get('reference_audio_sha256') or params.get('reference_audio_path')
        identity = ('clone', reference or role_id)
        saved = saved_role_voice_key(params)
        label = SAVED_ROLE_VOICES[saved]['label'] if saved else '参考音克隆'
    elif mode == 'design':
        description = ' '.join(str(params.get('voice_description') or '').split())
        identity = ('design', description or role_id)
        label = '描述音色' + (f' · {description[:36]}' if description else '（未填写描述）')
    else:
        voice = (params.get('voice_id') or params.get('voice')) if script.provider == 'minimax' else (params.get('voice') or params.get('voice_id'))
        identity = ('preset', voice or role_id)
        label = str(voice) if voice else '未指定声音'
    key = hashlib.sha256(json.dumps((script.provider, identity), ensure_ascii=False).encode()).hexdigest()
    return key, label


def review_voice_choices(script, selected='__all__'):
    from collections import Counter
    counts = Counter(s.role_id for c in script.chapters for s in c.segments)
    groups = {}
    for role_id, role in script.roles.items():
        key, label = review_voice_identity(script, role_id)
        group = groups.setdefault(key, {'label': label, 'names': [], 'count': 0})
        if counts[role_id]:
            group['names'].append(role.display_name)
        group['count'] += counts[role_id]
    choices = [('全部音色', '__all__')]
    for key, group in groups.items():
        if group['count'] or key == selected:
            names = ' / '.join(group['names'][:3]) + (' 等' if len(group['names']) > 3 else '')
            choices.append((f"{group['label']} · {names or '暂无使用段落'} · {group['count']} 段", key))
    return choices


def make_voice_profile(role_id, mode, voice, description, reference, language, pace,
                       instructions, output_dir):
    if mode not in {'preset', 'design', 'clone'} or language not in {'en', 'zh'}:
        raise ValueError('请选择有效的声音来源和朗读语言')
    if isinstance(pace, bool) or not math.isfinite(float(pace)) or not 0.25 <= float(pace) <= 4:
        raise ValueError('角色语速必须在0.25～4之间')
    if mode == 'preset' and voice in SAVED_ROLE_VOICES:
        from audiobook_generator.tts_providers.mimo_reference import load_clone_reference
        saved = SAVED_ROLE_VOICES[voice]
        reference = str(saved['path'])
        # 固定登记指纹，不能把被替换的参考音静默登记为同一个预设。
        load_clone_reference(reference, saved['sha256'])
        mode = 'clone'
    params = {'voice_mode': mode, 'voice_language': language, 'speed': float(pace)}
    if str(instructions or '').strip():
        params['instructions'] = str(instructions).strip()
    if mode == 'preset':
        from audiobook_generator.tts_providers.openai_tts_provider import get_openai_supported_voices
        if voice not in get_openai_supported_voices():
            raise ValueError('请选择有效的MiMo内置声音')
        params['voice'] = voice
    elif mode == 'design':
        description = str(description or '').strip()
        if not description or len(description) > 1500:
            raise ValueError('请填写1～1500字符的声音描述')
        params['voice_description'] = description
    else:
        from audiobook_generator.tts_providers.mimo_reference import load_clone_reference
        if not reference:
            raise ValueError('请上传已确认的参考音频')
        source = Path(reference).resolve()
        if source.stat().st_size > 7_500_000:
            raise ValueError('参考音频过大，请使用短WAV参考')
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        raw, _ = load_clone_reference(str(source), digest)
        destination = Path(output_dir).expanduser().resolve() / '.voice_references' / (digest + '.wav')
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=destination.parent, suffix='.tmp')
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(raw)
            os.replace(temporary, destination)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        params.update(reference_audio_path=str(destination), reference_audio_sha256=digest)
    identity = {k: v for k, v in params.items() if k not in {'reference_audio_path'}}
    version = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    params.update(voice_profile_id='ui_' + hashlib.sha256(str(role_id).encode()).hexdigest()[:16],
                  voice_version=version)
    return params
