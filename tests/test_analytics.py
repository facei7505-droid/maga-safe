"""Обзор аналитика: динамика по дням, каналы, ранние сигналы и маршрут /api/v1/overview."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pruf.analytics import daily_levels, surges, top_channels
from pruf.api.app import create_app
from pruf.pipeline import Pruf, Submission
from tests.helpers import KASPI_PHONE, LOTTERY_RU, make_settings


def _post(pid: int, channel: str, at: str, level: str = "high", track: str = "lottery", score: float = 90) -> dict:
    return {"id": pid, "channel": channel, "posted_at": at, "level": level, "track": track, "score": score}


def test_daily_levels_fills_gaps_between_days() -> None:
    # Arrange
    posts = [_post(1, "@a", "2026-10-01T10:00:00"), _post(2, "@a", "2026-10-03T10:00:00", level="low"),
             _post(3, "@b", None)]

    # Act
    days = daily_levels(posts)

    # Assert
    assert [d["date"] for d in days] == ["2026-10-01", "2026-10-02", "2026-10-03"]
    assert days[0]["high"] == 1 and days[1] == {"date": "2026-10-02", "high": 0, "medium": 0, "low": 0}
    assert days[2]["low"] == 1


def test_daily_levels_keeps_only_last_window_and_handles_empty_and_bad_dates() -> None:
    posts = [_post(i, "@a", f"2026-09-{i:02d}T00:00:00") for i in range(1, 31)] + [_post(99, "@a", "not-a-date")]
    assert len(daily_levels(posts, days=7)) == 7
    assert daily_levels([]) == []


def test_top_channels_ranks_by_risky_posts_and_skips_clean_channels() -> None:
    # Arrange
    posts = [_post(1, "@scam", "2026-10-01T00:00:00"), _post(2, "@scam", "2026-10-01T00:00:00", track="casino"),
             _post(3, "@mixed", "2026-10-01T00:00:00"), _post(4, "@mixed", "2026-10-01T00:00:00", level="low"),
             _post(5, "@clean", "2026-10-01T00:00:00", level="low"), _post(6, None, "2026-10-01T00:00:00")]

    # Act
    ranked = top_channels(posts)

    # Assert
    assert [c["channel"] for c in ranked] == ["@scam", "@mixed"]
    assert ranked[1]["risky"] == 1 and ranked[1]["total"] == 2
    assert set(ranked[0]["tracks"]) == {"lottery", "casino"}


def _req_rows(req_id: int, post_ids: list[int], display: str = "+77011112233") -> list[dict]:
    return [{"post_id": pid, "id": req_id, "kind": "phone", "key": f"phone:{display}", "display": display} for pid in post_ids]


def test_surge_found_when_requisite_spreads_to_three_channels_within_72h() -> None:
    # Arrange: номер за двое суток прошёл по трём каналам, четвёртый пост через неделю
    posts = [_post(1, "@a", "2026-10-01T09:00:00"), _post(2, "@b", "2026-10-02T09:00:00"),
             _post(3, "@c", "2026-10-03T08:00:00"), _post(4, "@d", "2026-10-10T08:00:00")]

    # Act
    found = surges(posts, _req_rows(7, [1, 2, 3, 4]), lambda pid: "C-1")

    # Assert
    assert len(found) == 1
    sg = found[0]
    assert sg["channels"] == ["@a", "@b", "@c"] and sg["posts"] == [1, 2, 3]
    assert sg["total_posts"] == 4 and sg["cases"] == ["C-1"]
    assert sg["start"].startswith("2026-10-01") and sg["end"].startswith("2026-10-03")


def test_no_surge_when_spread_is_slow_or_posts_are_low_risk() -> None:
    # Arrange: те же три канала, но по неделе между постами; и всплеск только из постов без признаков
    slow = [_post(1, "@a", "2026-10-01T00:00:00"), _post(2, "@b", "2026-10-08T00:00:00"), _post(3, "@c", "2026-10-15T00:00:00")]
    clean = [_post(i, f"@{i}", "2026-10-01T00:00:00", level="low") for i in range(1, 4)]

    # Act / Assert
    assert surges(slow, _req_rows(7, [1, 2, 3]), lambda pid: None) == []
    assert surges(clean, _req_rows(7, [1, 2, 3]), lambda pid: None) == []


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    settings = make_settings(tmp_path)
    pruf = Pruf(settings, ocr_enabled=False)
    text = LOTTERY_RU.format(phone=KASPI_PHONE)
    for i, ch in enumerate(["@almaty_news", "@astana_life", "@shymkent_today"]):
        pruf.ingest(Submission(text=text + f" #{i}", channel=ch, posted_at=f"2026-10-0{i + 1}T12:00:00+00:00"))
    with TestClient(create_app(settings, pruf=pruf), raise_server_exceptions=False) as c:
        yield c


def test_overview_endpoint_reports_surge_and_case_statuses(client: TestClient) -> None:
    # Act
    body = client.get("/api/v1/overview").json()

    # Assert
    assert body["success"] is True
    data = body["data"]
    assert data["tracks"] == {"lottery": 3}
    assert sum(data["case_statuses"].values()) == 1 and data["case_statuses"]["new"] == 1
    assert len(data["daily"]) == 3
    assert data["surges"][0]["requisite"] == "+77019998877"
    assert len(data["surges"][0]["channels"]) == 3 and data["surges"][0]["cases"]
