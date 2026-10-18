"""章节名称与转换范围必须一致，不调用外部服务。"""
import json
import inspect
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bs4 import BeautifulSoup
from ebooklib import epub

from audiobook_generator.ui.chapters import CHAPTER_HEAD_HTML, chapter_catalog

try:
    from audiobook_generator.ui import web_ui
except ImportError:
    web_ui = None


def payload(value):
    return json.loads(BeautifulSoup(value, 'html.parser').span['data-chapter-range'])


@unittest.skipIf(web_ui is None, 'UI 依赖不可用')
class ChapterSelectionTest(unittest.TestCase):
    def test_real_epub_empty_chapters_duplicates_and_over_100_match_converter(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'chapters.epub'
            book = epub.EpubBook()
            book.set_identifier('chapter-selection-test')
            book.set_title('Chapter selection')
            book.set_language('en')
            book.add_item(epub.EpubNcx())
            documents = []
            for index in range(107):
                item = epub.EpubHtml(title='Chapter', file_name=f'c{index}.xhtml', lang='en')
                item.content = '<html><body></body></html>' if index == 0 else '<h1>Same Chapter</h1><p>Hello world.</p>'
                book.add_item(item)
                documents.append(item)
            book.spine = documents
            epub.write_epub(str(path), book)
            # 读目录和生成使用相同解析设置，不能先实例化需要凭证的引擎。
            with patch.object(web_ui, 'get_tts_provider', side_effect=AssertionError('不得创建引擎')):
                result = web_ui.read_book_chapters([str(path)], 'Mimo', 'auto', 'double', False, False, None)
                chapters, *_ = web_ui._auto_split_chapters('Mimo', str(path), 1, -1, 'auto', 'double', False, False, None)
            catalog = result[0]['chapters']
            self.assertEqual(len(catalog), 106)
            self.assertEqual([item['index'] for item in catalog], list(range(1, 107)))
            self.assertEqual(result[1]['choices'][0], ('01 · Same Chapter', 1))
            self.assertEqual(result[1]['choices'][-1], ('106 · Same Chapter', 106))
            selection = web_ui.select_book_chapter(102, 106, catalog, 'start')
            self.assertEqual(selection[2:4], (102, 106))
            self.assertEqual(payload(selection[4])['chars'], sum(len(text) for _, text in chapters[101:106]))
            dropdown = web_ui.gr.Dropdown(choices=result[1]['choices'])
            self.assertEqual(dropdown.preprocess(106), 106)

    def test_reverse_range_keeps_changed_endpoint_and_allows_one_chapter(self):
        catalog = chapter_catalog([('First', 'one'), ('Second', 'two'), ('Third', 'three')])
        start = web_ui.select_book_chapter(3, 1, catalog, 'start')
        self.assertEqual(start[2:4], (3, 3))
        self.assertEqual(payload(start[4])['count'], 1)
        end = web_ui.select_book_chapter(3, 1, catalog, 'end')
        self.assertEqual(end[2:4], (1, 1))
        with self.assertRaises(web_ui.gr.Error):
            web_ui.select_book_chapter(4, 4, catalog, 'start')

    def test_removed_file_batch_and_failed_parse_clear_stale_names(self):
        for files in ([], ['one.epub', 'two.epub'], ['missing.epub']):
            with patch.object(web_ui, 'get_book_parser', side_effect=ValueError('解析失败')):
                result = web_ui.read_book_chapters(files, 'Mimo', 'auto', 'double', False, False, None)
            self.assertFalse(result[0].get('chapters'))
            self.assertIsNone(result[1]['value'])
            self.assertFalse(result[1]['interactive'])
            self.assertEqual(result[3]['value'], 1)
            self.assertEqual(result[4]['value'], -1)
            self.assertEqual(result[6]['visible'], len(files) > 1)
            self.assertEqual(payload(result[5])['total'], 0)
            if len(files) == 1:
                self.assertIn('重新读取目录', payload(result[5])['message'])

    def test_parser_settings_are_used_and_titles_are_safe_display_text(self):
        parser = SimpleNamespace(get_chapters=lambda break_string: [('A_<script>"B"', 'Hello')])
        with patch.object(web_ui, '_chapter_directory_source', return_value=('signature', ['book.epub'], ['booksha'])), \
             patch.object(web_ui, 'get_book_parser', return_value=parser) as factory:
            result = web_ui.read_book_chapters('book.epub', 'Mimo', 'first_few', 'none', True, True, 'replace.txt')
        config = factory.call_args.args[0]
        self.assertEqual(config.title_mode, 'first_few')
        self.assertEqual(config.newline_mode, 'none')
        self.assertTrue(config.remove_endnotes)
        self.assertTrue(config.remove_reference_numbers)
        self.assertEqual(config.search_and_replace_file, 'replace.txt')
        value = result[5]
        self.assertNotIn('<script>', value)
        self.assertEqual(payload(value)['first'], 'A <script>"B"')

    def test_execute_resolves_current_names_and_rejects_old_book_or_client_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            first = Path(folder) / 'A.epub'
            second = Path(folder) / 'B.epub'
            first.write_bytes(b'book A')
            second.write_bytes(b'book B')
            parser = SimpleNamespace(get_chapters=lambda _: [('One', 'text'), ('Two', 'text')])
            with patch.object(web_ui, 'get_book_parser', return_value=parser):
                old = web_ui.read_book_chapters([str(first)], 'Mimo', 'auto', 'double', False, False, None)
                current = web_ui.read_book_chapters([str(second)], 'Mimo', 'auto', 'double', False, False, None)
            def resolve(state, token, book=second, names=(2, 2), newline='double'):
                return web_ui.resolve_book_chapter_range(
                    [str(book)], 'Mimo', 'auto', newline, False, False, None,
                    1, -1, state, token, *names)
            self.assertEqual(resolve(current[0], current[8]), (2, 2))
            # 排队的旧A选章事件在B目录载入后执行：只能跳过，不能写回B的控件。
            stale_selection = web_ui.select_book_chapter(1, 1, current[0], 'start', old[8])
            self.assertTrue(all(update == web_ui.gr.skip() for update in stale_selection))
            self.assertEqual(web_ui.select_book_chapter(2, 2, current[0], 'start', current[8])[2:4], (2, 2))
            for state, token, newline in [(old[0], old[8], 'double'),
                                           (current[0], old[8], 'double'),
                                           (current[0], current[8], 'none')]:
                with self.assertRaisesRegex(ValueError, '目录正在更新'):
                    resolve(state, token, newline=newline)
            # 真正的生成与自动拆分入口都必须在创建进程/调用API前拒绝旧目录。
            kwargs = dict.fromkeys(inspect.signature(web_ui.process_form).parameters, None)
            kwargs.update(provider='Mimo', input_file=[str(second)], title_mode='auto', new_line_mode='double',
                          chapter_start=1, chapter_end=-1, chapter_catalog_state=old[0],
                          chapter_selection_source=old[8], chapter_from_name=1, chapter_to_name=1)
            with patch.object(web_ui.gr, 'Warning') as warning, patch.object(web_ui, 'get_context') as process:
                web_ui.process_form(**kwargs)
                process.assert_not_called()
                self.assertIn('目录正在更新', warning.call_args.args[0])
            with patch.object(web_ui, 'generate_v2_for_book') as generate:
                web_ui.auto_split_role_script(
                    [str(second)], True, True, 'Mimo', 1, -1, 'auto', 'double', False, False,
                    None, 'key', 'url', 'model', False, old[0], old[8], 1, 1)
                generate.assert_not_called()
            kwargs.update(output_dir=folder, worker_count=1, model='mimo-v2.5-tts', voices='mimo_default',
                          speed=1.0, openai_output_format='wav', instructions='', enable_stream=False,
                          chapter_catalog_state=current[0], chapter_selection_source=current[8],
                          chapter_from_name=2, chapter_to_name=2)
            # 隐藏数字仍是旧的1..-1，执行入口必须使用点击开始时的新下拉2..2。
            with patch.object(web_ui, 'launch_batch') as launch, \
                 patch.object(web_ui, 'get_progress_info', return_value=(web_ui.gr.update(), web_ui.gr.Timer(active=False))):
                web_ui.process_form(**kwargs)
                config = launch.call_args.args[0][0]
                self.assertEqual((config.chapter_start, config.chapter_end), (2, 2))
            with patch.object(web_ui, 'get_book_parser', return_value=parser), \
                 patch.object(web_ui, 'get_output_dir', return_value=folder), \
                 patch.object(web_ui, 'generate_v2_for_book', side_effect=ValueError('测试停止，不发送请求')) as generate:
                web_ui.auto_split_role_script(
                    [str(second)], True, True, 'Mimo', 1, -1, 'auto', 'double', False, False,
                    None, 'key', 'url', 'model', False, current[0], current[8], 2, 2)
                self.assertEqual(generate.call_args.args[1:3], (2, 2))
                self.assertFalse(generate.call_args.kwargs['index_full_book'])

    @unittest.skipUnless(shutil.which('node'), '动效脚本检验需要 Node')
    def test_motion_updates_range_interrupts_and_ignores_unrelated_mutations(self):
        # 模拟 DOM 状态驱动，验证快速切换不会排队；不代替浏览器视觉检查。
        harness = r'''
const assert = require('node:assert/strict');
const vm = require('node:vm');
function element() {
  return {textContent: '', style: {}, animations: [], animate(frames, options) {
    const a = {frames, options, cancelled: false, cancel() {this.cancelled = true;}};
    this.animations.push(a); return a;
  }};
}
const heading = element(), count = element(), detail = element(), bar = element(), fields = element();
const overview = element();
overview.querySelector = s => ({'[data-range-heading]': heading, '[data-range-count]': count,
  '[data-range-detail]': detail, '.chapter-fill': bar}[s]);
const source = {dataset: {chapterRange: JSON.stringify({total: 0, message: '等待上传'})}};
let notify;
const context = {document: {readyState: 'complete', body: {},
  querySelector: s => s.includes('chapter_range_state') ? source : overview,
  getElementById: () => fields},
  getComputedStyle: () => ({transform: 'matrix(0.3,0,0,1,20,0)'}),
  MutationObserver: class {constructor(fn) {notify = fn;} observe() {}}
};
vm.runInNewContext(SCRIPT, context);
function set(data) {source.dataset.chapterRange = JSON.stringify(data); notify();}
set({total: 20, start: 5, end: 5, count: 1, chars: 14311, first: 'Diving Under', last: 'Diving Under', message: '已选 1 章 / 共 20 章'});
assert.equal(heading.textContent, '单章试生成');
assert.equal(count.textContent, '已选 1 章 / 共 20 章');
assert.match(detail.textContent, /Diving Under/);
assert.equal(bar.style.transform, 'translateX(20%) scaleX(0.05)');
assert.equal(fields.animations.length, 1);
const ongoing = bar.animations.at(-1);
set({total: 20, start: 5, end: 7, count: 3, chars: 32000, first: 'Diving Under', last: 'Buddy Beware', message: '已选 3 章 / 共 20 章'});
assert(ongoing.cancelled);
assert.equal(bar.animations.at(-1).frames[0].transform, 'matrix(0.3,0,0,1,20,0)');
assert.equal(bar.style.transform, 'translateX(20%) scaleX(0.15)');
assert.match(detail.textContent, /Diving Under → Buddy Beware/);
const totalAnimations = bar.animations.length;
notify();
assert.equal(bar.animations.length, totalAnimations);
set({total: 0, message: '已移除文件'});
assert.equal(bar.style.transform, 'scaleX(0)');
assert.equal(detail.textContent, '已移除文件');
assert.equal(count.textContent, '');
'''
        source = CHAPTER_HEAD_HTML.removeprefix('<script>').removesuffix('</script>')
        result = subprocess.run([shutil.which('node'), '-e', harness.replace('SCRIPT', json.dumps(source))],
                                text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
