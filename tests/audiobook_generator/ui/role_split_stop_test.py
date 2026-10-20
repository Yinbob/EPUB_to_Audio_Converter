"""停止拆分的会话归属、后台退出与原项目保护，不调用模型。"""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import gradio as gr
from audiobook_generator.ui import web_ui
from audiobook_generator.ui.role_studio import iter_split_events
from audiobook_generator.role_script.split_control import SplitAborted, split_control_scope
from tests.audiobook_generator.ui import role_split_feedback_test as feedback


class RoleSplitStopTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = temporary.name
        self.book = Path(self.folder) / 'book.epub'
        self.book.write_bytes(b'offline stop fixture')
        for name, value in [('get_output_dir', lambda: self.folder), ('running_process', None)]:
            p = patch.object(web_ui, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.key = web_ui._begin_role_split(str(self.book))
        self.control = web_ui._ROLE_SPLIT_CONTROLS[self.key]
        self.control.owner = 'session-A'
        self.addCleanup(web_ui._end_role_split, self.key)

    def test_stop_current_session_even_after_uploaded_book_changes(self):
        started = threading.Event()
        def run(progress):
            started.set()
            progress(None, desc='离线请求')
            self.control.cancelled.wait(2)
            self.control.check()
            self.fail('取消后不能发布结果')
        stream = iter_split_events(run, [], control=self.control,
                                   on_finish=lambda: web_ui._end_role_split(self.key))
        next(stream)
        next(stream)
        self.assertTrue(started.is_set())
        stop = web_ui.stop_role_split(None, 'Mimo', gr.Request(session_hash='session-A'))
        try:
            first = next(stop)
            self.assertIn('正在停止拆分', first[-3])
            self.assertFalse(first[-2]['interactive'])
            stream.close()  # 模拟 Gradio 取消前端生成器，后台仍须执行清理。
            last = list(stop)[-1]
            self.assertIn('已停止拆分', last[-3])
            self.assertTrue(last[-2]['interactive'])
            self.assertTrue(self.control.finished.is_set())
            self.assertNotIn(self.key, web_ui._ROLE_SPLITTING_PROJECTS)
        finally:
            self.control.cancelled.set()
            stream.close()
            stop.close()

    def test_other_session_cannot_stop_this_job_and_completed_job_is_not_cancelled(self):
        result = list(web_ui.stop_role_split(str(self.book), 'Mimo', gr.Request(session_hash='session-B')))
        self.assertFalse(self.control.cancelled.is_set())
        self.assertIn('没有可停止', result[-1][-3])
        self.control.committed = True
        self.control.result = feedback.RoleSplitFeedbackTest().result()
        self.control.finished.set()
        list(web_ui.stop_role_split(str(self.book), 'Mimo', gr.Request(session_hash='session-A')))
        self.assertFalse(self.control.cancelled.is_set())

    def test_finished_result_is_replayed_if_stop_races_with_delivery(self):
        self.control.committed = True
        self.control.result = feedback.RoleSplitFeedbackTest().result()
        self.control.finished.set()
        web_ui._end_role_split(self.key)
        self.addCleanup(web_ui._ROLE_SPLIT_COMPLETED.pop, 'session-A', None)
        result = list(web_ui.stop_role_split(None, 'Mimo', gr.Request(session_hash='session-A')))[-1]
        self.assertEqual(len(result), 13)
        self.assertEqual(result[:10], self.control.result)
        self.assertIn('停止请求前完成并保存', result[-3])
        self.assertTrue(result[7])

    def test_cancel_immediately_before_save_preserves_existing_project(self):
        path = Path(self.key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'previous confirmed project')
        values = feedback.RoleSplitFeedbackTest().values()
        values[0] = str(self.book)
        def generate(*args, **kwargs):
            self.control.cancelled.set()
            return object()
        with patch.object(web_ui, 'resolve_book_chapter_range', return_value=(1, 1)), \
             patch.object(web_ui, '_auto_split_chapters', return_value=([('chapter', 'text')], 1, 1, 'a' * 64, None)), \
             patch.object(web_ui, 'load_project', return_value=None), \
             patch.object(web_ui, 'generate_v2_for_book', side_effect=generate), \
             patch.object(web_ui, '_ensure_role_voice_diversity', side_effect=lambda result, report: result), \
             patch.object(web_ui, 'save_project') as save:
            with split_control_scope(self.control), self.assertRaises(SplitAborted):
                web_ui.auto_split_role_script(*values)
        save.assert_not_called()
        self.assertEqual(path.read_bytes(), b'previous confirmed project')


if __name__ == '__main__':
    unittest.main()
