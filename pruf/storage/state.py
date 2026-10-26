"""Сохранение того, что делают люди, между перезапусками сервера.

На бесплатном Render нет диска: при каждом пробуждении база создаётся заново, и вместе с демо пропадали бы
решения аналитика, жалобы, отметки из бота и исходы от банков, а с ними и дообучение на решениях.
Посты и реестр пересоздаются (демо), а таблицы людей сохраняются снимком во внешнее хранилище:
Postgres (у Render есть бесплатный) или файл на постоянном диске. PRUF_STATE_URL=postgresql://… или file:/путь.

Снимок пишется через несколько секунд после изменения (изменения редкие, это действия людей) и при остановке
сервера; при старте снимок заменяет эти таблицы целиком. Таблиц немного и они маленькие, поэтому снимок — один
JSON, без миграций схемы: при восстановлении берутся только столбцы, которые есть в текущей базе.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Protocol

from pruf.storage.db import Database

log = logging.getLogger(__name__)
# Порядок важен: report_requisites ссылается на user_reports
HUMAN_TABLES = ("case_status", "requisite_status", "user_reports", "report_requisites", "bot_feedback",
                "bot_feature_shown", "bank_feedback", "audit_log")
SAVE_DELAY = 5.0  # секунд после изменения: несколько кликов аналитика подряд дают один снимок
SNAPSHOT_VERSION = 1


class Backend(Protocol):
    name: str

    def load(self) -> dict[str, Any] | None: ...
    def save(self, snapshot: dict[str, Any]) -> None: ...


class FileBackend:
    name = "file"

    def __init__(self, path: Path):
        self.path = path

    def load(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, snapshot: dict[str, Any]) -> None:
        # запись через временный файл: обрыв посреди записи не оставит половину снимка
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".state-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False)
        os.replace(tmp, self.path)


class PostgresBackend:
    """Одна строка в таблице pruf_state: снимок JSONB. psycopg импортируется, только если задан Postgres."""
    name = "postgres"

    def __init__(self, url: str):
        import psycopg

        self._psycopg = psycopg
        self._url = url
        with self._connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS pruf_state (id SMALLINT PRIMARY KEY, data JSONB NOT NULL, "
                         "saved_at TIMESTAMPTZ NOT NULL DEFAULT now())")

    def _connect(self):
        return self._psycopg.connect(self._url, connect_timeout=10, autocommit=True)

    def load(self) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT data FROM pruf_state WHERE id=1").fetchone()
        return row[0] if row else None

    def save(self, snapshot: dict[str, Any]) -> None:
        from psycopg.types.json import Jsonb

        with self._connect() as conn:
            conn.execute("INSERT INTO pruf_state (id, data, saved_at) VALUES (1, %s, now()) "
                         "ON CONFLICT (id) DO UPDATE SET data=excluded.data, saved_at=excluded.saved_at", (Jsonb(snapshot),))


def backend_for(url: str) -> Backend | None:
    if not url:
        return None
    if url.startswith(("postgres://", "postgresql://")):
        return PostgresBackend(url)
    if url.startswith("file:"):
        return FileBackend(Path(url[len("file:"):]))
    raise ValueError("PRUF_STATE_URL: нужен postgresql://… или file:/путь")


def dump(db: Database) -> dict[str, Any]:
    return {"version": SNAPSHOT_VERSION, "tables": {t: db._all(f"SELECT * FROM {t}") for t in HUMAN_TABLES}}


def restore(db: Database, snapshot: dict[str, Any]) -> dict[str, int]:
    """Заменить таблицы людей содержимым снимка в одной транзакции. Возвращает число строк по таблицам."""
    tables = snapshot.get("tables") or {}
    counts: dict[str, int] = {}
    with db._lock, db._conn:
        for table in reversed(HUMAN_TABLES):
            db._conn.execute(f"DELETE FROM {table}")
        for table in HUMAN_TABLES:
            rows = tables.get(table) or []
            cols = {r[1] for r in db._conn.execute(f"PRAGMA table_info({table})")}
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError(f"{table}: строка снимка не объект")
                keep = [c for c in row if c in cols]
                if not keep:
                    continue
                db._conn.execute(f"INSERT OR REPLACE INTO {table} ({', '.join(keep)}) VALUES ({', '.join('?' * len(keep))})",
                                 [row[c] for c in keep])
            counts[table] = len(rows)
    return counts


class StateKeeper:
    """Следит за изменениями базы и сохраняет снимок с задержкой; при остановке — сразу."""

    def __init__(self, db: Database, backend: Backend, delay: float = SAVE_DELAY):
        self._db = db
        self._backend = backend
        self._delay = delay
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()
        self.saves = 0
        self.last_error: str | None = None
        # Пока снимок не прочитан, писать нельзя: если хранилище при старте недоступно, сервер поднимется
        # на демо-данных, и первое же сохранение затёрло бы настоящие решения людей демо-состоянием.
        self._can_save = False

    def restore(self) -> dict[str, int] | None:
        try:
            snapshot = self._backend.load()
        except Exception as exc:  # noqa: BLE001
            self.last_error = f"снимок не прочитан, сохранение выключено: {type(exc).__name__}: {exc}"[:200]
            log.error("%s (%s)", self.last_error, self._backend.name)
            return None
        if not snapshot:
            self._can_save = True
            log.info("снимка состояния нет (%s): начинаем с демо-данных", self._backend.name)
            return None
        try:
            counts = restore(self._db, snapshot)
        except Exception as exc:  # noqa: BLE001 — битый снимок не должен ронять сервер; сам снимок не затираем
            self.last_error = f"снимок не восстановлен, сохранение выключено: {type(exc).__name__}: {exc}"[:200]
            log.error("%s (%s)", self.last_error, self._backend.name)
            return None
        self._can_save = True
        log.info("состояние восстановлено из %s: %s", self._backend.name, counts)
        return counts

    def changed(self) -> None:
        with self._lock:
            if self._timer is None:
                self._timer = threading.Timer(self._delay, self._flush)
                self._timer.daemon = True
                self._timer.start()

    def _flush(self) -> None:
        with self._lock:
            self._timer = None
        self.save_now()

    def save_now(self) -> bool:
        if not self._can_save:
            return False
        try:
            self._backend.save(dump(self._db))
        except Exception as exc:  # noqa: BLE001 — недоступное хранилище не должно ронять сервер; ошибка видна в stats
            self.last_error = f"{type(exc).__name__}: {exc}"[:200]
            log.error("снимок состояния не сохранён (%s): %s", self._backend.name, self.last_error)
            return False
        self.saves += 1
        self.last_error = None
        return True

    def close(self) -> None:
        with self._lock:
            pending, self._timer = self._timer, None
        if pending:
            pending.cancel()
        self.save_now()

    def info(self) -> dict[str, Any]:
        return {"backend": self._backend.name, "saves": self.saves, "error": self.last_error, "saving": self._can_save}
