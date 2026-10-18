"""验证直接下载与打包的文件边界、名称和源文件保留。"""
import tempfile
import unittest
import zipfile
from pathlib import Path
from audiobook_generator.ui.library import selected_paths, selection_details, create_archive


class TestLibrary(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.batch = self.root / '书名 & 章节'
        self.batch.mkdir()
        (self.batch / '第一章.mp3').write_bytes(b'audio')
        (self.batch / '第一章.txt').write_text('正文')
        (self.root / 'secret.txt').write_text('不可选文件')

    def test_direct_download_keeps_original_names_and_only_lists_selected_audio(self):
        summary, paths, audio = selection_details(self.root, self.batch.name, ['第一章.mp3', '第一章.txt'])
        self.assertIn('书名 &amp; 章节', summary)
        self.assertIn('已选择 2 个文件', summary)
        self.assertEqual([Path(path).name for path in paths], ['第一章.mp3', '第一章.txt'])
        self.assertEqual(audio, ['第一章.mp3'])

    def test_stale_missing_duplicate_and_outside_paths_are_not_downloadable(self):
        paths = selected_paths(self.root, self.batch.name, ['第一章.mp3', '第一章.mp3', 'missing.wav', '../secret.txt', str(self.root / 'secret.txt')])
        self.assertEqual([path.name for path in paths], ['第一章.mp3'])
        self.assertEqual(selected_paths(self.root, '..', ['secret.txt']), [])
        (self.batch / 'link.txt').symlink_to(self.root / 'secret.txt')
        self.assertEqual(selected_paths(self.root, self.batch.name, ['link.txt']), [])

    def test_archives_are_unique_and_keep_source_files(self):
        first, count = create_archive(self.root, self.batch.name, ['第一章.mp3', '第一章.txt'])
        second, _ = create_archive(self.root, self.batch.name, ['第一章.mp3'])
        self.assertNotEqual(first, second)
        self.assertEqual(count, 2)
        self.assertEqual(Path(first).name, '书名___章节.zip')
        with zipfile.ZipFile(first) as archive:
            self.assertEqual(archive.namelist(), ['第一章.mp3', '第一章.txt'])
            self.assertEqual(archive.read('第一章.mp3'), b'audio')
        self.assertTrue((self.batch / '第一章.mp3').is_file())
        self.assertTrue((self.batch / '第一章.txt').is_file())

    def test_empty_selection_does_not_produce_an_empty_download(self):
        with self.assertRaisesRegex(ValueError, '没有可下载'):
            create_archive(self.root, self.batch.name, ['missing.mp3'])
        self.assertFalse((self.root / '.temp_downloads').exists())
