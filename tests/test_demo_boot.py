"""Демо при первом старте: сервер отвечает сразу, заливка идёт в фоне, решения людей восстанавливаются поверх неё."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pruf import demo_boot
from pruf.api.app import create_app
from pruf.graph.builder import CaseGraph, artifact_timeline
from pruf.pipeline import Pruf, Submission
from tests.helpers import KASPI_PHONE, LOTTERY_RU, make_settings

READY_TIMEOUT = 10.0


@pytest.fixture(autouse=True)
def _single_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)


def _wait_ready(client: TestClient) -> None:
    end = time.monotonic() + READY_TIMEOUT
    while time.monotonic() < end:
        if client.get("/api/v1/health").status_code == 200:
            return
        time.sleep(0.05)
    raise AssertionError("демо не поднялось")


def test_site_answers_while_demo_is_seeding_and_restores_decisions_after(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange: заливка «долгая», в хранилище есть решение аналитика с прошлого запуска
    release = threading.Event()

    def slow_seed(p: Pruf) -> None:
        release.wait(READY_TIMEOUT)
        p.ingest(Submission(text=LOTTERY_RU.format(phone=KASPI_PHONE), source="seed", channel="@a"), allow_llm=False)

    monkeypatch.setattr(demo_boot, "seed", slow_seed)
    snapshot = tmp_path / "state.json"
    snapshot.write_text('{"version": 1, "tables": {"case_status": [{"case_key": "C-1", "status": "confirmed", '
                        '"note": null, "updated_at": "2026-10-01", "updated_by": "a"}]}}', encoding="utf-8")
    settings = make_settings(tmp_path, seed_demo=True, state_url=f"file:{snapshot}")

    with TestClient(create_app(settings)) as client:
        # Act + Assert: пока идёт заливка — понятная страница и 503, а не ошибка соединения
        health = client.get("/api/v1/health")
        assert health.status_code == 503 and health.json()["data"]["status"] == "seeding"
        assert health.headers["retry-after"] == "10"
        page = client.get("/")
        assert page.status_code == 503 and "демо загружается" in page.text and 'http-equiv="refresh"' in page.text
        assert client.get("/api/v1/cases").status_code == 503
        assert client.get("/static/app.js").status_code == 200

        release.set()
        _wait_ready(client)

        stats = client.get("/api/v1/stats").json()["data"]
        assert stats["posts"] == 1 and stats["demo_posts"] == 1 and stats["demo_error"] is None
        assert stats["state"]["backend"] == "file"
    # решение из снимка применено после заливки и не затёрто ею
    restored = Pruf(make_settings(tmp_path), ocr_enabled=False)
    try:
        assert restored.db.case_statuses()["C-1"]["status"] == "confirmed"
    finally:
        restored.db.close()


def test_failed_seed_still_brings_the_server_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken_seed(_p: Pruf) -> None:
        raise RuntimeError("нет синтетики")

    monkeypatch.setattr(demo_boot, "seed", broken_seed)
    with TestClient(create_app(make_settings(tmp_path, seed_demo=True))) as client:
        _wait_ready(client)
        stats = client.get("/api/v1/stats").json()["data"]
        assert stats["posts"] == 0 and "не созданы" in stats["demo_error"]


def test_existing_data_is_not_reseeded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    monkeypatch.setattr(demo_boot, "seed", lambda p: calls.append(1))
    settings = make_settings(tmp_path, seed_demo=True)
    core = Pruf(settings, ocr_enabled=False)
    core.ingest(Submission(text=LOTTERY_RU.format(phone=KASPI_PHONE), source="api"), allow_llm=False)

    with TestClient(create_app(settings, pruf=core)) as client:
        assert client.get("/api/v1/health").status_code == 200
    assert calls == []


def test_real_demo_seed_runs_inside_the_server_process(tmp_path: Path) -> None:
    # Arrange: тот же Pruf, что у сервера, — посты сразу попадают в его индексы
    p = Pruf(make_settings(tmp_path), ocr_enabled=False)
    try:
        # Act
        demo_boot.seed(p)

        # Assert: кейс-герой C-211 собирается и без OCR (так на бесплатном Render): похожие чеки фона к нему не липнут
        hero = {r["id"] for r in p.db._all("SELECT id FROM posts WHERE external_id LIKE 'hero%'")}
        graph = CaseGraph(p.db)
        graph.ensure(p.version)
        case = next(c for c in graph.cases() if c.key == "C-211")
        sources = {pid: p.db._one("SELECT source FROM posts WHERE id=?", (pid,))["source"] for pid in case.post_ids}
        # в кейсе 37 постов героя и каналы, найденные разведчиком по номеру оператора, но не фоновые кампании
        assert hero <= set(case.post_ids) and len(hero) == 37
        assert {pid for pid, src in sources.items() if src == "seed"} == hero
        assert artifact_timeline(p.db, p.db.artifacts_for_post(min(hero))[0]["id"])["appearances"] >= 30
        assert p.db.scout_last_run() is not None
    finally:
        p.db.close()
