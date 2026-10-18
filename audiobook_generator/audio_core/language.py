"""中英语言范围与计量单位；混合文本不套用单语言语速阈值。"""
import re


def normalize_language(language):
    value = (language or 'auto').strip().lower().replace('_', '-')
    if value in {'auto', 'mixed', 'unknown'}:
        return value
    if value in {'english', 'en'} or value.startswith('en-'):
        return 'en'
    if value in {'chinese', 'zh'} or value.startswith('zh-'):
        return 'zh'
    raise ValueError('统一质量核心当前支持 English/en、Chinese/zh 或 auto')


def resolve_language(text, language='auto'):
    requested = normalize_language(language)
    han = bool(re.search(r'[\u3400-\u9fff]', text))
    latin = bool(re.search(r'[A-Za-z]', text))
    if han and latin:
        return 'mixed'
    if han:
        return 'zh'
    if latin:
        return 'en'
    return requested if requested in {'en', 'zh'} else 'unknown'


def join_reading_texts(texts):
    # 英文句末标点也需要词界，避免 3.5%.The 被误当作版本／标识符上下文。
    result = ''
    for text in texts:
        if (result and text and re.search(r'''[A-Za-z0-9][.!?;:%,'"’”)\]]*$''', result)
                and re.match(r'''["'“‘(\[]*[A-Za-z0-9]''', text)):
            result += ' '
        result += text
    return result


def split_positions(text, *, clauses=False):
    """英文句号只在句尾识别；不切小数、常用缩写与单词。"""
    pattern = r'[。！？!?；;\n]' + (r'|[,，](?!\d)' if clauses else '')
    positions = {m.end() for m in re.finditer(pattern, text)}
    abbreviations = {'mr', 'mrs', 'ms', 'dr', 'prof', 'sr', 'jr', 'st', 'vs', 'etc', 'e.g', 'i.e'}
    for match in re.finditer(r'\.(?=\s|$)', text):
        prefix = text[:match.start()]
        word = re.search(r'([A-Za-z.]+)$', prefix)
        token = word.group(1).lower() if word else ''
        if token in abbreviations or (len(token) == 1 and token.isalpha()) or '.' in token:
            continue
        positions.add(match.end())
    return sorted(positions)
