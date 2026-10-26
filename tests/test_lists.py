"""Серый, чёрный и «снят» список: решение аналитика по кейсу, лента банка, выгрузка CSV, расширение."""

from __future__ import annotations

import csv
import io
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pruf.api.app import create_app
from pruf.lists import apply_case_decision, export_ref, list_info, mask, review_due, to_csv
from pruf.pipeline import Pruf
from pruf.storage.db import Database
from tests.helpers import CASINO_RU, KASPI_PHONE, LOTTERY_RU, make_settings

ANALYST = "analyst-secret-token"
BANK = "bank-secret-token"
EXT = "extension-secret-token"
PHONE = "+77019998877"


@pytest.fixture(autouse=True)
def _single_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)


def _client(tmp_path: Path, **overrides) -> TestClient:
    settings = make_settings(tmp_path, **overrides)
    return TestClient(create_app(settings, pruf=Pruf(settings, ocr_enabled=False)), raise_server_exceptions=False)


@pytest.fixture
def dev(tmp_path: Path):
    with _client(tmp_path) as client:
        yield client


def _seed_case(client: TestClient, headers: dict | None = None) -> str:
    for text in (LOTTERY_RU.format(phone=KASPI_PHONE), CASINO_RU.format(phone=KASPI_PHONE)):
        client.post("/api/v1/analyze/text", json={"text": text}, headers=headers or {})
    cases = client.get("/api/v1/cases", headers=headers or {}).json()["data"]
    return next(c["key"] for c in cases if any(PHONE in r for r in c["requisites"]))


def _feed_row(client: TestClient, **params) -> dict:
    rows = client.get("/api/v1/bank/requisites", params=params).json()["data"]
    return next(r for r in rows if r["value"] == PHONE)


def _set(client: TestClient, key: str, status: str) -> dict:
    return client.patch(f"/api/v1/cases/{key}", json={"status": status}).json()["data"]


def _inspect(client: TestClient) -> dict:
    return client.post("/api/v1/inspect", json={"requisites": [KASPI_PHONE]}).json()["data"]


# ---------- правила списков ----------
def test_review_due_counts_three_working_days_skipping_weekend() -> None:
    assert review_due("2026-10-23T18:00:00+00:00") == "2026-10-28"  # пятница → среда
    assert review_due("2026-10-26T09:00:00+00:00") == "2026-10-29"  # понедельник → четверг


def test_grey_is_overdue_only_after_due_date() -> None:
    info = list_info(None, None, "2026-10-23T18:00:00+00:00", today=date(2026, 10, 29))
    assert info["list"] == "grey" and info["overdue"] is True and info["list_reason"] == "кейс ещё не проверен"
    assert list_info(None, None, "2026-10-23T18:00:00+00:00", today=date(2026, 10, 28))["overdue"] is False
    black = list_info("black", "N-1:confirmed,C-7:dismissed", "2026-10-23T18:00:00+00:00")
    assert black["review_due"] is None and "N-1 подтверждён" in black["list_reason"] and "C-7 отклонён" in black["list_reason"]


@pytest.mark.parametrize("kind,display,expected", [
    ("phone", "+77019998877", "+7******8877"),
    ("iban", "KZ86125KZT5004100100", "KZ**************0100"),
    ("card", "440043******1234", "440043******1234"),
    ("kaspi_link", "kaspi.kz/pay/shop123", "kaspi.kz/pay/sh***"),
])
def test_mask_hides_the_middle_of_numbers(kind: str, display: str, expected: str) -> None:
    assert mask(kind, display) == expected


def test_csv_escapes_formula_cells() -> None:
    out = to_csv([{"ref": "=HYPERLINK(1)", "value_masked": "+7701***8877", "reason": "@cmd"}])
    row = list(csv.reader(io.StringIO(out)))[1]
    assert row[0] == "'=HYPERLINK(1)" and row[2] == "'+7701***8877" and row[8] == "'@cmd"


