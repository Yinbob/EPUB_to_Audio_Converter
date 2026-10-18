"""Flipped 单章准备及有请求记录的角色草稿；不执行TTS。"""
import argparse
import hashlib
import json
import shutil
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
OUTPUT = ROOT / 'audiobook_output/flipped_chapter_pilot_20261017'


def sha(value):
    return hashlib.sha256(value).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def prepare():
    from audiobook_generator.config.general_config import GeneralConfig
    from audiobook_generator.book_parsers.epub_book_parser import EpubBookParser
    if OUTPUT.exists():
        raise ValueError('已有单章准备材料，不覆盖')
    original = Path('/Users/yinzh/Desktop/Flipped.epub')
    config = GeneralConfig(None)
    config.input_file = str(original)
    settings = {'newline_mode': 'double', 'title_mode': 'auto', 'remove_endnotes': False,
                'remove_reference_numbers': False, 'search_and_replace_file': ''}
    for key, value in settings.items():
        setattr(config, key, value)
    parser = EpubBookParser(config)
    raw = parser.get_chapters('   ')
    selected = [(i, title, text) for i, (title, text) in enumerate(raw, 1) if text.strip()]
    chapters = [(title, text) for _, title, text in selected]
    chapter = next(i for i, (title, _) in enumerate(chapters, 1) if title == 'Diving_Under')
    assert chapter == 5
    OUTPUT.mkdir(parents=True)
    copy = OUTPUT / 'Flipped.source.epub'
    shutil.copy2(original, copy)
    assert sha(copy.read_bytes()) == sha(original.read_bytes())
    save(OUTPUT/'source_chapters.json', {'schema_version': 'flipped-single-chapter-source-v1',
        'book_path': str(copy), 'original_book_path': str(original), 'book_sha256': sha(copy.read_bytes()),
        'title': parser.get_book_title(), 'author': parser.get_book_author(),
        'parser_settings': settings, 'break_string': '   ', 'selected_conversion_chapter': chapter,
        'raw_document_index': selected[chapter-1][0],
        'chapters': [{'chapter_index': i, 'raw_document_index': raw_index, 'title': title, 'text': text,
                      'text_sha256': sha(text.encode())}
                     for i, (raw_index, title, text) in enumerate(selected, 1)]})
    (OUTPUT/'chapter_05.source.txt').write_text(chapters[chapter-1][1], encoding='utf-8')
    save(OUTPUT/'execution_plan.json', {'schema_version': 'flipped-single-chapter-plan-v1',
        'status': 'source_prepared_pending_role_draft', 'source_scope': 'one_chapter_only',
        'chapter_index': chapter, 'raw_document_index': selected[chapter-1][0],
        'characters': len(chapters[chapter-1][1]), 'words_whitespace_estimate': len(chapters[chapter-1][1].split()),
        'llm_chunk_chars': 6000, 'max_llm_requests': 6, 'llm_sdk_retries': 0,
        'tts_requests': 0, 'full_book_role_ranking_allowed': False,
        'book_sha256': sha(copy.read_bytes())})
    print('单章原文准备完成：Diving Under，正式转换编号5。', flush=True)


