"""Ссылки: извлечение, канонизация, сокращатели, опциональное раскрытие редиректов."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

_URL_RE = re.compile(
    r"(?:https?://|www\.)[^\s<>\"']+|\b(?:[a-z0-9\-]+\.)+(?:kz|ru|com|me|io|net|org|bet|xyz|site|online|top|club|app|ly|su|cc|pro|win|casino)(?:/[^\s<>\"']*)?",
    re.IGNORECASE,
)
SHORTENERS = frozenset({
    "bit.ly", "clck.ru", "tinyurl.com", "t.ly", "cutt.ly", "goo.su", "is.gd", "u.to", "rb.gy", "shorturl.at", "vk.cc",
})
MESSENGER_HOSTS = frozenset({"t.me", "telegram.me", "wa.me", "chat.whatsapp.com", "instagram.com", "tiktok.com"})
_MAX_REDIRECTS = 5


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
    return host[4:] if host.startswith("www.") else host


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
    """Защита от SSRF: не ходим на приватные адреса и localhost."""
    if host in {"localhost"} or host.endswith(".local") or host.endswith(".internal"):
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True
    return ip.is_global


def resolve_shortener(link: Link, timeout: float = 3.0) -> Link:
    """Раскрыть сокращённую ссылку через HEAD без перехода на итоговую страницу."""
    if not link.is_shortener:
        return link
    import httpx

    url = link.url
    try:
        with httpx.Client(follow_redirects=False, timeout=timeout) as client:
            for _ in range(_MAX_REDIRECTS):
                host = urlsplit(url).hostname or ""
                if not _is_public_host(host):
                    break
                resp = client.head(url)
                location = resp.headers.get("location")
                if not resp.is_redirect or not location:
                    break
                url = location if "://" in location else f"{urlsplit(url).scheme}://{host}{location}"
    except httpx.HTTPError:
        return link
    if url == link.url:
        return link
    return Link(url=link.url, domain=canonical_domain(urlsplit(url).hostname or link.domain),
                is_shortener=True, is_messenger=link.is_messenger, raw_span=link.raw_span, resolved=url)
