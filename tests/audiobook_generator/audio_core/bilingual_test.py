"""英文优先的内容、分块、语速及语言核验边界回归；不调用真实 API。"""
import contextlib
import io
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

from audiobook_generator.audio_core.__main__ import main
from audiobook_generator.audio_core.casting import apply_casting, optimize_casting
from audiobook_generator.audio_core.models import CoreOptions, ReadingChunk
from audiobook_generator.audio_core.language import join_reading_texts
from audiobook_generator.audio_core.quality import QualityEvaluator, align_text
from audiobook_generator.audio_core.reading import build_reading_plan, normalize_reading_text
from audiobook_generator.audio_core.repair import content_repair_profile, propose_actions, split_repair_chunk
from audiobook_generator.audio_core.pipeline import run_chapter
from audiobook_generator.core.audio_tags import AudioTags
from tests.audiobook_generator.audio_core.pipeline_test import ObservedFake, plan_for
from tests.audiobook_generator.audio_core import voice_bank_metadata_test


class BilingualCoreTest(unittest.TestCase):
    def test_percent_at_sentence_boundary_uses_same_equivalence_as_single_chunk(self):
        left = 'On October 16, 2026, growth was 3.5%.'
        right = 'The 21st runner carried 24 cards.'
        hypothesis = ('On October sixteenth twenty twenty six, growth was three point five percent. '
                      'The twenty first runner carried twenty four cards.')
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'constructed.wav'
            sf.write(path, .1 * np.sin(np.arange(64000) * .1), 16000)
            chunks = build_reading_plan(plan_for((left, right)).units, language='en')
            evaluator = QualityEvaluator(CoreOptions(enable_speaker=False), transcribe=lambda _: hypothesis)
            report = evaluator.evaluate_boundary(*chunks, path, path, assembled_window=path)
            self.assertEqual(report.dimensions['content'], 'passed')
            self.assertNotIn('boundary_content_mismatch', [i.code for i in report.issues])
            self.assertEqual(report.metrics['content_alignment']['error_rate'], 0)

    def test_english_join_handles_quotes_without_changing_chinese_or_existing_spaces(self):
        for parts, expected in [(['Growth was 3.5%.', 'Next year.'], 'Growth was 3.5%. Next year.'),
                                (['She said, "Wait."', '"I will."'], 'She said, "Wait." "I will."'),
                                (['Dr.', 'Smith arrived.'], 'Dr. Smith arrived.'),
                                (['First. ', 'Next.'], 'First. Next.'),
                                (['well-', 'known'], 'well-known'),
                                (['第一句。', '第二句。'], '第一句。第二句。')]:
            with self.subTest(parts=parts):
                self.assertEqual(join_reading_texts(parts), expected)

    def test_boundary_word_separation_does_not_hide_wrong_percent_or_omission(self):
        reference = join_reading_texts(['Growth was 3.5%.', 'Do not stop.'])
        for hypothesis in ['Growth was three point six percent. Do not stop.',
                           'Growth was three point five. Do not stop.',
                           'Growth was three point five percent. Do stop.',
                           'Growth was three point five percent. Do not stop. Do not stop.']:
            with self.subTest(hypothesis=hypothesis):
                self.assertGreater(align_text(reference, hypothesis, language='en')['error_rate'], 0)

    def test_english_dates_numbers_percent_remain_english_and_dictionary_has_mapping(self):
        text = 'On October 16, 2026, growth was 3.5%. API version 2.1 is ready.'
        spoken, mapping, edits = normalize_reading_text(text, language='en-US')
        self.assertEqual(spoken, text)
        self.assertEqual(mapping, [(i, i + 1) for i in range(len(text))])
        self.assertFalse(edits)
        spoken, mapping, edits = normalize_reading_text(text, language='en', dictionary={'API': 'A P I'})
        self.assertIn('A P I version', spoken)
        self.assertEqual(len(mapping), len(spoken))
        self.assertEqual(edits[0]['before'], 'API')

    def test_wer_retains_words_negation_repetition_and_apostrophes(self):
        for source, transcript in [('an ice cream', 'a nice cream'), ('the rapist', 'therapist'),
                                   ("I'll arrive", 'ill arrive'), ('do not stop', 'do stop'),
                                   ('wait here', 'wait wait here'), ('growth 3.5%', 'growth 3.5'),
                                   ('temperature -3 degrees', 'temperature 3 degrees')]:
            with self.subTest(source=source):
                alignment = align_text(source, transcript)
                self.assertEqual(alignment['error_metric'], 'WER')
                self.assertGreater(alignment['error_rate'], 0)
        alignment = align_text('One small step.', 'ONE step!')
        self.assertAlmostEqual(alignment['error_rate'], 1 / 3)
        self.assertEqual(alignment['deletions'], 1)
        self.assertEqual(align_text('Don’t stop.', "don't stop")['error_rate'], 0)
        self.assertEqual(align_text('café is open', 'Café is open!')['reference_unit_count'], 3)
        self.assertEqual(align_text('3.5%', '3.5 percent', language='en')['error_rate'], 0)
        self.assertEqual(align_text('增长3.5%', '增长百分之三点五')['error_metric'], 'CER')

    def test_ambiguous_number_and_contraction_equivalence_requires_explicit_dictionary(self):
        self.assertEqual(align_text('There are 20 books.', 'There are twenty books.')['error_rate'], 0)
        self.assertGreater(align_text('Use code 0012.', 'Use code twelve.')['error_rate'], 0)
        self.assertEqual(align_text('There are 20 books.', 'There are twenty books.',
                                   dictionary={'20': 'twenty'})['error_rate'], 0)
        self.assertGreater(align_text("don't stop", 'do not stop')['error_rate'], 0)

    def test_english_chunks_preserve_source_words_decimal_and_abbreviation(self):
        text = "Dr. Smith doesn't change version 3.5 today. Another sentence follows quietly."
        chunks = build_reading_plan(plan_for((text,)).units, chunk_chars=24, language='en')
        self.assertEqual(''.join(c.source_text for c in chunks), text)
        self.assertEqual(''.join(c.tts_text for c in chunks), text)
        for left, right in zip(chunks, chunks[1:]):
            self.assertFalse(left.tts_text[-1].isalnum() and right.tts_text[0].isalnum())
        self.assertTrue(any('3.5' in c.tts_text for c in chunks))
        self.assertTrue(any("doesn't" in c.tts_text for c in chunks))
        self.assertTrue(all(c.language == 'en' for c in chunks))
        long_word = 'x' * 80
        self.assertEqual(len(build_reading_plan(plan_for((long_word,)).units, chunk_chars=20)), 1)

    def test_english_content_repair_keeps_voice_and_uses_english_instructions(self):
        text = 'Please read this opening sentence carefully. Keep every word of the following sentence.'
        chunk = build_reading_plan(plan_for((text,)).units, language='en')[0]
        profile = content_repair_profile(chunk, 'Stay calm.')
        self.assertIn('Stay calm.', profile.provider_params['instructions'])
        self.assertIn('Read the supplied body text', profile.provider_params['instructions'])
        self.assertEqual(profile.provider_params['voice'], chunk.profile['voice'])
        parts = split_repair_chunk(chunk)
        self.assertEqual(len(parts), 2)
        self.assertEqual(''.join(c.source_text for c in parts), text)
        self.assertTrue(all(c.language == 'en' for c in parts))

    def test_english_rate_and_cross_language_reference_use_correct_units(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'sound.wav'
            sf.write(path, .1 * np.sin(np.arange(64000) * .1), 16000)
            text = 'One two three four five six seven eight nine ten eleven twelve.'
            chunk = ReadingChunk('en', 'u', 'narrator', text, text, 0, len(text), language='en')
            evaluator = QualityEvaluator(CoreOptions(max_english_wpm=120, enable_speaker=False),
                                         transcribe=lambda _: text)
            report = evaluator.evaluate_chunk(chunk, path, anchor=(path,
                {'articulation_rate': 3., 'articulation_rate_unit': 'han_characters_per_second'}))
            self.assertEqual(report.metrics['content_alignment']['error_metric'], 'WER')
            self.assertAlmostEqual(report.metrics['words_per_minute'], 180)
            self.assertEqual(report.metrics['articulation_rate_unit'], 'words_per_second')
            self.assertEqual(report.metrics['rate_threshold'], 2.)
            self.assertIn('too_fast', [i.code for i in report.issues])
            self.assertNotIn('rate_drift', [i.code for i in report.issues])
            self.assertEqual(propose_actions(report)[0].kind, 'local_speed')
            mixed = replace(chunk, tts_text='One two three 四五六', language='mixed')
            mixed_report = evaluator.evaluate_chunk(mixed, path)
            self.assertIsNone(mixed_report.metrics['articulation_rate'])
            self.assertIsNone(mixed_report.metrics['rate_threshold'])

    def test_boundary_and_encoded_reference_preserve_english_word_boundary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evaluator = QualityEvaluator(CoreOptions(enable_speaker=False), transcribe=lambda _: 'first second')
            result = run_chapter(replace(plan_for(('first', 'second')), output_format='mp3'), ObservedFake(), root / 'out.mp3',
                AudioTags('English', 'Test', 'Test', 1), root / 'project',
                options=CoreOptions(language='en', enable_speaker=False), evaluator=evaluator)
            self.assertEqual(result['reading_configuration']['language'], 'en')
            self.assertEqual(result['boundaries'][0]['metrics']['content_alignment']['reference_tokens'], ['first', 'second'])
            pairs = [c for c in result['final_verification']['metrics']['checks'] if '|' in c['scope_id']]
            self.assertEqual(len(pairs), 1)
            self.assertEqual(pairs[0]['content_alignment']['reference_tokens'], ['first', 'second'])

    def test_chinese_bank_cannot_be_claimed_as_english_or_used_for_english_chapter(self):
        bank = {'provider': 'openai', 'languages': ['zh'], 'voices': {
            '冰糖': {'verified': True, 'embeddings': {'a': [1., 0.], 'b': [1., 0.]}}}}
        with self.assertRaisesRegex(ValueError, '目标语言'):
            optimize_casting(['narrator'], {}, bank, language='en')
        result = optimize_casting(['narrator'], {}, bank, language='zh')
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'cast.json'
            path.write_text(json.dumps(result))
            with self.assertRaisesRegex(ValueError, '正文语言'):
                apply_casting(plan_for(('Hello world.',)), path, language='en-US')
            self.assertEqual(apply_casting(plan_for(), path, language='zh-CN').units[0].profile.provider_params['voice'], '冰糖')

    def test_english_bank_counts_words_and_keeps_language_scope(self):
        class Encoder:
            def cache_identity(self):
                return {'fingerprint': 'fixture-only'}
            def __call__(self, path):
                return np.array([1., 0.])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            helper = voice_bank_metadata_test.VoiceBankMetadataTest()
            path = helper.prepare(root)
            manifest = json.loads(path.read_text())
            for record in manifest['probes']:
                record.update(language='en', text='One two three four five six seven eight.')
            path.write_text(json.dumps(manifest))
            with patch('audiobook_generator.audio_core.backends.SpeakerEncoder', lambda _: Encoder()), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(helper.command(root)), 0)
            bank = json.loads((root / 'bank.json').read_text())
            self.assertEqual(bank['languages'], ['en'])
            record = bank['voices']['冰糖']['probes']['1']
            self.assertEqual(record['reading_unit_kind'], 'english_normalized_reading_words')
            self.assertAlmostEqual(record['metrics']['words_per_minute'], 120)

    def test_probe_budget_precheck_sends_no_requests(self):
        with patch('audiobook_generator.tts_providers.openai_tts_provider.OpenAITTSProvider') as provider, \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['probe', '--voices', 'Mia', 'Milo', '--prompt-count', '2',
                                   '--max-requests', '3', '--output', '/not-created']), 2)
            provider.assert_not_called()

    def test_english_rate_configuration_rejects_zero_boolean_and_nonfinite_values(self):
        from audiobook_generator.config.general_config import GeneralConfig
        for value in (0, -1, True, float('inf'), float('nan')):
            with self.subTest(value=value):
                config = GeneralConfig(None)
                config.audio_core_max_english_wpm = value
                with self.assertRaises(ValueError):
                    CoreOptions.from_config(config)
        config = GeneralConfig(None)
        config.language, config.audio_core_max_english_wpm = 'en-US', 240
        self.assertEqual(CoreOptions.from_config(config).language, 'en')
        self.assertEqual(CoreOptions.from_config(config).max_english_wpm, 240)
