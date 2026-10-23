import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from bs4 import BeautifulSoup
from ebooklib import epub

from audiobook_generator.book_parsers.epub_book_parser import EpubBookParser
from audiobook_generator.book_parsers.source_map import TrackedText, epub_source
from audiobook_generator.config.general_config import GeneralConfig
from audiobook_generator.role_script.narration import name_in_source
from audiobook_generator.role_script.v2_generation import _request_character_chunk


class EpubSourceMapTest(unittest.TestCase):
    def extract(self, html):
        return epub_source(BeautifulSoup(html, 'lxml-xml'), 'dedication.xhtml')

    def assert_coordinates(self, raw, records):
        tracked = TrackedText(raw).strip().sub(r'\s+', ' ')
        for record, cleaned in zip(records, tracked.paragraphs(records, 1)):
            self.assertEqual(raw[record['raw_start']:record['raw_end']], record['text'])
            self.assertEqual(tracked.text[cleaned['start']:cleaned['end']], cleaned['cleaned_text'])

    def test_line_break_preserves_name_boundary_and_source_coordinates(self):
        raw, records = self.extract(
            '<html><body><p>Dedicated with infinite love to<br/>Colton and Connor,'
            '<br/>who make me feel like so much more than the sum of my parts.</p></body></html>')
        self.assertIn('to\nColton', raw)
        self.assertTrue(name_in_source('Colton', raw))
        self.assertEqual(len(records), 1)
        self.assert_coordinates(raw, records)

    def test_adjacent_blocks_separate_words_without_splitting_inline_names(self):
        raw, records = self.extract(
            '<html><body><p>Dedicated to</p><p>Col<b>ton</b> and Connor.</p></body></html>')
        self.assertEqual(raw, 'Dedicated to\nColton and Connor.')
        self.assertEqual(len(records), 2)
        self.assertTrue(name_in_source('Colton', raw))
        self.assert_coordinates(raw, records)

    def test_inline_markup_and_comments_do_not_create_false_name_boundaries(self):
        raw, records = self.extract('<html><body><p>Jo<!--not text--><b>ann</b>e spoke.</p></body></html>')
        self.assertEqual(raw, 'Joanne spoke.')
        self.assertFalse(name_in_source('Ann', raw))
        self.assert_coordinates(raw, records)

    def test_existing_whitespace_is_preserved_between_blocks(self):
        soup = BeautifulSoup('<html><body><p>Juli.</p>\n\n<p>Bryce.</p></body></html>', 'lxml-xml')
        raw, records = epub_source(soup, 'dedication.xhtml')
        self.assertEqual(raw, soup.get_text())
        self.assert_coordinates(raw, records)

    def test_epub_parser_and_character_validator_accept_dedication_in_all_newline_modes(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'dedication.epub'
            book = epub.EpubBook()
            book.set_identifier('line-break-regression')
            book.set_title('换行回归书籍')
            book.set_language('en')
            page = epub.EpubHtml(title='Dedication', file_name='dedication.xhtml', lang='en')
            page.content = '<p>Dedicated with infinite love to<br/>Colton and Connor,<br/>who make me smile.</p>'
            book.add_item(page)
            book.add_item(epub.EpubNcx())
            book.toc = [page]
            book.spine = [page]
            epub.write_epub(str(path), book)
            for mode in ('single', 'double', 'none'):
                with self.subTest(mode=mode):
                    config = GeneralConfig(None)
                    config.input_file = str(path)
                    config.title_mode, config.newline_mode = 'auto', mode
                    parser = EpubBookParser(config)
                    text = parser.get_chapters('   ')[0][1]
                    self.assertIn('to Colton', text)
                    item = {'name': 'Colton', 'aliases': [], 'evidence_quote': text}
                    result = SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',
                        message=SimpleNamespace(content=json.dumps({'characters': [item]})))])
                    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(return_value=result))))
                    self.assertEqual(_request_character_chunk(client, 'test', 2, text, {}), [item])
                    self.assertEqual(client.chat.completions.create.call_count, 1)
                    for record in parser.source_chapters[0]['paragraphs']:
                        self.assertEqual(text[record['start']:record['end']], record['cleaned_text'])


if __name__ == '__main__':
    unittest.main()
