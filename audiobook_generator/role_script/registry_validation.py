"""人物索引的格式容错；输出始终恢复为原文切片，不做拼写猜测。"""
from dataclasses import dataclass, field
import re
import unicodedata

from .narration import source_name_match


_PUNCTUATION = str.maketrans({'‘': "'", '’': "'", 'ʼ': "'", '“': '"', '”': '"',
                             '‐': '-', '‑': '-', '–': '-', '—': '-'})


def _normalized(text):
    chars, starts, ends = [], [], []
    for index, char in enumerate(text):
        for value in unicodedata.normalize('NFKC', char).translate(_PUNCTUATION).casefold():
            if value.isspace():
                if chars and chars[-1] == ' ':
                    ends[-1] = index + 1
                    continue
                value = ' '
            chars.append(value); starts.append(index); ends.append(index + 1)
    return ''.join(chars), starts, ends


def source_surface(value, source, *, name=False):
    """只容忍空白、大小写、全半角和常见引号／横线，拒绝歧义映射。"""
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    if name:
        exact = source_name_match(value, source)
        if exact is not None:
            return exact.group()
    elif value in source:
        return value
    needle, _, _ = _normalized(value)
    text, starts, ends = _normalized(source)
    left = r'(?<![A-Za-z0-9_])' if name and needle[0].isascii() and needle[0].isalnum() else ''
    right = r'(?![A-Za-z0-9_])' if name and needle[-1].isascii() and needle[-1].isalnum() else ''
    matches = list(re.finditer(left + re.escape(needle) + right, text))
    if not matches:
        return None
    surfaces = {source[starts[m.start()]:ends[m.end() - 1]] for m in matches}
    # 多处相同姓名可以复用；不同原文写法归一后相同则留给模型纠正／人工核对。
    if (not name and len(matches) != 1) or len(surfaces) != 1:
        return None
    return surfaces.pop()


@dataclass
class CharacterValidation:
    items: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    affected: int = 0
    rejected: int = 0
    total: int = 0

    @property
    def recoverable(self):
        return bool(self.items) and self.affected <= max(1, self.total // 5)


class CharacterValidationError(ValueError):
    def __init__(self, result):
        self.result = result
        super().__init__('; '.join(result.errors[:3]))


def validate_characters(items, source):
    if not isinstance(items, list):
        raise ValueError('全书人物索引未返回 characters 数组')
    result = CharacterValidation(total=len(items))
    for index, item in enumerate(items):
        prefix = f'characters[{index}]'
        errors = []
        if not isinstance(item, dict) or not isinstance(item.get('name'), str):
            errors.append(f'{prefix}.name 缺少原文称呼')
        else:
            name = item['name'].strip()
            quote = source_surface(item.get('evidence_quote'), source)
            if source_surface(name, source, name=True) is None:
                errors.append(f'{prefix}.name={name[:80]!r} 无法追溯到当前原文')
            elif quote is None or source_surface(name, quote, name=True) is None:
                errors.append(f'{prefix}.evidence_quote 缺少包含 {name[:80]!r} 的逐字原文证据')
        if errors:
            result.rejected += 1
        else:
            grounded = {**item, 'name': source_surface(name, quote, name=True),
                        'evidence_quote': quote, 'aliases': []}
            aliases = item.get('aliases', [])
            if not isinstance(aliases, list):
                errors.append(f'{prefix}.aliases 必须为原文称呼数组')
            else:
                for alias_index, alias in enumerate(aliases):
                    surface = source_surface(alias, source, name=True)
                    if surface is None:
                        errors.append(f'{prefix}.aliases[{alias_index}]={str(alias)[:80]!r} 无法追溯到当前原文')
                    else:
                        grounded['aliases'].append(surface)
            result.items.append(grounded)
        if errors:
            result.affected += 1
            result.errors.extend(errors)
    return result
