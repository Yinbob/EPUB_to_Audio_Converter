import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from audiobook_generator.role_script.context_budget import checkpoint_scope
from audiobook_generator.role_script.models import AliasRecord, CharacterEntity
from audiobook_generator.role_script.split_control import SplitAborted
from audiobook_generator.role_script.v2_generation import _request_character_chunk, build_book_registry


def response(items):
    return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(
        content=json.dumps({'characters': items})))])


def character(name, quote, aliases=None):
    return {'name': name, 'aliases': aliases or [], 'evidence_quote': quote}


def client_for(*responses):
    return SimpleNamespace(base_url='https://example.invalid', chat=SimpleNamespace(
        completions=SimpleNamespace(create=Mock(side_effect=responses))))


class CharacterRegistryTest(unittest.TestCase):
    def test_full_name_is_corrected_to_local_surface_without_poisoning_cache(self):
        source = 'Juli watched my father paint.'
        good = character('Juli', source)
        client = client_for(response([character('Juli Baker', source)]), response([good]))
        with tempfile.TemporaryDirectory() as folder, checkpoint_scope(folder):
            result = _request_character_chunk(client, 'test', 8, source, {})
            cached = [json.loads(path.read_text()) for path in Path(folder).glob('*.json')]
        self.assertEqual(result, [good])
        self.assertEqual(len(cached), 1)
        self.assertEqual(json.loads(cached[0]['content'])['characters'], [good])
        calls = client.chat.completions.create.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertIn("characters[0].name='Juli Baker'", calls[1].kwargs['messages'][-1]['content'])

    def test_cards_only_include_exact_local_names_and_confirmed_aliases(self):
        client = client_for(response([]))
        cards = {
            'juli': CharacterEntity('Juli Baker', aliases=(AliasRecord('Juli', 'confirmed'),
                                                         AliasRecord('Julie', 'proposed'))),
            'bryce': CharacterEntity('Bryce Loski'),
            'ann': CharacterEntity('Ann'),
        }
        _request_character_chunk(client, 'test', 8, 'Juli and Joanne arrived.', cards)
        prompt = client.chat.completions.create.call_args.kwargs['messages'][1]['content']
        summary = json.loads(prompt.split('当前原文可用的人物卡片（仅供身份参考）：', 1)[1].split('\n章节：')[0])
        self.assertEqual(summary, [{'entity_id': 'juli', 'name': 'Juli', 'aliases': []}])

    def test_bad_names_aliases_and_evidence_have_bounded_retries_and_no_cache(self):
        for item, field in [
            (character('Ann', 'Joanne spoke.'), '.name'),
            (character('Joanne', 'Joanne smiled.'), '.evidence_quote'),
            (character('Joanne', 'spoke.'), '.evidence_quote'),
        ]:
            with self.subTest(item=item), tempfile.TemporaryDirectory() as folder, checkpoint_scope(folder):
                client = client_for(response([item]), response([item]))
                with self.assertRaises(ValueError) as error:
                    _request_character_chunk(client, 'test', 8, 'Joanne spoke.', {})
                self.assertIn('第 8 章人物索引经 2 次尝试', str(error.exception))
                self.assertIn(field, str(error.exception))
                self.assertEqual(client.chat.completions.create.call_count, 2)
                self.assertEqual(list(Path(folder).glob('*.json')), [])

    def test_format_variations_restore_verbatim_source_without_fuzzy_spelling(self):
        for source, name, quote in [
            ('My  father spoke.', 'my father', 'My father spoke.'),
            ('O’Neil spoke.', "O'Neil", "O'Neil spoke."),
            ('Anne–Marie spoke.', 'Anne-Marie', 'Anne-Marie spoke.'),
            ('Ｊｕｌｉ spoke.', 'Juli', 'Juli spoke.'),
        ]:
            with self.subTest(source=source):
                client = client_for(response([character(name, quote)]))
                result = _request_character_chunk(client, 'test', 2, source, {})
                self.assertEqual(result[0]['name'], source[:-7])
                self.assertEqual(result[0]['evidence_quote'], source)
                self.assertEqual(client.chat.completions.create.call_count, 1)

    def test_small_invalid_name_is_skipped_after_two_attempts_without_success_cache(self):
        source = 'Juli spoke.'
        items = [character('Juli', source), character('Julie', source)]
        client = client_for(response(items), response(items))
        warnings = []
        with tempfile.TemporaryDirectory() as folder, checkpoint_scope(folder):
            result = _request_character_chunk(client, 'test', 2, source, {}, warnings=warnings, source_start=50)
            self.assertEqual(list(Path(folder).glob('*.json')), [])
        self.assertEqual(result, [items[0]])
        self.assertEqual(client.chat.completions.create.call_count, 2)
        self.assertEqual((warnings[0].chapter_index, warnings[0].chunk_start), (2, 50))
        self.assertEqual((warnings[0].rejected_items, warnings[0].total_items), (1, 2))
        self.assertIn('Julie', warnings[0].message)

    def test_invalid_alias_does_not_discard_valid_person(self):
        source = 'Joanne spoke.'
        item = character('Joanne', source, ['Ann'])
        client = client_for(response([item]), response([item]))
        warnings = []
        self.assertEqual(_request_character_chunk(client, 'test', 2, source, {}, warnings=warnings),
                         [character('Joanne', source)])
        self.assertEqual(warnings[0].rejected_items, 0)
        self.assertIn('aliases[0]', warnings[0].message)

    def test_large_invalid_fraction_and_all_invalid_results_still_fail(self):
        for items in [[character('Julie', 'Juli spoke.')],
                      [character('Juli', 'Juli spoke.'), character('Julie', 'Juli spoke.'),
                       character('Julia', 'Juli spoke.')]]:
            with self.subTest(items=items):
                client = client_for(response(items), response(items))
                with self.assertRaisesRegex(ValueError, '经 2 次尝试'):
                    _request_character_chunk(client, 'test', 2, 'Juli spoke.', {})

    def test_later_malformed_response_cannot_salvage_previous_attempt(self):
        items = [character('Juli', 'Juli spoke.'), character('Julie', 'Juli spoke.')]
        client = client_for(response(items), response({'name': 'Juli'}))
        with self.assertRaisesRegex(ValueError, 'characters 数组'):
            _request_character_chunk(client, 'test', 2, 'Juli spoke.', {})

    def test_larger_index_uses_twenty_percent_limit(self):
        source = ' '.join(f'Person{i}' for i in range(10))
        for bad_count in (2, 3):
            items = [character(f'Person{i}', source) for i in range(10 - bad_count)]
            items += [character(f'Absent{i}', source) for i in range(bad_count)]
            client = client_for(response(items), response(items))
            with self.subTest(bad_count=bad_count):
                if bad_count == 3:
                    with self.assertRaisesRegex(ValueError, '经 2 次尝试'):
                        _request_character_chunk(client, 'test', 2, source, {})
                else:
                    warnings = []
                    result = _request_character_chunk(client, 'test', 2, source, {}, warnings=warnings)
                    self.assertEqual(len(result), 8)
                    self.assertEqual(warnings[0].rejected_items, 2)

    def test_invalid_cached_candidate_cannot_mask_malformed_fresh_response(self):
        source = 'Juli spoke.'
        items = [character('Juli', source), character('Julie', source)]
        first = client_for(response(items), response([items[0]]))
        with tempfile.TemporaryDirectory() as folder, checkpoint_scope(folder):
            _request_character_chunk(first, 'test', 2, source, {})
            path = next(Path(folder).glob('*.json'))
            content = json.dumps({'characters': items})
            path.write_text(json.dumps({'content': content, 'sha256': hashlib.sha256(content.encode()).hexdigest()}))
            fresh = client_for(response(items), response({'name': 'Juli'}))
            with self.assertRaisesRegex(ValueError, 'characters 数组'):
                _request_character_chunk(fresh, 'test', 2, source, {})

    def test_ambiguous_format_normalization_requires_correction(self):
        source = 'O’Neil and OʼNeil spoke.'
        item = character("O'Neil", source)
        client = client_for(response([item]), response([item]))
        with self.assertRaisesRegex(ValueError, '无法追溯'):
            _request_character_chunk(client, 'test', 2, source, {})

    def test_partial_registry_checkpoint_is_retried_and_can_recover(self):
        source = 'Juli spoke.'
        bad = [character('Juli', source), character('Julie', source)]
        client = client_for(response(bad), response(bad), response([bad[0]]))
        with tempfile.TemporaryDirectory() as folder, checkpoint_scope(folder), \
                patch('audiobook_generator.role_script.v2_generation.splitter._create_client', return_value=client):
            warnings = []
            entities = build_book_registry([('一', source)], api_key='dummy', base_url='https://example.invalid',
                                           model='test', warnings=warnings)
            self.assertEqual(len(warnings), 1)
            cached = json.loads(next(Path(folder).glob('registry-*.json')).read_text())
            self.assertEqual(cached['processed'], [])
            recovered = []
            second = build_book_registry([('一', source)], api_key='dummy', base_url='https://example.invalid',
                                         model='test', warnings=recovered)
            self.assertEqual(recovered, [])
            self.assertEqual(set(entities), set(second))
            self.assertEqual(client.chat.completions.create.call_count, 3)

    def test_case_changes_restore_exact_source_surface_without_another_request(self):
        source = 'my father paints.'
        good = character('my father', source)
        client = client_for(response([character('My Father', source, ['MY FATHER'])]))
        good['aliases'] = ['my father']
        self.assertEqual(_request_character_chunk(client, 'test', 8, source, {}), [good])
        self.assertEqual(client.chat.completions.create.call_count, 1)

    def test_cached_case_variations_are_grounded_again_on_restore(self):
        source = 'My mom smiled.'
        client = client_for(response([character('my mom', source, ['MY MOM'])]))
        with tempfile.TemporaryDirectory() as folder, checkpoint_scope(folder):
            for _ in range(2):
                self.assertEqual(_request_character_chunk(client, 'test', 8, source, {}),
                                 [character('My mom', source, ['My mom'])])
        self.assertEqual(client.chat.completions.create.call_count, 1)

    def test_malformed_response_gets_one_correction_request(self):
        good = character('Juli', 'Juli spoke.')
        client = client_for(response({'name': 'Juli'}), response([good]))
        self.assertEqual(_request_character_chunk(client, 'test', 8, 'Juli spoke.', {}), [good])
        self.assertEqual(client.chat.completions.create.call_count, 2)

    def test_case_and_word_boundary_must_match_the_same_occurrence(self):
        source = 'JoAnn met ann.'
        item = character('Ann', 'JoAnn')
        client = client_for(response([item]), response([item]))
        with self.assertRaisesRegex(ValueError, 'evidence_quote'):
            _request_character_chunk(client, 'test', 8, source, {})

    def test_valid_content_is_cached_and_empty_registry_is_allowed(self):
        for items in [[], [character('Juli', 'Juli spoke.')]]:
            with self.subTest(items=items), tempfile.TemporaryDirectory() as folder, checkpoint_scope(folder):
                client = client_for(response(items))
                for _ in range(2):
                    self.assertEqual(_request_character_chunk(client, 'test', 8, 'Juli spoke.', {}), items)
                self.assertEqual(client.chat.completions.create.call_count, 1)

    def test_cancel_and_network_failure_do_not_trigger_correction_requests(self):
        for error in [SplitAborted(), TimeoutError('timeout')]:
            with self.subTest(error=type(error).__name__):
                client = client_for(error)
                with self.assertRaises(type(error)):
                    _request_character_chunk(client, 'test', 8, 'Juli spoke.', {})
                self.assertEqual(client.chat.completions.create.call_count, 1)

    def test_registry_strips_name_before_matching_source(self):
        with patch('audiobook_generator.role_script.v2_generation.splitter._create_client', return_value=object()), \
             patch('audiobook_generator.role_script.v2_generation._request_character_chunk',
                   return_value=[character(' Juli ', 'Juli spoke.')]):
            entities = build_book_registry([('一', 'Juli spoke.')], api_key='dummy',
                                           base_url='https://example.invalid', model='test')
        self.assertIn('Juli', [entity.canonical_name for entity in entities.values()])


if __name__ == '__main__':
    unittest.main()
