"""MiMo角色请求解析；内部档案ID不作voice发送，克隆参考须本地校验。"""
from __future__ import annotations

MODELS = {'preset': 'mimo-v2.5-tts', 'design': 'mimo-v2.5-tts-voicedesign',
          'clone': 'mimo-v2.5-tts-voiceclone'}
REQUEST_VERSION = 'mimo-role-request-v2'
CLONE_DEFAULT_EN = ('Speak in clear, neutral American English at a steady, moderate audiobook pace. '
                    'Keep the reference speaker voice identity. Read only the supplied text, without additions, omissions or repeats.')


def resolve_voice(config, params=None, *, tone=None):
    params = dict(params or {})
    model_default = getattr(config, 'model_name', None) or MODELS['preset']
    custom = bool(getattr(config, 'allow_custom_tts', False))
    if model_default not in MODELS.values() and not custom:
        raise ValueError('只支持MiMo内置声音、VoiceDesign或VoiceClone模型')
    mode = params.get('voice_mode', 'preset' if 'voice' in params else
                      'design' if model_default == MODELS['design'] else
                      'clone' if model_default == MODELS['clone'] else 'preset')
    if mode not in MODELS:
        raise ValueError('voice_mode 只允许 preset/design/clone')
    instructions = params.get('instructions', getattr(config, 'instructions', None))
    if instructions is not None and not isinstance(instructions, str):
        raise ValueError('朗读指令必须是字符串')
    language = params.get('voice_language') or getattr(config, 'language', '') or ''
    english = str(language).lower().startswith('en')
    description = params.get('voice_description')
    if mode != 'clone' and any(k in params for k in ('reference_audio_path', 'reference_audio_sha256')):
        raise ValueError('只有clone模式可以携带参考音频')
    if mode == 'clone':
        if 'voice' in params or description is not None:
            raise ValueError('克隆声音不能同时设置内置voice或声音设计描述')
        if any(not isinstance(params.get(k), str) or not params[k].strip()
               for k in ('voice_profile_id', 'voice_version', 'voice_language')):
            raise ValueError('克隆声音必须有声音档案ID、版本和语言')
        if params['voice_language'] not in {'en', 'zh'}:
            raise ValueError('克隆声音语言只允许en/zh')
        from .mimo_reference import load_clone_reference
        _, reference = load_clone_reference(params.get('reference_audio_path'), params.get('reference_audio_sha256'))
        effective = instructions or (CLONE_DEFAULT_EN if english else
            '使用清晰自然的普通话和稳定适中的有声书语速。保持参考音的声音身份，只朗读所给正文，不增加、删减或重复。')
        tone = tone or params.get('_tone')
        if tone:
            effective += '\n' + (f'Tone requirement: {tone}' if english else f'语气要求：{tone}')
        return {'version': 'mimo-role-request-clone-v1', 'mode': mode, 'model': MODELS[mode],
                'voice': None, 'instructions': effective, 'stream': False, 'format': 'wav',
                'voice_profile_id': params['voice_profile_id'], 'voice_version': params['voice_version'],
                'language': language, 'optimize_text_preview': None, **reference}
    if mode == 'design':
        if 'voice' in params:
            raise ValueError('描述声音不能同时携带内置 voice')
        if not params and model_default == MODELS['design']:
            description, instructions = instructions, None
        if not isinstance(description, str) or not description.strip() or len(description) > 1500:
            raise ValueError('VoiceDesign 需要有效固定声音描述，不能回退到内置声音')
        voice, stream, extension = None, False, 'wav'
    else:
        if description is not None:
            raise ValueError('内置声音不支持声音设计描述')
        from .openai_tts_provider import get_openai_supported_voices
        voice = params.get('voice') or getattr(config, 'voice_name', None) or 'mimo_default'
        if voice not in get_openai_supported_voices() and not custom:
            raise ValueError(f'不支持的 MiMo 内置声音：{voice}')
        stream = bool(getattr(config, 'stream', False))
        extension = 'wav' if stream else getattr(config, 'output_format', None) or 'wav'
    tone = tone or params.get('_tone')
    effective = '\n'.join(filter(None, [
        ('Fixed voice identity: ' + description) if description and english else
            ('固定声音身份：' + description) if description else None,
        instructions,
        (f'Tone requirement: {tone}' if english else f'语气要求：{tone}') if tone else None,
        'Unless an explicit pace is requested above, use a steady, moderate audiobook pace. '
        'Keep the voice identity consistent. Read only the supplied text without omissions, additions or repeats.'
        if english else '除非上文明确要求快慢，否则使用稳定、适中的有声书语速。保持声音身份一致，读全句首和句尾，只朗读所给正文，不增加、删减或重复文字。']))
    return {'version': REQUEST_VERSION, 'mode': mode, 'model': model_default if mode == 'preset' else MODELS[mode], 'voice': voice,
            'instructions': effective, 'stream': stream, 'format': extension,
            'voice_profile_id': params.get('voice_profile_id'), 'voice_version': params.get('voice_version'),
            'language': language, 'optimize_text_preview': False if mode == 'design' else None}
