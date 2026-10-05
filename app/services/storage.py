from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.config import settings
from app.models import Segment, TaskResult, TaskStatus, TranscriptSource

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "app.db"
OUTPUT_DIR = DATA_DIR / "output"


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def _db():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY, url TEXT, normalized_url TEXT, platform TEXT,
            status TEXT NOT NULL, title TEXT, duration REAL, source TEXT,
            language TEXT, subtitle_lang TEXT, text TEXT, error TEXT,
            error_type TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            completed_at TEXT, file_path TEXT, resolved_tier TEXT, cached INTEGER DEFAULT 0, cancelled INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS segments (
            task_id TEXT NOT NULL, idx INTEGER NOT NULL, start REAL NOT NULL,
            end REAL NOT NULL, text TEXT NOT NULL,
            PRIMARY KEY (task_id, idx), FOREIGN KEY(task_id) REFERENCES tasks(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_segments_task_id ON segments(task_id);
        CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at);
        CREATE INDEX IF NOT EXISTS idx_tasks_platform ON tasks(platform);
        CREATE INDEX IF NOT EXISTS idx_tasks_normalized_url ON tasks(normalized_url);
        CREATE TABLE IF NOT EXISTS result_cache (
            cache_key TEXT PRIMARY KEY, task_id TEXT NOT NULL, normalized_url TEXT NOT NULL,
            platform TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_cache_updated_at ON result_cache(updated_at);
        """)
        _ensure_column(conn, "tasks", "subtitle_lang", "TEXT")
        _ensure_column(conn, "tasks", "resolved_tier", "TEXT")
        _ensure_column(conn, "tasks", "cached", "INTEGER DEFAULT 0")
        _ensure_column(conn, "tasks", "cancelled", "INTEGER DEFAULT 0")


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    names = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in names:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _row_to_task(row: sqlite3.Row) -> TaskResult:
    with _db() as conn:
        segment_rows = conn.execute("SELECT start,end,text FROM segments WHERE task_id=? ORDER BY idx", (row["id"],)).fetchall()
    segments = [Segment(start=r["start"], end=r["end"], text=r["text"]) for r in segment_rows] or None
    source = TranscriptSource(row["source"]) if row["source"] else None
    return TaskResult(
        task_id=row["id"], status=TaskStatus(row["status"]), video_title=row["title"],
        video_duration=row["duration"], source=source, language=row["language"],
        subtitle_lang=row["subtitle_lang"], text=row["text"], error=row["error"],
        error_type=row["error_type"], platform=row["platform"], normalized_url=row["normalized_url"],
        resolved_tier=row["resolved_tier"], created_at=_dt(row["created_at"]) or datetime.now(),
        updated_at=_dt(row["updated_at"]) if "updated_at" in row.keys() else None,
        completed_at=_dt(row["completed_at"]), file_path=row["file_path"], cached=bool(row["cached"]), cancelled=bool(row["cancelled"]),
        segments=segments,
    )


def save_task(task: TaskResult, url: str | None = None) -> None:
    now = datetime.now().isoformat()
    with _db() as conn:
        conn.execute("""INSERT INTO tasks
            (id,url,normalized_url,platform,status,title,duration,source,language,subtitle_lang,text,error,error_type,created_at,updated_at,completed_at,file_path,resolved_tier,cached,cancelled)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET normalized_url=excluded.normalized_url, platform=excluded.platform,
            status=excluded.status,title=excluded.title,duration=excluded.duration,source=excluded.source,
            language=excluded.language,subtitle_lang=excluded.subtitle_lang,text=excluded.text,error=excluded.error,
            error_type=excluded.error_type,updated_at=excluded.updated_at,completed_at=excluded.completed_at,
            file_path=excluded.file_path,resolved_tier=excluded.resolved_tier,cached=excluded.cached,cancelled=excluded.cancelled""", 
            (task.task_id, url or task.normalized_url or "", task.normalized_url, task.platform, task.status.value,
             task.video_title, task.video_duration, task.source.value if task.source else None, task.language,
             task.subtitle_lang, task.text, task.error, task.error_type, _iso(task.created_at), now,
             _iso(task.completed_at), task.file_path, task.resolved_tier, int(task.cached), int(task.cancelled)))
        conn.execute("DELETE FROM segments WHERE task_id=?", (task.task_id,))
        for idx, segment in enumerate(task.segments or []):
            conn.execute("INSERT INTO segments(task_id,idx,start,end,text) VALUES(?,?,?,?,?)",
                         (task.task_id, idx, segment.start, segment.end, segment.text))


def get_task(task_id: str) -> TaskResult | None:
    with _db() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    return _row_to_task(row) if row else None


def load_tasks(limit: int = 1000) -> list[TaskResult]:
    with _db() as conn:
        rows = conn.execute("SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [_row_to_task(row) for row in rows]


def _safe_title(title: str | None, task_id: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|]", "_", (title or "").strip())
    value = re.sub(r"[^\w\u4e00-\u9fff .-]", "", value).strip(" .")[:80]
    return value or task_id


def write_output(task: TaskResult) -> str | None:
    if task.status != TaskStatus.COMPLETED or not task.text:
        return None
    folder = OUTPUT_DIR / (task.platform or "generic")
    folder.mkdir(parents=True, exist_ok=True)
    day = (task.completed_at or datetime.now()).strftime("%Y%m%d")
    path = folder / f"{day}_{task.task_id}_{_safe_title(task.video_title, task.task_id)}.md"
    if path.exists():
        path = path.with_name(f"{path.stem}_{secrets.token_hex(2)}{path.suffix}")
    lines = ["---", f"source_url: {task.normalized_url or ''}", f"platform: {task.platform or ''}",
             f"title: {task.video_title or ''}", f"duration: {task.video_duration or 0}",
             f"source: {task.source.value if task.source else ''}", f"language: {task.language or ''}",
             f"generated_at: {(task.completed_at or datetime.now()).isoformat()}", "---", "", task.text, ""]
    if task.segments:
        lines.extend(["## 时间戳", ""])
        for idx, segment in enumerate(task.segments, 1):
            lines.append(f"{idx}. [{segment.start:.3f} - {segment.end:.3f}] {segment.text}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(path).replace("\\", "/")


def list_tasks(limit: int, offset: int, platform: str | None = None, q: str | None = None) -> tuple[list[TaskResult], int]:
    where, args = [], []
    if platform:
        where.append("platform=?"); args.append(platform)
    if q:
        where.append("(title LIKE ? OR text LIKE ? OR normalized_url LIKE ?)"); args.extend([f"%{q}%"] * 3)
    clause = " WHERE " + " AND ".join(where) if where else ""
    with _db() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM tasks{clause}", args).fetchone()[0]
        rows = conn.execute(f"SELECT * FROM tasks{clause} ORDER BY created_at DESC LIMIT ? OFFSET ?", args + [limit, offset]).fetchall()
    return [_row_to_task(row) for row in rows], total


def delete_task(task_id: str) -> bool:
    task = get_task(task_id)
    if not task:
        return False
    with _db() as conn:
        conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
    if task.file_path:
        Path(task.file_path).unlink(missing_ok=True)
    return True


def cache_key(platform: str | None, normalized_url: str, video_id: str | None = None) -> str:
    # Bump when runtime routing semantics change so stale ASR results cannot
    # mask a newly available subtitle path.
    identity = video_id or normalized_url
    return f"v3:{platform or 'generic'}:{hashlib.sha256(identity.encode()).hexdigest()}"


def get_cached(key: str) -> TaskResult | None:
    with _db() as conn:
        row = conn.execute("SELECT task_id,updated_at FROM result_cache WHERE cache_key=?", (key,)).fetchone()
    if not row or datetime.fromisoformat(row["updated_at"]) < datetime.now() - timedelta(days=settings.CACHE_TTL_DAYS):
        return None
    return get_task(row["task_id"])


def put_cache(key: str, task: TaskResult) -> None:
    now = datetime.now().isoformat()
    with _db() as conn:
        conn.execute("INSERT INTO result_cache(cache_key,task_id,normalized_url,platform,created_at,updated_at) VALUES(?,?,?,?,?,?) ON CONFLICT(cache_key) DO UPDATE SET task_id=excluded.task_id,updated_at=excluded.updated_at", (key, task.task_id, task.normalized_url or "", task.platform, now, now))


def cache_stats() -> tuple[int, int, int]:
    cutoff = (datetime.now() - timedelta(days=settings.CACHE_TTL_DAYS)).isoformat()
    with _db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM result_cache").fetchone()[0]
        valid = conn.execute("SELECT COUNT(*) FROM result_cache WHERE updated_at>=?", (cutoff,)).fetchone()[0]
    return total, valid, total - valid


def clear_cache() -> int:
    with _db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM result_cache").fetchone()[0]
        conn.execute("DELETE FROM result_cache")
    return count


def purge_expired_cache() -> int:
    cutoff = (datetime.now() - timedelta(days=settings.CACHE_TTL_DAYS)).isoformat()
    with _db() as conn:
        cur = conn.execute("DELETE FROM result_cache WHERE updated_at<?", (cutoff,))
        return cur.rowcount
