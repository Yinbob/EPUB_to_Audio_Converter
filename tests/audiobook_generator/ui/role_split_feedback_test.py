"""慢请求、失败与会话隔离下的拆分反馈；所有模型调用均为离线替身。"""
import threading
import hashlib
import inspect
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import gradio as gr
from audiobook_generator.ui import web_ui
from audiobook_generator.ui.role_studio import iter_split_events, render_split_status, ROLE_SPLIT_HEAD


class RoleSplitFeedbackTest(unittest.TestCase):
    def values(self):
        return [None, True, True, 'Mimo', 1, 1, 'auto', 'double', False, False,
                None, 'dummy', 'https://example.invalid', 'model', False, None, None, None, None]

    def result(self, success=True):
        return tuple([gr.skip(), gr.skip(), gr.update(value='正常' if success else '**失败**\n\n连接失败\n\n请重试'),
                      gr.skip(), gr.skip(), gr.skip(), False, success, '', gr.skip()])

    def test_waiting_is_sent_before_work_and_heartbeat_survives_slow_call(self):
        release = threading.Event()
        called = threading.Event()
        def run(*args, progress):
            called.set()
            progress(None, desc='正在等待 DeepSeek 分析当前章节')
            release.wait(3)
            return self.result()
        stream = iter_split_events(run, [], heartbeat=.01)
        try:
            self.assertEqual(next(stream)['state'], 'starting')
            self.assertFalse(called.is_set())
            self.assertIn('DeepSeek', next(stream)['message'])
            self.assertEqual(next(stream)['state'], 'heartbeat')
            release.set()
            self.assertEqual(next(stream)['state'], 'result')
        finally:
            release.set()
            stream.close()

    def test_ui_resets_confirmation_then_restores_button_on_success_and_failure(self):
        for success in (True, False):
            with self.subTest(success=success), patch.object(web_ui, 'auto_split_role_script', return_value=self.result(success)):
                frames = list(web_ui.auto_split_role_script_ui(*self.values()))
            self.assertTrue(all(len(frame) == 12 for frame in frames))
            self.assertEqual(frames[0][6:9], (False, False, ''))
            self.assertFalse(frames[0][-1]['interactive'])
            self.assertTrue(frames[-1][-1]['interactive'])
            self.assertIn('data-state="done"' if success else 'data-state="failed"', frames[-1][-2])
            self.assertNotIn('role-split-spinner', frames[-1][-2])

    def test_unexpected_worker_error_is_visible_and_controls_recover(self):
        with patch.object(web_ui, 'auto_split_role_script', side_effect=RuntimeError('离线测试错误')):
            frames = list(web_ui.split_role_script_now_ui(*self.values()))
        self.assertIn('离线测试错误', frames[-1][-2])
        self.assertIn('data-state="failed"', frames[-1][-2])
        self.assertTrue(frames[-1][-1]['interactive'])
        self.assertFalse(frames[-1][6])

    def test_disabled_automatic_split_never_flashes_running(self):
        for field in (1, 2):
            values = self.values()
            values[field] = False
            with patch.object(web_ui, 'generate_v2_for_book') as generate:
                frames = list(web_ui.auto_split_role_script_ui(*values))
            generate.assert_not_called()
            self.assertEqual(len(frames), 1)
            self.assertIn('data-state="idle"', frames[0][-2])

    def test_stage_queues_are_isolated(self):
        def run(name, progress):
            progress(None, desc=name)
            return name
        a, b = iter_split_events(run, ['A']), iter_split_events(run, ['B'])
        next(a)
        next(b)
        self.assertEqual(next(a)['message'], 'A')
        self.assertEqual(next(b)['message'], 'B')
        self.assertEqual(next(a)['result'], 'A')
        self.assertEqual(next(b)['result'], 'B')

    def test_status_escapes_model_errors_and_client_keeps_svelte_owner(self):
        text = render_split_status('running', '<script>alert(1)</script>', started=123)
        self.assertNotIn('<script>', text)
        self.assertIn('&lt;script&gt;', text)
        self.assertIn('data-role-split-started="123"', text)
        self.assertIn("querySelector('#role_split_status .role-split-activity')", ROLE_SPLIT_HEAD)
        self.assertNotIn("querySelector('#role_split_status .html-container')", ROLE_SPLIT_HEAD)

    def test_resplit_blocks_old_confirmation_even_with_stale_start_snapshot(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(web_ui, 'get_output_dir', return_value=folder):
            book = Path(folder) / 'book.epub'
            book.write_bytes(b'offline book fixture')
            key = web_ui.project_path(folder, hashlib.sha256(book.read_bytes()).hexdigest())
            key.parent.mkdir(parents=True)
            # 保留原文件，忙碌门禁应在读取／校验剧本前生效。
            key.write_text('{"old": true}')
            web_ui._register_role_script_origin(key)
            web_ui._remember_role_confirmation(str(key), 'old-confirmed-signature')
            values = self.values()
            values[0] = [str(book)]
            with patch.object(web_ui, 'auto_split_role_script', return_value=self.result()):
                stream = web_ui.auto_split_role_script_ui(*values)
                try:
                    next(stream)
                    self.assertTrue(web_ui._role_project_is_splitting(str(key)))
                    self.assertEqual(web_ui._recall_role_confirmation(str(key)), '')
                    confirmed = web_ui.confirm_auto_role_script(str(key), [], 'Mimo', 'wav', 'mp3')
                    self.assertFalse(confirmed[0])
                    self.assertIn('正在重新拆分', confirmed[1])
                    with self.assertRaisesRegex(ValueError, '重新拆分'):
                        web_ui._editable_role_project(str(key))
                    params = {name: None for name in inspect.signature(web_ui.process_form).parameters}
                    params.update(provider='Mimo', input_file=[str(book)], role_mode=True,
                                  role_script_file=str(key), role_split_confirmed=True,
                                  role_confirmed_signature='old-confirmed-signature')
                    with patch.object(web_ui, 'launch_batch') as launch, patch.object(web_ui.gr, 'Warning') as warning:
                        web_ui.process_form(**params)
                    launch.assert_not_called()
                    self.assertIn('正在重新拆分', warning.call_args.args[0])
                    self.assertEqual(key.read_text(), '{"old": true}')
                finally:
                    stream.close()
            self.assertFalse(web_ui._role_project_is_splitting(str(key)))
            self.assertTrue(web_ui._role_project_needs_reconfirmation(str(key)))
            with patch.object(web_ui, 'launch_batch') as launch, patch.object(web_ui.gr, 'Warning') as warning:
                web_ui.process_form(**params)
            launch.assert_not_called()
            self.assertIn('重新确认', warning.call_args.args[0])
            web_ui._remember_role_confirmation(str(key), 'new-confirmed-signature')
            self.assertFalse(web_ui._role_project_needs_reconfirmation(str(key)))

    def test_closed_feedback_keeps_project_busy_until_worker_actually_finishes(self):
        release, finished = threading.Event(), threading.Event()
        def run(*args, progress):
            progress(None, desc='等待离线替身')
            release.wait(3)
            return self.result()
        with tempfile.TemporaryDirectory() as folder, patch.object(web_ui, 'get_output_dir', return_value=folder):
            book = Path(folder) / 'book.epub'
            book.write_bytes(b'offline worker fixture')
            values = self.values()
            values[0] = str(book)
            key = str(web_ui.project_path(folder, hashlib.sha256(book.read_bytes()).hexdigest()).resolve())
            def end(actual):
                web_ui._ROLE_SPLITTING_PROJECTS.discard(actual)
                finished.set()
            with patch.object(web_ui, 'auto_split_role_script', side_effect=run), \
                 patch.object(web_ui, '_end_role_split', side_effect=end):
                stream = web_ui.auto_split_role_script_ui(*values)
                try:
                    next(stream)
                    next(stream)
                    stream.close()
                    self.assertIn(key, web_ui._ROLE_SPLITTING_PROJECTS)
                    with self.assertRaisesRegex(ValueError, '正在拆分'):
                        web_ui._begin_role_split(str(book))
                    release.set()
                    self.assertTrue(finished.wait(2))
                    self.assertNotIn(key, web_ui._ROLE_SPLITTING_PROJECTS)
                finally:
                    release.set()
                    stream.close()

    def test_worker_failure_releases_project_for_retry(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(web_ui, 'get_output_dir', return_value=folder):
            book = Path(folder) / 'book.epub'
            book.write_bytes(b'offline failure fixture')
            values = self.values()
            values[0] = str(book)
            with patch.object(web_ui, 'auto_split_role_script', side_effect=RuntimeError('offline failure')):
                self.assertIn('offline failure', list(web_ui.auto_split_role_script_ui(*values))[-1][-2])
            key = web_ui._begin_role_split(str(book))
            web_ui._end_role_split(key)


if __name__ == '__main__':
    unittest.main()
