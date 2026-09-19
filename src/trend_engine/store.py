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
    score REAL NOT NULL,
    category TEXT
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
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(clusters)")}
        if "category" not in cols:  # migrate caches created before categories existed
            self.db.execute("ALTER TABLE clusters ADD COLUMN category TEXT")
            self.db.commit()

    # --- reports -------------------------------------------------------------
    def save_report(self, report: dict[str, Any]) -> int:
        cur = self.db.execute(
            "INSERT INTO reports(region, generated_at, payload) VALUES (?,?,?)",
            (report["region"], report["generated_at"], json.dumps(report, ensure_ascii=False)),
        )
        rid = cur.lastrowid
        self.db.executemany(
            "INSERT INTO clusters(report_id, rank, key, label, score, category) VALUES (?,?,?,?,?,?)",
            [(rid, i + 1, c["key"], c["label"], c["score"], c.get("category")) for i, c in enumerate(report["clusters"])],
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

    def cluster_rows(self, region: str, start: datetime, end: datetime) -> list[dict[str, Any]]:
        """Every (snapshot, cluster) row in [start, end) — input for daily aggregation (archive.py)."""
        rows = self.db.execute(
            """SELECT r.generated_at, c.rank, c.key, c.label, c.score, c.category FROM clusters c
               JOIN reports r ON r.id=c.report_id
               WHERE r.region=? AND r.generated_at>=? AND r.generated_at<? ORDER BY r.generated_at""",
            # timestamps are stored as UTC ISO strings; compare in the same form
            (region, start.astimezone(timezone.utc).isoformat(timespec="seconds"),
             end.astimezone(timezone.utc).isoformat(timespec="seconds")),
        ).fetchall()
        return [dict(r) for r in rows]

    def snapshot_times(self, region: str) -> list[str]:
        return [r[0] for r in self.db.execute(
            "SELECT generated_at FROM reports WHERE region=? ORDER BY generated_at", (region,)).fetchall()]

    def prune(self, payload_days: int = 3, keep_days: int = 45) -> None:
        """Keep the cache DB small: drop full report payloads after `payload_days` (ranks stay for
        aggregation) and everything after `keep_days` (by then it is in the archive)."""
        now = utcnow()
        self.db.execute("UPDATE reports SET payload='null' WHERE generated_at<? AND payload!='null'",
                        ((now - timedelta(days=payload_days)).isoformat(),))
        old = (now - timedelta(days=keep_days)).isoformat()
        self.db.execute("DELETE FROM clusters WHERE report_id IN (SELECT id FROM reports WHERE generated_at<?)", (old,))
        self.db.execute("DELETE FROM reports WHERE generated_at<?", (old,))
        self.db.execute("DELETE FROM cache WHERE created_at<?", (old,))
        self.db.commit()

    # --- generic cache (Naver DataLab quota, derived views, daily snapshots) ------------
    def cache_get(self, key: str, max_age: timedelta) -> Any | None:
        row = self.db.execute("SELECT created_at, payload FROM cache WHERE key=?", (key,)).fetchone()
        if not row or datetime.fromisoformat(row["created_at"]) < utcnow() - max_age:
            return None
        return json.loads(row["payload"])

    def cache_keys(self, prefix: str) -> list[str]:
        return [r[0] for r in self.db.execute("SELECT key FROM cache WHERE key LIKE ? ORDER BY key", (prefix + "%",))]

    def cache_set(self, key: str, value: Any) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO cache(key, created_at, payload) VALUES (?,?,?)",
            (key, utcnow().isoformat(), json.dumps(value, ensure_ascii=False)),
        )
        self.db.commit()
