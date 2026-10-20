"""WebUI 拆分任务的取消与请求时限；不影响其他 DeepSeek 调用。"""
import asyncio
import contextvars
import threading
import time
from contextlib import contextmanager
from types import SimpleNamespace


class SplitAborted(BaseException):
    """必须越过普通失败重试与旁白回退，避免停止后继续调用或保存。"""
    def __init__(self, message='已停止拆分，未保存本次未完成的结果。', state='cancelled'):
        super().__init__(message)
        self.state = state


class SplitControl:
    def __init__(self, request_seconds=120, task_seconds=1800, report=None):
        self.cancelled = threading.Event()
        self.finished = threading.Event()
        self.committed = False
        self.result = None
        self.deadline = time.monotonic() + task_seconds
        self.request_seconds = request_seconds
        self.report = report
        self.phase = '正在分析所选章节'
        self.request_count = 0

    def check(self):
        if self.cancelled.is_set():
            raise SplitAborted()
        if time.monotonic() >= self.deadline:
            raise SplitAborted('拆分达到 30 分钟任务上限，已停止；请缩小章节范围后重试。', 'failed')

    def create(self, api_key, base_url, **kwargs):
        """取消 asyncio 请求会关闭本地连接，不留同步网络线程继续重试。"""
        self.check()
        self.request_count += 1
        if self.report:
            self.report(None, desc=f'{self.phase} · 第 {self.request_count} 次请求（单次最多 {self.request_seconds:g} 秒）')

        async def request():
            from openai import AsyncOpenAI
            async with AsyncOpenAI(api_key=api_key, base_url=base_url,
                                   timeout=self.request_seconds, max_retries=0) as client:
                task = asyncio.create_task(client.chat.completions.create(**kwargs))
                started = time.monotonic()
                try:
                    while True:
                        self.check()
                        if time.monotonic() - started >= self.request_seconds:
                            raise TimeoutError(f'DeepSeek 单次请求超过 {self.request_seconds:g} 秒，已中断')
                        done, _ = await asyncio.wait({task}, timeout=.1)
                        if done:
                            self.check()
                            return task.result()
                finally:
                    if not task.done():
                        task.cancel()
                    await asyncio.gather(task, return_exceptions=True)

        return asyncio.run(request())


_CURRENT = contextvars.ContextVar('role_split_control', default=None)


def current_split_control():
    return _CURRENT.get()


@contextmanager
def split_control_scope(control):
    token = _CURRENT.set(control)
    try:
        yield
    finally:
        _CURRENT.reset(token)


def controlled_client(api_key, base_url):
    control = current_split_control()
    if control is None:
        return None
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kwargs: control.create(api_key, base_url, **kwargs))))
