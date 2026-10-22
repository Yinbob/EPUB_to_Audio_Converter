"""实际 Gradio 接线与项目互斥，全部使用模拟响应，不启动服务。"""
import asyncio
import hashlib
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import gradio as gr
from gradio.state_holder import SessionState
from audiobook_generator.ui import web_ui
from audiobook_generator.ui import book_casting_ui as view
from audiobook_generator.ui.book_casting import BookCasting, draft_rows, read_json
from audiobook_generator.role_script.project_store import save_project
from tests.audiobook_generator.ui.book_casting_test import long_book, CardsClient
from tests.audiobook_generator.audio_core.hybrid_casting_test import bank


class BookCastingWiringTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.object(gr.Blocks, 'launch', autospec=True) as launch:
            web_ui.host_ui(SimpleNamespace(host='127.0.0.1', port=7998))
            cls.app = launch.call_args.args[0]
        cls.config = cls.app.config

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.book = self.root / 'offline.epub'
        self.book.write_bytes(b'offline book fixture')
        script, self.parsed = long_book()
        self.full = replace(script, book_sha256=hashlib.sha256(self.book.read_bytes()).hexdigest())
        self.source = replace(self.full, chapters=(self.full.chapters[0],))
        self.path = self.root / '.role_projects' / (self.full.book_sha256 + '.json')
        save_project(self.source, self.path)
        self.bank_path = self.root / 'voice_bank.json'
        self.bank_path.write_text(json.dumps(bank()))
        self.controller = BookCasting(self.root, self.parsed, 'parser', self.source)
        for name, value in [('get_output_dir', lambda: str(self.root)), ('running_process', None)]:
            p = patch.object(web_ui, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.base = [str(self.book), 'Mimo', str(self.path), web_ui._role_table_rows(self.source),
                     'auto', 'single', False, False, None, 'en', str(self.bank_path), None]

    def fake_generate(self, chapters, start, end, provider, book_sha, key, url, model, **kwargs):
        return replace(self.full, chapters=tuple(sorted(kwargs['previous'].chapters + (self.full.chapters[start - 1],), key=lambda c:c.chapter_index)))

    def test_only_explicit_buttons_start_full_book_tasks(self):
        ids = {c['props'].get('elem_id'):c['id'] for c in self.config['components'] if c['props'].get('elem_id')}
        for api, button in [('book_casting_analyze','book_casting_analyze'), ('book_casting_make','book_casting_make')]:
            event = next(d for d in self.config['dependencies'] if d.get('api_name') == api)
            self.assertEqual(event['targets'], [(ids[button], 'click')])
            self.assertTrue(event['types']['generator'])
            self.assertIn(ids['book_casting_activity'], event['outputs'])
            self.assertNotIn(ids.get('chapter_range_start'), event['outputs'])
        event = next(d for d in self.config['dependencies'] if d.get('api_name') == 'book_casting_apply')
        self.assertEqual(len(event['outputs']), 9)
        self.assertEqual(event['targets'], [(ids['book_casting_apply'], 'click')])
        followup = next(d for d in self.config['dependencies'] if d.get('trigger_after') == event['id'])
        self.assertEqual(len(followup['outputs']), 8)
        self.assertIn(ids['role_voice_controls'], [c['id'] for c in self.config['components']])

    def test_actual_gradio_executor_delivers_analyze_make_and_apply(self):
        # 实际注册函数、State、表格预处理、生成器及输出后处理都经过 Gradio。
        async def execute(api, values):
            fn = next(f for f in self.app.fns.values() if f.api_name == api)
            state = SessionState(self.app)
            for c, v in zip(fn.inputs, values):
                if c.stateful:
                    state[c._id] = v
            iterator, frames = None, []
            for _ in range(80):
                frame = await self.app.process_api(fn, values, state=state, iterator=iterator,
                    session_hash='offline-book-casting', simple_format=True)
                iterator = frame['iterator']
                frames.append(frame['data'])
                if not frame['is_generating']:
                    break
            return frames, state
        # 文件由真实 context 测试另行验证，此处用 None 避免上传缓存干扰 Gradio 执行器。
        values = [None, 'Mimo', None, {'headers':web_ui.ROLE_TABLE_HEADERS,'data':[]}, 'auto', 'single', False, False, None, 'en', None, None]
        real_context = (self.controller, str(self.bank_path), 'en', self.path)
        original_begin = web_ui._begin_role_split
        def begin(*args, **kwargs):
            return original_begin(str(self.book), **kwargs)
        with patch.object(view, 'context', return_value=real_context), \
             patch.object(web_ui, '_begin_role_split', side_effect=begin), \
             patch('audiobook_generator.ui.book_casting.generate_v2_for_book', side_effect=self.fake_generate), \
             patch.object(view, 'controlled_client', return_value=CardsClient()):
            frames, _ = asyncio.run(execute('book_casting_analyze', values + ['dummy', 'https://example.invalid', 'mock']))
            self.assertIn('正在准备全书任务', frames[0][-1]['value'])
            self.assertTrue(self.controller.progress()['full_book'])
            frames, state = asyncio.run(execute('book_casting_make', values + ['dummy', 'https://example.invalid', 'mock']))
            self.assertTrue(self.controller.read_draft()['cards'])
            draft = self.controller.read_draft()
            table = {'headers':['人物编号', '人物', '声音来源', '内置声音', '声音描述（可改）', '朗读要求（可改）', '分配原因'], 'data':draft_rows(draft)}
            applied, state = asyncio.run(execute('book_casting_apply', values + [draft['draft_id'], table]))
            self.assertIn('已应用', applied[0][3])
            apply_fn = next(f for f in self.app.fns.values() if f.api_name == 'book_casting_apply')
            self.assertIs(state[apply_fn.outputs[4]._id], False)
            self.assertIn(str(self.path.resolve()), web_ui._ROLE_RECONFIRM_PROJECTS)
            saved = read_json(self.path)
            self.assertEqual(len(saved['chapters']), 12)
            self.assertTrue(any(s['speaker']['status'] == 'proposed' for c in saved['chapters'] for s in c['segments']))

    def test_shared_mutex_and_owner_stop_after_switching_book(self):
        old_confirmation = 'confirmed-signature'
        web_ui._ROLE_CONFIRMED_SCRIPTS[str(self.path.resolve())] = old_confirmation
        key = web_ui._begin_role_split(str(self.book), invalidate_confirmation=False)
        self.addCleanup(web_ui._end_role_split, key)
        control = web_ui._ROLE_SPLIT_CONTROLS[key]
        control.task_kind = 'book_casting'
        control.owner = ('book_casting', 'session-A')
        self.assertEqual(web_ui._ROLE_CONFIRMED_SCRIPTS[key], old_confirmation)
        with self.assertRaises(ValueError):
            web_ui._begin_role_split(str(self.book))
        view.stop(None, gr.Request(session_hash='session-B'))
        self.assertFalse(control.cancelled.is_set())
        view.stop(None, gr.Request(session_hash='session-A'))
        self.assertTrue(control.cancelled.is_set())
        before = self.path.read_bytes()
        with patch.object(view, 'context', return_value=(self.controller, str(self.bank_path), 'en', self.path)):
            result = view.apply(*self.base, 'draft', [])
        self.assertIn('请等待', result[3])
        self.assertEqual(self.path.read_bytes(), before)

    def test_actual_context_detects_external_edit_and_keeps_original_project(self):
        with patch.object(web_ui, '_auto_split_chapters', return_value=(self.parsed,1,12,self.full.book_sha256,None)):
            controller, _, _, _ = view.context(self.base)
            # 使用与真实解析设置一致的分析缓存。
            full = replace(self.full, parser_fingerprint=controller.parser_fp)
            from audiobook_generator.ui.book_casting import atomic_json
            from audiobook_generator.role_script.deepseek_splitter import role_script_to_dict
            atomic_json(controller.analysis_path, {'source_binding':controller.binding, 'script':role_script_to_dict(full)})
            draft = controller.make_draft(bank(), 'en', client=CardsClient(), model='mock')
            changed = replace(self.source, entities={**self.source.entities,
                'lead':replace(self.source.entities['lead'], voice_locked=True)})
            save_project(changed, self.path)
            before = self.path.read_bytes()
            result = view.apply(*self.base, draft['draft_id'], draft_rows(draft))
            self.assertIn('失效', result[3])
            self.assertEqual(self.path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
