"""SQLite-хранилище с репозиторным интерфейсом. Все запросы параметризованы.

Для пилота схема переносится в Postgres без изменений логики: методы класса Database
и есть контракт хранилища.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY,
    external_id TEXT,
    source TEXT NOT NULL,
    channel TEXT,
    author TEXT,
    posted_at TEXT,
    text TEXT,
    ocr_text TEXT,
    transcript TEXT,
    score REAL DEFAULT 0,
    level TEXT DEFAULT 'low',
    track TEXT,
    analysis_json TEXT,
    label TEXT,
    status TEXT DEFAULT 'processing',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_posts_level ON posts(level, score);
CREATE INDEX IF NOT EXISTS idx_posts_channel ON posts(channel);
CREATE TABLE IF NOT EXISTS artifacts (
    id INTEGER PRIMARY KEY,
    post_id INTEGER NOT NULL REFERENCES posts(id),
    kind TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    ext TEXT,
    pdq TEXT,
    pdq_quality INTEGER,
    minhash BLOB,
    ocr_json TEXT,
    width INTEGER,
    height INTEGER,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_artifacts_post ON artifacts(post_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_sha ON artifacts(sha256);
CREATE TABLE IF NOT EXISTS matches (
    artifact_id INTEGER NOT NULL REFERENCES artifacts(id),
    other_id INTEGER NOT NULL REFERENCES artifacts(id),
    kind TEXT NOT NULL,
    distance REAL NOT NULL,
    diff_json TEXT,
    PRIMARY KEY (artifact_id, other_id)
);
CREATE INDEX IF NOT EXISTS idx_matches_other ON matches(other_id);
CREATE TABLE IF NOT EXISTS requisites (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    key TEXT NOT NULL UNIQUE,
    display TEXT NOT NULL,
    first_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS post_requisites (
    post_id INTEGER NOT NULL REFERENCES posts(id),
    requisite_id INTEGER NOT NULL REFERENCES requisites(id),
    PRIMARY KEY (post_id, requisite_id)
);
CREATE INDEX IF NOT EXISTS idx_pr_req ON post_requisites(requisite_id);
CREATE TABLE IF NOT EXISTS links (
    post_id INTEGER NOT NULL REFERENCES posts(id),
    url TEXT NOT NULL,
    domain TEXT NOT NULL,
    resolved TEXT,
    PRIMARY KEY (post_id, url)
);
CREATE INDEX IF NOT EXISTS idx_links_domain ON links(domain);
CREATE TABLE IF NOT EXISTS case_status (
    case_key TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    note TEXT,
    updated_at TEXT NOT NULL,
    updated_by TEXT
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT
);
"""

