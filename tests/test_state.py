"""Решения людей переживают перезапуск сервера: снимок в файл или Postgres и восстановление при старте."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pruf.api.app import create_app
from pruf.pipeline import Pruf, Submission
from pruf.storage.state import HUMAN_TABLES, FileBackend, StateKeeper, backend_for, dump, restore
from tests.helpers import KASPI_PHONE, LOTTERY_RU, make_settings

BANK = "bank-secret-token-" + "b" * 16
BANK_H = {"Authorization": f"Bearer {BANK}"}


@pytest.fixture(autouse=True)
def _single_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)


def _server(data: Path, state_url: str) -> TestClient:
    """Новый «контейнер»: своя пустая база с тем же постом (как демо после пробуждения), общее хранилище состояния."""
    settings = make_settings(data, state_url=state_url, bank_tokens=(f"halyk:{BANK}",))
    core = Pruf(settings, ocr_enabled=False)
    core.ingest(Submission(text=LOTTERY_RU.format(phone=KASPI_PHONE), source="seed", channel="@a"), allow_llm=False)
    return TestClient(create_app(settings, pruf=core))


def _decide(client: TestClient) -> str:
    key = client.get("/api/v1/cases").json()["data"][0]["key"]
    assert client.patch(f"/api/v1/cases/{key}", json={"status": "confirmed", "note": "проверено"}).status_code == 200
    client.post("/api/v1/bank/feedback", json={"value": KASPI_PHONE, "outcome": "fraud_confirmed"}, headers=BANK_H)
    return key


def _check_restored(client: TestClient, key: str) -> None:
    case = client.get(f"/api/v1/cases/{key}").json()["data"]
    assert case["status"]["status"] == "confirmed"
    check = client.post("/api/v1/bank/check", json={"value": KASPI_PHONE}, headers=BANK_H).json()["data"]
    assert check["list"] == "black" and check["bank_outcomes"]["fraud_confirmed"] == 1


def test_decisions_survive_a_restart_through_a_file(tmp_path: Path) -> None:
    # Arrange
    url = f"file:{tmp_path / 'disk' / 'state.json'}"
    with _server(tmp_path / "first", url) as client:
        key = _decide(client)
    # Act: сервер «уснул», база пропала, новый запуск
    with _server(tmp_path / "second", url) as client:
        # Assert
        _check_restored(client, key)
        assert client.get("/api/v1/stats").json()["data"]["state"]["backend"] == "file"


def test_unreadable_store_never_overwrites_the_snapshot(tmp_path: Path) -> None:
    # Arrange: снимок есть, но при старте хранилище недоступно
    class Flaky(FileBackend):
        def load(self):
            raise ConnectionError("db down")

    target = tmp_path / "state.json"
    target.write_text('{"version": 1, "tables": {"case_status": [{"case_key": "C-1"}]}}', encoding="utf-8")
    core = Pruf(make_settings(tmp_path), ocr_enabled=False)
    keeper = StateKeeper(core.db, Flaky(target), delay=0)

    # Act
    keeper.restore()
    core.db.set_case_status("C-9", "new", None, "a")
    saved = keeper.save_now()
    keeper.close()

    # Assert: демо-состояние не затёрло снимок, ошибка видна
    assert not saved and "C-1" in target.read_text(encoding="utf-8")
    assert keeper.info()["saving"] is False and "db down" in keeper.info()["error"]
    core.db.close()


def test_changes_are_saved_after_a_short_delay(tmp_path: Path) -> None:
    core = Pruf(make_settings(tmp_path), ocr_enabled=False)
    backend = FileBackend(tmp_path / "state.json")
    keeper = StateKeeper(core.db, backend, delay=0.05)
    keeper.restore()
    core.db.on_change = keeper.changed
    core.db.set_case_status("C-3", "in_review", None, "a")
    core.db.set_case_status("C-4", "dismissed", None, "a")
    import time
    for _ in range(50):
        if keeper.saves:
            break
        time.sleep(0.02)
    assert keeper.saves == 1  # два клика — один снимок
    assert {r["case_key"] for r in backend.load()["tables"]["case_status"]} == {"C-3", "C-4"}
    keeper.close()
    core.db.close()


def test_restore_replaces_tables_and_ignores_unknown_columns(tmp_path: Path) -> None:
    core = Pruf(make_settings(tmp_path), ocr_enabled=False)
    core.db.set_case_status("C-old", "new", None, "a")
    snap = dump(core.db)
    snap["tables"]["case_status"] = [{"case_key": "C-1", "status": "confirmed", "note": None, "updated_at": "2026-10-01",
                                      "updated_by": "a", "column_from_the_future": 1}]
    counts = restore(core.db, snap)
    assert counts["case_status"] == 1 and set(counts) == set(HUMAN_TABLES)
    assert list(core.db.case_statuses()) == ["C-1"]
    core.db.close()


def test_bad_state_url_is_rejected() -> None:
    with pytest.raises(ValueError):
        backend_for("redis://x")
    assert backend_for("") is None


@pytest.mark.skipif(not os.environ.get("PRUF_TEST_POSTGRES_URL"), reason="нужен PRUF_TEST_POSTGRES_URL")
def test_decisions_survive_a_restart_through_postgres(tmp_path: Path) -> None:
    import psycopg

    url = os.environ["PRUF_TEST_POSTGRES_URL"]
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS pruf_state")
    with _server(tmp_path / "first", url) as client:
        key = _decide(client)
    with _server(tmp_path / "second", url) as client:
        _check_restored(client, key)
        assert client.get("/api/v1/stats").json()["data"]["state"]["backend"] == "postgres"
