"""显式上下文预算与断点缓存；UTF-8 字节数是无 tokenizer 时的保守 token 上界。"""
import hashlib
import json
import os
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from audiobook_generator.services.common import atomic_json, read_json

_CHECKPOINT = ContextVar('role_checkpoint', default=None)


class ContextLimit(ValueError):
    pass


class TruncatedCompletion(ValueError):
    pass


def context_tokens():
    value = int(os.getenv('ROLE_LLM_CONTEXT_TOKENS', '16384'))
    if value < 4096:
        raise ValueError('ROLE_LLM_CONTEXT_TOKENS 不能小于 4096')
    return value


def output_tokens(target=8192):
    return min(target, context_tokens() // 3)


def check_messages(messages, output):
    count = sum(len(str(m['content']).encode('utf-8')) + 32 for m in messages)
    if count + output + 1024 > context_tokens():
        raise ContextLimit('本次正文及人物上下文超过配置的 LLM 上下文预算')


def checked_content(response):
    choice = response.choices[0]
    if getattr(choice, 'finish_reason', None) in ('length', 'max_tokens'):
        raise TruncatedCompletion('模型输出达到长度上限，需要缩小正文块')
    return choice.message.content


def relevant_cards(cards, source, limit=2048):
    ranked = sorted(cards, key=lambda p: (-sum(source.count(name) for name in
        [p.get('name') or p.get('display_name', ''), *p.get('aliases', [])] if name),
        str(p.get('entity_id') or p.get('role_id') or '')))
    result, size = [], 0
    for card in ranked:
        encoded = json.dumps(card, ensure_ascii=False)
        if size + len(encoded.encode()) <= limit:
            result.append(card); size += len(encoded.encode())
    return result


def bounded_context(context, source, limit=2048):
    """人物、章级证据和相邻原文共用上限，正文递分时不被固定上下文挤满。"""
    value = dict(context)
    for key in ('left_context', 'right_context'):
        raw = str(value.get(key, '')).encode('utf-8')
        value[key] = (raw[-256:] if key == 'left_context' else raw[:256]).decode('utf-8', errors='ignore')
    value['known_characters'] = relevant_cards(value.get('known_characters', []), source, limit // 2)
    chapter = dict(value.get('chapter_narration') or {})
    if chapter:
        chapter['narrators'] = relevant_cards(chapter.get('narrators', []), source, limit // 3)
        value['chapter_narration'] = chapter
    while len(json.dumps(value, ensure_ascii=False).encode('utf-8')) > limit:
        if value['known_characters']:
            value['known_characters'].pop()
        elif chapter.get('narrators'):
            chapter['narrators'].pop()
        elif value.get('left_context') or value.get('right_context'):
            value['left_context'] = value.get('left_context', '')[len(value.get('left_context', '')) // 2:]
            value['right_context'] = value.get('right_context', '')[:len(value.get('right_context', '')) // 2]
        else:
            raise ContextLimit('固定人物上下文超过配置预算')
    return value


def split_middle(text):
    middle = len(text) // 2
    boundaries = [i + 1 for i, c in enumerate(text) if c in '。！？.!?\n' and len(text) // 4 < i < len(text) * 3 // 4]
    cut = min(boundaries, key=lambda i: abs(i - middle)) if boundaries else middle
    return text[:cut], text[cut:]


@contextmanager
def checkpoint_scope(directory):
    token = _CHECKPOINT.set(Path(directory))
    try:
        yield
    finally:
        _CHECKPOINT.reset(token)


def completion(client, *, identity='', validator=None, **kwargs):
    """业务校验成功后才落盘；恢复时再次验证，避免坏结果阻断重试。"""
    from .split_control import current_split_control
    control = current_split_control()
    if control:
        control.check()
    check_messages(kwargs['messages'], kwargs.get('max_tokens', 0))
    root = _CHECKPOINT.get()
    key = hashlib.sha256(json.dumps({'request': kwargs, 'identity': identity,
        'endpoint': str(getattr(client, 'base_url', '')),
        'prompt_version': 'bounded-v2'}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    path = root / (key + '.json') if root else None
    try:
        cached = read_json(path, {}) if path else {}
    except (ValueError, OSError):
        cached = {}  # 中断或损坏的检查点不能阻止重算。
    if cached.get('content') and cached.get('sha256') == hashlib.sha256(cached['content'].encode()).hexdigest():
        try:
            if validator is not None:
                if validator(cached['content']) is not False:
                    return cached['content']
        except (ValueError, TypeError, KeyError, RuntimeError):
            pass
    response = client.chat.completions.create(**kwargs)
    content = checked_content(response)
    # 仅语法正确不足以证明成功：正文完整覆盖等业务约束也必须通过。
    from .deepseek_splitter import _extract_json_object
    _extract_json_object(content)
    validated = validator is not None and validator(content) is not False
    if path and validated:
        atomic_json(path, {'content': content, 'sha256': hashlib.sha256(content.encode()).hexdigest()})
    return content


def checkpoint_directory():
    return _CHECKPOINT.get()
