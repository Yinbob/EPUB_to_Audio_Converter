"""上传登记和文件访问边界；客户端只传登记 ID。"""
import hashlib
import threading
import uuid
from pathlib import Path

from .common import ServiceError, atomic_json, read_json

ALLOWED = {'.epub', '.doc', '.docx', '.json', '.txt', '.csv', '.tsv', '.md', '.html', '.htm', '.pdf',
           '.wav', '.mp3', '.flac', '.m4a', '.aac', '.ogg', '.zip', '.opus'}


class FileStore:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.directory = self.root / '.studio' / 'uploads'
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.index = self.root / '.studio' / 'files.json'
        self.entries = read_json(self.index, {})
        self.names_path = self.root / '.studio' / 'file-names.json'
        self.names = read_json(self.names_path, {})

    def register(self, path):
        path = Path(path).resolve()
        if not path.is_file():
            raise ServiceError('file_missing', '文件不存在，请刷新后重试。', 404)
        with self.lock:
            key = hashlib.sha256(str(path).encode()).hexdigest()[:32]
            if self.entries.get(key) != str(path):
                self.entries[key] = str(path)
                atomic_json(self.index, self.entries)
        return {'id': key, 'name': self.names.get(key, path.name), 'size': path.stat().st_size, 'category': path.suffix[1:]}

    def resolve(self, key):
        with self.lock:
            raw = self.entries.get(key)
        if not raw:
            raise ServiceError('file_missing', '文件登记已失效，请重新选择。', 404)
        path = Path(raw).resolve()
        # 上传和输出文件必须仍位于登记的根内，防止登记后被符号链接替换。
        if str(path) != raw or not path.is_file():
            raise ServiceError('file_missing', '文件已移除或路径已变化。', 404)
        return path

    def upload(self, name, stream, limit=256 * 1024 * 1024):
        suffix = Path(name or '').suffix.lower()
        if suffix not in ALLOWED:
            raise ServiceError('file_type', '不支持此文件类型。')
        path = self.directory / (uuid.uuid4().hex + suffix)
        size = 0
        try:
            with path.open('wb') as target:
                while chunk := stream.read(1024 * 1024):
                    size += len(chunk)
                    if size > limit:
                        raise ServiceError('file_too_large', '文件超过 256 MB，请拆分后上传。', 413)
                    target.write(chunk)
            result = self.register(path)
            result['name'] = Path(name).name
            with self.lock:
                self.names[result['id']] = result['name']
                atomic_json(self.names_path, self.names)
            if suffix in ('.epub', '.doc', '.docx'):
                from .covers import create_cover
                cover = create_cover(path)
                result['cover_id'] = self.register(cover)['id'] if cover else None
            return result
        except Exception:
            path.unlink(missing_ok=True)
            raise
