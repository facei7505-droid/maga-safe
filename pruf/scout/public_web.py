"""Источник Telegram без аккаунта: открытые страницы t.me/s/<канал>.

Telegram показывает последние посты публичного канала на веб-странице без входа. Источник только читает
эти страницы: ни аккаунта, ни ключей my.telegram.org, ни возможности что-то отправить. Подходит для
проверки на реальных постах и для живого запуска разведчика. Поиска по всему Telegram у веб-страниц нет,
поэтому разведчик идёт только по ссылкам, репостам, упоминаниям и общим реквизитам.
"""

from __future__ import annotations

import html
import logging
import re
from collections.abc import Callable
from html.parser import HTMLParser

from pruf.scout.models import ChannelInfo, ScoutPost, SourceUnavailable
from pruf.scout.refs import normalize_username

log = logging.getLogger(__name__)
BASE_URL = "https://t.me/s/"
USER_AGENT = "Mozilla/5.0 (compatible; PRUF-research/1.0; read-only public channel preview)"
MAX_PAGES = 30  # одна страница ≈ 20 постов; глубже не листаем
TIMEOUT = 20.0

_POST_RE = re.compile(r'<div class="tgme_widget_message [^"]*"[^>]*\bdata-post="([^"/]+)/(\d+)"')
_TEXT_RE = re.compile(r'<div class="tgme_widget_message_text[^"]*"[^>]*>', re.S)
_TIME_RE = re.compile(r'<time[^>]*\bdatetime="([^"]+)"')
_FWD_RE = re.compile(r'class="tgme_widget_message_forwarded_from_name"[^>]*href="https?://t\.me/([A-Za-z0-9_]{4,32})')
_PHOTO_RE = re.compile(r'tgme_widget_message_(?:photo_wrap|video_player|grouped_wrap)')
_TITLE_RE = re.compile(r'<div class="tgme_channel_info_header_title"[^>]*>(.*?)</div>', re.S)
_COUNTER_RE = re.compile(r'<span class="counter_value">([^<]+)</span>\s*<span class="counter_type">([^<]+)</span>')
_PREV_RE = re.compile(r'<link rel="prev" href="[^"]*\?before=(\d+)"')


class _TextExtractor(HTMLParser):
    """Текст поста с переносами строк; адреса ссылок дописываются, если их не видно в тексте."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hrefs: list[str] = []
        self.depth = 1  # мы уже внутри div текста; 0 значит текст поста закончился

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.depth == 0:
            return
        if tag == "div":
            self.depth += 1
        elif tag == "br":
            self.parts.append("\n")
        elif tag == "a":
            href = dict(attrs).get("href") or ""
            if href.startswith("http"):
                self.hrefs.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self.depth > 0:
            self.depth -= 1

    def handle_data(self, data: str) -> None:
        if self.depth > 0:
            self.parts.append(data)

    def text(self) -> str:
        body = "".join(self.parts).strip()
        extra = [h for h in dict.fromkeys(self.hrefs) if h not in body]
        return "\n".join([body, *extra]) if extra else body


def _post_text(block: str) -> str:
    m = _TEXT_RE.search(block)
    if not m:
        return ""
    parser = _TextExtractor()
    parser.feed(block[m.end():])
    return parser.text()


def parse_page(page: str) -> tuple[list[ScoutPost], dict[int, bool], int | None]:
    """Посты страницы (в порядке id), есть ли у поста фото или видео, id для следующей страницы назад."""
    starts = [(m.start(), m.group(1), int(m.group(2))) for m in _POST_RE.finditer(page)]
    posts: list[ScoutPost] = []
    media: dict[int, bool] = {}
    for i, (pos, channel, msg_id) in enumerate(starts):
        block = page[pos:starts[i + 1][0] if i + 1 < len(starts) else len(page)]
        when = _TIME_RE.search(block)
        fwd = _FWD_RE.search(block)
        posts.append(ScoutPost(channel=normalize_username(channel) or channel.lower(), message_id=msg_id,
                               text=_post_text(block), posted_at=when.group(1) if when else None,
                               forwarded_from=normalize_username(fwd.group(1)) if fwd else None))
        media[msg_id] = bool(_PHOTO_RE.search(block))
    prev = _PREV_RE.search(page)
    posts.sort(key=lambda p: p.message_id)
    return posts, media, int(prev.group(1)) if prev else None


def parse_subscribers(value: str) -> int | None:
    """«12.3K» → 12300, «1.2M» → 1200000, «845» → 845."""
    m = re.fullmatch(r"([\d.,\s]+)([KM]?)", value.strip().upper())
    if not m:
        return None
    number = float(m.group(1).replace(" ", "").replace(",", "."))
    return int(number * {"": 1, "K": 1_000, "M": 1_000_000}[m.group(2)])


def parse_channel(page: str, username: str) -> ChannelInfo | None:
    title = _TITLE_RE.search(page)
    if not title:
        return None  # не публичный канал: t.me отдаёт страницу без ленты
    subscribers = None
    for value, kind in _COUNTER_RE.findall(page):
        if kind.strip().lower().startswith(("subscriber", "подписчик", "member", "участник")):
            subscribers = parse_subscribers(value)
    name = html.unescape(re.sub(r"<[^>]+>", "", title.group(1))).strip()
    return ChannelInfo(username=username, title=name, subscribers=subscribers)


class PublicWebSource:
    """ChannelSource поверх t.me/s. fetch(url) → HTML; по умолчанию httpx с честным User-Agent."""

    def __init__(self, fetch: Callable[[str], str] | None = None, max_pages: int = MAX_PAGES):
        self._fetch = fetch or _http_fetch()
        self._max_pages = max_pages
        self._first_page: dict[str, str] = {}

    def _page(self, username: str, before: int | None = None) -> str:
        url = BASE_URL + username + (f"?before={before}" if before else "")
        try:
            return self._fetch(url)
        except Exception as exc:  # сеть, 429, таймаут: разведчик отложит канал
            raise SourceUnavailable(f"{url}: {exc}") from exc

    def channel_info(self, username: str) -> ChannelInfo | None:
        page = self._page(username)
        self._first_page[username] = page
        return parse_channel(page, username)

    def recent_posts(self, username: str, limit: int) -> list[ScoutPost]:
        return [p for p, _ in self.recent_posts_with_media(username, limit)]

    def recent_posts_with_media(self, username: str, limit: int) -> list[tuple[ScoutPost, bool]]:
        """Последние посты канала, новые первыми; посты без текста пропускаются."""
        found: dict[int, tuple[ScoutPost, bool]] = {}
        page = self._first_page.pop(username, None) or self._page(username)
        for _ in range(self._max_pages):
            posts, media, before = parse_page(page)
            for p in posts:
                if p.text and p.channel == username.lower():
                    found[p.message_id] = (p, media[p.message_id])
            if len(found) >= limit or not before or not posts:
                break
            page = self._page(username, before)
        newest = sorted(found.values(), key=lambda pm: -pm[0].message_id)
        return newest[:limit]

    def search_channels(self, query: str, limit: int) -> list[str]:
        return []  # у веб-страниц нет поиска по Telegram

    def search_posts(self, query: str, limit: int) -> list[ScoutPost]:
        return []


def _http_fetch() -> Callable[[str], str]:
    import httpx

    client = httpx.Client(timeout=TIMEOUT, follow_redirects=True, headers={"User-Agent": USER_AGENT})

    def fetch(url: str) -> str:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.text

    return fetch
