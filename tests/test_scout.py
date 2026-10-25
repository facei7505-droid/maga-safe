"""Агент-Разведчик: снежный ком на офлайн-фикстуре, приоритеты, лимиты, только чтение Telegram."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from pruf.pipeline import Pruf, Submission
from pruf.scout import __main__ as cli
from pruf.scout.models import Candidate, ChannelInfo, ScoutPost, SourceUnavailable
from pruf.scout.refs import channel_refs, normalize_username
from pruf.scout.scout import Scout, ScoutConfig, channel_risk, freshness_bonus
from pruf.scout.sources import BudgetExceeded, FixtureSource, Throttle, ThrottledSource
from pruf.scout.telegram import ReadOnlyClient, TelethonSource
from tests.helpers import make_settings

NOW = datetime(2026, 10, 25, 12, 0, tzinfo=timezone.utc)
SNOWBALL = ScoutConfig(keywords=())


@pytest.fixture
def pruf(tmp_path: Path, detector):
    p = Pruf(make_settings(tmp_path), detector=detector, ocr_enabled=False)
    yield p
    p.db.close()


def _run(pruf: Pruf, config: ScoutConfig = SNOWBALL, seeds=("iphone_razdacha_kz",), source=None) -> dict:
    return Scout(pruf, source or FixtureSource(), config, now=NOW).run(list(seeds))


# ---------- ссылки на каналы ----------
def test_channel_refs_find_links_and_mentions_but_skip_bots_invites_and_emails() -> None:
    text = ("Подпишись на @Priz_Dnya_KZ и t.me/kazino_vyvod_24, бот @casino_pay_bot, приглашение t.me/+AbCdEf, "
            "t.me/joinchat/xyz, почта info@mail.kz, https://t.me/s/slot_kings_kz")
    assert channel_refs(text) == [("kazino_vyvod_24", "link"), ("slot_kings_kz", "link"), ("priz_dnya_kz", "mention")]


@pytest.mark.parametrize("raw,expected", [("@Some_Channel", "some_channel"), ("https://t.me/abcde", "abcde"),
                                          ("t.me/joinchat", None), ("@abc", None), ("", None), (None, None)])
def test_normalize_username(raw, expected) -> None:
    assert normalize_username(raw) == expected


# ---------- снежный ком ----------
def test_one_complaint_unrolls_the_network(pruf: Pruf) -> None:
    report = _run(pruf)
    related = [r for r in report["risky_channels"] if r["via"] != "seed"]
    assert len(related) == 15
    phones = {s["value"] for s in report["shared_requisites"] if s["type"] == "phone"}
    assert phones == {"+77473185264", "+77054412019", "+77769023318", "+77016550742"}
    domains = {s["value"] for s in report["shared_requisites"] if s["type"] == "domain"}
    assert domains == {"joy-slots-kz.top"}
    assert report["stopped"] is None


def test_requisite_search_jumps_between_tracks(pruf: Pruf) -> None:
    """Номер из розыгрыша приводит к пирамиде, хотя ссылок между каналами нет."""
    report = _run(pruf)
    passive = next(r for r in report["risky_channels"] if r["username"] == "passive_dohod_kz")
    assert passive["via"] == "requisite" and passive["parent"] == "iphone_razdacha_kz" and passive["track"] == "pyramid"
    assert {"src": "iphone_razdacha_kz", "dst": "passive_dohod_kz", "via": "requisite", "detail": "+77473185264"} in report["edges"]


def test_clean_channel_is_checked_but_not_expanded(pruf: Pruf) -> None:
    report = _run(pruf, seeds=("shymkent_zhanalyktary",))
    assert report["clean_channels"] == ["shymkent_zhanalyktary"]
    assert report["risky_channels"] == []
    assert report["channels_checked"] == 1  # новости упоминают скам-канал, но разведчик туда не идёт


def test_keyword_search_finds_channels_and_filters_legit_giveaway(pruf: Pruf) -> None:
    report = _run(pruf, ScoutConfig(keywords=("розыгрыш iphone",)), seeds=())
    assert "recepty_s_lyubovyu" in report["clean_channels"]
    assert "iphone_razdacha_kz" in {r["username"] for r in report["risky_channels"]}


def test_scout_posts_go_to_registry_once(pruf: Pruf) -> None:
    _run(pruf)
    n = pruf.db.count_posts()
    post = pruf.db.find_post_by_external_id("tg:iphone_razdacha_kz/1")
    assert post["source"] == "scout" and post["channel"] == "@iphone_razdacha_kz"
    Scout(pruf, FixtureSource(), ScoutConfig(keywords=(), recheck_risky=timedelta(0)), now=NOW).run(["iphone_razdacha_kz"])
    assert pruf.db.count_posts() == n  # повторный обход не дублирует посты


def test_no_store_mode_writes_nothing_and_does_not_block_real_run(pruf: Pruf) -> None:
    report = _run(pruf, ScoutConfig(keywords=(), store=False))
    assert pruf.db.count_posts() == 0 and pruf.db.scout_channels() == [] and pruf.db.scout_edges() == []
    assert len(report["risky_channels"]) == 16
    assert len(_run(pruf)["risky_channels"]) == 16  # настоящий запуск следом не считает каналы проверенными


def test_channel_without_text_posts_is_not_marked_clean(pruf: Pruf) -> None:
    fixture = {"channels": {"empty_chan": {"title": "x", "posts": []}}}
    path = pruf.settings.data_dir / "empty.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")
    report = _run(pruf, seeds=("empty_chan",), source=FixtureSource(path))
    assert report["channels_checked"] == 0 and pruf.db.scout_channel("empty_chan") is None


def test_outage_during_enqueue_stops_run(pruf: Pruf) -> None:
    class Flaky(FixtureSource):
        def channel_info(self, username: str):
            if username != "iphone_razdacha_kz":
                raise SourceUnavailable("Telegram просит подождать 300 с")
            return super().channel_info(username)

    report = _run(pruf, source=Flaky())
    assert report["stopped"].startswith("источник недоступен") and report["channels_checked"] == 1


def test_failed_ingest_is_retried_without_piling_up_rows(pruf: Pruf) -> None:
    pid = pruf.db.create_post(source="scout", channel="@x", author=None, posted_at=None, text="t", external_id="tg:x/1")
    pruf.db.mark_post_failed(pid, "boom")
    ok = pruf.db.create_post(source="scout", channel="@x", author=None, posted_at=None, text="t", external_id="tg:x/1")
    pruf.db.update_post_analysis(ok, score=1, level="low", track=None, analysis={"score": 1}, ocr_text=None, transcript=None)
    assert pruf.db.find_post_by_external_id("tg:x/1")["id"] == ok


def test_scout_never_calls_llm(tmp_path: Path, detector, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    real = detector.detect
    monkeypatch.setattr(detector, "detect", lambda *a, **kw: calls.append(kw.get("allow_llm", True)) or real(*a, **kw))
    p = Pruf(make_settings(tmp_path), detector=detector, ocr_enabled=False)
    _run(p, ScoutConfig(keywords=(), max_channels=2))
    p.db.close()
    assert calls and not any(calls)


def test_recently_checked_channel_is_skipped_but_still_linked(pruf: Pruf) -> None:
    _run(pruf, ScoutConfig(keywords=(), max_channels=1))  # проверили только семя
    report = Scout(pruf, FixtureSource(), ScoutConfig(keywords=(), max_channels=3), now=NOW + timedelta(hours=1)).run(
        ["priz_dnya_kz"])
    assert "iphone_razdacha_kz" not in {r["username"] for r in report["risky_channels"]}
    assert any(e["dst"] == "iphone_razdacha_kz" for e in report["edges"])


def test_registry_links_connect_scout_finds_to_earlier_complaints(pruf: Pruf) -> None:
    text = "РОЗЫГРЫШ iPhone! Участие 2000 тг на Kaspi +7 747 318 52 64, осталось 5 мест, итоги в пятницу"
    pruf.ingest(Submission(text=text, channel="@aktobe_konkurs", source="seed"))
    report = _run(pruf, ScoutConfig(keywords=(), max_channels=1))
    assert {"src": "iphone_razdacha_kz", "dst": "aktobe_konkurs", "via": "requisite", "detail": "+77473185264"} in report["edges"]
    assert "@aktobe_konkurs" in pruf.db.risky_channels()


def test_channel_table_and_api_view(pruf: Pruf) -> None:
    _run(pruf, ScoutConfig(keywords=(), max_channels=3))
    rows = pruf.db.scout_channels()
    assert len(rows) == 3 and all(r["status"] == "risky" for r in rows)
    assert rows[0]["first_seen"] and rows[0]["last_checked"]
    passive = next(r for r in pruf.db.scout_channels() if r["username"] == "bonus_akciya_kz")
    assert (passive["found_via"], passive["found_from"]) == ("forward", "iphone_razdacha_kz")


# ---------- приоритеты и лимиты ----------
def test_channel_risk_uses_top_three_posts() -> None:
    assert channel_risk([90, 80, 70, 0, 0]) == 80.0
    assert channel_risk([]) == 0.0


def test_fresh_fast_growing_channel_gets_priority_bonus() -> None:
    fresh = ChannelInfo("a_chan", "A", subscribers=2000, subscribers_week_ago=1000, created_at="2026-10-20")
    old = ChannelInfo("b_chan", "B", subscribers=1000, subscribers_week_ago=1000, created_at="2019-01-01T00:00:00+00:00")
    assert freshness_bonus(fresh, None, NOW) == 30
    assert freshness_bonus(old, None, NOW) == 0
    assert freshness_bonus(ChannelInfo("c_chan", "C", subscribers=1200), {"subscribers": 1000}, NOW) == 10
    assert freshness_bonus(None, None, NOW) == 0
    assert freshness_bonus(ChannelInfo("d_chan", "D", created_at="не дата"), None, NOW) == 0


def test_direct_evidence_is_visited_before_mentions(pruf: Pruf) -> None:
    scout = Scout(pruf, FixtureSource(), SNOWBALL, now=NOW)
    scout.enqueue(Candidate("priz_dnya_kz", 1, "x_chan", "mention"))
    scout.enqueue(Candidate("passive_dohod_kz", 1, "x_chan", "requisite", "+77473185264"))
    first = scout._heap[0][2]
    assert first.username == "passive_dohod_kz"


def test_unknown_channels_and_bots_are_not_queued(pruf: Pruf) -> None:
    scout = Scout(pruf, FixtureSource(), SNOWBALL, now=NOW)
    scout.enqueue(Candidate("no_such_channel", 1, "x_chan", "mention"))
    scout.enqueue(Candidate("casino_pay_bot", 1, "x_chan", "mention"))
    scout.enqueue(Candidate("priz_dnya_kz", 9, "x_chan", "mention"))  # глубже лимита
    assert scout._heap == [] and scout.edges == set()


def test_max_channels_limit_stops_run(pruf: Pruf) -> None:
    report = _run(pruf, ScoutConfig(keywords=(), max_channels=4))
    assert report["channels_checked"] == 4
    assert "лимит 4 каналов" in report["stopped"]


def test_request_budget_stops_run_gracefully(pruf: Pruf) -> None:
    source = ThrottledSource(FixtureSource(), Throttle(0, max_requests=5))
    report = _run(pruf, source=source)
    assert report["stopped"].startswith("лимит 5 запросов")
    assert report["requests_used"] == 5


def test_throttle_spaces_requests() -> None:
    clock = [0.0]
    slept: list[float] = []

    def sleep(s: float) -> None:
        slept.append(s)
        clock[0] += s

    t = Throttle(1.5, 10, clock=lambda: clock[0], sleep=sleep)
    t.wait()
    clock[0] += 0.5
    t.wait()
    assert slept == [1.0]
    with pytest.raises(BudgetExceeded):
        Throttle(0, 0).wait()


def test_source_outage_stops_run_with_reason(pruf: Pruf) -> None:
    class Broken(FixtureSource):
        def recent_posts(self, username: str, limit: int):
            raise SourceUnavailable("Telegram просит подождать 300 с")

    report = _run(pruf, source=Broken())
    assert report["stopped"] == "источник недоступен: Telegram просит подождать 300 с"


def test_card_numbers_are_not_searched(pruf: Pruf) -> None:
    searched: list[str] = []

    class Spy(FixtureSource):
        def search_posts(self, query: str, limit: int):
            searched.append(query)
            return super().search_posts(query, limit)

    fixture = {"channels": {"card_scam_kz": {"title": "x", "posts": [
        {"id": 1, "text": "РОЗЫГРЫШ iPhone! Участие 2000 тг на карту 4111 1111 1111 1111, осталось 5 мест, итоги в пятницу"}]}}}
    path = pruf.settings.data_dir / "f.json"
    path.write_text(json.dumps(fixture, ensure_ascii=False), encoding="utf-8")
    _run(pruf, seeds=("card_scam_kz",), source=Spy(path))
    assert not any("4111" in q for q in searched)


# ---------- Telegram только на чтение ----------
class _FakeTelethon:
    def __init__(self):
        self.calls: list[str] = []

    def send_message(self, *a, **kw):  # pragma: no cover - не должен вызываться
        self.calls.append("send_message")

    def __call__(self, request):
        self.calls.append(type(request).__name__)
        return "ok"


def test_read_only_client_blocks_writes_before_reaching_telegram() -> None:
    fake = _FakeTelethon()
    client = ReadOnlyClient(fake)
    for method in ("send_message", "forward_messages", "send_file", "delete_messages", "edit_message"):
        with pytest.raises(PermissionError):
            getattr(client, method)
    JoinChannelRequest = type("JoinChannelRequest", (), {})
    SendMessageRequest = type("SendMessageRequest", (), {})
    for req in (JoinChannelRequest(), SendMessageRequest()):
        with pytest.raises(PermissionError):
            client(req)
    assert fake.calls == []
    SearchRequest = type("SearchRequest", (), {})
    assert client(SearchRequest()) == "ok"
    assert fake.calls == ["SearchRequest"]


def _channel(username="kazino_vyvod_24", cid=10):
    Channel = type("Channel", (), {})
    ch = Channel()
    ch.id, ch.username, ch.title, ch.broadcast, ch.megagroup = cid, username, "Казино", True, False
    ch.date = datetime(2026, 10, 5, tzinfo=timezone.utc)
    return ch


class _FakeTg:
    """Ответы в форме Telethon для TelethonSource (без сети)."""

    def __init__(self):
        self.requests: list[str] = []

    def get_entity(self, username):
        if username == "private_user":
            return type("User", (), {"username": "private_user"})()
        if username == "missing_chan":
            raise ValueError("No user has that username")
        return _channel(username)

    def iter_messages(self, entity, limit):
        fwd = SimpleNamespace(chat=SimpleNamespace(username="Slot_Kings_KZ"))
        return [SimpleNamespace(id=2, message="Поднял x500, каспи +7 776 902 33 18", date=NOW, forward=fwd),
                SimpleNamespace(id=1, message="", date=NOW, forward=None)][:limit]

    def __call__(self, request):
        name = type(request).__name__
        self.requests.append(name)
        if name == "GetFullChannelRequest":
            return SimpleNamespace(full_chat=SimpleNamespace(participants_count=15800))
        if name == "SearchRequest":
            return SimpleNamespace(chats=[_channel("kazino_vyvod_24"), SimpleNamespace(username="someone", broadcast=False)])
        if name == "SearchGlobalRequest":
            msg = SimpleNamespace(id=7, message="каспи +7 776 902 33 18", date=NOW, forward=None, peer_id=SimpleNamespace(channel_id=10))
            return SimpleNamespace(chats=[_channel("crash_aviator_kz", 10)], messages=[msg])
        raise AssertionError(name)


def test_telethon_source_maps_read_only_responses() -> None:
    pytest.importorskip("telethon")
    fake = _FakeTg()
    src = TelethonSource(fake)
    info = src.channel_info("kazino_vyvod_24")
    assert info.subscribers == 15800 and info.title == "Казино" and info.created_at.startswith("2026-10-05")
    posts = src.recent_posts("kazino_vyvod_24", 10)
    assert posts == [ScoutPost("kazino_vyvod_24", 2, "Поднял x500, каспи +7 776 902 33 18", NOW.isoformat(), "slot_kings_kz")]
    assert src.search_channels("казино", 10) == ["kazino_vyvod_24"]
    assert [p.channel for p in src.search_posts("+77769023318", 10)] == ["crash_aviator_kz"]
    assert src.channel_info("private_user") is None and src.channel_info("missing_chan") is None
    assert set(fake.requests) <= {"GetFullChannelRequest", "SearchRequest", "SearchGlobalRequest"}


def test_telethon_caches_entities_and_turns_rpc_errors_into_outage() -> None:
    errors = pytest.importorskip("telethon.errors")
    fake = _FakeTg()
    calls = []
    real = fake.get_entity
    fake.get_entity = lambda u: calls.append(u) or real(u)
    src = TelethonSource(fake)
    src.channel_info("kazino_vyvod_24")
    src.recent_posts("kazino_vyvod_24", 5)
    assert calls == ["kazino_vyvod_24"]  # ResolveUsername один раз на канал

    def private(_):
        raise errors.ChannelPrivateError(request=None)

    def server_down(_):
        raise errors.RPCError(request=None, message="INTERNAL", code=500)

    fake.get_entity = private
    assert src.channel_info("closed_chan") is None
    fake.get_entity = server_down
    with pytest.raises(SourceUnavailable):
        src.channel_info("other_chan")


def test_telethon_flood_wait_retries_once_then_stops() -> None:
    errors = pytest.importorskip("telethon.errors")
    slept: list[float] = []
    src = TelethonSource(_FakeTg(), sleep=slept.append)

    def flood(seconds):
        exc = errors.FloodWaitError(request=None, capture=seconds)
        return exc

    attempts = iter([flood(5), "ok"])

    def flaky():
        value = next(attempts)
        if isinstance(value, Exception):
            raise value
        return value

    assert src._call(flaky) == "ok" and slept == [6]
    with pytest.raises(SourceUnavailable):
        src._call(lambda: (_ for _ in ()).throw(flood(600)))


def test_telethon_from_env_requires_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("telethon")
    monkeypatch.delenv("TG_API_ID", raising=False)
    monkeypatch.delenv("TG_API_HASH", raising=False)
    with pytest.raises(RuntimeError, match="TG_API_ID"):
        TelethonSource.from_env()


# ---------- CLI ----------
def test_cli_demo_prints_summary_and_saves_report(env: Path, capsys: pytest.CaptureFixture) -> None:
    out = env / "report.json"
    assert cli.main(["--demo", "--no-keywords", "--out", str(out)]) == 0
    text = capsys.readouterr().out
    assert "Найдено связанных каналов с признаками схем: 15; общих номеров Kaspi: 4" in text
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["source"] == "fixture" and report["requests_used"] > 0
