"""本地评估模型的内容版本；不导入模型运行时或下载权重。"""
import hashlib
from functools import lru_cache
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from .store import fingerprint


@lru_cache(maxsize=16)
def runtime_version(package):
    try:
        return version(package)
    except PackageNotFoundError:
        return None


def _stat_key(path):
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino


@lru_cache(maxsize=256)
def _content_hash(path, stat_key):
    source = Path(path)
    value = hashlib.sha256()
    with source.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    if _stat_key(source) != stat_key:
        raise RuntimeError('模型文件在核验过程中发生变化，请更新完成后重新评估')
    return value.hexdigest()


def local_model_identity(kind, directory):
    package = {'asr': 'funasr', 'speaker': 'speechbrain'}.get(kind)
    root = Path(directory).expanduser().resolve() if directory else None
    files = []
    error = None
    if root and root.is_dir():
        # 包含权重、配置、归一化与词表；排除 README 和下载缓存等无关内容。
        suffixes = {'.pt', '.pth', '.ckpt', '.bin', '.safetensors', '.onnx', '.yaml', '.yml', '.json', '.mvn', '.model', '.txt'}
        try:
            for source in sorted(root.rglob('*')):
                relative = source.relative_to(root)
                if source.is_file() and source.suffix in suffixes and not any(p.startswith('.') for p in relative.parts):
                    stat = _stat_key(source)
                    files.append({'path': str(relative), 'bytes': stat[0], 'sha256': _content_hash(str(source), stat)})
        except (OSError, RuntimeError) as exc:
            error = type(exc).__name__
    value = {'kind': kind, 'directory': str(root) if root else None,
             'state': 'unavailable' if error else 'local_files' if files else 'missing' if root else 'unconfigured',
             'runtime_version': runtime_version(package) if package else None, 'files': files}
    if error:
        value['error_type'] = error
    return {**value, 'fingerprint': fingerprint(value)}
