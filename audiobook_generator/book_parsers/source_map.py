"""清洗文本的原文坐标；替换文字关联到整个原匹配区间。"""
from array import array
from bisect import bisect_left, bisect_right
import re
from bs4.element import CData, NavigableString, Tag


class TrackedText:
    def __init__(self, text):
        self.text = text
        self.starts = array('q', range(len(text)))
        self.ends = array('q', range(1, len(text) + 1))

    def strip(self):
        first, last = len(self.text) - len(self.text.lstrip()), len(self.text.rstrip())
        self.text, self.starts, self.ends = self.text[first:last], self.starts[first:last], self.ends[first:last]
        return self

    def sub(self, pattern, replacement):
        parts, starts, ends, previous = [], array('q'), array('q'), 0
        for match in re.finditer(pattern, self.text):
            a, b = match.span()
            parts.append(self.text[previous:a])
            starts.extend(self.starts[previous:a]); ends.extend(self.ends[previous:a])
            value = match.expand(replacement)
            raw_start = self.starts[a] if a < len(self.starts) else (self.ends[-1] if self.ends else 0)
            raw_end = self.ends[b - 1] if b > a else raw_start
            parts.append(value)
            starts.extend([raw_start] * len(value)); ends.extend([raw_end] * len(value))
            previous = b
        parts.append(self.text[previous:])
        starts.extend(self.starts[previous:]); ends.extend(self.ends[previous:])
        self.text, self.starts, self.ends = ''.join(parts), starts, ends
        return self

    def paragraphs(self, records, chapter_index):
        result = []
        for index, record in enumerate(records, 1):
            start = bisect_right(self.ends, record['raw_start'])
            end = bisect_left(self.starts, record['raw_end'])
            result.append({**record, 'id': f'ch{chapter_index}:p{index}', 'chapter_index': chapter_index,
                           'start': start, 'end': end, 'cleaned_text': self.text[start:end]})
        return result


def node_path(node):
    parts = []
    while node is not None and getattr(node, 'name', None) not in (None, '[document]'):
        siblings = node.parent.find_all(node.name, recursive=False) if node.parent else [node]
        index = next((i for i, sibling in enumerate(siblings, 1) if sibling is node), 1)
        parts.append(f'{node.name}[{index}]'); node = node.parent
    return '/' + '/'.join(reversed(parts))


def epub_source(soup, href):
    raw_parts, records, offset = [], [], 0
    blocks = {'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'blockquote', 'td', 'pre'}
    for value in soup.descendants:
        # strings 会跳过 <br>，把 to<br/>Colton 拼成 toColton；保留结构换行，
        # 同时仍让 Col<b>ton</b> 这样的内联文字保持相连。
        if isinstance(value, Tag) and value.name == 'br':
            raw_parts.append('\n'); offset += 1
            continue
        if type(value) not in (NavigableString, CData):
            continue
        text = str(value)
        if not text:
            continue
        if text.strip():
            block = value.parent
            while block.parent is not None and block.name not in blocks and block.name not in ('body', 'head'):
                block = block.parent
            locator = {'kind': 'epub', 'href': href, 'node_path': node_path(block), 'precision': 'node'}
            # XHTML 可以省略段落标签之间的空白，段落边界仍应分隔英文单词。
            if (records and records[-1]['locator'] != locator and raw_parts
                    and not raw_parts[-1][-1].isspace() and not text[0].isspace()):
                raw_parts.append('\n'); offset += 1
            if records and records[-1]['locator'] == locator:
                records[-1]['raw_end'] = offset + len(text); records[-1]['text'] += text
            else:
                records.append({'raw_start': offset, 'raw_end': offset + len(text), 'text': text, 'locator': locator})
        raw_parts.append(text)
        offset += len(text)
    raw = ''.join(raw_parts)
    # 内联节点之间可能有独立的空白字符串，原文必须与其区间完全一致。
    for record in records:
        record['text'] = raw[record['raw_start']:record['raw_end']]
    return raw, records
