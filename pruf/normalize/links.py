"""Ссылки: извлечение, канонизация, сокращатели, опциональное раскрытие редиректов."""

from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

# Домены, которые сами по себе не признак (банки, госсайты, соцсети)
ALLOWLIST_DOMAINS = frozenset({
    "kaspi.kz", "halykbank.kz", "egov.kz", "gov.kz", "nationalbank.kz", "instagram.com", "t.me", "telegram.me",
    "wa.me", "chat.whatsapp.com", "tiktok.com", "youtube.com", "youtu.be", "vk.com", "google.com", "2gis.kz",
})

# Голый домен: метки ограничены по длине и числу, иначе «a.a.a.…» даёт квадратичный перебор (ReDoS)
_URL_RE = re.compile(
    r"(?:https?://|www\.)[^\s<>\"']+|(?<![a-z0-9.\-])(?:[a-z0-9\-]{1,63}\.){1,6}(?:kz|ru|com|me|io|net|org|bet|xyz|site|online|top|club|app|ly|su|cc|pro|win|casino)(?:/[^\s<>\"']*)?",
    re.IGNORECASE,
)
SHORTENERS = frozenset({
    "bit.ly", "clck.ru", "tinyurl.com", "t.ly", "cutt.ly", "goo.su", "is.gd", "u.to", "rb.gy", "shorturl.at", "vk.cc",
})
MESSENGER_HOSTS = frozenset({"t.me", "telegram.me", "wa.me", "chat.whatsapp.com", "instagram.com", "tiktok.com"})
_MAX_REDIRECTS = 5
MAX_RESOLVE_PER_POST = 3


@dataclass(frozen=True)
class Link:
    url: str
    domain: str
    is_shortener: bool
    is_messenger: bool
    raw_span: tuple[int, int]
    resolved: str | None = None


def canonical_domain(host: str) -> str:
    host = host.lower().strip(".")
    return host.removeprefix("www.")


def extract_links(text: str) -> list[Link]:
    links: list[Link] = []
    seen: set[str] = set()
    for m in _URL_RE.finditer(text):
        raw = m.group().rstrip(".,!?)»")
        url = raw if "://" in raw else "http://" + raw
        try:
            host = urlsplit(url).hostname or ""
        except ValueError:
            continue
        domain = canonical_domain(host)
        if not domain or url.lower() in seen:
            continue
        seen.add(url.lower())
        links.append(Link(url=url, domain=domain, is_shortener=domain in SHORTENERS,
                          is_messenger=domain in MESSENGER_HOSTS, raw_span=(m.start(), m.start() + len(raw))))
    return links


def _is_public_host(host: str) -> bool:
    """Защита от SSRF: хост резолвится, и все его адреса должны быть публичными.

    Резолвинг через getaddrinfo ловит и числовые формы (2130706433, 0x7f000001, 127.1),
    и домены, указывающие на внутренние адреса. Остаточный риск DNS rebinding между
    проверкой и запросом принят: раскрытие ссылок по умолчанию выключено.
    """
    if not host or host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError, ValueError):
        return False
    addresses = {info[4][0] for info in infos}
    return bool(addresses) and all(ipaddress.ip_address(a.split("%")[0]).is_global for a in addresses)


def resolve_shortener(link: Link, timeout: float = 3.0) -> Link:
    """Раскрыть сокращённую ссылку через HEAD без перехода на итоговую страницу."""
    if not link.is_shortener:
        return link
    import httpx

    url = link.url
    try:
        with httpx.Client(follow_redirects=False, timeout=timeout) as client:
            for _ in range(_MAX_REDIRECTS):
                parts = urlsplit(url)
                if parts.scheme not in ("http", "https") or not _is_public_host(parts.hostname or ""):
                    break
                resp = client.head(url)
                location = resp.headers.get("location")
                if not resp.is_redirect or not location:
                    break
                nxt = urljoin(url, location)
                if urlsplit(nxt).scheme not in ("http", "https"):
                    break
                url = nxt
    except httpx.HTTPError:
        return link
    if url == link.url:
        return link
    return Link(url=link.url, domain=canonical_domain(urlsplit(url).hostname or link.domain),
                is_shortener=True, is_messenger=link.is_messenger, raw_span=link.raw_span, resolved=url)
