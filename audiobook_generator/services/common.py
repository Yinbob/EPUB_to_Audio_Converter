"""原子持久化、运行锁与可展示错误。"""
import json
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class ServiceError(Exception):
    def __init__(self, code, message, status=422):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path, default=None):
    return json.loads(Path(path).read_text(encoding='utf-8')) if Path(path).exists() else default


class RuntimeLock:
    """同一项目只允许一个工作台服务；文件锁随进程退出自动释放。"""
    def __init__(self, root=ROOT):
        self.path = Path(root) / '.studio-runtime.lock'
        self.stream = None

    def acquire(self):
        import fcntl
        self.stream = self.path.open('a+')
        try:
            fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.stream.close()
            self.stream = None
            raise ServiceError('service_running', '已有工作台服务正在使用此项目，请先关闭另一个界面服务。', 409)
        return self

    def close(self):
        if self.stream:
            self.stream.close()
            self.stream = None
