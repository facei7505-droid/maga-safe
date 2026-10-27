"""Структуры разведчика: пост и карточка канала из источника, кандидат в очереди."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScoutPost:
    channel: str  # username без @, в нижнем регистре
    message_id: int
    text: str
    posted_at: str | None = None
    forwarded_from: str | None = None  # username канала, из которого переслан пост


@dataclass(frozen=True)
class ChannelInfo:
    username: str
    title: str
    subscribers: int | None = None
    created_at: str | None = None  # ISO-дата создания канала (или первого поста)
    subscribers_week_ago: int | None = None  # если источник знает историю, иначе берём снимок из базы


@dataclass(frozen=True)
class Candidate:
    username: str
    depth: int
    parent: str | None  # откуда пришли; None для семян и поиска по словам
    via: str  # seed | forward | link | mention | requisite | search
    detail: str = ""  # реквизит или поисковая фраза


class SourceUnavailable(Exception):
    """Источник не отвечает или просит подождать дольше разумного (FloodWait)."""
