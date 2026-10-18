"""仅在本地准备两章叙述者探针范围；不读取凭证，不创建API客户端。"""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def main():
    from audiobook_generator.ui import web_ui
    from audiobook_generator.role_script.deepseek_splitter import _split_text_chunks, _has_visible_text

    book = Path('/Users/yinzh/Desktop/Flipped.epub')
    chapters, *_ = web_ui._auto_split_chapters('Mimo', str(book), 1, -1, 'auto', 'double', False, False, None)
    selected = []
    # 本书另有后部同名Flipped章，故必须同时限定绝对目录位置与标题。
    for index, expected in [(5, 'diving under'), (6, 'flipped')]:
        title, text = chapters[index - 1]
        assert title.casefold().replace('_', ' ').strip() == expected, (index, title)
        chunks = sum(_has_visible_text(part) for part in _split_text_chunks(text))
        selected.append({'chapter_index': index, 'title': title, 'characters': len(text),
                         'source_sha256': hashlib.sha256(text.encode()).hexdigest(),
                         'index_requests': chunks, 'narration_requests': 1,
                         'split_requests_normal': chunks, 'split_requests_max': chunks * 2})
    plan = {'status': 'prepared_pending_user_authorization', 'book_path': str(book),
            'book_sha256': hashlib.sha256(book.read_bytes()).hexdigest(), 'chapters': selected,
            'total_source_characters': sum(c['characters'] for c in selected),
            'normal_requests': sum(c['index_requests'] + c['narration_requests'] + c['split_requests_normal'] for c in selected),
            'max_requests': sum(c['index_requests'] + c['narration_requests'] + c['split_requests_max'] for c in selected),
            'service': 'project-configured DeepSeek text API', 'index_full_book': False,
            'tts_requests': 0, 'modify_existing_projects': False,
            'result_directory': str(ROOT / 'audiobook_output' / 'narration_identity_probe_20261017'),
            'validation': 'compare machine narration ownership with user-provided Bryce/Juli viewpoints; do not count machine proposals as human confirmation'}
    destination = Path(__file__).with_name('flipped_probe_plan.json')
    destination.write_text(json.dumps(plan, ensure_ascii=False, indent=2))
    print(json.dumps(plan, ensure_ascii=False))


if __name__ == '__main__':
    main()
