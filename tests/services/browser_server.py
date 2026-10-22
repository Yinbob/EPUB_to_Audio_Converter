"""浏览器验收专用服务；只使用临时数据和无网络假任务。"""
import os
import tempfile
import time
import wave
from contextlib import asynccontextmanager
from pathlib import Path

from audiobook_generator.api.app import create_app
from audiobook_generator.services.common import atomic_json
from audiobook_generator.services.settings import Settings
from audiobook_generator.services.projects import encode
from tests.audiobook_generator.role_script.v2_io_test import _script


def browser_worker(payload, result_path, log_path, ready):
    os.setsid()
    ready.set()
    path = Path(log_path)
    for i in range(3):
        with path.open('a') as log:
            log.write(f'离线验证步骤 {i + 1}/3\n')
        time.sleep(1)
    atomic_json(result_path, {'ok': True, 'result': {'offline': True}})


def app_factory():
    directory = tempfile.TemporaryDirectory(prefix='studio-browser-')
    root = Path(directory.name)
    app = create_app(root, acquire_lock=False)
    original = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app):
        async with original(app):
            app.state.settings = Settings(root)
            app.state.tasks.runner = browser_worker
            batch = root / '演示书籍'
            batch.mkdir()
            with wave.open(str(batch / '第一章.wav'), 'w') as stream:
                stream.setnchannels(1)
                stream.setsampwidth(2)
                stream.setframerate(16000)
                stream.writeframes(b'\0\0' * 16000)
            app.state.projects.put(_script()[0])
            yield
        directory.cleanup()
    app.router.lifespan_context = lifespan
    return app
