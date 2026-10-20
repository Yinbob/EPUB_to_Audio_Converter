"""人工核对的展示筛选与同章上下文，不改动人物归属。"""
import re

CONTEXT_MAX_CHARS = 300
CONTEXT_MIN_CHARS = 180


def chapter_role_choices(script, chapter_index=None, show_all=False, selected=None):
    """可分配声音的人物使用同一章范围和计数，不把全书候选当成本章参与者。"""
    from collections import Counter
    counts = Counter(s.role_id for c in script.chapters if chapter_index is None or c.chapter_index == chapter_index
                     for s in c.segments)
    scope_label = '本章' if chapter_index is not None else '已保存章节'
    return [(f'{"默认旁白" if key == "narrator" else role.display_name} · {scope_label} {counts[key]} 段', key)
            for key, role in script.roles.items() if key in script.entities
            and (counts[key] or show_all or key == selected)]


def review_segments(script, entity_id=None, scope='all', chapter_index=None):
    rows = []
    for chapter in script.chapters:
        if chapter_index is not None and chapter.chapter_index != chapter_index:
            continue
        for segment in chapter.segments:
            if entity_id and entity_id != '__all__' and segment.role_id != entity_id:
                continue
            if scope == 'pending' and segment.speaker and segment.speaker.status == 'confirmed':
                continue
            if scope == 'dialogue' and segment.text_kind != 'dialogue':
                continue
            rows.append((chapter, segment))
    return rows


def _context_edge(text, before):
    """每侧最多300字符，优先保留180～300字符的完整句子，英文避免截词。"""
    limit = CONTEXT_MAX_CHARS
    minimum = CONTEXT_MIN_CHARS
    if len(text) <= limit:
        return text
    if before:
        part = text[-limit:]
        boundaries = list(re.finditer(r'[。！？.!?][”’"\']?\s*|\n+', part[:limit - minimum]))
        cut = boundaries[-1].end() if boundaries else 0
        if not cut and part[:1].isascii() and part[:1].isalnum():
            space = part.find(' ', 0, limit - minimum)
            cut = space + 1 if space >= 0 else 0
        return '…' + part[cut:]
    part = text[:limit]
    boundaries = list(re.finditer(r'[。！？.!?][”’"\']?|\n+', part[minimum:]))
    end = minimum + boundaries[0].end() if boundaries else limit
    if end == limit and part[-1:].isascii() and part[-1:].isalnum():
        space = part.rfind(' ', minimum)
        end = space if space >= 0 else end
    return part[:end] + '…'


def segment_context(chapter, segment_id):
    """按段落顺序定位，重复句也不会错取第一次出现的上下文。"""
    for index, segment in enumerate(chapter.segments):
        if segment.segment_id == segment_id:
            before = '\n'.join(s.text for s in chapter.segments[:index])
            after = '\n'.join(s.text for s in chapter.segments[index + 1:])
            return _context_edge(before, True), _context_edge(after, False)
    return '', ''