def test_black_wins_over_cleared_and_decision_survives_case_key_change(tmp_path: Path) -> None:
    # Arrange: номер в двух кейсах; один подтверждён, другой отклонён. Ключи кейсов из прошлой сборки графа.
    db = Database(tmp_path / "x.db")
    post = db.create_post(source="t", channel="c", author=None, posted_at=None, text="t")
    db.update_post_analysis(post, score=80, level="high", track="lottery", analysis={}, ocr_text=None, transcript=None)
    db.link_requisite(post, "phone", "phone:" + PHONE, PHONE)

    # Act
    db.set_case_decision("OLD-2", ["phone:" + PHONE], "dismissed", "a")
    cleared = db.lookup_requisite("phone:" + PHONE)
    db.set_case_decision("OLD-1", ["phone:" + PHONE], "confirmed", "a")
    both = db.lookup_requisite("phone:" + PHONE)

    # Assert
    assert cleared["list"] == "cleared"
    assert both["list"] == "black" and set(both["decided"].split(",")) == {"OLD-1:confirmed", "OLD-2:dismissed"}
    assert [r["list"] for r in db.requisite_feed(None, "medium", 10, 0, "black")] == ["black"]
    assert db.requisite_feed(None, "medium", 10, 0, "grey") == []
    with pytest.raises(ValueError):
        db.set_case_decision("X", [], "maybe", "a")


# ---------- кейс → список ----------
def test_new_requisite_is_grey_with_review_due(dev: TestClient) -> None:
    _seed_case(dev)
    row = _feed_row(dev)
    assert row["list"] == "grey" and row["review_due"] and "проверить" in row["advice"] and "key" not in row
    assert dev.post("/api/v1/inspect", json={"requisites": [KASPI_PHONE]}).json()["data"]["requisites"][0]["list"] == "grey"


def test_confirming_case_blacklists_its_requisites_and_extension_shows_banner(dev: TestClient) -> None:
    # Arrange
    key = _seed_case(dev)
    assert dev.get(f"/api/v1/cases/{key}").json()["data"]["money_requisites"] >= 1

    # Act
    result = _set(dev, key, "confirmed")

    # Assert
    assert result["requisites_listed"] >= 1
    row = _feed_row(dev)
    assert row["list"] == "black" and row["review_due"] is None and "приостановить" in row["advice"] and key in row["list_reason"]
    verdict = _inspect(dev)
    assert verdict["requisites"][0]["list"] == "black" and verdict["show_banner"] is True
    assert "registry.black" in {r["id"] for r in verdict["reasons"]} and "registry.requisite" not in {r["id"] for r in verdict["reasons"]}
    assert dev.post("/api/v1/bank/check", json={"value": KASPI_PHONE}).json()["data"]["list"] == "black"
    assert [r["value"] for r in dev.get("/api/v1/bank/requisites", params={"list": "black"}).json()["data"]] == [PHONE]


def test_dismissing_case_clears_number_and_extension_stays_silent(dev: TestClient) -> None:
    key = _seed_case(dev)
    _set(dev, key, "dismissed")
    assert _feed_row(dev)["list"] == "cleared"
    checked = _inspect(dev)["requisites"][0]
    assert checked["found"] is False and checked["list"] is None
    assert dev.post("/api/v1/bank/check", json={"value": KASPI_PHONE}).json()["data"]["advice"].endswith("не блокировать")


def test_reopening_case_returns_number_to_grey(dev: TestClient) -> None:
    key = _seed_case(dev)
    _set(dev, key, "confirmed")
    _set(dev, key, "in_review")
    assert _feed_row(dev)["list"] == "grey"


def test_list_filter_is_validated(dev: TestClient) -> None:
    assert dev.get("/api/v1/bank/requisites", params={"list": "white"}).status_code == 422
    assert dev.get("/api/v1/bank/requisites.csv", params={"list": "white"}).status_code == 422


