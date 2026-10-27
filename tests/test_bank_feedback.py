"""Обратная связь банков: исход по реквизиту, видимость для аналитика и для других банков, только по токену банка."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pruf.api.app import create_app
from pruf.pipeline import Pruf, Submission
from tests.helpers import KASPI_PHONE, LOTTERY_RU, make_settings

ANALYST = "analyst-secret-token-" + "a" * 16
HALYK = "halyk-secret-token-" + "h" * 16
KASPI = "kaspi-secret-token-" + "k" * 16
H = {"Authorization": f"Bearer {HALYK}"}
K = {"Authorization": f"Bearer {KASPI}"}
A = {"Authorization": f"Bearer {ANALYST}"}


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    settings = make_settings(tmp_path, dev_mode=False, analyst_token=f"alice:{ANALYST}",
                             bank_tokens=(f"halyk:{HALYK}", f"kaspi:{KASPI}"))
    core = Pruf(settings, ocr_enabled=False)
    core.ingest(Submission(text=LOTTERY_RU.format(phone=KASPI_PHONE), source="t", channel="@a"), allow_llm=False)
    with TestClient(create_app(settings, pruf=core)) as c:
        yield c


def test_banks_report_outcomes_and_other_banks_see_counts(client: TestClient) -> None:
    # Act: два банка подтвердили мошенничество, один из них потом передумал бы — последнее мнение побеждает
    assert client.post("/api/v1/bank/feedback", json={"value": KASPI_PHONE, "outcome": "legit_client"}, headers=H).status_code == 200
    client.post("/api/v1/bank/feedback", json={"value": KASPI_PHONE, "outcome": "fraud_confirmed"}, headers=H)
    client.post("/api/v1/bank/feedback", json={"value": KASPI_PHONE, "outcome": "fraud_confirmed"}, headers=K)
    check = client.post("/api/v1/bank/check", json={"value": KASPI_PHONE}, headers=H).json()["data"]
    listed = client.get("/api/v1/bank/feedback", headers=A).json()["data"]

    # Assert
    assert check["bank_outcomes"] == {"fraud_confirmed": 2, "legit_client": 0}
    assert len(listed) == 1 and listed[0]["fraud_confirmed"] == 2 and listed[0]["banks"] == 2 and listed[0]["in_registry"]
    assert "*" in listed[0]["value"]  # номер маскирован


def test_unknown_number_feedback_is_kept_and_visible_in_check(client: TestClient) -> None:
    client.post("/api/v1/bank/feedback", json={"value": "+7 701 222 33 44", "outcome": "fraud_confirmed"}, headers=K)
    check = client.post("/api/v1/bank/check", json={"value": "87012223344"}, headers=H).json()["data"]
    assert check["found"] is False and check["bank_outcomes"]["fraud_confirmed"] == 1


def test_feedback_needs_a_bank_token_and_valid_input(client: TestClient) -> None:
    body = {"value": KASPI_PHONE, "outcome": "fraud_confirmed"}
    assert client.post("/api/v1/bank/feedback", json=body).status_code == 401
    assert client.post("/api/v1/bank/feedback", json=body, headers=A).status_code == 401  # аналитик не банк
    assert client.post("/api/v1/bank/feedback", json={**body, "outcome": "maybe"}, headers=H).status_code in (400, 422)
    assert client.post("/api/v1/bank/feedback", json={**body, "value": "hello world"}, headers=H).status_code == 400
    assert client.get("/api/v1/bank/feedback", headers=H).status_code == 401  # список — только аналитику
