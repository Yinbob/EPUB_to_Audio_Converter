from unittest.mock import MagicMock
from audiobook_generator.config.general_config import GeneralConfig


def _base_args(**overrides):
    values = dict(
        input_file='examples/The_Life_and_Adventures_of_Robinson_Crusoe.epub',
        output_folder='output',
        preview=False,
        output_text=False,
        title_mode='auto',
        log='INFO',
        newline_mode='double',
        chapter_start=1,
        chapter_end=-1,
        remove_endnotes=False,
        remove_reference_numbers=False,
        search_and_replace_file=None,
        worker_count=1,
        use_pydub_merge=False,
        no_prompt=True,
        language='zh-CN',
    )
    values.update(overrides)
    return MagicMock(**values)


def get_openai_config():
    return GeneralConfig(_base_args(
        tts='openai',
        voice_name='冰糖',
        output_format='mp3',
        model_name='mimo-v2.5-tts',
        speed=1.0,
        instructions=None,
        stream=False,
    ))


def get_minimax_config():
    return GeneralConfig(_base_args(
        tts='minimax',
        voice_name='male-qn-qingse',
        output_format='mp3',
        model_name='speech-2.8-hd',
        speed=1.0,
    ))
