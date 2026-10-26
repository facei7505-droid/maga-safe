"""SQLite-хранилище с репозиторным интерфейсом. Все запросы параметризованы.

Для пилота схема переносится в Postgres без изменений логики: методы класса Database
и есть контракт хранилища.
"""

from __future__ import annotations

import functools
import json
import sqlite3
import threading
from collections.abc import Callable, Iterable, Sequence
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
CREATE TABLE IF NOT EXISTS requisite_status (
    key TEXT NOT NULL,
    case_key TEXT NOT NULL,
    decision TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by TEXT,
    PRIMARY KEY (key, case_key)
);
CREATE INDEX IF NOT EXISTS idx_requisite_status_case ON requisite_status(case_key);
CREATE TABLE IF NOT EXISTS scout_channels (
    username TEXT PRIMARY KEY,
    title TEXT,
    subscribers INTEGER,
    created_at TEXT,
    risk REAL,
    level TEXT,
    track TEXT,
    posts_checked INTEGER DEFAULT 0,
    risky_posts INTEGER DEFAULT 0,
    status TEXT NOT NULL,
    found_via TEXT,
    found_from TEXT,
    found_detail TEXT,
    depth INTEGER,
    first_seen TEXT NOT NULL,
    last_checked TEXT
);
CREATE TABLE IF NOT EXISTS scout_edges (
    src TEXT NOT NULL,
    dst TEXT NOT NULL,
    via TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    first_seen TEXT NOT NULL,
    PRIMARY KEY (src, dst, via, detail)
);
CREATE INDEX IF NOT EXISTS idx_scout_edges_dst ON scout_edges(dst);
CREATE TABLE IF NOT EXISTS user_reports (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    reporter TEXT NOT NULL,
    platform TEXT NOT NULL,
    text_hash TEXT NOT NULL,
    cues TEXT NOT NULL DEFAULT '',
    domains TEXT NOT NULL DEFAULT '',
    UNIQUE (reporter, text_hash)
);
CREATE TABLE IF NOT EXISTS report_requisites (
    report_id INTEGER NOT NULL REFERENCES user_reports(id),
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    display TEXT NOT NULL,
    PRIMARY KEY (report_id, key)
);
CREATE INDEX IF NOT EXISTS idx_report_req_key ON report_requisites(key);
CREATE TABLE IF NOT EXISTS bot_feedback (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    reporter TEXT NOT NULL,
    check_id TEXT NOT NULL,
    level TEXT NOT NULL,
    score REAL NOT NULL,
    track TEXT,
    lang TEXT NOT NULL,
    features TEXT NOT NULL DEFAULT '[]',
    UNIQUE (reporter, check_id)
);
CREATE TABLE IF NOT EXISTS bot_feature_shown (
    feature_id TEXT NOT NULL,
    day TEXT NOT NULL,
    label TEXT NOT NULL,
    shown INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (feature_id, day)
);
CREATE TABLE IF NOT EXISTS bank_feedback (
    bank TEXT NOT NULL,
    key TEXT NOT NULL,
    kind TEXT NOT NULL,
    display TEXT NOT NULL,
    outcome TEXT NOT NULL,
    ts TEXT NOT NULL,
    PRIMARY KEY (bank, key)
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
BANK_OUTCOMES = ("fraud_confirmed", "legit_client")  # банк: перевод оказался мошенничеством / это наш честный клиент
# Решения аналитика по реквизиту (pruf/lists.py): подтверждённый кейс делает номер чёрным, отклонённый снимает;
# без решений номер серый. Чёрный побеждает: номер из подтверждённого кейса не снимается другим кейсом.
_LIST_JOIN = ("LEFT JOIN (SELECT key AS dkey, MAX(decision='confirmed') AS black, MAX(decision='dismissed') AS cleared, "
              "GROUP_CONCAT(case_key || ':' || decision) AS decided FROM requisite_status GROUP BY key) d ON d.dkey=r.key")
_LIST_EXPR = "CASE WHEN d.black THEN 'black' WHEN d.cleared THEN 'cleared' ELSE 'grey' END"


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _mutates(method):
    """Метод меняет таблицы людей: после него база сообщает об изменении (снимок состояния, pruf/storage/state.py)."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        result = method(self, *args, **kwargs)
        self._changed()
        return result
    return wrapper


class Database:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self.on_change: Callable[[], None] | None = None  # изменились таблицы людей (pruf/storage/state.py)
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

    def _changed(self) -> None:
        if self.on_change is not None:
            self.on_change()

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

    def find_post_by_external_id(self, external_id: str) -> dict[str, Any] | None:
        # Успешно разобранный пост важнее упавших попыток, иначе каждый повтор создавал бы новую строку
        row = self._one("SELECT id FROM posts WHERE external_id=? ORDER BY status='ok' DESC, id DESC LIMIT 1", (external_id,))
        return self.get_post(row["id"]) if row else None

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

    def count_posts_from(self, source: str) -> int:
        row = self._one("SELECT COUNT(*) AS n FROM posts WHERE source=?", (source,))
        return int(row["n"]) if row else 0

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

    def artifacts_by_ids(self, artifact_ids: Iterable[int]) -> dict[int, dict[str, Any]]:
        """Пачкой: id, post_id, kind и разобранный OCR (для таймлайна без запроса на каждую копию)."""
        ids = list(artifact_ids)
        out: dict[int, dict[str, Any]] = {}
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            marks = ",".join("?" * len(chunk))
            for r in self._all(f"SELECT id, post_id, kind, ocr_json FROM artifacts WHERE id IN ({marks})", chunk):
                r["ocr"] = json.loads(r.pop("ocr_json")) if r.get("ocr_json") else []
                out[r["id"]] = r
        return out

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

    def requisite_cleared_at(self, key: str) -> str | None:
        """Когда аналитик снял реквизит (отклонил кейс), если подтверждённых решений по нему нет; иначе None."""
        row = self._one("SELECT MAX(decision='confirmed') AS black, MAX(CASE WHEN decision='dismissed' THEN updated_at END) AS cleared "
                        "FROM requisite_status WHERE key=?", (key,))
        return None if not row or row["black"] else row["cleared"]

    def posts_created_after(self, ids: Iterable[int], ts: str) -> set[int]:
        ids = list(ids)
        if not ids:
            return set()
        marks = ",".join("?" * len(ids))
        return {r["id"] for r in self._all(f"SELECT id FROM posts WHERE id IN ({marks}) AND created_at>?", [*ids, ts])}

    def lookup_requisite(self, key: str) -> dict[str, Any] | None:
        return self._one(
            "SELECT r.kind, r.display, r.first_seen, COUNT(DISTINCT p.id) AS posts, MAX(p.score) AS max_score, "
            f"GROUP_CONCAT(DISTINCT p.track) AS tracks, MIN(p.created_at) AS grey_since, {_LIST_EXPR} AS list, d.decided "
            f"FROM requisites r JOIN post_requisites pr ON pr.requisite_id=r.id JOIN posts p ON p.id=pr.post_id {_LIST_JOIN} "
            "WHERE r.key=? AND p.level IN ('medium','high') GROUP BY r.id", (key,))

    def requisites_for_post(self, post_id: int) -> list[dict[str, Any]]:
        return self._all("SELECT r.id, r.kind, r.key, r.display FROM requisites r JOIN post_requisites pr ON pr.requisite_id=r.id WHERE pr.post_id=?", (post_id,))

    def all_post_requisites(self) -> list[dict[str, Any]]:
        return self._all("SELECT pr.post_id, r.id, r.kind, r.key, r.display FROM post_requisites pr JOIN requisites r ON r.id=pr.requisite_id")

    def requisite_feed(self, since: str | None, min_level: str, limit: int, offset: int,
                       list_name: str | None = None) -> list[dict[str, Any]]:
        levels = {"low": ("low", "medium", "high"), "medium": ("medium", "high"), "high": ("high",)}[min_level]
        marks = ",".join("?" * len(levels))
        params: list[Any] = list(levels)
        where = f"p.level IN ({marks})"
        if since:
            where += " AND r.first_seen >= ?"
            params.append(since)
        if list_name:
            where += f" AND {_LIST_EXPR} = ?"
            params.append(list_name)
        params.extend([limit, offset])
        return self._all(
            "SELECT r.id, r.kind, r.display, r.key, r.first_seen, MAX(p.score) AS max_score, COUNT(DISTINCT p.id) AS posts, "
            f"GROUP_CONCAT(DISTINCT p.track) AS tracks, MAX(p.posted_at) AS last_seen, MIN(p.created_at) AS grey_since, "
            f"{_LIST_EXPR} AS list, d.decided "
            f"FROM requisites r JOIN post_requisites pr ON pr.requisite_id=r.id JOIN posts p ON p.id=pr.post_id {_LIST_JOIN} "
            f"WHERE {where} GROUP BY r.id ORDER BY max_score DESC, posts DESC LIMIT ? OFFSET ?",
            params,
        )

    @_mutates
    def drop_stale_decisions(self, keys: Sequence[str], live_cases: set[str]) -> int:
        """Убрать решения по этим реквизитам от кейсов, которых нет в текущем графе (слились или распались)."""
        if not keys:
            return 0
        marks = ",".join("?" * len(keys))
        rows = self._all(f"SELECT key, case_key FROM requisite_status WHERE key IN ({marks})", list(keys))
        stale = [(r["key"], r["case_key"]) for r in rows if r["case_key"] not in live_cases]
        with self._lock, self._conn:
            self._conn.executemany("DELETE FROM requisite_status WHERE key=? AND case_key=?", stale)
        return len(stale)

    @_mutates
    def set_case_decision(self, case_key: str, keys: Sequence[str], decision: str | None, actor: str) -> None:
        """Решение аналитика по кейсу переносится на его реквизиты; прежнее решение этого кейса заменяется."""
        if decision not in (None, "confirmed", "dismissed"):
            raise ValueError("недопустимое решение")
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM requisite_status WHERE case_key=?", (case_key,))
            if decision:
                now = utcnow()
                self._conn.executemany(
                    "INSERT INTO requisite_status (key, case_key, decision, updated_at, updated_by) VALUES (?,?,?,?,?)",
                    [(key, case_key, decision, now, actor) for key in keys])

    def add_link(self, post_id: int, url: str, domain: str, resolved: str | None) -> None:
        self._exec("INSERT OR IGNORE INTO links (post_id, url, domain, resolved) VALUES (?,?,?,?)", (post_id, url, domain, resolved))

    def all_links(self) -> list[dict[str, Any]]:
        return self._all("SELECT post_id, url, domain FROM links")

    def links_for_post(self, post_id: int) -> list[dict[str, Any]]:
        return self._all("SELECT url, domain, resolved FROM links WHERE post_id=?", (post_id,))

    # ---------- cases ----------
    def case_statuses(self) -> dict[str, dict[str, Any]]:
        return {r["case_key"]: r for r in self._all("SELECT * FROM case_status")}

    @_mutates
    def set_case_status(self, case_key: str, status: str, note: str | None, actor: str) -> None:
        if status not in CASE_STATUSES:
            raise ValueError("недопустимый статус")
        self._exec(
            "INSERT INTO case_status (case_key, status, note, updated_at, updated_by) VALUES (?,?,?,?,?) "
            "ON CONFLICT(case_key) DO UPDATE SET status=excluded.status, note=excluded.note, updated_at=excluded.updated_at, updated_by=excluded.updated_by",
            (case_key, status, note, utcnow(), actor),
        )

    @_mutates
    def audit(self, actor: str, action: str, target: str | None) -> None:
        self._exec("INSERT INTO audit_log (ts, actor, action, target) VALUES (?,?,?,?)", (utcnow(), actor, action, target))

    # ---------- расширение ----------
    def risky_texts(self, limit: int = 50_000) -> list[str]:
        return [r["text"] for r in self._all(
            "SELECT text FROM posts WHERE level='high' AND text IS NOT NULL ORDER BY id DESC LIMIT ?", (limit,))]

    def risky_domains(self, limit: int = 5000) -> list[dict[str, Any]]:
        """Домены из постов высокого риска (ссылки на бренды и мессенджеры сюда не пишутся при приёме)."""
        return self._all(
            "SELECT l.domain, COUNT(DISTINCT p.id) AS posts, COUNT(DISTINCT p.channel) AS channels, MAX(p.score) AS max_score FROM links l "
            "JOIN posts p ON p.id=l.post_id WHERE p.level='high' GROUP BY l.domain ORDER BY posts DESC, l.domain LIMIT ?",
            (limit,))

    # ---------- жалобы из расширения ----------
    @_mutates
    def add_report(self, *, reporter: str, platform: str, text_hash: str, cues: Sequence[str], domains: Sequence[str],
                   requisites: Sequence[tuple[str, str, str]], daily_cap: int = 30) -> bool:
        """Жалоба пользователя. Повторная жалоба того же человека на тот же пост и жалобы сверх daily_cap
        в сутки не считаются. Хранится дата без времени: по ней не сопоставить жалобу с логами доступа."""
        today = utcnow()[:10]
        # with self._conn: коммит или откат в любом случае, иначе пустой INSERT OR IGNORE держит блокировку записи
        with self._lock, self._conn:
            sent = self._conn.execute("SELECT COUNT(*) FROM user_reports WHERE reporter=? AND ts=?", (reporter, today)).fetchone()[0]
            if sent >= daily_cap:
                return False
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO user_reports (ts, reporter, platform, text_hash, cues, domains) VALUES (?,?,?,?,?,?)",
                (today, reporter, platform, text_hash, ",".join(cues), ",".join(domains)))
            if not cur.rowcount:
                return False
            self._conn.executemany("INSERT OR IGNORE INTO report_requisites (report_id, kind, key, display) VALUES (?,?,?,?)",
                                   [(cur.lastrowid, kind, key, display) for kind, key, display in requisites])
        return True

    def reported_requisites(self, limit: int = 200, trusted_min: float = 0.7) -> list[dict[str, Any]]:
        """Реквизиты из жалоб для аналитика: сколько людей, с каких площадок, есть ли уже в реестре и сколько
        жалоб от проверенных людей. Надёжность жалобщика (c+1)/(c+d+2): c — его номера, ставшие чёрными,
        d — снятые. Проверенный: надёжность ≥ trusted_min и хотя бы один подтверждённый номер. Анонимный id
        жалобщика меняется раз в месяц, поэтому и история доверия живёт месяц: это плата за приватность."""
        return self._all(
            "WITH st AS (SELECT key, MAX(decision='confirmed') AS black, MAX(decision='dismissed') AS cleared "
            "FROM requisite_status GROUP BY key), "
            "hist AS (SELECT r.reporter, COUNT(DISTINCT CASE WHEN st.black THEN rr.key END) AS c, "
            "COUNT(DISTINCT CASE WHEN st.cleared AND NOT st.black THEN rr.key END) AS d "
            "FROM user_reports r JOIN report_requisites rr ON rr.report_id=r.id LEFT JOIN st ON st.key=rr.key GROUP BY r.reporter), "
            "trust AS (SELECT reporter, c, (c + 1.0) / (c + d + 2.0) AS t FROM hist), "
            "pairs AS (SELECT DISTINCT rr.key, r.reporter FROM report_requisites rr JOIN user_reports r ON r.id=rr.report_id), "
            "per_key AS (SELECT p.key, AVG(t.t) AS trust, SUM(t.t >= ? AND t.c >= 1) AS trusted_reporters "
            "FROM pairs p JOIN trust t ON t.reporter=p.reporter GROUP BY p.key) "
            "SELECT rr.kind, rr.key, rr.display, COUNT(DISTINCT r.reporter) AS reporters, COUNT(DISTINCT r.id) AS reports, "
            "GROUP_CONCAT(DISTINCT r.platform) AS platforms, MAX(r.ts) AS last_report, "
            "EXISTS (SELECT 1 FROM requisites q WHERE q.key=rr.key) AS in_registry, "
            "MAX(k.trusted_reporters) AS trusted_reporters, MAX(k.trust) AS trust "
            "FROM report_requisites rr JOIN user_reports r ON r.id=rr.report_id JOIN per_key k ON k.key=rr.key GROUP BY rr.key "
            "ORDER BY trusted_reporters DESC, reporters DESC, last_report DESC LIMIT ?", (trusted_min, limit))

    # ---------- «Это не мошенничество» из бота ----------
    @_mutates
    def count_bot_features(self, features: Sequence[tuple[str, str]]) -> None:
        """Сколько раз признак показан в ответе бота со средним или высоким риском: знаменатель доли споров.
        Только счётчики по дням, без текста и без того, кто спрашивал."""
        if not features:
            return
        today = utcnow()[:10]
        with self._lock, self._conn:
            self._conn.executemany(
                "INSERT INTO bot_feature_shown (feature_id, day, label, shown) VALUES (?,?,?,1) "
                "ON CONFLICT(feature_id, day) DO UPDATE SET shown=shown+1, label=excluded.label",
                [(fid, today, label) for fid, label in dict(features).items()])

    @_mutates
    def add_bot_feedback(self, *, reporter: str, check_id: str, level: str, score: float, track: str | None,
                         lang: str, features: Sequence[tuple[str, str]], daily_cap: int = 30) -> bool:
        """Отметка «это не мошенничество». Хранятся только номера и названия сработавших признаков,
        уровень и балл; текст и цитаты поста не сохраняются. Повтор и отметки сверх daily_cap не считаются."""
        today = utcnow()[:10]
        with self._lock, self._conn:
            sent = self._conn.execute("SELECT COUNT(*) FROM bot_feedback WHERE reporter=? AND ts=?", (reporter, today)).fetchone()[0]
            if sent >= daily_cap:
                return False
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO bot_feedback (ts, reporter, check_id, level, score, track, lang, features) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (today, reporter, check_id, level, score, track, lang, json.dumps([list(f) for f in features], ensure_ascii=False)))
            return bool(cur.rowcount)

    def disputed_features(self, since: str | None = None) -> list[dict[str, Any]]:
        """Признаки, которые люди оспорили в боте: сколько отметок и людей, сколько раз признак был показан
        и доля споров. Сверху признаки с наибольшим числом людей: это кандидаты на ревью словаря."""
        since = since or "0000"
        rows = self._all("SELECT reporter, ts, features FROM bot_feedback WHERE ts>=?", (since,))
        shown = {r["feature_id"]: r for r in self._all(
            "SELECT feature_id, SUM(shown) AS shown, MAX(label) AS label FROM bot_feature_shown WHERE day>=? GROUP BY feature_id",
            (since,))}
        agg: dict[str, dict[str, Any]] = {}
        for r in rows:
            for fid, label in json.loads(r["features"]):
                a = agg.setdefault(fid, {"feature_id": fid, "label": label, "disputes": 0, "reporters": set(), "last": r["ts"]})
                a["disputes"] += 1
                a["reporters"].add(r["reporter"])
                a["last"] = max(a["last"], r["ts"])
        out = []
        for fid, a in agg.items():
            n = int((shown.get(fid) or {}).get("shown") or 0)
            # показов не меньше споров: счётчик показов мог начаться позже первых отметок
            n = max(n, a["disputes"])
            out.append({**a, "reporters": len(a["reporters"]), "shown": n, "rate": round(a["disputes"] / n, 3)})
        out.sort(key=lambda a: (-a["reporters"], -a["rate"], a["feature_id"]))
        return out

    def bot_feedback_count(self) -> int:
        row = self._one("SELECT COUNT(*) AS n FROM bot_feedback")
        return int(row["n"]) if row else 0

    # ---------- обратная связь банков ----------
    @_mutates
    def set_bank_feedback(self, *, bank: str, key: str, kind: str, display: str, outcome: str) -> None:
        """Исход по реквизиту от банка. Один банк — одно последнее мнение о реквизите; хранится дата без времени
        и маскированный реквизит."""
        if outcome not in BANK_OUTCOMES:
            raise ValueError("недопустимый исход")
        self._exec("INSERT INTO bank_feedback (bank, key, kind, display, outcome, ts) VALUES (?,?,?,?,?,?) "
                   "ON CONFLICT(bank, key) DO UPDATE SET outcome=excluded.outcome, ts=excluded.ts",
                   (bank, key, kind, display, outcome, utcnow()[:10]))

    def bank_outcomes(self, key: str) -> dict[str, int]:
        rows = self._all("SELECT outcome, COUNT(*) AS n FROM bank_feedback WHERE key=? GROUP BY outcome", (key,))
        return {o: next((r["n"] for r in rows if r["outcome"] == o), 0) for o in BANK_OUTCOMES}

    def bank_feedback_list(self, limit: int = 200) -> list[dict[str, Any]]:
        """Для аналитика: реквизиты с исходами от банков, сверху подтверждённое мошенничество от нескольких банков."""
        return self._all(
            "SELECT f.kind, f.key, MAX(f.display) AS display, SUM(f.outcome='fraud_confirmed') AS fraud_confirmed, "
            "SUM(f.outcome='legit_client') AS legit_client, COUNT(DISTINCT f.bank) AS banks, MAX(f.ts) AS last, "
            "EXISTS(SELECT 1 FROM requisites r WHERE r.key=f.key) AS in_registry "
            "FROM bank_feedback f GROUP BY f.key ORDER BY fraud_confirmed DESC, banks DESC, last DESC LIMIT ?", (limit,))

    def report_count(self) -> int:
        row = self._one("SELECT COUNT(*) AS n FROM user_reports")
        return int(row["n"]) if row else 0

    # ---------- разведчик ----------
    def risky_channels(self, limit: int = 20) -> list[str]:
        """Каналы постов высокого риска: семена для разведчика (самые рискованные первыми)."""
        return [r["channel"] for r in self._all(
            "SELECT channel, MAX(score) AS s FROM posts WHERE level='high' AND channel IS NOT NULL "
            "GROUP BY channel ORDER BY s DESC, COUNT(*) DESC LIMIT ?", (limit,))]

    def scout_channel(self, username: str) -> dict[str, Any] | None:
        return self._one("SELECT * FROM scout_channels WHERE username=?", (username,))

    def scout_channels(self) -> list[dict[str, Any]]:
        return self._all("SELECT * FROM scout_channels ORDER BY risk DESC, username")

    def scout_save_channel(self, row: dict[str, Any]) -> None:
        """Записать результат проверки канала; first_seen сохраняется с первого раза."""
        cols = ("username", "title", "subscribers", "created_at", "risk", "level", "track", "posts_checked",
                "risky_posts", "status", "found_via", "found_from", "found_detail", "depth", "last_checked")
        values = [row.get(c) for c in cols]
        updates = ", ".join(f"{c}=excluded.{c}" for c in cols[1:] if not c.startswith("found_") and c != "depth")
        self._exec(
            f"INSERT INTO scout_channels ({', '.join(cols)}, first_seen) VALUES ({', '.join('?' * len(cols))}, ?) "
            f"ON CONFLICT(username) DO UPDATE SET {updates}",
            (*values, utcnow()),
        )

    def scout_add_edge(self, src: str, dst: str, via: str, detail: str = "") -> None:
        self._exec("INSERT OR IGNORE INTO scout_edges (src, dst, via, detail, first_seen) VALUES (?,?,?,?,?)",
                   (src, dst, via, detail, utcnow()))

    def scout_edges(self) -> list[dict[str, Any]]:
        return self._all("SELECT src, dst, via, detail, first_seen FROM scout_edges ORDER BY first_seen, src, dst")