CASE_STATUSES = ("new", "in_review", "confirmed", "dismissed")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(SCHEMA)
            cols = {r[1] for r in self._conn.execute("PRAGMA table_info(posts)")}
            if "status" not in cols:  # миграция баз, созданных до появления статуса
                self._conn.execute("ALTER TABLE posts ADD COLUMN status TEXT DEFAULT 'ok'")
                self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _all(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def _one(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def _exec(self, sql: str, params: Sequence[Any] = ()) -> int:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return int(cur.lastrowid or 0)

    # ---------- posts ----------
    def create_post(self, *, source: str, channel: str | None, author: str | None, posted_at: str | None,
                    text: str | None, external_id: str | None = None, label: str | None = None) -> int:
        return self._exec(
            "INSERT INTO posts (external_id, source, channel, author, posted_at, text, label, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (external_id, source, channel, author, posted_at or utcnow(), text, label, utcnow()),
        )

    def update_post_analysis(self, post_id: int, *, score: float, level: str, track: str | None,
                             analysis: dict[str, Any], ocr_text: str | None, transcript: str | None) -> None:
        self._exec(
            "UPDATE posts SET score=?, level=?, track=?, analysis_json=?, ocr_text=?, transcript=?, status='ok' WHERE id=?",
            (score, level, track, json.dumps(analysis, ensure_ascii=False), ocr_text, transcript, post_id),
        )

    def mark_post_failed(self, post_id: int, reason: str) -> None:
        self._exec("UPDATE posts SET status='failed', analysis_json=? WHERE id=?",
                   (json.dumps({"error": reason}, ensure_ascii=False), post_id))

    def get_post(self, post_id: int) -> dict[str, Any] | None:
        post = self._one("SELECT * FROM posts WHERE id=?", (post_id,))
        if post and post.get("analysis_json"):
            post["analysis"] = json.loads(post.pop("analysis_json"))
        return post

    def get_posts(self, ids: Iterable[int]) -> list[dict[str, Any]]:
        ids = list(ids)
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        rows = self._all(f"SELECT id, source, channel, author, posted_at, text, score, level, track, label FROM posts WHERE id IN ({marks})", ids)
        return sorted(rows, key=lambda r: (r["posted_at"] or "", r["id"]))

    def post_levels(self, ids: Iterable[int]) -> dict[int, tuple[str, str | None, float]]:
        return {r["id"]: (r["level"], r["track"], r["score"]) for r in self.get_posts(ids)}

    def all_posts_brief(self) -> list[dict[str, Any]]:
        return self._all("SELECT id, channel, posted_at, score, level, track FROM posts WHERE status='ok'")

    def count_posts(self) -> int:
        row = self._one("SELECT COUNT(*) AS n FROM posts")
        return int(row["n"]) if row else 0

    def level_counts(self) -> dict[str, int]:
        return {r["level"]: r["n"] for r in self._all("SELECT level, COUNT(*) AS n FROM posts GROUP BY level")}

    # ---------- artifacts ----------
    def create_artifact(self, *, post_id: int, kind: str, sha256: str, ext: str | None, pdq: str | None = None,
                        pdq_quality: int | None = None, minhash: bytes | None = None, ocr: list[dict] | None = None,
                        width: int | None = None, height: int | None = None) -> int:
        return self._exec(
            "INSERT INTO artifacts (post_id, kind, sha256, ext, pdq, pdq_quality, minhash, ocr_json, width, height, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (post_id, kind, sha256, ext, pdq, pdq_quality, minhash,
             json.dumps(ocr, ensure_ascii=False) if ocr is not None else None, width, height, utcnow()),
        )

    def get_artifact(self, artifact_id: int) -> dict[str, Any] | None:
        art = self._one("SELECT id, post_id, kind, sha256, ext, pdq, pdq_quality, ocr_json, width, height, created_at FROM artifacts WHERE id=?", (artifact_id,))
        if art:
            art["ocr"] = json.loads(art.pop("ocr_json")) if art.get("ocr_json") else []
        return art

    def artifacts_for_post(self, post_id: int) -> list[dict[str, Any]]:
        return self._all("SELECT id, post_id, kind, sha256, ext, pdq, width, height FROM artifacts WHERE post_id=?", (post_id,))

    def artifacts_by_sha(self, sha256: str) -> list[dict[str, Any]]:
        return self._all("SELECT id, post_id FROM artifacts WHERE sha256=?", (sha256,))

    def iter_index_rows(self) -> list[dict[str, Any]]:
        return self._all("SELECT id, kind, pdq, minhash, ocr_json FROM artifacts WHERE pdq IS NOT NULL OR minhash IS NOT NULL")

    def artifact_post_ids(self, artifact_ids: Iterable[int]) -> dict[int, int]:
        ids = list(artifact_ids)
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        return {r["id"]: r["post_id"] for r in self._all(f"SELECT id, post_id FROM artifacts WHERE id IN ({marks})", ids)}

    # ---------- matches ----------
    def add_match(self, artifact_id: int, other_id: int, kind: str, distance: float, diff: dict | None = None) -> None:
        self._exec(
            "INSERT OR REPLACE INTO matches (artifact_id, other_id, kind, distance, diff_json) VALUES (?,?,?,?,?)",
            (artifact_id, other_id, kind, distance, json.dumps(diff, ensure_ascii=False) if diff else None),
        )

    def matches_for(self, artifact_id: int) -> list[dict[str, Any]]:
        rows = self._all(
            "SELECT artifact_id, other_id, kind, distance, diff_json FROM matches WHERE artifact_id=? OR other_id=?",
            (artifact_id, artifact_id),
        )
        for r in rows:
            r["diff"] = json.loads(r.pop("diff_json")) if r.get("diff_json") else None
        return rows

    def all_matches(self) -> list[dict[str, Any]]:
        return self._all(
            "SELECT m.artifact_id, m.other_id, m.kind, m.distance, a.post_id AS post_a, b.post_id AS post_b "
            "FROM matches m JOIN artifacts a ON a.id=m.artifact_id JOIN artifacts b ON b.id=m.other_id"
        )

    # ---------- requisites & links ----------
    def link_requisite(self, post_id: int, kind: str, key: str, display: str) -> int:
        with self._lock:
            self._conn.execute("INSERT OR IGNORE INTO requisites (kind, key, display, first_seen) VALUES (?,?,?,?)",
                               (kind, key, display, utcnow()))
            req_id = self._conn.execute("SELECT id FROM requisites WHERE key=?", (key,)).fetchone()["id"]
            self._conn.execute("INSERT OR IGNORE INTO post_requisites (post_id, requisite_id) VALUES (?,?)", (post_id, req_id))
            self._conn.commit()
        return int(req_id)

    def posts_with_requisite(self, key: str, limit: int = 1000) -> list[int]:
        return [r["post_id"] for r in self._all(
            "SELECT pr.post_id FROM post_requisites pr JOIN requisites r ON r.id=pr.requisite_id WHERE r.key=? "
            "ORDER BY pr.post_id DESC LIMIT ?", (key, limit))]

    def lookup_requisite(self, key: str) -> dict[str, Any] | None:
        return self._one(
            "SELECT r.kind, r.display, r.first_seen, COUNT(DISTINCT p.id) AS posts, MAX(p.score) AS max_score, "
            "GROUP_CONCAT(DISTINCT p.track) AS tracks FROM requisites r JOIN post_requisites pr ON pr.requisite_id=r.id "
            "JOIN posts p ON p.id=pr.post_id WHERE r.key=? AND p.level IN ('medium','high') GROUP BY r.id", (key,))

    def requisites_for_post(self, post_id: int) -> list[dict[str, Any]]:
        return self._all("SELECT r.id, r.kind, r.key, r.display FROM requisites r JOIN post_requisites pr ON pr.requisite_id=r.id WHERE pr.post_id=?", (post_id,))

    def all_post_requisites(self) -> list[dict[str, Any]]:
        return self._all("SELECT pr.post_id, r.id, r.kind, r.key, r.display FROM post_requisites pr JOIN requisites r ON r.id=pr.requisite_id")

    def requisite_feed(self, since: str | None, min_level: str, limit: int, offset: int) -> list[dict[str, Any]]:
        levels = {"low": ("low", "medium", "high"), "medium": ("medium", "high"), "high": ("high",)}[min_level]
        marks = ",".join("?" * len(levels))
        params: list[Any] = list(levels)
        where = f"p.level IN ({marks})"
        if since:
            where += " AND r.first_seen >= ?"
            params.append(since)
        params.extend([limit, offset])
        return self._all(
            "SELECT r.id, r.kind, r.display, r.key, r.first_seen, MAX(p.score) AS max_score, COUNT(DISTINCT p.id) AS posts, "
            "GROUP_CONCAT(DISTINCT p.track) AS tracks, MAX(p.posted_at) AS last_seen "
            f"FROM requisites r JOIN post_requisites pr ON pr.requisite_id=r.id JOIN posts p ON p.id=pr.post_id WHERE {where} "
            "GROUP BY r.id ORDER BY max_score DESC, posts DESC LIMIT ? OFFSET ?",
            params,
        )

    def add_link(self, post_id: int, url: str, domain: str, resolved: str | None) -> None:
        self._exec("INSERT OR IGNORE INTO links (post_id, url, domain, resolved) VALUES (?,?,?,?)", (post_id, url, domain, resolved))

    def all_links(self) -> list[dict[str, Any]]:
        return self._all("SELECT post_id, url, domain FROM links")

    def links_for_post(self, post_id: int) -> list[dict[str, Any]]:
        return self._all("SELECT url, domain, resolved FROM links WHERE post_id=?", (post_id,))

    # ---------- cases ----------
    def case_statuses(self) -> dict[str, dict[str, Any]]:
        return {r["case_key"]: r for r in self._all("SELECT * FROM case_status")}

    def set_case_status(self, case_key: str, status: str, note: str | None, actor: str) -> None:
        if status not in CASE_STATUSES:
            raise ValueError("недопустимый статус")
        self._exec(
            "INSERT INTO case_status (case_key, status, note, updated_at, updated_by) VALUES (?,?,?,?,?) "
            "ON CONFLICT(case_key) DO UPDATE SET status=excluded.status, note=excluded.note, updated_at=excluded.updated_at, updated_by=excluded.updated_by",
            (case_key, status, note, utcnow(), actor),
        )

    def audit(self, actor: str, action: str, target: str | None) -> None:
        self._exec("INSERT INTO audit_log (ts, actor, action, target) VALUES (?,?,?,?)", (utcnow(), actor, action, target))
