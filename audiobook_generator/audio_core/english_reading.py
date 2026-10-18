"""英文核验参考的有限等价规则；不改发送给 TTS 的正文。"""
from __future__ import annotations

from datetime import date
import re

VERSION = 'en-comparison-v1'
_SMALL = ('zero one two three four five six seven eight nine ten eleven twelve thirteen '
          'fourteen fifteen sixteen seventeen eighteen nineteen').split()
_TENS = 'zero ten twenty thirty forty fifty sixty seventy eighty ninety'.split()
_ORDINAL = {'one': 'first', 'two': 'second', 'three': 'third', 'five': 'fifth', 'eight': 'eighth',
            'nine': 'ninth', 'twelve': 'twelfth'}
_MONTHS = 'January February March April May June July August September October November December'.split()


def cardinal(number):
    if not 0 <= number <= 999999:
        raise ValueError('英文数值比较当前支持 0～999999')
    if number < 20:
        return _SMALL[number]
    if number < 100:
        return _TENS[number // 10] + (' ' + cardinal(number % 10) if number % 10 else '')
    divisor, unit = (100, 'hundred') if number < 1000 else (1000, 'thousand')
    return cardinal(number // divisor) + ' ' + unit + (' ' + cardinal(number % divisor) if number % divisor else '')


def ordinal(number):
    words = cardinal(number).split()
    last = words[-1]
    words[-1] = _ORDINAL.get(last, last[:-1] + 'ieth' if last.endswith('y') else last + 'th')
    return ' '.join(words)


def _suffix(number):
    return 'th' if 10 <= number % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(number % 10, 'th')


def _key(text):
    return ' '.join(text.casefold().replace('-', ' ').split())


def _phrase_pattern(text):
    return r'[ \t-]+'.join(re.escape(word) for word in text.split())


_DAYS = {alias: day for day in range(1, 32) for alias in (cardinal(day), ordinal(day))}
_YEARS = {}
for _year in range(1900, 2100):
    _head, _tail = divmod(_year, 100)
    _aliases = {cardinal(_year), cardinal(_head) + ' ' + (cardinal(_tail) if _tail >= 10 else
        'oh ' + cardinal(_tail) if _tail else 'hundred')}
    if _year > 2000:
        _aliases.add('two thousand and ' + cardinal(_year - 2000))
    if _head == 19 and _tail:
        _aliases.add('one thousand nine hundred and ' + cardinal(_tail))
    for _alias in _aliases:
        _YEARS[_alias] = _year
_DAY_PATTERN = r'(?:\d{1,2}(?:st|nd|rd|th)?|' + '|'.join(
    _phrase_pattern(word) for word in sorted(_DAYS, key=lambda w: (-len(w), w))) + ')'
_YEAR_PATTERN = r'(?:(?:19|20)\d{2}|' + '|'.join(
    _phrase_pattern(word) for word in sorted(_YEARS, key=lambda w: (-len(w), w))) + ')'
_MONTH_PATTERN = '(?:' + '|'.join(_MONTHS) + ')'
_DATE_PATTERN = (rf'{_MONTH_PATTERN}[ \t]+{_DAY_PATTERN}[ \t]*,[ \t]*{_YEAR_PATTERN}'
                 rf'|{_MONTH_PATTERN}[ \t]+{_DAY_PATTERN}[ \t]+{_YEAR_PATTERN}'
                 rf'|{_DAY_PATTERN}[ \t]+(?:of[ \t]+)?{_MONTH_PATTERN}[ \t,]+{_YEAR_PATTERN}')
_NUMBER_PATTERN = r'[+−-]?(?:[1-9]\d{0,2}(?:,\d{3})+|\d+)(?:\.\d+)?(?:st|nd|rd|th|[ \t]*[%％])?'
_PATTERN = re.compile(rf'(?<![\w./,:$£€#@+−-])(?:(?P<date>{_DATE_PATTERN})|(?P<number>{_NUMBER_PATTERN}))'
                      r'(?![\w/%:+−-]|\.\w|,\d)', re.I)
_IDENTIFIER_CONTEXT = re.compile(
    r'\b(?:version|ver|build|model|id|code|serial|order|invoice|reference|ref|ticket|phone|tel|isbn|room|route|flight)'
    r'[ \t]*(?:(?:no|number)\.?[ \t]*)?[:#]?[ \t]*$', re.I)


def _date_reading(text):
    month = re.search(_MONTH_PATTERN, text, re.I)
    month_number = next(i for i, name in enumerate(_MONTHS, 1) if name.casefold() == month.group().casefold())
    if month.start() == 0:
        value = text[month.end():].strip()
        match = re.fullmatch(rf'(?P<day>{_DAY_PATTERN})[ \t,]+(?P<year>{_YEAR_PATTERN})', value, re.I)
        day_text, year_text = match['day'], match['year']
    else:
        day_text = re.sub(r'[ \t]+of$', '', text[:month.start()].strip(), flags=re.I)
        year_text = text[month.end():].strip(' ,\t')
    if day_text[0].isdigit():
        match = re.fullmatch(r'(\d+)(st|nd|rd|th)?', day_text, re.I)
        day_number = int(match[1])
        if match[2] and match[2].casefold() != _suffix(day_number):
            raise ValueError('invalid_ordinal_suffix')
    else:
        day_number = _DAYS[_key(day_text)]
    year = int(year_text) if year_text.isdigit() else _YEARS[_key(year_text)]
    date(year, month_number, day_number)
    return f'{_MONTHS[month_number - 1].lower()} {ordinal(day_number)} {cardinal(year)}'


def _number_reading(text, prefix):
    if _IDENTIFIER_CONTEXT.search(prefix):
        return text, 'identifier_context'
    suffix = re.search(r'(st|nd|rd|th)$', text, re.I)
    percent = text.rstrip().endswith(('%', '％'))
    value = text[:suffix.start()] if suffix else text.rstrip(' \t%％')
    sign = 'minus ' if value.startswith(('-', '−')) else 'plus ' if value.startswith('+') else ''
    value = value.lstrip('+−-')
    integer, dot, fraction = value.partition('.')
    digits = integer.replace(',', '')
    if (len(digits) > 1 and digits.startswith('0')) or len(digits) > 6 or len(fraction) > 4:
        return text, 'ambiguous_identifier_or_precision'
    number = int(digits)
    if not dot and not percent and not suffix and ',' not in integer and number >= 1000:
        return text, 'ambiguous_year_or_identifier'
    if suffix:
        if dot or sign or suffix[0].casefold() != _suffix(number):
            return text, 'invalid_ordinal_suffix'
        rendered = ordinal(number)
    else:
        rendered = cardinal(number)
        if dot:
            rendered += ' point ' + ' '.join(_SMALL[int(char)] for char in fraction)
    return sign + rendered + (' percent' if percent else ''), None


def comparison_reading(text):
    """返回对齐文本及输入字符坐标；不把模型输出当作规则来源。"""
    pieces, events, cursor = [], [], 0
    for match in _PATTERN.finditer(text):
        original = match.group()
        try:
            if match['date']:
                rendered, reason = _date_reading(original), None
            else:
                rendered, reason = _number_reading(original, text[:match.start()])
        except (ValueError, KeyError):
            rendered, reason = original, 'invalid_or_unsupported_date'
        pieces += [text[cursor:match.start()], rendered]
        events.append({'kind': 'english_date' if match['date'] else 'english_number',
                       'input_start': match.start(), 'input_end': match.end(),
                       'before': original, 'after': rendered, 'version': VERSION,
                       'status': 'needs_review' if reason else 'normalized', 'reason': reason})
        cursor = match.end()
    pieces.append(text[cursor:])
    return ''.join(pieces), events
