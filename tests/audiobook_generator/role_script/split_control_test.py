"""请求取消与绝对时限；使用可取消的异步替身，不连接网络。"""
import asyncio
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from audiobook_generator.role_script.split_control import (
    SplitAborted, SplitControl, controlled_client, split_control_scope,
)


class SplitControlTest(unittest.TestCase):
    def client(self, create, closed):
        class Client:
            def __init__(self, **kwargs):
                self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))
            async def __aenter__(self):
                return self
            async def __aexit__(self, *args):
                closed.set()
        return Client

    def test_cancel_inflight_closes_client_and_prevents_followup(self):
        started, cancelled, closed = (threading.Event() for _ in range(3))
        control, errors, calls = SplitControl(), [], []
        async def create(**kwargs):
            calls.append(kwargs)
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
        def run():
            try:
                with split_control_scope(control):
                    client = controlled_client('dummy', 'https://example.invalid')
                    client.chat.completions.create(model='offline')
                    client.chat.completions.create(model='must-not-run')
            except SplitAborted as exc:
                errors.append(exc)
        with patch('openai.AsyncOpenAI', self.client(create, closed)):
            worker = threading.Thread(target=run)
            worker.start()
            try:
                self.assertTrue(started.wait(2))
                control.cancelled.set()
            finally:
                control.cancelled.set()
                worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertTrue(cancelled.is_set())
        self.assertTrue(closed.is_set())
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(errors), 1)

    def test_absolute_request_timeout_cancels_even_when_connection_keeps_alive(self):
        cancelled, closed = threading.Event(), threading.Event()
        async def create(**kwargs):
            try:
                while True:
                    await asyncio.sleep(.001)
            finally:
                cancelled.set()
        with patch('openai.AsyncOpenAI', self.client(create, closed)):
            with self.assertRaisesRegex(TimeoutError, '单次请求超过'):
                SplitControl(request_seconds=.02).create('dummy', 'https://example.invalid')
        self.assertTrue(cancelled.is_set())
        self.assertTrue(closed.is_set())

    def test_pre_cancel_and_task_deadline_never_create_client(self):
        with patch('openai.AsyncOpenAI') as client:
            control = SplitControl()
            control.cancelled.set()
            with self.assertRaises(SplitAborted):
                control.create('dummy', 'https://example.invalid')
            with self.assertRaises(SplitAborted) as caught:
                SplitControl(task_seconds=0).create('dummy', 'https://example.invalid')
            self.assertEqual(caught.exception.state, 'failed')
        client.assert_not_called()

    def test_success_and_context_cleanup(self):
        closed = threading.Event()
        async def create(**kwargs):
            return 'response'
        with patch('openai.AsyncOpenAI', self.client(create, closed)):
            with split_control_scope(SplitControl()):
                self.assertEqual(controlled_client('dummy', 'https://example.invalid').chat.completions.create(), 'response')
        self.assertTrue(closed.is_set())
        self.assertIsNone(controlled_client('dummy', 'https://example.invalid'))


if __name__ == '__main__':
    unittest.main()
