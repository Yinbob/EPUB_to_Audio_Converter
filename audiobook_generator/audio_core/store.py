"""内容寻址产物与可恢复请求账本，不记录 API 密钥。"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from audiobook_generator.tts_providers.segment_synthesis import atomic_write_bytes
from .models import ResourceLimits


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


class ResourceExhausted(RuntimeError):
    pass


class ArtifactStore:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.database = self.root / "project.sqlite"
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, started REAL, limits TEXT);
                CREATE TABLE IF NOT EXISTS requests(
                    id TEXT PRIMARY KEY, run_id TEXT, request_key TEXT, repair INTEGER,
                    status TEXT, started REAL, finished REAL, characters INTEGER,
                    artifact TEXT, error_type TEXT);
                CREATE TABLE IF NOT EXISTS samples(
                    request_key TEXT, sample_id TEXT PRIMARY KEY, path TEXT, sha256 TEXT);
                CREATE TABLE IF NOT EXISTS selected_samples(
                    request_key TEXT PRIMARY KEY, sample_id TEXT);
                CREATE TABLE IF NOT EXISTS role_anchors(
                    anchor_key TEXT PRIMARY KEY, path TEXT, sha256 TEXT, metrics TEXT);
                CREATE TABLE IF NOT EXISTS selected_renders(
                    selection_key TEXT PRIMARY KEY, payload TEXT);
            """)

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.database, timeout=30)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def start_run(self, limits: ResourceLimits):
        run_id = uuid.uuid4().hex
        with self.connect() as db:
            db.execute("INSERT INTO runs VALUES(?,?,?)", (run_id, time.time(), json.dumps(asdict(limits))))
        return run_id

    def reserve(self, run_id, request_key, characters, *, repair=False):
        if type(characters) is not int or characters < 0:
            raise ValueError("请求正文字符数必须是非负整数")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT started,limits FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise ValueError("未知运行编号")
            started, raw_limits = row
            limits = ResourceLimits(**json.loads(raw_limits))
            count, repairs, repair_chars = db.execute(
                "SELECT COUNT(*),COALESCE(SUM(repair),0),COALESCE(SUM(CASE WHEN repair=1 THEN characters ELSE 0 END),0) "
                "FROM requests WHERE run_id=?", (run_id,)).fetchone()
            if (count >= limits.max_requests or (repair and repairs >= limits.max_repair_requests)
                    or time.time() - started >= limits.max_seconds):
                raise ResourceExhausted("请求次数、追加修复次数或运行时限已达到限制")
            if repair and limits.max_repair_characters is not None and repair_chars + characters > limits.max_repair_characters:
                raise ResourceExhausted("追加修复正文字符数已达到限制")
            request_id = uuid.uuid4().hex
            db.execute("INSERT INTO requests VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (request_id, run_id, request_key, int(repair), "running", time.time(), None,
                        characters, None, None))
        return request_id

    def settle(self, request_id, *, artifact=None, error=None):
        with self.connect() as db:
            db.execute("UPDATE requests SET status=?,finished=?,artifact=?,error_type=? WHERE id=?",
                       ("failed" if error else "succeeded", time.time(), artifact,
                        type(error).__name__ if error else None, request_id))

    def remaining_seconds(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT started,limits FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise ValueError("未知运行编号")
        return max(0.0, json.loads(row[1])["max_seconds"] - (time.time() - row[0]))

    def remaining_requests(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT limits FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise ValueError("未知运行编号")
            limits = ResourceLimits(**json.loads(row[0]))
            count, repairs = db.execute("SELECT COUNT(*),COALESCE(SUM(repair),0) FROM requests WHERE run_id=?", (run_id,)).fetchone()
        return min(max(0, limits.max_requests - count), max(0, limits.max_repair_requests - repairs))

    def run_limits(self, run_id):
        with self.connect() as db:
            row = db.execute("SELECT limits FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise ValueError("未知运行编号")
        return ResourceLimits(**json.loads(row[0]))

    def remaining_repair_characters(self, run_id):
        limit = self.run_limits(run_id).max_repair_characters
        if limit is None:
            return None
        with self.connect() as db:
            used = db.execute("SELECT COALESCE(SUM(characters),0) FROM requests WHERE run_id=? AND repair=1",
                              (run_id,)).fetchone()[0]
        return max(0, limit - used)

    def save_sample(self, key, data: bytes, extension):
        if extension not in {"wav", "mp3", "flac", "aac", "opus", "pcm"}:
            raise ValueError("不支持的原始音频格式")
        sample_id = uuid.uuid4().hex
        path = self.root / "raw" / key / f"{sample_id}.{extension}"
        atomic_write_bytes(str(path), data)
        digest = hashlib.sha256(data).hexdigest()
        with self.connect() as db:
            db.execute("INSERT INTO samples VALUES(?,?,?,?)", (key, sample_id, str(path), digest))
        return str(path)

    def cached(self, key):
        with self.connect() as db:
            rows = db.execute("""SELECT s.path,s.sha256 FROM samples s
                LEFT JOIN selected_samples p ON p.request_key=s.request_key
                WHERE s.request_key=? ORDER BY (s.sample_id=p.sample_id) DESC,s.rowid ASC""", (key,)).fetchall()
        for path, digest in rows:
            source = Path(path)
            if source.is_file() and hashlib.sha256(source.read_bytes()).hexdigest() == digest:
                return path
        return None

    def select_sample(self, path):
        """只有完成候选比较并成功导出的样本才能成为恢复时的首选。"""
        with self.connect() as db:
            row = db.execute("SELECT request_key,sample_id,sha256 FROM samples WHERE path=?", (str(path),)).fetchone()
            if row is None or hashlib.sha256(Path(path).read_bytes()).hexdigest() != row[2]:
                raise ValueError("不能选用未登记或已损坏的原始样本")
            db.execute("INSERT OR REPLACE INTO selected_samples VALUES(?,?)", row[:2])

    def load_anchor(self, key):
        with self.connect() as db:
            row = db.execute("SELECT path,sha256,metrics FROM role_anchors WHERE anchor_key=?", (key,)).fetchone()
        if row and Path(row[0]).is_file() and hashlib.sha256(Path(row[0]).read_bytes()).hexdigest() == row[1]:
            return row[0], json.loads(row[2])
        return None

    def save_anchor(self, key, path, metrics):
        source = Path(path).resolve()
        if not source.is_relative_to(self.root):
            raise ValueError("角色参考必须属于本项目")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO role_anchors VALUES(?,?,?,?)",
                       (key, str(source), digest, json.dumps(metrics, allow_nan=False)))

    def save_render_selection(self, key, payload):
        """持久化已导出候选的组合来源，不把合并 PCM 冒充 Provider 原始响应。"""
        value = {**payload, "version": "selected-render-v1"}
        target = Path(value["rendered_path"]).resolve()
        if not target.is_relative_to(self.root) or not target.is_file() or not value.get("parts"):
            raise ValueError("选中渲染必须位于本项目且具有原始样本来源")
        value["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
        with self.connect() as db:
            for part in value["parts"]:
                row = db.execute("SELECT sha256 FROM samples WHERE path=?", (part["raw_path"],)).fetchone()
                path = Path(part["raw_path"])
                if row is None or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != row[0]:
                    raise ValueError("选中组合包含未登记或损坏的原始样本")
            db.execute("INSERT OR REPLACE INTO selected_renders VALUES(?,?)",
                       (key, json.dumps(value, ensure_ascii=False, allow_nan=False)))

    def load_render_selection(self, key):
        with self.connect() as db:
            row = db.execute("SELECT payload FROM selected_renders WHERE selection_key=?", (key,)).fetchone()
            if row is None:
                return None
            try:
                value = json.loads(row[0])
                if value.get("version") != "selected-render-v1" or not value.get("parts"):
                    return None
                for part in value["parts"]:
                    path = Path(part["raw_path"])
                    registered = db.execute("SELECT sha256 FROM samples WHERE path=?", (str(path),)).fetchone()
                    if (registered is None or not path.resolve().is_relative_to(self.root) or not path.is_file()
                            or hashlib.sha256(path.read_bytes()).hexdigest() != registered[0]):
                        return None
                rendered = Path(value["rendered_path"])
                if not rendered.resolve().is_relative_to(self.root):
                    return None
                value["render_valid"] = rendered.is_file() and hashlib.sha256(rendered.read_bytes()).hexdigest() == value["sha256"]
                return value
            except (ValueError, KeyError, TypeError, OSError):
                return None

    def write_json(self, relative, value):
        path = self.root / relative
        if not path.resolve().is_relative_to(self.root):
            raise ValueError("报告路径必须在项目目录内")
        atomic_write_bytes(str(path), json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode())
        return str(path)

    def summary(self, run_id):
        with self.connect() as db:
            rows = db.execute("SELECT status,COUNT(*),SUM(characters),SUM(repair) FROM requests WHERE run_id=? GROUP BY status", (run_id,)).fetchall()
        return {status: {"requests": count, "characters": chars, "repair_requests": repairs}
                for status, count, chars, repairs in rows}

    def request_events(self, *, run_id=None, request_ids=None):
        """返回已记录的实际请求；不从文件数量推测请求或补造未知历史。"""
        if (run_id is None) == (request_ids is None):
            raise ValueError("请且仅请指定运行编号或请求编号集合")
        fields = ("id", "run_id", "request_key", "repair", "status", "started", "finished", "characters", "artifact", "error_type")
        if request_ids is not None:
            ids = sorted(set(request_ids))
            if not ids:
                return []
            # 避免整本恢复时超过 SQLite 参数数量限制。
            rows = []
            with self.connect() as db:
                for start in range(0, len(ids), 500):
                    batch = ids[start:start + 500]
                    rows.extend(db.execute("SELECT * FROM requests WHERE id IN (" + ",".join("?" for _ in batch) + ")", batch).fetchall())
        else:
            with self.connect() as db:
                rows = db.execute("SELECT * FROM requests WHERE run_id=?", (run_id,)).fetchall()
        return [dict(zip(fields, row)) for row in sorted(rows, key=lambda row: (row[5], row[0]))]

    def sample_provenance(self, path):
        source = Path(path).resolve()
        with self.connect() as db:
            row = db.execute("SELECT request_key,sample_id,sha256 FROM samples WHERE path=?", (str(source),)).fetchone()
            ids = [r[0] for r in db.execute("SELECT id FROM requests WHERE artifact=?", (str(source),)).fetchall()]
        if (row is None or not source.is_relative_to(self.root) or not source.is_file()
                or hashlib.sha256(source.read_bytes()).hexdigest() != row[2]):
            raise ValueError("原始样本未登记或校验失败，不能提供生成来源")
        return {"path": str(source), "request_key": row[0], "sample_id": row[1], "sha256": row[2],
                "origin_status": "recorded" if ids else "unknown", "origin_request_ids": sorted(ids)}

    def resource_provenance(self, run_id, selected_paths, chunk_lineages=()):
        actual = self.request_events(run_id=run_id)
        sources = [self.sample_provenance(path) for path in sorted(set(map(str, selected_paths)))]
        chunks = list(chunk_lineages)
        ids = {request_id for chunk in chunks for request_id in chunk["request_ids"]}
        ids.update(request_id for source in sources for request_id in source["origin_request_ids"])
        events = self.request_events(request_ids=ids)
        missing = sorted(ids - {event["id"] for event in events})
        summary = {}
        for event in events:
            item = summary.setdefault(event["status"], {"requests": 0, "characters": 0, "repair_requests": 0})
            item["requests"] += 1
            item["characters"] += event["characters"]
            item["repair_requests"] += event["repair"]
        unknown_sources = [source["path"] for source in sources if source["origin_status"] == "unknown"]
        return {"version": "request-provenance-v1", "project_database": str(self.database),
                "actual_run": {"run_id": run_id, "scope": "cumulative_run", "request_events": actual,
                               "summary": self.summary(run_id)},
                "selected_sources": sources,
                "recorded_generation": {"scope": "selected_sources_and_observed_candidate_lineage",
                    "request_events": events, "summary": summary, "chunks": chunks,
                    "history_incomplete": bool(missing or unknown_sources or not chunks
                                               or any(c["history_incomplete"] for c in chunks)),
                    "missing_request_ids": missing, "unknown_source_paths": unknown_sources,
                    "note": "历史记录不全时保留未知；本次零请求不等于这些音频的生成资源为零。"}}
