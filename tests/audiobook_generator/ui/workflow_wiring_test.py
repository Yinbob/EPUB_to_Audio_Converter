"""生成准备状态与资源库交互的回归检查，无需调用语音服务。"""
import asyncio
import inspect
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

try:
    import gradio as gr
    from audiobook_generator.config.ui_config import UiConfig
    from audiobook_generator.ui import web_ui
except Exception as exc:
    gr = None
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


@unittest.skipIf(gr is None, f'UI 依赖不可用：{IMPORT_ERROR}')
class TestWorkflowWiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.object(gr.Blocks, 'launch', lambda ui, **kwargs: ui):
            cls.ui = None
            captured = {}
            def capture(ui, **kwargs):
                captured['ui'] = ui
            with patch.object(gr.Blocks, 'launch', capture):
                web_ui.host_ui(UiConfig(SimpleNamespace(host='127.0.0.1', port=7999)))
            cls.ui = captured['ui']
        cls.config = cls.ui.get_config_file()

    def callback(self, name):
        return next(fn.fn for fn in self.ui.fns.values() if fn.fn and fn.fn.__name__ == name)

    def component(self, elem_id):
        return next(c for c in self.config['components'] if c['props'].get('elem_id') == elem_id)

    def test_role_voice_picker_contains_saved_young_male(self):
        choices = self.component('role_voice_preset')['props']['choices']
        self.assertIn(['青年男声 · Bryce（英语）', 'saved_bryce_young_en'], [list(choice) for choice in choices])

    def test_readiness_follows_books_provider_confirmation_and_parse_only(self):
        fn = self.callback('update_generation_summary')
        summary, update = fn([], 'Mimo', False, False, False)
        self.assertFalse(update['interactive'])
        self.assertIn('上传书籍', summary)
        summary, update = fn(['book.epub'], 'Mimo', False, False, False)
        self.assertTrue(update['interactive'])
        self.assertIn('单声音朗读', summary)
        for provider, files, confirmed, expected in [
            ('Edge', ['book.epub'], True, '切换引擎'),
            ('Mimo', ['one.epub', 'two.epub'], True, '一本书'),
            ('MiniMax', ['book.epub'], False, '确认角色参数'),
        ]:
            summary, update = fn(files, provider, True, confirmed, False)
            self.assertFalse(update['interactive'])
            self.assertIn(expected, summary)
        summary, update = fn(['book.epub'], 'Mimo', True, True, True, str(Path(web_ui.__file__).parents[2] / 'examples' / 'role_script.example.json'))
        self.assertTrue(update['interactive'])
        self.assertEqual(update['value'], '开始生成有声书')
        summary, update = fn(['book.epub'], 'MiniMax', True, True, False, str(Path(web_ui.__file__).parents[2] / 'examples' / 'role_script.example.json'))
        self.assertFalse(update['interactive'])
        self.assertIn('不匹配', summary)
        summary, update = fn(['book.epub'], 'Edge', False, False, True)
        self.assertEqual(update['value'], '开始解析书籍')
        self.assertIn('不生成音频', summary)

    def test_selection_changes_invalidate_zip_and_clear_preview(self):
        fn = self.callback('update_library_selection')
        with tempfile.TemporaryDirectory() as root:
            batch = Path(root) / 'book'
            batch.mkdir()
            (batch / '1.mp3').write_bytes(b'audio')
            with patch.object(web_ui, 'get_output_dir', return_value=root):
                outputs = fn('book', ['1.mp3'])
                self.assertTrue(outputs[4]['interactive'])
                self.assertEqual(outputs[1]['value'], [str((batch / '1.mp3').resolve())])
                self.assertEqual(outputs[2]['choices'], ['1.mp3'])
                self.assertIsNone(outputs[3]['value'])
                self.assertFalse(outputs[5]['visible'])
                self.assertIsNone(outputs[5]['value'])
                empty = fn('book', [])
                self.assertFalse(empty[4]['interactive'])
                self.assertIsNone(empty[1]['value'])

    def test_search_removes_hidden_files_from_the_action_set(self):
        with patch.object(web_ui, 'get_files_in_folder', return_value=['1.mp3', '1.txt', '2.mp3']):
            update = self.callback('filter_library_files')('book', 'MP3', ['1.mp3', '1.txt'])
        self.assertEqual(update['choices'], ['1.mp3', '2.mp3'])
        self.assertEqual(update['value'], ['1.mp3'])

    def test_process_form_order_and_visible_timer_are_preserved(self):
        event = next(d for d in self.config['dependencies'] if d.get('api_name') == 'process_form')
        self.assertEqual(len(event['inputs']), len(inspect.signature(web_ui.process_form).parameters))
        components = {c['id']: c for c in self.config['components']}
        timer = next(c for c in components.values() if c['type'] == 'timer')
        def path(node, target, parents=()):
            if node['id'] == target:
                return parents
            for child in node.get('children', []):
                found = path(child, target, parents + (node['id'],))
                if found is not None:
                    return found
        for parent in path(self.config['layout'], timer['id']):
            self.assertIsNot(components.get(parent, {}).get('props', {}).get('visible'), False)
        self.assertEqual(self.component('library_zip_download')['type'], 'downloadbutton')
        self.assertEqual(self.component('library_direct_download')['props']['file_count'], 'multiple')
        editor = self.component('role_editor')
        self.assertFalse(editor['props']['visible'])
        self.assertFalse(self.component('generation_start')['props']['interactive'])

    def test_named_chapters_load_locally_and_feed_existing_generation_range(self):
        components = {c['id']: c for c in self.config['components']}
        event = next(d for d in self.config['dependencies'] if d.get('api_name') == 'read_book_chapters')
        self.assertEqual(len(event['inputs']), 7)
        self.assertEqual(len(event['outputs']), 10)
        self.assertEqual(event['trigger_mode'], 'always_last')
        for name in ('chapter_from_name', 'chapter_to_name'):
            control = self.component(name)
            self.assertEqual(control['type'], 'dropdown')
            self.assertFalse(control['props']['interactive'])
            self.assertTrue(control['props']['filterable'])
        start, end = event['outputs'][3:5]
        self.assertEqual(components[start]['type'], 'number')
        self.assertEqual(components[end]['type'], 'number')
        process = next(d for d in self.config['dependencies'] if d.get('api_name') == 'process_form')
        parameters = list(inspect.signature(web_ui.process_form).parameters)
        self.assertEqual([process['inputs'][parameters.index(name)] for name in ('chapter_start', 'chapter_end')], [start, end])
        # 名称选择只用 input 事件，程序回填另一端不会造成循环请求。
        named_ids = {self.component(name)['id'] for name in ('chapter_from_name', 'chapter_to_name')}
        selections = [d for d in self.config['dependencies'] if any(t[0] in named_ids for t in d['targets'])]
        self.assertEqual(len(selections), 2)
        self.assertTrue(all(t[1] == 'input' for d in selections for t in d['targets']))
        self.assertTrue(all(d['outputs'][2:4] == [start, end] for d in selections))
        self.assertTrue(all(d['inputs'][-1] == event['outputs'][8] for d in selections))
        self.assertEqual(process['inputs'][-4:], [event['outputs'][0], event['outputs'][8],
                                                self.component('chapter_from_name')['id'], self.component('chapter_to_name')['id']])
        auto = next(d for d in self.config['dependencies'] if d.get('api_name') == 'auto_split_role_script')
        self.assertEqual(auto['targets'], [(event['outputs'][9], 'change')])

    def test_role_workspace_exposes_daily_actions_and_has_dedicated_split_progress(self):
        components = {c['id']: c for c in self.config['components']}
        def ancestors(node, target, parents=()):
            if node['id'] == target:
                return parents
            for child in node.get('children', []):
                result = ancestors(child, target, parents + (node['id'],))
                if result is not None:
                    return result
        for elem_id in ('role_current_character', 'role_voice_controls', 'role_voice_apply',
                        'role_preview_btn', 'role_voice_freeze', 'role_confirm_btn',
                        'role_narration_chapter', 'role_narration_entity', 'role_narration_apply'):
            path = ancestors(self.config['layout'], self.component(elem_id)['id'])
            self.assertIsNotNone(path)
            self.assertNotIn('accordion', [components[p]['type'] for p in path if p in components])
        calibrate_path = ancestors(self.config['layout'], self.component('role_calibrate_btn')['id'])
        self.assertIn('高级工具', [components[p]['props'].get('label') for p in calibrate_path if p in components])
        status = self.component('role_split_status')['id']
        status_path = ancestors(self.config['layout'], status)
        self.assertNotIn(self.component('role_setup_tabs')['id'], status_path)
        events = [d for d in self.config['dependencies'] if d.get('api_name', '').startswith(
            ('auto_split_role_script', 'split_role_script_now'))]
        self.assertEqual(len(events), 3)
        for event in events:
            self.assertEqual(event['show_progress'], 'hidden')
            self.assertEqual(event['outputs'][-2:], [status, self.component('role_split_btn')['id']])
            self.assertTrue(event['types']['generator'])
            self.assertEqual(event['trigger_mode'], 'once')
        self.assertEqual(self.component('role_split_status')['type'], 'html')
        self.assertIn('roleSplitStarted', web_ui.HEAD_HTML)

    def test_gradio_delivers_waiting_and_stage_before_mock_work_finishes(self):
        # 走实际注册函数和 Gradio 生成器执行器，防止只调用 Progress 而页面没有输出。
        fn = next(fn for fn in self.ui.fns.values() if fn.fn and fn.fn.__name__ == 'split_role_script_now_ui')
        values = [None, True, False, 'Mimo', 1, 1, 'auto', 'double', False, False,
                  None, 'dummy', 'https://example.invalid', 'model', False, None, None, None, None]
        finished = []
        def run(*args, progress):
            progress(None, desc='DeepSeek 正在拆分第 1 章（1/1）')
            finished.append(True)
            return tuple([gr.skip()] * 6 + [False, True, '', gr.skip()])
        async def exercise():
            from gradio.state_holder import SessionState
            state = SessionState(self.ui)
            for component, value in zip(fn.inputs, values):
                if component.stateful:
                    state[component._id] = value
            iterator = None
            frames = []
            for _ in range(8):
                frame = await self.ui.process_api(fn, values, state=state, iterator=iterator,
                                                  session_hash='offline-split-feedback', simple_format=True)
                iterator = frame['iterator']
                if not frame['is_generating']:
                    break
                frames.append(frame['data'])
                if len(frames) == 1:
                    self.assertFalse(finished)
            return frames
        with patch.object(web_ui, 'auto_split_role_script', side_effect=run):
            frames = asyncio.run(exercise())
        self.assertEqual(len(frames), 3)
        self.assertIn('正在准备剧本', frames[0][-2])
        self.assertIn('DeepSeek 正在拆分第 1 章', frames[1][-2])
        self.assertIn('剧本已准备好', frames[-1][-2])
        self.assertTrue(frames[-1][-1]['interactive'])

    def test_old_confirmed_snapshot_cannot_enable_start_while_resplitting(self):
        fn = self.callback('update_generation_summary')
        with tempfile.TemporaryDirectory() as folder, patch.object(web_ui, 'get_output_dir', return_value=folder):
            book = Path(folder) / 'book.epub'
            book.write_bytes(b'offline readiness fixture')
            key = web_ui.project_path(folder, web_ui._sha256_file_ui(str(book)))
            key.parent.mkdir(parents=True)
            key.write_text('{}')
            web_ui._remember_role_confirmation(str(key), 'old-signature')
            active = web_ui._begin_role_split(str(book))
            try:
                summary, update = fn([str(book)], 'Mimo', True, True, False, str(key))
                self.assertFalse(update['interactive'])
                self.assertIn('data-ready="0"', summary)
            finally:
                web_ui._end_role_split(active)
            # 失败后旧文件没变，仍不能让旧 State 重新启用生成。
            summary, update = fn([str(book)], 'Mimo', True, True, False, str(key))
            self.assertFalse(update['interactive'])
            web_ui._remember_role_confirmation(str(key), 'new-confirmation')
            self.assertFalse(web_ui._role_project_needs_reconfirmation(str(key)))
        changed = next(d for d in self.config['dependencies'] if d.get('api_name') == 'role_table_changed')
        self.assertEqual(changed['inputs'][-1], self.component('role_current_character')['id'])
        narration = next(d for d in self.config['dependencies'] if d.get('api_name') == 'apply_chapter_narration')
        self.assertEqual(narration['inputs'][-2:], [self.component('role_narration_chapter')['id'],
                                                  self.component('role_narration_entity')['id']])
        self.assertEqual(len(narration['inputs']), 4)
        for name in ('apply_chapter_narration', 'confirm_auto_role_script_ui'):
            binding = next(fn for fn in self.ui.fns.values() if fn.fn and fn.fn.__name__ == name)
            self.assertEqual(binding.concurrency_id, 'role-project-review')
            self.assertEqual(binding.concurrency_limit, 1)

    def test_registered_confirmation_stream_delivers_wait_then_real_result(self):
        from gradio.state_holder import SessionState
        fn = next(fn for fn in self.ui.fns.values() if fn.fn and fn.fn.__name__ == 'confirm_auto_role_script_ui')
        values = [None, {'data': [], 'headers': web_ui.ROLE_TABLE_HEADERS}, 'Mimo', 'wav', 'mp3']
        result = (True, '已确认', gr.skip(), 'offline-signature',
                  gr.update(value=web_ui._role_confirmation_probe(True, 'offline-signature')))
        async def exercise(confirm):
            state = SessionState(self.ui)
            for component, value in zip(fn.inputs, values):
                if component.stateful:
                    state[component._id] = value
            first = await self.ui.process_api(fn, values, state=state,
                session_hash='offline-confirm-motion', simple_format=True)
            confirm.assert_not_called()
            self.assertFalse(first['data'][-1]['interactive'])
            second = await self.ui.process_api(fn, [], state=state, iterator=first['iterator'],
                session_hash='offline-confirm-motion', simple_format=True)
            self.assertTrue(second['data'][-1]['interactive'])
            self.assertIn('data-confirmed="1"', second['data'][-2]['value'])
            self.assertTrue(state[fn.outputs[0]._id])
            await self.ui.process_api(fn, [], state=state, iterator=second['iterator'],
                session_hash='offline-confirm-motion', simple_format=True)
        with patch.object(web_ui, 'confirm_auto_role_script', return_value=result) as confirm:
            asyncio.run(exercise(confirm))
