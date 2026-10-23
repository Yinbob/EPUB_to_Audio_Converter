"""迁移后的生成语义回归；临时文件与假 Provider，不调用远程接口。"""
import io
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from audiobook_generator.services.books import configs_for
from audiobook_generator.services.common import ServiceError
from audiobook_generator.services.files import FileStore
from audiobook_generator.services.models import Generation
from audiobook_generator.services.worker import BatchConversionError, execute, preview_book


class GenerationParityTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.files = FileStore(self.root)
        self.book = self.files.upload('一册书.epub', io.BytesIO(b'book'))
        self.log = logging.getLogger('test.generation')

    def generation(self, **kwargs):
        return Generation(file_ids=[self.book['id']], engine={'provider': 'openai'}, **kwargs)

    def test_quality_normalizes_workers_and_disabled_config_is_ignored(self):
        cfg = configs_for(self.generation(audio_core_enabled=True, worker_count=3), self.files, self.root)[0]
        self.assertEqual(cfg.worker_count, 1)
        invalid = self.files.upload('settings.json', io.BytesIO(b'{"unknown": true}'))
        cfg = configs_for(self.generation(audio_core_enabled=False, audio_core_settings_file=invalid['id']),
                          self.files, self.root)[0]
        self.assertFalse(cfg.audio_core_enabled)
        with self.assertRaises(ValueError):
            configs_for(self.generation(audio_core_enabled=True, audio_core_settings_file=invalid['id']),
                        self.files, self.root)

    def test_preview_config_without_book_requires_explicit_opt_in(self):
        request = self.generation().model_copy(update={'file_ids': []})
        with self.assertRaises(ServiceError):
            configs_for(request, self.files, self.root)
        config = configs_for(request, self.files, self.root, allow_empty=True)[0]
        self.assertIsNone(config.input_file)
        self.assertEqual(config.tts, 'openai')

    def test_batch_preserves_original_names_and_avoids_duplicate_folders(self):
        duplicate = self.files.upload('一册书.epub', io.BytesIO(b'another book'))
        request = self.generation().model_copy(update={'file_ids': [self.book['id'], duplicate['id']]})
        configs = configs_for(request, self.files, self.root)
        self.assertEqual(Path(configs[0].output_folder).name, '一册书')
        self.assertNotEqual(configs[0].output_folder, configs[1].output_folder)
        self.assertEqual([cfg.source_name for cfg in configs], ['一册书.epub', '一册书.epub'])

    def test_preview_exports_only_selected_chapters_without_provider(self):
        cfg = configs_for(self.generation(preview=True, output_text=True, chapter_start=2, chapter_end=2),
                          self.files, self.root / 'output')[0]
        with patch('audiobook_generator.book_parsers.base_book_parser.get_book_parser') as parser:
            parser.return_value.get_chapters.return_value = [('第一章', '甲'), ('第二章', '乙乙'), ('第三章', '丙')]
            summaries = preview_book(cfg, self.log)
        self.assertEqual(summaries, [{'index': 2, 'title': '第二章', 'characters': 2}])
        outputs = list((self.root / 'output').glob('*.txt'))
        self.assertEqual(len(outputs), 1)
        self.assertEqual(outputs[0].read_text(encoding='utf-8'), '乙乙')
        self.assertIn('第二章', outputs[0].name)

    def test_preview_rejects_range_beyond_book(self):
        cfg = configs_for(self.generation(preview=True, chapter_start=2), self.files, self.root)[0]
        with patch('audiobook_generator.book_parsers.base_book_parser.get_book_parser') as parser:
            parser.return_value.get_chapters.return_value = [('第一章', '甲')]
            with self.assertRaises(ValueError):
                preview_book(cfg, self.log)

    def test_failed_book_does_not_skip_later_books_and_final_result_fails(self):
        second = self.files.upload('第二册.epub', io.BytesIO(b'second'))
        request = self.generation().model_copy(update={'file_ids': [self.book['id'], second['id']]})
        configs = configs_for(request, self.files, self.root)
        previous_level = logging.getLogger().level
        self.addCleanup(logging.getLogger().setLevel, previous_level)
        with patch('audiobook_generator.core.audiobook_generator.AudiobookGenerator') as generator:
            generator.return_value.run.side_effect = [False, True]
            with self.assertRaises(BatchConversionError) as failure:
                execute({'kind': 'generate', 'configs': configs}, self.log, self.root / 'result.json')
        self.assertEqual(generator.call_count, 2)
        self.assertEqual([book['status'] for book in failure.exception.result['books']], ['failed', 'succeeded'])
        self.assertIn('1 本成功，1 本失败', str(failure.exception))


if __name__ == '__main__':
    unittest.main()
