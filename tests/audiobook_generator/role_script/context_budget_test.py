import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from audiobook_generator.role_script.context_budget import (checkpoint_scope, check_messages,
    completion, relevant_cards, TruncatedCompletion)
from audiobook_generator.role_script.deepseek_splitter import _request_chunk, DeepSeekSplitError
from audiobook_generator.role_script.v2_generation import build_book_registry


def response(value, finish='stop'):
    return SimpleNamespace(choices=[SimpleNamespace(finish_reason=finish,
        message=SimpleNamespace(content=json.dumps(value, ensure_ascii=False)))])


def client_for(create):
    return SimpleNamespace(base_url='https://example.invalid/v1',
        chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(side_effect=create))))


def source_in(kwargs):
    text = kwargs['messages'][1]['content'].split('原文：\n', 1)[1]
    return text.split('\n本章上下文', 1)[0].removesuffix('\n') if '\n本章上下文' in text else text


class ContextBudgetTest(unittest.TestCase):
    def test_long_chinese_input_is_complete_bounded_and_resumable(self):
        source = '甲说：“你好。”乙走进房间。' * 800
        def create(**kwargs):
            check_messages(kwargs['messages'], kwargs['max_tokens'])
            return response({'roles': {}, 'segments': [{'role_id':'narrator', 'text':source_in(kwargs)}]})
        client = client_for(create)
        with tempfile.TemporaryDirectory() as root, patch.dict('os.environ', {'ROLE_LLM_CONTEXT_TOKENS':'4096'}), checkpoint_scope(root):
            result = _request_chunk(client, 'test', 1, '长章', source, 'openai')
            self.assertEqual(''.join(s['text'] for s in result['segments']), source)
            calls = client.chat.completions.create.call_count
            self.assertGreater(calls, 2)
            again = _request_chunk(client, 'test', 1, '长章', source, 'openai')
            self.assertEqual(result, again)
            self.assertEqual(client.chat.completions.create.call_count, calls)

    def test_output_truncation_splits_without_losing_or_duplicating_text(self):
        source = '一段正文。' * 100
        calls = []
        def create(**kwargs):
            text = source_in(kwargs)
            calls.append(text)
            return response({'roles':{}, 'segments':[{'role_id':'narrator','text':text}]},
                            'length' if len(calls) == 1 else 'stop')
        client = client_for(create)
        result = _request_chunk(client, 'test', 1, '章', source, 'openai')
        self.assertEqual(''.join(s['text'] for s in result['segments']), source)
        self.assertEqual(''.join(calls[1:]), source)

    def test_semantically_invalid_response_is_never_a_success_checkpoint(self):
        source = '完整的原文。'
        client = client_for([response({'roles':{}, 'segments':[{'role_id':'narrator','text':'错文'}]}),
                             response({'roles':{}, 'segments':[{'role_id':'narrator','text':source}]})])
        with tempfile.TemporaryDirectory() as root, checkpoint_scope(root):
            with self.assertRaises(DeepSeekSplitError):
                _request_chunk(client, 'test', 1, '章', source, 'openai')
            self.assertEqual(list(Path(root).glob('*.json')), [])
            _request_chunk(client, 'test', 1, '章', source, 'openai')
            _request_chunk(client, 'test', 1, '章', source, 'openai')
        self.assertEqual(client.chat.completions.create.call_count, 2)

    def test_registry_resume_preserves_ids_and_only_requests_remaining_chapters(self):
        chapters = [('一', '张三说。'), ('二', '李四说。')]
        def create(client, model, chapter, text, cards, **kwargs):
            if chapter == 2:
                raise TimeoutError('断点')
            return [{'name':'张三', 'aliases':[], 'evidence_quote':'张三说。'}]
        with tempfile.TemporaryDirectory() as root, checkpoint_scope(root), patch(
                'audiobook_generator.role_script.deepseek_splitter._create_client', return_value=object()), patch(
                'audiobook_generator.role_script.v2_generation._request_character_chunk', side_effect=create):
            with self.assertRaises(TimeoutError):
                build_book_registry(chapters, api_key='dummy', base_url='https://example.invalid', model='test')
            saved = json.loads(next(Path(root).glob('registry-*.json')).read_text())
            original_id = next(k for k,v in saved['entities'].items() if v['canonical_name'] == '张三')
            with patch('audiobook_generator.role_script.v2_generation._request_character_chunk', return_value=[
                    {'name':'李四','aliases':[],'evidence_quote':'李四说。'}]) as remaining:
                result = build_book_registry(chapters, api_key='dummy', base_url='https://example.invalid', model='test')
            self.assertEqual(remaining.call_count, 1)
            self.assertEqual(remaining.call_args.args[2], 2)
            self.assertEqual(result[original_id].canonical_name, '张三')

    def test_relevant_person_is_not_dropped_by_last_thirty_limit(self):
        cards = [{'role_id':f'id{i}', 'display_name':f'人物{i}号', 'aliases':[]} for i in range(150)]
        selected = relevant_cards(cards, '人物0号说话了。', limit=200)
        self.assertEqual(selected[0]['role_id'], 'id0')

    def test_cached_response_is_scoped_to_model_and_endpoint(self):
        kwargs = {'model':'test', 'messages':[{'role':'user','content':'source'}], 'max_tokens':20}
        client = client_for(lambda **k: response({'ok':True}))
        with tempfile.TemporaryDirectory() as root, checkpoint_scope(root):
            for _ in range(2): completion(client, validator=lambda content: True, **kwargs)
            client.base_url = 'https://another.invalid/v1'
            completion(client, validator=lambda content: True, **kwargs)
            completion(client, validator=lambda content: True, **{**kwargs,'model':'other'})
        self.assertEqual(client.chat.completions.create.call_count, 3)