def split():
    from audiobook_generator.role_script import deepseek_splitter as splitter
    from audiobook_generator.role_script.models import CharacterEntity
    from audiobook_generator.role_script.errors import ValidationReport
    from audiobook_generator.role_script.v2_generation import upgrade_generated_script
    from audiobook_generator.role_script.project_store import parser_fingerprint
    from audiobook_generator.role_script.validator import validate_role_script
    from audiobook_generator.utils.deepseek_config import get_deepseek_credentials
    output = OUTPUT/'chapter_05.roles.proposed.json'
    if output.exists():
        raise ValueError('角色草稿已存在，不能重复请求')
    source = json.loads((OUTPUT/'source_chapters.json').read_text())
    assert sha(Path(source['book_path']).read_bytes()) == source['book_sha256']
    chapters = [(c['title'], c['text']) for c in source['chapters']]
    api_key, base_url, model = get_deepseek_credentials()
    if not api_key:
        raise ValueError('缺少已配置的DeepSeek凭据')
    client = splitter._create_client(api_key, base_url)
    receipts = OUTPUT/'llm_requests'
    receipts.mkdir(exist_ok=True)

    class Recorder:
        def create(self, **kwargs):
            key = sha(json.dumps(kwargs, ensure_ascii=False, sort_keys=True).encode())
            paths = sorted(receipts.glob('*.json'))
            for path in paths:
                record = json.loads(path.read_text())
                if record['request_sha256'] == key and record['status'] == 'succeeded':
                    content = record['response']['choices'][0]['message']['content']
                    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
            if len(paths) >= 6:
                raise ValueError('本章文本请求达到6次上限，停止自动尝试')
            path = receipts/f'{len(paths)+1:03d}.json'
            record = {'request_sha256': key, 'request': kwargs, 'status': 'started'}
            save(path, record)
            print(f'DeepSeek实际请求 {len(paths)+1}/6', flush=True)
            try:
                response = client.chat.completions.create(**kwargs)
                record.update(status='succeeded', response=response.model_dump(mode='json'))
                save(path, record)
                return response
            except Exception as exc:
                record.update(status='failed', error_type=type(exc).__name__)
                save(path, record)
                raise

    proxy = SimpleNamespace(chat=SimpleNamespace(completions=Recorder()))
    report = ValidationReport(schema_version=1)
    chapter = source['selected_conversion_chapter']
    with patch.object(splitter, '_create_client', return_value=proxy):
        generated = splitter.split_chapters_with_deepseek(chapters, chapter, chapter, 'openai',
            source['book_sha256'], api_key, base_url, model, report=report, language='en',
            progress=lambda message: print(message, flush=True))
    save(OUTPUT/'split_validation.json', report.to_dict())
    splitter.write_role_script(generated, OUTPUT/'chapter_05.roles.raw_v1.json')
    entities = {role: CharacterEntity(value.display_name, voice_profile_id='voice_'+role,
                                    gender=value.gender) for role, value in generated.roles.items()}
    upgraded = upgrade_generated_script(generated, chapters, entities,
        parser_fingerprint=parser_fingerprint(source['parser_settings']), model=model)
    upgraded = replace(upgraded, registry_complete=False, chapters=tuple(replace(c, segments=tuple(
        replace(s, speaker=replace(s.speaker, status='proposed')) if s.speaker.status=='confirmed' else s
        for s in c.segments)) for c in upgraded.chapters))
    checked = validate_role_script(upgraded, expected_book_sha256=source['book_sha256'],
                                   chapters=chapters, chapter_start=chapter, chapter_end=chapter)
    if not checked.ok:
        raise ValueError('V2角色草稿未通过来源校验')
    assert ''.join(s.text for s in upgraded.chapters[0].segments) == chapters[chapter-1][1]
    splitter.write_role_script(upgraded, output)
    save(OUTPUT/'draft_summary.json', {'schema_version': 'flipped-role-draft-summary-v1',
        'status': 'proposed_not_human_confirmed', 'book_sha256': source['book_sha256'],
        'chapter_index': chapter, 'characters': len(chapters[chapter-1][1]),
        'segments': len(upgraded.chapters[0].segments), 'roles': {r:v.display_name for r,v in upgraded.roles.items()},
        'source_coverage_exact': True, 'registry_complete': False,
        'human_labels': 0, 'tts_requests': 0, 'actual_llm_requests': len(list(receipts.glob('*.json'))),
        'role_script_sha256': sha(output.read_bytes())})
    print('单章V2角色草稿完成；保持归属待核验和局部范围。', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare', 'split'])
    args = parser.parse_args()
    prepare() if args.action == 'prepare' else split()
