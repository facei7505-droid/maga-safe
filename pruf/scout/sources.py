"""Источники для разведчика: офлайн-фикстура для демо и тестов и ограничитель запросов.

Источник умеет только читать: карточку канала, последние посты, поиск каналов и публичных постов.
Методов отправки, вступления в канал и любых действий от имени аккаунта в протоколе нет.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from pruf.normalize.requisites import extract_requisites
from pruf.scout.models import ChannelInfo, ScoutPost
from pruf.scout.refs import normalize_username

DEMO_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "demo_network.json"
# Ключ только для сравнения реквизитов внутри фикстуры: в реестр он не попадает
_FIXTURE_KEY = b"scout-fixture"


class ChannelSource(Protocol):
    name: str

    def channel_info(self, username: str) -> ChannelInfo | None: ...
    def recent_posts(self, username: str, limit: int) -> list[ScoutPost]: ...
    def search_channels(self, query: str, limit: int) -> list[str]: ...
    def search_posts(self, query: str, limit: int) -> list[ScoutPost]: ...


class FixtureSource:
    """Публичные каналы из JSON-файла: демо без аккаунта Telegram и детерминированные тесты."""

    name = "fixture"

    def __init__(self, path: Path = DEMO_FIXTURE):
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        self._channels: dict[str, dict[str, Any]] = {k.lower(): v for k, v in data["channels"].items()}

    def channel_info(self, username: str) -> ChannelInfo | None:
        ch = self._channels.get(username)
        if ch is None:
            return None
        return ChannelInfo(username=username, title=ch.get("title", username), subscribers=ch.get("subscribers"),
                           created_at=ch.get("created_at"), subscribers_week_ago=ch.get("subscribers_week_ago"))

    def recent_posts(self, username: str, limit: int) -> list[ScoutPost]:
        ch = self._channels.get(username) or {}
        posts = sorted(ch.get("posts", []), key=lambda p: p["id"], reverse=True)[:limit]
        return [self._post(username, p) for p in posts]

    def search_channels(self, query: str, limit: int) -> list[str]:
        """Как поиск Telegram: по названию, имени и описанию канала, не по постам."""
        q = query.lower()
        hits = [u for u, ch in self._channels.items()
                if q in u or q in ch.get("title", "").lower() or q in ch.get("description", "").lower()]
        return hits[:limit]

    def search_posts(self, query: str, limit: int) -> list[ScoutPost]:
        """Поиск по публичным постам: реквизит находится в любом написании (+7 / 8 / с пробелами)."""
        keys = {r.key for r in extract_requisites(query, _FIXTURE_KEY)}
        out = []
        for username, ch in self._channels.items():
            for p in ch.get("posts", []):
                text = p.get("text", "")
                found = {r.key for r in extract_requisites(text, _FIXTURE_KEY)}
                if (keys and keys & found) or (not keys and query.lower() in text.lower()):
                    out.append(self._post(username, p))
        return out[:limit]

    @staticmethod
    def _post(username: str, p: dict[str, Any]) -> ScoutPost:
        return ScoutPost(channel=username, message_id=int(p["id"]), text=p.get("text", ""), posted_at=p.get("date"),
                         forwarded_from=normalize_username(p.get("forwarded_from")))


class BudgetExceeded(Exception):
    """Исчерпан лимит запросов к источнику на один запуск."""


class Throttle:
    """Не чаще одного запроса в min_interval секунд и не больше max_requests за запуск."""

    def __init__(self, min_interval: float, max_requests: int, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.min_interval = min_interval
        self.max_requests = max_requests
        self.used = 0
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None

    def wait(self) -> None:
        if self.used >= self.max_requests:
            raise BudgetExceeded(f"лимит {self.max_requests} запросов за запуск")
        if self._last is not None:
            delay = self.min_interval - (self._clock() - self._last)
            if delay > 0:
                self._sleep(delay)
        self._last = self._clock()
        self.used += 1


class ThrottledSource:
    """Обёртка над любым источником: каждый вызов проходит через Throttle."""

    def __init__(self, source: ChannelSource, throttle: Throttle):
        self._source = source
        self.throttle = throttle
        self.name = source.name

    def channel_info(self, username: str) -> ChannelInfo | None:
        self.throttle.wait()
        return self._source.channel_info(username)

    def recent_posts(self, username: str, limit: int) -> list[ScoutPost]:
        self.throttle.wait()
        return self._source.recent_posts(username, limit)

    def search_channels(self, query: str, limit: int) -> list[str]:
        self.throttle.wait()
        return self._source.search_channels(query, limit)

    def search_posts(self, query: str, limit: int) -> list[ScoutPost]:
        self.throttle.wait()
        return self._source.search_posts(query, limit)
