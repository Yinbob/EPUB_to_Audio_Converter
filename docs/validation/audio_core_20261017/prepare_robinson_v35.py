"""离线准备真实书籍候选；不分配角色、不调用模型、不生成音频。"""
import hashlib
import json
import re
import sys
from pathlib import Path
import ebooklib
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from audiobook_generator.config.general_config import GeneralConfig
from audiobook_generator.book_parsers.epub_book_parser import EpubBookParser
from audiobook_generator.audio_core.language import split_positions


def digest(value):
    return hashlib.sha256(value).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    source = ROOT / 'examples/The_Life_and_Adventures_of_Robinson_Crusoe.epub'
    destination = ROOT / 'audiobook_output/robinson_realbook_plan_20261017_v3'
    if destination.exists():
        raise ValueError('候选目录已存在，不覆盖已提取原文或后续人工记录')
    config_values = {'newline_mode': 'double', 'title_mode': 'auto', 'remove_endnotes': False,
                     'remove_reference_numbers': False, 'search_and_replace_file': ''}
    config = GeneralConfig(None)
    config.input_file = str(source)
    for key, value in config_values.items():
        setattr(config, key, value)
    parser = EpubBookParser(config)
    chapters = parser.get_chapters('   ')
    # 显式定位本书二十个小说章节，不把此规则推广到其他EPUB。
    novel_indices = [i for i, (title, _) in enumerate(chapters, 1) if title.startswith('CHAPTER_')]
    assert novel_indices == list(range(2, 22))
    records = [{'conversion_chapter_index': i, 'title': title, 'text': text,
                'text_sha256': digest(text.encode()), 'characters': len(text),
                'included_as_novel': i in novel_indices,
                'curly_quotation_pairs_heuristic': len(re.findall('“[^”]+”', text))}
               for i, (title, text) in enumerate(chapters, 1)]
    documents = list(parser.book.get_items_of_type(ebooklib.ITEM_DOCUMENT))
    for record, document in zip(records, documents):
        record['body_start'] = 0
        if record['included_as_novel']:
            soup = BeautifulSoup(document.get_content(), 'lxml-xml')
            heading = re.sub(r'\s+', ' ', soup.find('h2').get_text()).strip()
            assert record['text'].startswith(heading)
            record['body_start'] = len(heading)
    candidates = []
    # 预先固定取样规则，不查看声音输出或挑选有利的检测结果。
    selection = [(2, 'narration'), (4, 'narration'), (2, 'digits'), (6, 'digits'),
                 (3, 'quotes'), (16, 'quotes'), (17, 'quotes'), (18, 'quotes'),
                 (19, 'quotes'), (21, 'quotes')]
    occupied = {}
    for chapter_index, category in selection:
        text = records[chapter_index - 1]['text']
        # 完整句窗口排除章标题、未闭合引语和缩写句点。
        body_start = records[chapter_index - 1]['body_start']
        sentence_cuts = [body_start]
        abbreviations = {'mr', 'mrs', 'ms', 'dr', 'prof', 'sr', 'jr', 'st', 'etc'}
        for match in re.finditer(r'[.!?][”"’]*(?=\s+[A-Z“"]|$)', text):
            word = re.search(r'([A-Za-z]+)$', text[:match.start()])
            if text[match.start()] == '.' and word and word.group(1).lower() in abbreviations:
                continue
            cut = match.end()
            if cut > body_start and text[:cut].count('“') == text[:cut].count('”'):
                sentence_cuts.append(cut)
        cuts = {0, len(text)}
        for cut in split_positions(text, clauses=True):
            while cut < len(text) and text[cut] in '”"’':
                cut += 1
            if text[:cut].count('“') == text[:cut].count('”'):
                cuts.add(cut)
        cuts.update(sentence_cuts)
        cuts = sorted(cuts)
        options = []
        for start in sentence_cuts:
            for end in sentence_cuts:
                if not 180 <= end - start <= 850:
                    continue
                if any(start < b and end > a for a, b in occupied.get(chapter_index, [])):
                    continue
                excerpt = text[start:end]
                quotes = excerpt.count('“') + excerpt.count('”')
                digits = len(re.findall(r'\d+', excerpt))
                if ((category == 'narration' and (quotes or digits))
                        or (category == 'digits' and not digits) or (category == 'quotes' and quotes < 4)):
                    continue
                points = [start]
                for part in (1, 2, 3):
                    available = [cut for cut in cuts if points[-1] + 15 <= cut < end
                                 and cut - points[-1] <= 300 and end - cut >= (4 - part) * 15]
                    if not available:
                        break
                    points.append(min(available, key=lambda cut: (abs(cut - (start + (end-start)*part/4)), cut)))
                points.append(end)
                if len(points) == 5 and all(15 <= b-a <= 300 for a,b in zip(points,points[1:])):
                    options.append((start, end, points))
            if options:
                break
        if not options:
            raise ValueError(f'第{chapter_index}章没有满足预先规则的候选，不静默改取样条件')
        start, end, points = min(options, key=lambda value: (value[0], value[1]))
        occupied.setdefault(chapter_index, []).append((start, end))
        scene_id = f'R{len(candidates) + 1:02d}'
        units = [{'unit_id': f'{scene_id}_{i}', 'source_start': a, 'source_end': b,
                  'text': text[a:b], 'role_id': None, 'speaker_status': 'unassigned'}
                 for i, (a, b) in enumerate(zip(points, points[1:]), 1)]
        candidates.append({'scene_id': scene_id, 'selection_category_heuristic': category,
            'conversion_chapter_index': chapter_index, 'title': records[chapter_index - 1]['title'],
            'chapter_text_sha256': records[chapter_index - 1]['text_sha256'],
            'source_start': start, 'source_end': end, 'text': text[start:end], 'units': units,
            'context_before': text[max(0, start - 250):start], 'context_after': text[end:end + 250],
            'role_assignment_confirmed': False, 'synthesis_ready': False})
    # 每一项都按转换器输出的Unicode字符区间复核，保留空格及引号。
    for scene in candidates:
        text = records[scene['conversion_chapter_index'] - 1]['text']
        assert scene['text'] == text[scene['source_start']:scene['source_end']]
        assert ''.join(unit['text'] for unit in scene['units']) == scene['text']
        for unit in scene['units']:
            assert unit['text'] == text[unit['source_start']:unit['source_end']]
    destination.mkdir(parents=True)
    save(destination / 'source_chapters.json', {'schema_version': 'realbook-source-v1',
        'book_path': str(source), 'book_sha256': digest(source.read_bytes()),
        'title': parser.get_book_title(), 'author': parser.get_book_author(),
        'parser_settings': config_values, 'break_string': '   ',
        'chapter_numbering': 'production_parser_document_order_before_empty_chapter_filter',
        'offset_unit': 'unicode_code_points_in_exact_production_parser_text',
        'novel_conversion_indices': novel_indices, 'chapters': records})
    save(destination / 'scene_candidates.proposed.json', {'schema_version': 'realbook-candidates-v1',
        'book_sha256': digest(source.read_bytes()), 'source_scope': 'partial_excerpt_candidates',
        'selection_rule': 'first nonoverlapping complete-sentence window 180..850 chars per fixed chapter/category, partition into four 15..300-char punctuation units without unclosed curly quotations; exclude exact XHTML h2 heading span',
        'selection_fixed_before_tts': True, 'scenes': candidates,
        'full_book_role_ranking_allowed': False, 'synthesis_ready': False,
        'human_labels_present': False, 'online_requests': 0})
    save(destination / 'preparation_validation.json', {'schema_version': 'realbook-preparation-validation-v1',
        'status': 'offline_candidates_only', 'book_sha256': digest(source.read_bytes()),
        'parser_documents': len(records), 'novel_chapters': len(novel_indices),
        'novel_characters': sum(row['characters'] for row in records if row['included_as_novel']),
        'scenes': len(candidates), 'units': sum(len(s['units']) for s in candidates),
        'candidate_characters': sum(len(s['text']) for s in candidates),
        'exact_source_spans_verified': True, 'adjacent_unit_continuity_verified': True,
        'speaker_assignments_confirmed': 0, 'online_requests': 0,
        'offline_preparation_revision': 'two earlier candidate drafts preserved separately; revised before any model call to require complete sentence windows, exact XHTML heading exclusion and balanced quotation boundaries',
        'source_files': {str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in (
            Path(__file__), ROOT/'audiobook_generator/book_parsers/epub_book_parser.py',
            ROOT/'audiobook_generator/audio_core/language.py')},
        'artifacts': {name: digest((destination/name).read_bytes()) for name in (
            'source_chapters.json', 'scene_candidates.proposed.json')}})
    print(json.dumps({'folder': str(destination), 'scenes': len(candidates),
                      'units': sum(len(s['units']) for s in candidates)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
