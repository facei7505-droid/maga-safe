"""Источник t.me/s без аккаунта: разбор страниц, листание назад, сборщик реальных постов."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from pruf.scout import __main__ as cli
from pruf.scout.models import SourceUnavailable
from pruf.scout.public_web import PublicWebSource, parse_channel, parse_page, parse_subscribers

FIXTURES = Path(__file__).parent / "fixtures"
PAGE1 = (FIXTURES / "tme_s_page1.html").read_text(encoding="utf-8")
PAGE0 = (FIXTURES / "tme_s_page0.html").read_text(encoding="utf-8")
PRIVATE = "<html><body><div class='tgme_page'>If you have Telegram, you can contact</div></body></html>"


def fake_fetch(pages: dict[str, str], log: list[str] | None = None):
    def fetch(url: str) -> str:
        if log is not None:
            log.append(url)
        return pages[url]
    return fetch


def test_parse_page_extracts_text_dates_forwards_media_and_prev():
    posts, media, before = parse_page(PAGE1)
    assert [p.message_id for p in posts] == [101, 102, 103]
    first, second, photo_only = posts
    assert first.channel == "prizy_kz"
    assert "РОЗЫГРЫШ iPhone!\nУчастие 2 000 ₸ на Kaspi +7 747 318 52 64" in first.text
    assert "https://t.me/bonus_mirror_kz" in first.text  # адрес ссылки дописан: разведчик пойдёт по нему
    assert first.posted_at == "2026-10-20T09:15:00+00:00"
    assert second.forwarded_from == "kazino_win"
    assert "«без проигрыша»" in second.text and "вложенный" in second.text and second.text.endswith("конец")
    assert second.text.count("https://bit.ly/abc") == 1  # видимую ссылку не дублируем
    assert photo_only.text == ""
    assert media == {101: True, 102: False, 103: True}
    assert before == 101


def test_parse_channel_title_and_subscribers():
    info = parse_channel(PAGE1, "prizy_kz")
    assert info.title == "Призы KZ & бонусы" and info.subscribers == 12_300
    assert parse_channel(PRIVATE, "closed") is None


@pytest.mark.parametrize("raw,expected", [("12.3K", 12_300), ("1.2M", 1_200_000), ("845", 845), ("1 204", 1204), ("n/a", None)])
def test_parse_subscribers(raw, expected):
    assert parse_subscribers(raw) == expected


def test_recent_posts_pages_back_skips_empty_and_reuses_first_page():
    log: list[str] = []
    src = PublicWebSource(fetch=fake_fetch({"https://t.me/s/prizy_kz": PAGE1,
                                            "https://t.me/s/prizy_kz?before=101": PAGE0}, log))
    assert src.channel_info("prizy_kz").title
    posts = src.recent_posts("prizy_kz", 5)
    assert [p.message_id for p in posts] == [102, 101, 99]  # новые первыми, пост без текста пропущен
    assert log == ["https://t.me/s/prizy_kz", "https://t.me/s/prizy_kz?before=101"]  # первая страница не скачана дважды


def test_recent_posts_stops_at_limit_and_page_cap():
    log: list[str] = []
    src = PublicWebSource(fetch=fake_fetch({"https://t.me/s/prizy_kz": PAGE1}, log), max_pages=1)
    assert len(src.recent_posts("prizy_kz", 2)) == 2
    assert len(log) == 1


def test_network_errors_become_source_unavailable_and_search_is_empty():
    def broken(url: str) -> str:
        raise TimeoutError("timeout")
    src = PublicWebSource(fetch=broken)
    with pytest.raises(SourceUnavailable):
        src.recent_posts("prizy_kz", 5)
    assert src.search_channels("розыгрыш", 5) == [] and src.search_posts("kaspi", 5) == []


def test_scout_cli_accepts_web_source():
    args = cli.build_parser().parse_args(["--web", "--seed", "@prizy_kz"])
    assert args.web and args.seed == ["@prizy_kz"]


def test_collector_writes_rows_and_summary(tmp_path, monkeypatch):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import collect_public

    channels = tmp_path / "channels.txt"
    channels.write_text("# список\n@prizy_kz suspect\nclosed_one legit\n", encoding="utf-8")
    pages = {"https://t.me/s/prizy_kz": PAGE1, "https://t.me/s/prizy_kz?before=101": PAGE0,
             "https://t.me/s/closed_one": PRIVATE}
    source = PublicWebSource(fetch=fake_fetch(pages))
    rows, summary = collect_public.collect(source, collect_public.read_channels(channels), 10)
    assert [r["message_id"] for r in rows] == [102, 101, 99]
    assert rows[1]["group"] == "suspect" and rows[1]["has_media"] is True
    assert rows[1]["url"] == "https://t.me/prizy_kz/101"
    assert summary[1] == {"channel": "closed_one", "group": "legit", "posts": 0, "note": "не публичный или не найден"}
    json.dumps(rows, ensure_ascii=False)


def test_collector_rejects_unknown_group(tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import collect_public

    bad = tmp_path / "c.txt"
    bad.write_text("prizy_kz spam\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        collect_public.read_channels(bad)
