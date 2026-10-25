"""Источник Telegram через Telethon: только чтение публичных каналов.

Клиент Telethon оборачивается в ReadOnlyClient: доступны лишь методы и запросы чтения из белого
списка, всё остальное (отправка, пересылка, вступление в канал, реакции) падает с PermissionError
ещё до обращения к Telegram. Поэтому разведчик не может написать мошенникам даже по ошибке.

Ключи берутся только из окружения: TG_API_ID, TG_API_HASH (my.telegram.org), файл сессии
PRUF_SCOUT_SESSION. Нужен отдельный аккаунт, не личный.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

from pruf.scout.models import ChannelInfo, ScoutPost, SourceUnavailable
from pruf.scout.refs import normalize_username

log = logging.getLogger(__name__)
ALLOWED_METHODS = frozenset({"start", "connect", "disconnect", "is_user_authorized", "get_entity", "iter_messages"})
ALLOWED_REQUESTS = frozenset({"SearchRequest", "SearchGlobalRequest", "GetFullChannelRequest", "ResolveUsernameRequest"})
MAX_FLOOD_WAIT = 60  # дольше ждать не будем: запуск остановится, очередь продолжится в следующий раз


class ReadOnlyClient:
    """Белый список поверх клиента Telethon."""

    def __init__(self, client: Any):
        self._client = client

    def __getattr__(self, name: str) -> Any:
        if name not in ALLOWED_METHODS:
            raise PermissionError(f"Разведчик только читает: метод {name} запрещён")
        return getattr(self._client, name)

    def __call__(self, request: Any) -> Any:
        kind = type(request).__name__
        if kind not in ALLOWED_REQUESTS:
            raise PermissionError(f"Разведчик только читает: запрос {kind} запрещён")
        return self._client(request)


def _iso(dt: Any) -> str | None:
    return dt.isoformat() if dt is not None and hasattr(dt, "isoformat") else None


class TelethonSource:
    name = "telegram"

    def __init__(self, client: Any, sleep=time.sleep):
        self._tg = client if isinstance(client, ReadOnlyClient) else ReadOnlyClient(client)
        self._sleep = sleep
        # get_entity(имя) каждый раз шлёт ResolveUsername, а у него жёсткий лимит Telegram: кэшируем
        self._entities: dict[str, Any] = {}

    @classmethod
    def from_env(cls) -> TelethonSource:
        try:
            from telethon.sync import TelegramClient
        except ImportError as exc:
            raise RuntimeError("Установите telethon: pip install -r requirements-scout.txt") from exc
        api_id, api_hash = os.environ.get("TG_API_ID", ""), os.environ.get("TG_API_HASH", "")
        if not api_id.isdigit() or not api_hash:
            raise RuntimeError("Задайте TG_API_ID и TG_API_HASH (my.telegram.org) в окружении, не в файлах репозитория")
        session = os.environ.get("PRUF_SCOUT_SESSION", "data/scout.session")
        client = ReadOnlyClient(TelegramClient(session, int(api_id), api_hash))
        old_umask = os.umask(0o077)  # файл сессии = полный доступ к аккаунту: только владельцу
        try:
            client.start()  # первый раз спросит телефон и код в консоли, дальше берёт файл сессии
        finally:
            os.umask(old_umask)
        return cls(client)

    def _call(self, fn, *args: Any, **kwargs: Any) -> Any:
        """Один повтор после короткого FloodWait; длинный останавливает запуск."""
        from telethon import errors

        for attempt in (1, 2):
            try:
                return fn(*args, **kwargs)
            except errors.FloodWaitError as exc:
                if exc.seconds > MAX_FLOOD_WAIT or attempt == 2:
                    raise SourceUnavailable(f"Telegram просит подождать {exc.seconds} с") from exc
                log.warning("FloodWait %s с", exc.seconds)
                self._sleep(exc.seconds + 1)
        return None

    def _read(self, fn, *args: Any) -> Any:
        """Чтение канала: закрытый канал = пусто, прочие ошибки Telegram останавливают запуск, а не роняют его."""
        from telethon import errors

        try:
            return self._call(fn, *args)
        except errors.ChannelPrivateError:
            return None
        except errors.RPCError as exc:
            raise SourceUnavailable(f"Telegram: {type(exc).__name__}") from exc

    def _entity(self, username: str) -> Any | None:
        from telethon import errors

        if username in self._entities:
            return self._entities[username]
        try:
            entity = self._call(self._tg.get_entity, username)
        except (ValueError, errors.UsernameNotOccupiedError, errors.UsernameInvalidError, errors.ChannelPrivateError):
            entity = None  # нет такого имени, приватный или удалён
        except errors.RPCError as exc:
            raise SourceUnavailable(f"Telegram: {type(exc).__name__}") from exc
        # Только публичные каналы и группы: личные аккаунты разведчик не читает
        if entity is not None and (type(entity).__name__ != "Channel" or not getattr(entity, "username", None)):
            entity = None
        self._entities[username] = entity
        return entity

    def channel_info(self, username: str) -> ChannelInfo | None:
        from telethon.tl.functions.channels import GetFullChannelRequest

        entity = self._entity(username)
        if entity is None:
            return None
        full = self._read(self._tg, GetFullChannelRequest(entity))
        if full is None:
            return None
        return ChannelInfo(username=username, title=getattr(entity, "title", username),
                           subscribers=getattr(full.full_chat, "participants_count", None), created_at=_iso(entity.date))

    def recent_posts(self, username: str, limit: int) -> list[ScoutPost]:
        entity = self._entity(username)
        if entity is None:
            return []
        messages = self._read(lambda: list(self._tg.iter_messages(entity, limit=limit))) or []
        return [self._post(username, m) for m in messages if getattr(m, "message", None)]

    def search_channels(self, query: str, limit: int) -> list[str]:
        from telethon.tl.functions.contacts import SearchRequest

        found = self._read(self._tg, SearchRequest(q=query, limit=limit))
        if found is None:
            return []
        return [u for u in (normalize_username(getattr(c, "username", None)) for c in found.chats
                            if getattr(c, "broadcast", False) or getattr(c, "megagroup", False)) if u]

    def search_posts(self, query: str, limit: int) -> list[ScoutPost]:
        from telethon.tl.functions.messages import SearchGlobalRequest
        from telethon.tl.types import InputMessagesFilterEmpty, InputPeerEmpty

        res = self._read(self._tg, SearchGlobalRequest(
            q=query, filter=InputMessagesFilterEmpty(), min_date=None, max_date=None, offset_rate=0,
            offset_peer=InputPeerEmpty(), offset_id=0, limit=limit, broadcasts_only=True))
        if res is None:
            return []
        chats = {c.id: normalize_username(getattr(c, "username", None)) for c in res.chats}
        out = []
        for m in res.messages:
            username = chats.get(getattr(getattr(m, "peer_id", None), "channel_id", None))
            if username and getattr(m, "message", None):
                out.append(self._post(username, m))
        return out

    @staticmethod
    def _post(username: str, m: Any) -> ScoutPost:
        fwd_chat = getattr(getattr(m, "forward", None), "chat", None)
        return ScoutPost(channel=username, message_id=int(m.id), text=m.message or "", posted_at=_iso(getattr(m, "date", None)),
                         forwarded_from=normalize_username(getattr(fwd_chat, "username", None)))
