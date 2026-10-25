"""Ссылки на другие каналы в тексте поста: t.me/имя и @упоминания."""

from __future__ import annotations

import re

# Имя в Telegram: 5–32 символа, начинается с буквы. t.me/+… и joinchat — приватные приглашения, их не трогаем.
_TME_RE = re.compile(r"(?:https?://)?(?:t\.me|telegram\.me)/(?:s/)?([A-Za-z][A-Za-z0-9_]{4,31})(?![A-Za-z0-9_])", re.IGNORECASE)
_MENTION_RE = re.compile(r"(?<![\w@./])@([A-Za-z][A-Za-z0-9_]{4,31})(?![A-Za-z0-9_])")
_USERNAME_RE = re.compile(r"^@?([A-Za-z][A-Za-z0-9_]{4,31})$")
# Служебные пути t.me, а не каналы
_RESERVED = frozenset({"joinchat", "addstickers", "addemoji", "share", "proxy", "socks", "setlanguage", "addlist",
                       "boost", "giftcode", "invoice", "login", "confirmphone"})


def normalize_username(raw: str | None) -> str | None:
    """«@Some_Channel» или «t.me/Some_Channel» → «some_channel»; не похоже на имя канала → None."""
    if not raw:
        return None
    raw = raw.strip()
    m = _TME_RE.fullmatch(raw) or _USERNAME_RE.match(raw)
    if not m:
        return None
    name = m.group(1).lower()
    return None if name in _RESERVED else name


def is_bot(username: str) -> bool:
    """Боты не каналы: читать их ленту нельзя, и разведчик не пишет им."""
    return username.endswith("bot")


def channel_refs(text: str) -> list[tuple[str, str]]:
    """(username, via) для каждого упомянутого канала: via = link | mention. Без повторов и ботов."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for regex, via in ((_TME_RE, "link"), (_MENTION_RE, "mention")):
        for m in regex.finditer(text or ""):
            name = m.group(1).lower()
            if name in seen or name in _RESERVED or is_bot(name):
                continue
            seen.add(name)
            out.append((name, via))
    return out