# ---------- выгрузка CSV ----------
def test_csv_export_has_masked_values_hmac_refs_and_no_raw_numbers(dev: TestClient) -> None:
    # Arrange
    key = _seed_case(dev)
    _set(dev, key, "confirmed")

    # Act
    res = dev.get("/api/v1/bank/requisites.csv")

    # Assert
    assert res.status_code == 200 and res.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(res.text)))
    assert list(rows[0]) == ["ref", "type", "value_masked", "list", "cases", "first_seen", "last_seen", "review_due", "reason"]
    row = next(r for r in rows if r["type"] == "phone")
    assert len(row["ref"]) == 64 and row["value_masked"] == "'+7******8877" and row["list"] == "black" and key in row["cases"]
    assert PHONE not in res.text and "phone:" not in res.text and res.headers["x-pruf-truncated"] == "0"


def test_exchange_ref_does_not_use_the_server_key_directly() -> None:
    import hmac
    server_key = b"k" * 32
    assert export_ref("phone:" + PHONE, server_key) != hmac.new(server_key, ("phone:" + PHONE).encode(), "sha256").hexdigest()


def _db_with_posts(tmp_path: Path) -> tuple[Database, int, int]:
    db = Database(tmp_path / "x.db")
    ids = []
    for level, phones in (("high", [PHONE]), ("low", [PHONE, "+77272500000"])):
        post = db.create_post(source="t", channel="c", author=None, posted_at=None, text="t")
        db.update_post_analysis(post, score=80 if level == "high" else 5, level=level, track=None, analysis={},
                                ocr_text=None, transcript=None)
        for ph in phones:
            db.link_requisite(post, "phone", "phone:" + ph, ph)
        ids.append(post)
    return db, ids[0], ids[1]


def test_context_posts_of_a_case_do_not_blacklist_their_numbers(tmp_path: Path) -> None:
    # Предупреждение низкого риска называет номер схемы и номер поддержки банка: в чёрный уходит только первый
    db, core, context = _db_with_posts(tmp_path)
    assert apply_case_decision(db, "C-1", [core, context], "confirmed", "a") == 1
    assert [r[0] for r in db._conn.execute("SELECT key FROM requisite_status")] == ["phone:" + PHONE]


def test_new_decision_replaces_decisions_of_merged_cases(tmp_path: Path) -> None:
    # C-5 был подтверждён, потом слился в C-3; аналитик отклоняет C-3 — старое решение C-5 не держит номер чёрным
    db, core, _ = _db_with_posts(tmp_path)
    apply_case_decision(db, "C-5", [core], "confirmed", "a", ["C-5"])
    apply_case_decision(db, "C-3", [core], "dismissed", "a", ["C-3"])
    assert db.lookup_requisite("phone:" + PHONE)["list"] == "cleared"
    apply_case_decision(db, "C-3", [core], "in_review", "a", ["C-3"])
    assert db.lookup_requisite("phone:" + PHONE)["decided"] is None


def test_csv_export_requires_bank_token(tmp_path: Path) -> None:
    with _client(tmp_path, dev_mode=False, analyst_token=f"alice:{ANALYST}", bank_tokens=(f"halyk:{BANK}",),
                 extension_tokens=(f"ext:{EXT}",)) as client:
        _seed_case(client, {"Authorization": f"Bearer {ANALYST}"})
        assert client.get("/api/v1/bank/requisites.csv").status_code == 401
        assert client.get("/api/v1/bank/requisites.csv", headers={"Authorization": f"Bearer {EXT}"}).status_code == 401
        assert client.get("/api/v1/bank/requisites.csv", headers={"Authorization": f"Bearer {ANALYST}"}).status_code == 401
        assert client.get("/api/v1/bank/requisites.csv", headers={"Authorization": f"Bearer {BANK}"}).status_code == 200


# ---------- доверие к жалобщику ----------
def _report(db: Database, reporter: str, phone: str, n: int = 0) -> None:
    db.add_report(reporter=reporter, platform="telegram", text_hash=f"{reporter}-{phone}-{n}", cues=["kaspi_transfer"],
                  domains=[], requisites=[("phone", "phone:" + phone, phone)])


