"""人工编写的英文正反例；检验比较规则，不作为真实 TTS 缺陷数据。"""
import unittest
import tempfile
from pathlib import Path

from audiobook_generator.audio_core.english_reading import comparison_reading
from audiobook_generator.audio_core.quality import align_text
from audiobook_generator.audio_core.reading import normalize_reading_text, reading_count
from audiobook_generator.audio_core.models import CoreOptions, ResourceLimits
from audiobook_generator.audio_core.pipeline import run_chapter
from audiobook_generator.audio_core.quality import QualityEvaluator
from audiobook_generator.core.audio_tags import AudioTags
from tests.audiobook_generator.audio_core.pipeline_test import ObservedFake, plan_for


class EnglishReadingTest(unittest.TestCase):
    def test_safe_numeric_forms_match_without_changing_tts_body(self):
        cases = [('There are 20 books.', 'There are twenty books.'),
                 ('Count 105 birds.', 'Count one hundred five birds.'),
                 ('There are 1,024 pages.', 'There are one thousand twenty four pages.'),
                 ('Growth was 3.5%.', 'Growth was three point five percent.'),
                 ('Growth was -3.50%.', 'Growth was minus three point five zero percent.'),
                 ('The reading is +0.25.', 'The reading is plus zero point two five.'),
                 ('This is the 21st chapter.', 'This is the twenty first chapter.'),
                 ('This is the 12th book.', 'This is the twelfth book.'),
                 ('The probability is 0.5 %.', 'The probability is zero point five percent.')]
        for reference, transcript in cases:
            with self.subTest(reference=reference):
                self.assertEqual(align_text(reference, transcript, language='en')['error_rate'], 0)
                self.assertEqual(normalize_reading_text(reference, language='en')[0], reference)

    def test_date_equivalence_is_scoped_to_valid_named_month_dates(self):
        for form in ('October 16, 2026', 'October 16th 2026', '16 October 2026',
                     '16th of October 2026', 'October sixteenth twenty twenty six',
                     'October sixteen two thousand and twenty six',
                     'October sixteenth, two thousand twenty six'):
            with self.subTest(form=form):
                self.assertEqual(align_text('On October 16, 2026.', 'On ' + form + '.', language='en')['error_rate'], 0)
        self.assertEqual(align_text('On February 29, 2024.',
                         'On February twenty ninth twenty twenty four.')['error_rate'], 0)
        self.assertEqual(align_text('On December 31, 1999.',
                         'On December thirty first nineteen ninety nine.')['error_rate'], 0)

    def test_wrong_date_number_negation_repetition_or_added_text_does_not_pass(self):
        cases = [('There are 20 books.', 'There are twenty one books.'),
                 ('Growth was 3.5%.', 'Growth was thirty five percent.'),
                 ('Growth was 3.5%.', 'Growth was three point five.'),
                 ('Growth was -3.5%.', 'Growth was three point five percent.'),
                 ('On October 16, 2026.', 'On October seventeenth twenty twenty six.'),
                 ('On October 16, 2026.', 'On November sixteenth twenty twenty six.'),
                 ('On October 16, 2026.', 'On October sixteenth twenty twenty five.'),
                 ('Do not read 20 twice.', 'Do read twenty twice.'),
                 ('Read 20 once.', 'Read twenty twenty once.'),
                 ('Read 20 once.', 'Read twenty once and add this sentence.')]
        for reference, transcript in cases:
            with self.subTest(reference=reference, transcript=transcript):
                self.assertGreater(align_text(reference, transcript, language='en')['error_rate'], 0)

    def test_invalid_dates_are_not_silently_corrected_or_partially_expanded(self):
        for value in ('February 30, 2026', 'February 29, 2025', 'April 31, 2026', 'October 16st, 2026'):
            text = 'On ' + value + '.'
            rendered, events = comparison_reading(text)
            self.assertEqual(rendered, text)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]['status'], 'needs_review')
        self.assertGreater(align_text('On February 30, 2026.',
                                     'On March second twenty twenty six.')['error_rate'], 0)

    def test_ambiguous_identifiers_versions_and_numeric_dates_are_preserved(self):
        cases = ['Use code 0012.', 'Use code 12.', 'Use version 2.1.', 'Use model 3.', 'Use order 123.',
                 'Read ISBN 123456.', 'Read v2.1 and A320.', 'Meet on 03/04/2026.',
                 'Meet on 2026-10-16.', 'Call 555-1234.', 'Read 1e3 and 1.2.3.',
                 'Read 0003.5 and 3.123456.', 'Read 1,00 and 1,234,56.', 'Read 2026 and 1234567.',
                 'Read 21th and 12nd.', 'Read 3kg and 3GHz.']
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(comparison_reading(text)[0], text)

    def test_acronyms_and_contractions_still_require_explicit_readings(self):
        self.assertGreater(align_text('Use API.', 'Use application programming interface.')['error_rate'], 0)
        self.assertEqual(align_text('Use API.', 'Use application programming interface.',
            dictionary={'API': 'application programming interface'})['error_rate'], 0)
        self.assertGreater(align_text("Don't stop.", 'Do not stop.')['error_rate'], 0)

    def test_numeric_events_retain_input_spans_and_policy_version(self):
        text = 'At 3.5%, on October 16, 2026, use version 2.1.'
        report = align_text(text, 'At three point five percent on October sixteenth twenty twenty six use version 2.1.')
        self.assertEqual(report['error_rate'], 0)
        details = report['comparison_normalization']['reference']
        self.assertEqual(details['event_coordinate_scope'], 'NFKC_and_explicit_dictionary_comparison_input')
        self.assertEqual(report['normalization_version'], 'bilingual-reading-v6')
        for event in details['english_events']:
            self.assertEqual(text[event['input_start']:event['input_end']], event['before'])
            self.assertEqual(event['version'], 'en-comparison-v1')
        self.assertTrue(any(e['status'] == 'needs_review' for e in details['english_events']))

    def test_equivalent_numeric_rendering_does_not_request_content_repair(self):
        # 假音频和可控转写只验证修复调度，不代表真实 ASR 或修复效果。
        for transcript, repair_requests in (('There are twenty books.', 0),
                                             ('There are twenty one books.', 1)):
            with self.subTest(transcript=transcript), tempfile.TemporaryDirectory() as root:
                provider = ObservedFake()
                options = CoreOptions(language='en', enable_speaker=False, auto_repair=True,
                    limits=ResourceLimits(max_requests=2, max_repair_requests=1))
                evaluator = QualityEvaluator(options, transcribe=lambda _: transcript)
                result = run_chapter(plan_for(('There are 20 books.',)), provider,
                    Path(root) / 'out.wav', AudioTags('章', '作者', '书', 1),
                    Path(root) / 'project', options=options, evaluator=evaluator)
                self.assertEqual(len(provider.calls), 1 + repair_requests)
                self.assertEqual(sum(call[2] for call in provider.calls), repair_requests)
                attempts = [r for r in result['repair_attempts'] if r['action']['kind'] == 'content_repair']
                self.assertEqual(len(attempts), repair_requests)
                issues = result['chunks'][0]['report']['issues']
                self.assertEqual(any(i['code'] == 'asr_mismatch' for i in issues), bool(repair_requests))
                self.assertEqual(provider.calls[0][0], 'There are 20 books.')

    def test_rate_counts_spoken_numeric_units_and_preserves_chinese(self):
        count, language, unit = reading_count('Growth was 3.5%.')
        self.assertEqual((count, language, unit), (6, 'en', 'word'))
        self.assertEqual(align_text('今天增长3.5%', '今天增长百分之三点五')['error_rate'], 0)
        self.assertEqual(normalize_reading_text('今天增长3.5%')[0], '今天增长百分之三点五')
