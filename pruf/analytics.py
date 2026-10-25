"""Обзор для аналитика: динамика по дням, треки, каналы и ранние сигналы.

Ранний сигнал («всплеск»): один реквизит за короткое окно всплывает в постах с признаками
схем сразу в нескольких каналах. Так выглядит запуск новой волны: схему разгоняют по сетке
каналов раньше, чем она наберёт жалобы. Это признак для проверки, не вердикт.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any, Callable

from pruf.pipeline import RISKY_LEVELS
from pruf.storage.db import CASE_STATUSES, Database

SURGE_WINDOW = timedelta(hours=72)
SURGE_MIN_CHANNELS = 3
TOP_CHANNELS = 8
MAX_SURGES = 10
DAILY_DAYS = 60


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(value)
    except ValueError:
        return None
    return ts.replace(tzinfo=None)


def daily_levels(posts: list[dict[str, Any]], days: int = DAILY_DAYS) -> list[dict[str, Any]]:
    """Посты по дням публикации и уровню риска за последние `days` дней с данными, без пропусков."""
    by_day: dict[str, Counter] = defaultdict(Counter)
    for p in posts:
        ts = _parse_ts(p.get("posted_at"))
        if ts:
            by_day[ts.date().isoformat()][p.get("level") or "low"] += 1
    if not by_day:
        return []
    last = datetime.fromisoformat(max(by_day)).date()
    first = max(datetime.fromisoformat(min(by_day)).date(), last - timedelta(days=days - 1))
    out = []
    day = first
    while day <= last:
        c = by_day.get(day.isoformat(), Counter())
        out.append({"date": day.isoformat(), "high": c["high"], "medium": c["medium"], "low": c["low"]})
        day += timedelta(days=1)
    return out


def top_channels(posts: list[dict[str, Any]], limit: int = TOP_CHANNELS) -> list[dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = {}
    for p in posts:
        ch = p.get("channel")
        if not ch:
            continue
        s = stats.setdefault(ch, {"channel": ch, "total": 0, "risky": 0, "max_score": 0.0, "tracks": Counter()})
        s["total"] += 1
        if p.get("level") in RISKY_LEVELS:
            s["risky"] += 1
            s["max_score"] = max(s["max_score"], float(p.get("score") or 0))
            if p.get("track"):
                s["tracks"][p["track"]] += 1
    ranked = sorted((s for s in stats.values() if s["risky"]), key=lambda s: (-s["risky"], -s["max_score"], s["channel"]))
    return [{**s, "tracks": [t for t, _ in s["tracks"].most_common()]} for s in ranked[:limit]]


def surges(posts: list[dict[str, Any]], post_requisites: list[dict[str, Any]],
           case_for_post: Callable[[int], str | None], window: timedelta = SURGE_WINDOW,
           min_channels: int = SURGE_MIN_CHANNELS) -> list[dict[str, Any]]:
    """Реквизиты, которые за окно `window` появились в рискованных постах в `min_channels`+ каналах."""
    risky = {p["id"]: p for p in posts if p.get("level") in RISKY_LEVELS and p.get("channel") and _parse_ts(p.get("posted_at"))}
    by_req: dict[int, list[dict[str, Any]]] = defaultdict(list)
    meta: dict[int, dict[str, Any]] = {}
    for row in post_requisites:
        post = risky.get(row["post_id"])
        if post:
            by_req[row["id"]].append(post)
            meta[row["id"]] = row
    found = []
    for req_id, req_posts in by_req.items():
        best = _densest_window(sorted(req_posts, key=lambda p: _parse_ts(p["posted_at"])), window)
        if len(best["channels"]) < min_channels:
            continue
        cases = sorted({c for c in (case_for_post(p["id"]) for p in best["posts"]) if c})
        found.append({
            "requisite": meta[req_id]["display"], "type": meta[req_id]["kind"],
            "channels": sorted(best["channels"]), "posts": [p["id"] for p in best["posts"]],
            "start": best["posts"][0]["posted_at"], "end": best["posts"][-1]["posted_at"],
            "total_posts": len(req_posts), "cases": cases,
        })
    found.sort(key=lambda s: (-len(s["channels"]), -len(s["posts"]), s["requisite"]))
    return found[:MAX_SURGES]


def _densest_window(posts: list[dict[str, Any]], window: timedelta) -> dict[str, Any]:
    """Окно с наибольшим числом разных каналов (два указателя по отсортированным постам)."""
    best: dict[str, Any] = {"channels": set(), "posts": []}
    left = 0
    for right in range(len(posts)):
        end = _parse_ts(posts[right]["posted_at"])
        while end - _parse_ts(posts[left]["posted_at"]) > window:
            left += 1
        chunk = posts[left:right + 1]
        channels = {p["channel"] for p in chunk}
        if len(channels) > len(best["channels"]):
            best = {"channels": channels, "posts": chunk}
    return best


def overview(db: Database, case_keys: list[str], case_for_post: Callable[[int], str | None]) -> dict[str, Any]:
    posts = db.all_posts_brief()
    statuses = db.case_statuses()
    status_counts = Counter(statuses.get(k, {}).get("status", "new") for k in case_keys)
    tracks = Counter(p["track"] for p in posts if p.get("level") in RISKY_LEVELS and p.get("track"))
    return {
        "daily": daily_levels(posts),
        "tracks": dict(tracks),
        "channels": top_channels(posts),
        "case_statuses": {s: status_counts.get(s, 0) for s in CASE_STATUSES},
        "surges": surges(posts, db.all_post_requisites(), case_for_post),
    }
