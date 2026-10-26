"""Разогрев демо перед питчем (scripts/warmup.py): ждёт демо-данные и ловит пустые разделы, без сети."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from pruf.api.app import create_app
from pruf.pipeline import Pruf
from tests.helpers import make_settings

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import warmup  # noqa: E402


def test_wait_ready_retries_until_hero_case_exists() -> None:
    # Arrange: сервер спит, потом отвечает без данных, потом готов
    answers = iter([httpx.ConnectError("sleeping"), 404, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        a = next(answers)
        if isinstance(a, Exception):
            raise a
        return httpx.Response(a, json={})

    client = httpx.Client(base_url="http://pruf", transport=httpx.MockTransport(handler))
    logs: list[str] = []

    # Act
    ready = warmup.wait_ready(client, timeout=5, poll=0, log=logs.append)

    # Assert
    assert ready and len(logs) == 2


def test_wait_ready_gives_up() -> None:
    client = httpx.Client(base_url="http://pruf", transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    assert not warmup.wait_ready(client, timeout=0.05, poll=0.01, log=lambda _: None)


def test_demo_path_on_empty_server_names_what_is_missing(tmp_path: Path, monkeypatch) -> None:
    # Arrange: настоящий API без демо-данных
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    settings = make_settings(tmp_path)
    with TestClient(create_app(settings, pruf=Pruf(settings, ocr_enabled=False))) as client:
        # Act
        steps = {s.name: s for s in warmup.demo_path(client)}

    # Assert: проверка поста работает и без данных, а пустые разделы демо названы
    assert steps["Проверка поста"].ok and "риск" in steps["Проверка поста"].note
    assert not steps["Очередь кейсов"].ok and steps["Очередь кейсов"].note == "пусто: кейсов"
    assert not steps["Разведка"].ok and "pruf.scout" in steps["Разведка"].note
    assert not steps[f"Кейс {warmup.HERO_CASE}"].ok
