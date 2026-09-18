"""SQLite snapshot store: every collect() is kept so we can compute rising/new and history."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    region TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS reports_region_time ON reports(region, generated_at);
CREATE TABLE IF NOT EXISTS clusters (
    report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    rank INTEGER NOT NULL,
    key TEXT NOT NULL,
    label TEXT NOT NULL,
    score REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS clusters_key ON clusters(key);
CREATE TABLE IF NOT EXISTS cache (
    key TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Store:
    def __init__(self, path: str | Path = "data/trends.db"):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    # --- reports -------------------------------------------------------------
    def save_report(self, report: dict[str, Any]) -> int:
        cur = self.db.execute(
            "INSERT INTO reports(region, generated_at, payload) VALUES (?,?,?)",
            (report["region"], report["generated_at"], json.dumps(report, ensure_ascii=False)),
        )
        rid = cur.lastrowid
        self.db.executemany(
            "INSERT INTO clusters(report_id, rank, key, label, score) VALUES (?,?,?,?,?)",
            [(rid, i + 1, c["key"], c["label"], c["score"]) for i, c in enumerate(report["clusters"])],
        )
        self.db.commit()
        return int(rid)

    def latest_report(self, region: str, max_age: timedelta | None = None) -> dict[str, Any] | None:
        row = self.db.execute(
            "SELECT payload, generated_at FROM reports WHERE region=? ORDER BY generated_at DESC LIMIT 1",
            (region,),
        ).fetchone()
        if not row:
            return None
        if max_age and datetime.fromisoformat(row["generated_at"]) < utcnow() - max_age:
            return None
        return json.loads(row["payload"])

    def previous_report(self, region: str, min_gap: timedelta = timedelta(minutes=30)) -> dict[str, Any] | None:
        """Baseline for rising/new: newest report at least `min_gap` old, else the newest one."""
        cutoff = (utcnow() - min_gap).isoformat()
        row = self.db.execute(
            "SELECT payload FROM reports WHERE region=? AND generated_at<=? ORDER BY generated_at DESC LIMIT 1",
            (region, cutoff),
        ).fetchone() or self.db.execute(
            "SELECT payload FROM reports WHERE region=? ORDER BY generated_at DESC LIMIT 1", (region,)
        ).fetchone()
        return json.loads(row["payload"]) if row else None

    def history(self, key: str, region: str, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db.execute(
            """SELECT r.generated_at, c.rank, c.score, c.label FROM clusters c
               JOIN reports r ON r.id=c.report_id
               WHERE c.key=? AND r.region=? ORDER BY r.generated_at DESC LIMIT ?""",
            (key, region, limit),
        ).fetchall()
        return [dict(r) for r in reversed(rows)]

    # --- generic cache (Naver DataLab quota, Seoul API, AI briefs) ------------
    def cache_get(self, key: str, max_age: timedelta) -> Any | None:
        row = self.db.execute("SELECT created_at, payload FROM cache WHERE key=?", (key,)).fetchone()
        if not row or datetime.fromisoformat(row["created_at"]) < utcnow() - max_age:
            return None
        return json.loads(row["payload"])

    def cache_set(self, key: str, value: Any) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO cache(key, created_at, payload) VALUES (?,?,?)",
            (key, utcnow().isoformat(), json.dumps(value, ensure_ascii=False)),
        )
        self.db.commit()
