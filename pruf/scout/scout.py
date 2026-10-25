"""Движок разведчика: семена → снежный ком по ссылкам, репостам, упоминаниям и реквизитам.

Каждый найденный канал проверяется детектором ПРУФ (посты пишутся в реестр с source="scout"),
и только от каналов с высоким риском разведчик идёт дальше. Очередь приоритетная: прямые улики
(общий реквизит, репост) и свежие быстрорастущие каналы проверяются первыми.
"""

from __future__ import annotations

import hashlib
import heapq
import itertools
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from pruf.models import HIGH_THRESHOLD, LEVEL_HIGH, level_for
from pruf.normalize.links import ALLOWLIST_DOMAINS
from pruf.normalize.text import normalize_text
from pruf.pipeline import Pruf, Submission
from pruf.scout.models import Candidate, ChannelInfo, ScoutPost, SourceUnavailable
from pruf.scout.refs import channel_refs, is_bot, normalize_username
from pruf.scout.sources import BudgetExceeded, ChannelSource
from pruf.storage.db import utcnow

log = logging.getLogger(__name__)

# Фразы для поиска каналов: русский, казахский и латиница
DEFAULT_KEYWORDS = ("розыгрыш iphone", "пассивный доход", "казино бонус", "ұтыс", "табыс", "dohod", "vyvod")
VIA_PRIORITY = {"seed": 100, "requisite": 40, "forward": 35, "domain": 30, "link": 25, "mention": 20, "search": 10}
SEARCHABLE_REQUISITES = ("phone", "kaspi_link", "iban")  # карту ищем нельзя: у нас только маска
TOP_POSTS_FOR_RISK = 3
FRESH_DAYS = 30
FRESH_BONUS = 15
GROWTH_BONUS_MAX = 15
DEPTH_PENALTY = 10
PARENT_RISK_SHARE = 0.3


@dataclass(frozen=True)
class ScoutConfig:
    max_channels: int = 40
    max_depth: int = 4
    posts_per_channel: int = 30
    expand_threshold: float = HIGH_THRESHOLD  # от канала с таким риском идём дальше
    keywords: tuple[str, ...] = DEFAULT_KEYWORDS
    search_limit: int = 20
    store: bool = True  # писать посты в реестр ПРУФ; False — только проверка
    allow_llm: bool = False  # Claude по умолчанию не зовём: разведка не тратит бюджет API
    recheck_risky: timedelta = timedelta(hours=6)
    recheck_clean: timedelta = timedelta(days=7)


@dataclass
class ChannelResult:
    username: str
    risk: float
    level: str
    track: str | None
    posts_checked: int
    risky_posts: int
    depth: int
    via: str
    parent: str | None
    requisites: dict[str, tuple[str, str]] = field(default_factory=dict)  # key → (kind, display) из рискованных постов
    domains: set[str] = field(default_factory=set)  # домены из рискованных постов (зеркала, лендинги)


def channel_risk(scores: list[float]) -> float:
    """Среднее по трём самым рискованным постам: один пост новостей о мошенниках не делает канал скамом."""
    top = sorted(scores, reverse=True)[:TOP_POSTS_FOR_RISK]
    return round(sum(top) / len(top), 1) if top else 0.0


def _age_days(created_at: str | None, now: datetime) -> float | None:
    if not created_at:
        return None
    try:
        dt = datetime.fromisoformat(created_at)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max((now - dt).total_seconds() / 86400, 0.0)


def freshness_bonus(info: ChannelInfo | None, previous: dict[str, Any] | None, now: datetime) -> float:
    """Свежий канал и быстрый рост подписчиков поднимают его в очереди."""
    if info is None:
        return 0.0
    bonus = 0.0
    age = _age_days(info.created_at, now)
    if age is not None and age < FRESH_DAYS:
        bonus += FRESH_BONUS
    before = info.subscribers_week_ago
    if before is None and previous and previous.get("subscribers"):
        before = previous["subscribers"]  # снимок с прошлой проверки
    if info.subscribers and before:
        growth_pct = (info.subscribers - before) / before * 100
        bonus += min(max(growth_pct / 2, 0.0), GROWTH_BONUS_MAX)
    return bonus


def _searchable_domain(link: dict[str, Any]) -> bool:
    """Домен схемы, а не площадка: банки, госсайты, мессенджеры и сокращатели не ищем."""
    return not (link["domain"] in ALLOWLIST_DOMAINS or link.get("is_messenger") or link.get("is_shortener"))


