"""用线程屏障覆盖已进入确认／启动函数后的拆分交错，不调用模型。"""
import inspect
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from audiobook_generator.ui import web_ui
from tests.audiobook_generator.role_script.v2_io_test import _script


class RoleSplitLifecycleTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = temporary.name
        self.book = Path(self.folder) / 'book.epub'
        self.book.write_bytes(b'offline lifecycle book')
        script, _ = _script()
        self.script = replace(script, book_sha256=web_ui._sha256_file_ui(str(self.book)))
        self.path = web_ui.project_path(self.folder, self.script.book_sha256)
        web_ui.save_project(self.script, self.path)
        self.report = web_ui.ValidationReport(schema_version=2)
        for name, value in [('get_output_dir', lambda: self.folder), ('running_process', None)]:
            p = patch.object(web_ui, name, value)
            p.start()
            self.addCleanup(p.stop)

    def race(self, operation, hook_name, commit):
        entered, release, attempted, split_done = [threading.Event() for _ in range(4)]
        trace, errors, result = [], [], {}

        def pause(*args, **kwargs):
            entered.set()
            if not release.wait(3):
                raise RuntimeError('离线屏障超时')
            value = commit(*args, **kwargs)
            trace.append('commit')
            return value

        def invoke():
            try:
                result['operation'] = operation()
            except Exception as exc:
                errors.append(exc)

        def split():
            attempted.set()
            try:
                result['key'] = web_ui._begin_role_split(str(self.book))
                trace.append('split')
            except ValueError as exc:
                result['split_error'] = str(exc)
            finally:
                split_done.set()

        with patch.object(web_ui, hook_name, side_effect=pause):
            first, second = threading.Thread(target=invoke), threading.Thread(target=split)
            first.start()
            try:
                self.assertTrue(entered.wait(2))
                acquired = web_ui._ROLE_SPLIT_LOCK.acquire(blocking=False)
                if acquired:
                    web_ui._ROLE_SPLIT_LOCK.release()
                self.assertFalse(acquired, '校验到保存／启动之间必须持有同一操作锁')
                second.start()
                self.assertTrue(attempted.wait(2))
                self.assertFalse(split_done.wait(.05), '拆分不能穿插进已开始的保存／启动')
            finally:
                release.set()
                first.join(3)
                if second.ident is not None:
                    second.join(3)
                if result.get('key'):
                    web_ui._end_role_split(result['key'])
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(errors, [])
        return trace, result

    def test_confirmation_save_commits_before_resplit_can_start(self):
        original_save = web_ui.save_project
        with patch.object(web_ui, '_load_uploaded_role_script', return_value=(self.script, self.report)), \
             patch.object(web_ui, '_apply_role_table', return_value=self.script), \
             patch.object(web_ui, '_validate_uploaded_role_script', return_value=(self.script, self.report)):
            trace, result = self.race(
                lambda: web_ui.confirm_auto_role_script(str(self.path), [], 'Mimo', 'wav', 'mp3'),
                'save_project', original_save)
        self.assertTrue(result['operation'][0])
        self.assertEqual(trace, ['commit', 'split'])
        self.assertEqual(web_ui._recall_role_confirmation(str(self.path)), '')
        self.assertTrue(web_ui._role_project_needs_reconfirmation(str(self.path)))

    def test_generation_launch_finishes_reservation_before_resplit_check(self):
        params = {name: None for name in inspect.signature(web_ui.process_form).parameters}
        params.update(provider='Mimo', input_file=[str(self.book)], output_dir=self.folder,
                      worker_count=1, chapter_start=1, chapter_end=1, role_mode=True,
                      role_script_file=str(self.path), role_table=[], role_split_confirmed=True,
                      role_confirmed_signature=web_ui._role_confirmation_signature(self.script),
                      openai_output_format='wav', model='mimo-v2.5-tts', voices='冰糖', speed=1.0)
        def launched(configs):
            self.assertEqual(len(configs), 1)
            web_ui.running_process = SimpleNamespace(is_alive=lambda: True)
        with patch.object(web_ui, '_load_uploaded_role_script', return_value=(self.script, self.report)), \
             patch.object(web_ui, '_apply_role_table', return_value=self.script), \
             patch.object(web_ui, '_validate_uploaded_role_script', return_value=(self.script, self.report)), \
             patch.object(web_ui, 'get_progress_info', return_value=(None, None)):
            trace, result = self.race(lambda: web_ui.process_form(**params), 'launch_batch', launched)
        self.assertEqual(trace, ['commit'])
        self.assertIn('当前音频生成', result['split_error'])


if __name__ == '__main__':
    unittest.main()