def test_reports_from_proven_reporters_rank_above_many_new_ones(tmp_path: Path) -> None:
    # Arrange: двое жалобщиков раньше жаловались на два номера, которые стали чёрными
    db = Database(tmp_path / "x.db")
    for old in ("+77000000001", "+77000000002"):
        db.set_case_decision("C-" + old[-1], ["phone:" + old], "confirmed", "a")
        for who in ("proven-a", "proven-b"):
            _report(db, who, old)
    for who in ("proven-a", "proven-b"):
        _report(db, who, "+77011111111")
    for i in range(10):
        _report(db, f"new-{i}", "+77022222222")

    # Act
    rows = {r["display"]: r for r in db.reported_requisites()}
    order = [r["display"] for r in db.reported_requisites() if r["display"] in ("+77011111111", "+77022222222")]

    # Assert
    assert order == ["+77011111111", "+77022222222"]
    assert rows["+77011111111"]["trusted_reporters"] == 2 and rows["+77011111111"]["trust"] == pytest.approx(0.75)
    assert rows["+77022222222"]["trusted_reporters"] == 0 and rows["+77022222222"]["trust"] == pytest.approx(0.5)


def test_dismissed_numbers_lower_reporter_trust(tmp_path: Path) -> None:
    db = Database(tmp_path / "x.db")
    db.set_case_decision("C-1", ["phone:+77000000001"], "dismissed", "a")
    _report(db, "slanderer", "+77000000001")
    _report(db, "slanderer", "+77033333333")
    row = next(r for r in db.reported_requisites() if r["display"] == "+77033333333")
    assert row["trust"] == pytest.approx(1 / 3) and row["trusted_reporters"] == 0


def test_reports_api_exposes_trust_and_public_verdict_ignores_reports(dev: TestClient) -> None:
    before = _inspect(dev)
    for i in range(5):
        dev.post("/api/v1/reports", json={"requisites": [KASPI_PHONE], "text_hash": f"{i:064x}", "install_id": f"install-{i}",
                                          "cues": ["kaspi_transfer"]})
    row = dev.get("/api/v1/reports").json()["data"][0]
    assert row["trusted_reporters"] == 0 and row["trust"] == 0.5 and row["reporters"] == 5
    assert _inspect(dev)["score"] == before["score"]


HONEST = ("🎁 РОЗЫГРЫШ от магазина «Дала Текстиль»! Разыгрываем 3 сертификата по 20 000 ₸. Условия: подписка и репост. "
          "Итоги 5 ноября в прямом эфире. Доставка приза бесплатно. Вопросы: +7 702 640 18 33")


def _requisite_signals(result: dict) -> list[str]:
    return [e["feature_id"] for e in result["analysis"]["evidence"] if e["feature_id"].startswith("graph.requisite.")]


def test_dismissed_case_stops_flagging_its_number_until_new_risky_posts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange: честный розыгрыш получил средний риск, его номер засвечен самим этим постом
    core = Pruf(make_settings(tmp_path), ocr_enabled=False)
    honest = core.ingest(_sub(HONEST), allow_llm=False)
    assert honest["analysis"]["level"] in ("medium", "high")
    assert _requisite_signals(core.check(HONEST, public=True)) == ["graph.requisite.phone"]

    # Act: аналитик отклонил кейс
    apply_case_decision(core.db, "C-1", [honest["post_id"]], "dismissed", "a", ["C-1"])
    after_dismiss = core.check(HONEST, public=True)

    # ...а позже тот же номер появился в новом скам-посте
    monkeypatch.setattr("pruf.storage.db.utcnow", lambda: "2999-01-01T00:00:00+00:00")
    core.ingest(_sub(LOTTERY_RU.format(phone="+7 702 640 18 33")), allow_llm=False)
    after_new_scam = core.check(HONEST, public=True)

    # Assert
    assert _requisite_signals(after_dismiss) == []
    assert _requisite_signals(after_new_scam) == ["graph.requisite.phone"]
    core.db.close()


def _sub(text: str):
    from pruf.pipeline import Submission

    return Submission(text=text, source="test", channel="@shop")