class Scout:
    def __init__(self, pruf: Pruf, source: ChannelSource, config: ScoutConfig | None = None,
                 now: datetime | None = None):
        self.pruf = pruf
        self.source = source
        self.config = config or ScoutConfig()
        self.now = now or datetime.now(timezone.utc)
        self._heap: list[tuple[float, int, Candidate]] = []
        self._seq = itertools.count()
        self._queued: set[str] = set()
        self._searched: set[str] = set()
        self._score_cache: dict[str, dict[str, Any]] = {}
        self._info: dict[str, ChannelInfo] = {}
        self.results: dict[str, ChannelResult] = {}
        self.edges: set[tuple[str, str, str, str]] = set()
        self.stopped: str | None = None

    # ---------- очередь ----------
    def enqueue(self, cand: Candidate, parent_risk: float = 0.0) -> None:
        name = cand.username
        if is_bot(name):
            return
        prev = self.pruf.db.scout_channel(name)
        if name in self._queued or (cand.via != "seed" and self._recently_checked(prev)):
            self._link(cand)  # канал уже известен: только связь в графе
            return
        if cand.depth > self.config.max_depth:
            return
        info = None
        if cand.via != "seed":
            try:
                info = self.source.channel_info(name)
            except SourceUnavailable as exc:
                log.warning("карточка %s недоступна: %s", name, exc)
            if info is None:
                return  # нет такого публичного канала
            self._info[name] = info
        self._link(cand)
        self._queued.add(name)
        priority = (VIA_PRIORITY[cand.via] + PARENT_RISK_SHARE * parent_risk + freshness_bonus(info, prev, self.now)
                    - DEPTH_PENALTY * cand.depth)
        heapq.heappush(self._heap, (-priority, next(self._seq), cand))

    def _link(self, cand: Candidate) -> None:
        if cand.parent:
            self._edge(cand.parent, cand.username, cand.via, cand.detail)

    def _recently_checked(self, prev: dict[str, Any] | None) -> bool:
        if not prev or not prev.get("last_checked"):
            return False
        window = self.config.recheck_risky if prev.get("level") == LEVEL_HIGH else self.config.recheck_clean
        return datetime.fromisoformat(prev["last_checked"]) > self.now - window

    def _edge(self, src: str, dst: str, via: str, detail: str = "") -> None:
        if src != dst and (src, dst, via, detail) not in self.edges:
            self.edges.add((src, dst, via, detail))
            self.pruf.db.scout_add_edge(src, dst, via, detail)

    # ---------- запуск ----------
    def run(self, seeds: list[str]) -> dict[str, Any]:
        try:
            for raw in seeds:
                name = normalize_username(raw)
                if name:
                    self.enqueue(Candidate(name, 0, None, "seed"))
            self._keyword_search()
            while self._heap and len(self.results) < self.config.max_channels:
                _, _, cand = heapq.heappop(self._heap)
                self._visit(cand)
            if self._heap and not self.stopped:
                self.stopped = f"достигнут лимит {self.config.max_channels} каналов"
        except BudgetExceeded as exc:
            self.stopped = str(exc)
        except SourceUnavailable as exc:
            self.stopped = f"источник недоступен: {exc}"
        return self.report()

    def _keyword_search(self) -> None:
        for phrase in self.config.keywords:
            for name in self.source.search_channels(phrase, self.config.search_limit):
                self.enqueue(Candidate(name, 1, None, "search", phrase))

    def _visit(self, cand: Candidate) -> None:
        info = self._info.get(cand.username) or self.source.channel_info(cand.username)
        if info is None:
            return
        posts = self.source.recent_posts(cand.username, self.config.posts_per_channel)
        result = self._score_channel(cand, posts)
        self.results[cand.username] = result
        self.pruf.db.scout_save_channel({
            "username": cand.username, "title": info.title, "subscribers": info.subscribers, "created_at": info.created_at,
            "risk": result.risk, "level": result.level, "track": result.track, "posts_checked": result.posts_checked,
            "risky_posts": result.risky_posts, "status": "risky" if result.level == LEVEL_HIGH else "clean",
            "found_via": cand.via, "found_from": cand.parent, "found_detail": cand.detail or None, "depth": cand.depth,
            "last_checked": self.now.isoformat(timespec="seconds"),
        })
        log.info("%s: риск %.0f (%s), постов %d", cand.username, result.risk, result.level, result.posts_checked)
        if result.risk >= self.config.expand_threshold:
            self._expand(cand, posts, result)

    def _score_channel(self, cand: Candidate, posts: list[ScoutPost]) -> ChannelResult:
        scores: list[float] = []
        tracks: dict[str, float] = {}
        requisites: dict[str, tuple[str, str]] = {}
        domains: set[str] = set()
        for post in posts:
            analysis = self._analyze(post)
            score = float(analysis["score"])
            scores.append(score)
            if analysis["level"] == LEVEL_HIGH:
                if analysis.get("track"):
                    tracks[analysis["track"]] = tracks.get(analysis["track"], 0) + score
                for r in analysis.get("requisites", ()):
                    requisites[r["key"]] = (r["kind"], r["display"])
                domains.update(link["domain"] for link in analysis.get("links", ()) if _searchable_domain(link))
        risk = channel_risk(scores)
        return ChannelResult(username=cand.username, risk=risk, level=level_for(risk),
                             track=max(tracks, key=tracks.get) if tracks else None, posts_checked=len(posts),
                             risky_posts=sum(1 for s in scores if level_for(s) == LEVEL_HIGH), depth=cand.depth,
                             via=cand.via, parent=cand.parent, requisites=requisites, domains=domains)

    def _analyze(self, post: ScoutPost) -> dict[str, Any]:
        """Пост проверяется детектором ПРУФ; уже принятый раньше пост не пишется второй раз."""
        external_id = f"tg:{post.channel}/{post.message_id}"
        if self.config.store:
            existing = self.pruf.db.find_post_by_external_id(external_id)
            if existing and existing.get("status") == "ok" and "analysis" in existing:
                return existing["analysis"]
            result = self.pruf.ingest(Submission(text=post.text, source="scout", channel="@" + post.channel,
                                                 posted_at=post.posted_at, external_id=external_id),
                                      allow_llm=self.config.allow_llm)
            return result["analysis"]
        digest = hashlib.sha256(normalize_text(post.text).folded.encode()).hexdigest()
        if digest not in self._score_cache:  # один и тот же текст в разных каналах проверяем один раз
            self._score_cache[digest] = self.pruf.check(post.text, allow_llm=self.config.allow_llm)["analysis"]
        return self._score_cache[digest]

    # ---------- снежный ком ----------
    def _expand(self, cand: Candidate, posts: list[ScoutPost], result: ChannelResult) -> None:
        depth = cand.depth + 1
        for post in posts:
            if post.forwarded_from:
                self.enqueue(Candidate(post.forwarded_from, depth, cand.username, "forward"), result.risk)
            for name, via in channel_refs(post.text):
                self.enqueue(Candidate(name, depth, cand.username, via), result.risk)
        for key, (kind, display) in result.requisites.items():
            self._registry_links(cand.username, key, display)
            if kind in SEARCHABLE_REQUISITES and key not in self._searched:
                self._searched.add(key)
                self._search_posts(cand.username, display, "requisite", depth, result.risk)
        for domain in sorted(result.domains):
            if "domain:" + domain not in self._searched:
                self._searched.add("domain:" + domain)
                self._search_posts(cand.username, domain, "domain", depth, result.risk)

    def _search_posts(self, parent: str, query: str, via: str, depth: int, risk: float) -> None:
        for found in self.source.search_posts(query, self.config.search_limit):
            if found.channel != parent:
                self.enqueue(Candidate(found.channel, depth, parent, via, query), risk)

    def _registry_links(self, username: str, key: str, display: str) -> None:
        """Реквизит уже есть в реестре: связываем с каналами из прошлых жалоб без запросов к Telegram."""
        post_ids = self.pruf.db.posts_with_requisite(key, limit=200)
        for post in self.pruf.db.get_posts(post_ids):
            other = normalize_username(post.get("channel"))
            if other and other != username and post.get("level") == LEVEL_HIGH:
                self._edge(username, other, "requisite", display)

    # ---------- отчёт ----------
    def report(self) -> dict[str, Any]:
        risky = [r for r in self.results.values() if r.level == LEVEL_HIGH]  # в порядке обхода
        holders: dict[str, dict[str, Any]] = {}
        for r in risky:
            for key, (kind, display) in r.requisites.items():
                holders.setdefault(key, {"type": kind, "value": display, "channels": []})["channels"].append(r.username)
            for domain in sorted(r.domains):
                holders.setdefault("domain:" + domain, {"type": "domain", "value": domain, "channels": []})["channels"].append(r.username)
        shared = sorted((h for h in holders.values() if len(h["channels"]) > 1), key=lambda h: -len(h["channels"]))
        return {
            "finished_at": utcnow(),
            "source": self.source.name,
            "channels_checked": len(self.results),
            "risky_channels": [{"username": r.username, "risk": r.risk, "track": r.track, "depth": r.depth, "via": r.via,
                                "parent": r.parent, "risky_posts": r.risky_posts, "posts_checked": r.posts_checked}
                               for r in risky],
            "clean_channels": sorted(r.username for r in self.results.values() if r.level != LEVEL_HIGH),
            "shared_requisites": shared,
            "edges": [{"src": s, "dst": d, "via": v, "detail": det} for s, d, v, det in sorted(self.edges)],
            "requests_used": getattr(getattr(self.source, "throttle", None), "used", None),
            "stopped": self.stopped,
        }
