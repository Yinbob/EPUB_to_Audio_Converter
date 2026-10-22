"""轻量引擎目录；不导入本地模型或探测 CUDA。"""
from .models import MiMo, MiniMax, Edge, Qwen, Chatterbox, VoxCPM


def capabilities():
    from audiobook_generator.tts_providers.openai_tts_provider import (
        get_openai_supported_models, get_openai_supported_voices, get_openai_supported_output_formats)
    from audiobook_generator.tts_providers.minimax_tts_provider import (
        get_minimax_supported_models, get_minimax_supported_voices, get_minimax_supported_output_formats)
    from audiobook_generator.tts_providers.qwen_tts_provider import get_qwen_supported_voices, get_qwen_supported_languages
    from audiobook_generator.utils.voxcpm_voices import get_voxcpm_voice_choices, VOXCPM_DEFAULT_VOICE_VALUE
    from audiobook_generator.tts_providers.edge_tts_provider import get_edge_tts_supported_voices, get_edge_tts_supported_language
    items = []
    for cls, label, models, voices, formats, languages in [
        (MiMo, 'MiMo', get_openai_supported_models(), get_openai_supported_voices(), get_openai_supported_output_formats(), []),
        (MiniMax, 'MiniMax', get_minimax_supported_models(), get_minimax_supported_voices(), get_minimax_supported_output_formats(), []),
        (Edge, 'Edge', [], get_edge_tts_supported_voices(), ['mp3'], get_edge_tts_supported_language()),
        (Qwen, 'Qwen', [], get_qwen_supported_voices(), ['mp3'], get_qwen_supported_languages()),
        (Chatterbox, 'Chatterbox', ['chatterbox-multilingual-v3'], [], ['mp3', 'wav', 'aac', 'flac'], []),
        (VoxCPM, 'VoxCPM', ['openbmb/VoxCPM2'], [value for label, value in get_voxcpm_voice_choices()], ['mp3', 'wav', 'aac', 'flac'], []),
    ]:
        name = cls.model_fields['provider'].default
        if not isinstance(name, str):
            name = cls.model_fields['provider'].annotation.__args__[0]
        defaults = cls(provider=name).model_dump()
        if name == 'voxcpm':
            defaults['voice'] = VOXCPM_DEFAULT_VOICE_VALUE
        items.append(dict(id=name, label=label, models=models, voices=list(voices), formats=formats,
                          languages=languages, roles=name in ('openai', 'minimax'), quality=name == 'openai',
                          defaults=defaults, fields=cls.model_json_schema()['properties'],
                          devices=['auto', 'cpu', 'cuda', 'mps'] if name in ('chatterbox', 'voxcpm') else []))
    return items
