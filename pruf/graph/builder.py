"""Граф связей и кейсы. NetworkX для MVP; узлы и рёбра один в один ложатся в Neo4j.

Узлы: post:<id>, req:<key>, domain:<host>, channel:<name>.
Рёбра: post—req (mentions), post—domain (links_to), post—post (reuses: общий пруф), post—channel (posted_in).
Кейс: компонента связности рискованных постов (средний/высокий риск) по рёбрам mentions/links_to/reuses.
Посты без признаков присоединяются к кейсу как контекст, но не склеивают разные кейсы.
Хабы (реквизит или домен в >50 постах или в основном в легальных постах) кейсы не связывают.
Каналы в связность не входят: один канал публикует и легальное, и нет, это атрибут, а не улика.
Семейство кампании: подкомпонента только по рёбрам reuses (один и тот же пруф).
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from collections import Counter
from dataclasses import dataclass
from typing import Any

import networkx as nx

from pruf.graph import network
from pruf.pipeline import ALLOWLIST_DOMAINS, RISKY_LEVELS
from pruf.registry.imagediff import diff_tokens
from pruf.registry.registry import changes_to_json, tokens_from_json
from pruf.storage.db import Database

LINK_EDGES = ("mentions", "links_to", "reuses")
REBUILD_COST_FACTOR = 10.0
HUB_MAX_POSTS = 50  # реквизит или домен в большем числе постов считается «хабом»
HUB_MIN_POSTS = 5
HUB_LOW_SHARE = 0.7  # ...или если 70%+ его постов без признаков схем
# Насыщение составляющих приоритета кейса
PRIORITY_MAX_CHANNELS = 12
PRIORITY_MAX_REUSE = 20
PRIORITY_MAX_RATE = 5.0  # постов с признаками в день
PRIORITY_MIN_SERIES = 3


@dataclass(frozen=True)
class CaseSummary:
    key: str
    post_ids: tuple[int, ...]
    score: float
    level: str
    tracks: tuple[str, ...]
    requisites: tuple[str, ...]
    domains: tuple[str, ...]
    channels: tuple[str, ...]
    first_seen: str | None
    last_seen: str | None
    families: int
    priority: float = 0.0
    priority_reasons: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "post_ids": list(self.post_ids), "size": len(self.post_ids)}


def plural(n: int, one: str, few: str, many: str) -> str:
    """Русское согласование: 1 канал, 3 канала, 5 каналов."""
    tail = n % 100
    form = many if 11 <= tail <= 14 else one if n % 10 == 1 else few if 2 <= n % 10 <= 4 else many
    return f"{n} {form}"


def _days_between(dates: list[str]) -> float:
    try:
        first, last = datetime.fromisoformat(dates[0]), datetime.fromisoformat(dates[-1])
    except (IndexError, ValueError):
        return 1.0
    return max((last - first).total_seconds() / 86400, 1.0)


def case_priority(score: float, risky_posts: int, channels: tuple[str, ...], tracks: tuple[str, ...],
                  families: list, requisites: tuple[str, ...], dates: list[str]) -> tuple[float, tuple[str, ...]]:
    """Приоритет кейса 0–100 для очереди: у многих кейсов балл риска упирается в 100, поэтому
    очередь ранжируется по масштабу и скорости схемы. Каждая составляющая видна аналитику."""
    reasons: list[str] = []
    parts = {"risk": score * 0.35}
    parts["reach"] = min(len(channels), PRIORITY_MAX_CHANNELS) / PRIORITY_MAX_CHANNELS * 20
    if len(channels) >= 3:
        reasons.append(plural(len(channels), "канал", "канала", "каналов"))
    parts["tracks"] = (len(tracks) - 1) * 7.5 if tracks else 0.0
    if len(tracks) > 1:
        reasons.append(f"{len(tracks)} трека одной сети")  # треков не больше трёх
    reused = max((len(f) for f in families), default=0)
    parts["proofs"] = min(reused, PRIORITY_MAX_REUSE) / PRIORITY_MAX_REUSE * 10
    if reused > 1:
        reasons.append(f"пруф ×{reused}")
    # Скорость считаем только для серии: один-два поста за день — ещё не «волна»
    rate = risky_posts / _days_between(dates) if risky_posts >= PRIORITY_MIN_SERIES else 0.0
    parts["speed"] = min(rate, PRIORITY_MAX_RATE) / PRIORITY_MAX_RATE * 10
    if rate >= 1:
        reasons.append(f"{rate:.1f} поста в день".replace(".", ","))
    parts["money"] = 10.0 if requisites else 0.0
    if requisites:
        reasons.append("реквизиты для перевода")
    return round(min(sum(parts.values()), 100.0), 1), tuple(reasons)


class CaseGraph:
    def __init__(self, db: Database):
        self._db = db
        self._lock = threading.Lock()
        self._built_version = -1
        self._built_at = 0.0
        self._build_cost = 0.0
        self._linking = nx.Graph()
        self.graph = nx.Graph()
        self._cases: dict[str, CaseSummary] = {}
        self._case_of_post: dict[int, str] = {}
        self._networks: list[dict[str, Any]] | None = None
        self._case_networks: dict[str, dict[str, Any]] = {}
        self._generation = 0  # растёт при каждой сборке: по нему отбрасываем расчёт по старому графу

    def ensure(self, version: int, force: bool = False) -> None:
        """Пересобрать граф, если были новые посты. Маленький граф пересобирается сразу; большой
        не чаще, чем раз в REBUILD_COST_FACTOR × время прошлой сборки, чтобы поток приёма не
        превращал каждый клик аналитика в полную пересборку."""
        with self._lock:
            if version == self._built_version:
                return
            since = time.monotonic() - self._built_at
            if not force and self._built_version >= 0 and since < REBUILD_COST_FACTOR * self._build_cost:
                return
            started = time.monotonic()
            self._build()
            self._build_cost = time.monotonic() - started
            self._built_version = version
            self._built_at = time.monotonic()

    def _build(self) -> None:
        g = nx.Graph()
        posts = {p["id"]: p for p in self._db.all_posts_brief()}
        for pid, p in posts.items():
            g.add_node(f"post:{pid}", type="post", **p)
            if p.get("channel"):
                g.add_node(f"channel:{p['channel']}", type="channel", label=p["channel"])
                g.add_edge(f"post:{pid}", f"channel:{p['channel']}", type="posted_in")
        for r in self._db.all_post_requisites():
            if r["post_id"] not in posts:  # пост появился после снимка или не обработан
                continue
            node = f"req:{r['key']}"
            g.add_node(node, type="requisite", kind=r["kind"], label=r["display"])
            g.add_edge(f"post:{r['post_id']}", node, type="mentions")
        for link in self._db.all_links():
            if link["domain"] in ALLOWLIST_DOMAINS or link["post_id"] not in posts:
                continue
            node = f"domain:{link['domain']}"
            g.add_node(node, type="domain", label=link["domain"])
            g.add_edge(f"post:{link['post_id']}", node, type="links_to")
        for m in self._db.all_matches():
            if m["post_a"] != m["post_b"] and m["post_a"] in posts and m["post_b"] in posts:
                g.add_edge(f"post:{m['post_a']}", f"post:{m['post_b']}", type="reuses", kind=m["kind"], distance=m["distance"])
        self.graph = g
        self._linking = nx.Graph((u, v) for u, v, d in g.edges(data=True) if d["type"] in LINK_EDGES)
        self._cases, self._case_of_post = self._compute_cases(g, posts)
        self._networks = None  # считаются по первому запросу
        self._case_networks = {}
        self._generation += 1

    @staticmethod
    def _hubs(g: nx.Graph, posts: dict[int, dict]) -> set[str]:
        """Узлы-«хабы» (популярный номер, общий домен) не связывают кейсы, чтобы кейс не разрастался."""
        hubs = set()
        for node, data in g.nodes(data=True):
            if data.get("type") not in ("requisite", "domain"):
                continue
            pids = [int(n[5:]) for n in g.neighbors(node) if n.startswith("post:")]
            low = sum(1 for p in pids if posts[p]["level"] not in RISKY_LEVELS)
            if len(pids) > HUB_MAX_POSTS or (len(pids) >= HUB_MIN_POSTS and low / len(pids) > HUB_LOW_SHARE):
                hubs.add(node)
        return hubs

    def _compute_cases(self, g: nx.Graph, posts: dict[int, dict]) -> tuple[dict[str, CaseSummary], dict[int, str]]:
        hubs = self._hubs(g, posts)
        for h in hubs:
            g.nodes[h]["hub"] = True
        risky = {p for p, row in posts.items() if row["level"] in RISKY_LEVELS}

        def is_risky(n: str) -> bool:
            return n.startswith("post:") and int(n[5:]) in risky

        # Связность строится только через рискованные посты: обычный пост не склеивает два кейса.
        linking = nx.Graph()
        linking.add_nodes_from(f"post:{p}" for p in risky)
        for u, v, d in g.edges(data=True):
            if d["type"] not in LINK_EDGES or u in hubs or v in hubs:
                continue
            if (u.startswith("post:") and not is_risky(u)) or (v.startswith("post:") and not is_risky(v)):
                continue
            linking.add_edge(u, v)
        statuses = self._db.case_statuses()
        reuse = nx.Graph([(u, v) for u, v, d in g.edges(data=True) if d["type"] == "reuses"])
        cases: dict[str, CaseSummary] = {}
        case_of: dict[int, str] = {}
        for comp in nx.connected_components(linking):
            core = sorted(int(n[5:]) for n in comp if n.startswith("post:"))
            if not core:
                continue
            # Ключ стабилен: если у одного из постов уже был кейс со статусом, сохраняем его ключ.
            known = [p for p in core if f"C-{p}" in statuses]
            key = f"C-{min(known) if known else core[0]}"
            context = set()
            for n in comp:
                for nb in g.neighbors(n):
                    if nb.startswith("post:") and not is_risky(nb) and nb not in comp \
                            and g.edges[n, nb]["type"] in LINK_EDGES and n not in hubs:
                        context.add(int(nb[5:]))
            pids = sorted(set(core) | context)
            top = max(core, key=lambda p: posts[p]["score"])
            tracks = Counter(posts[p]["track"] for p in core if posts[p]["track"])
            dates = sorted(posts[p]["posted_at"] for p in pids if posts[p]["posted_at"])
            sub = reuse.subgraph([f"post:{p}" for p in pids]) if reuse else nx.Graph()
            fam_comps = [c for c in nx.connected_components(sub) if len(c) > 1]
            fam = len(fam_comps)
            channels = tuple(sorted({posts[p]["channel"] for p in pids if posts[p].get("channel")}))
            requisites = tuple(sorted(g.nodes[n]["label"] for n in comp if n.startswith("req:")))
            priority, reasons = case_priority(posts[top]["score"], len(core), channels, tuple(tracks), fam_comps,
                                              requisites, dates)
            cases[key] = CaseSummary(
                key=key, post_ids=tuple(pids), score=posts[top]["score"], level=posts[top]["level"],
                tracks=tuple(t for t, _ in tracks.most_common()),
                requisites=requisites,
                domains=tuple(sorted(g.nodes[n]["label"] for n in comp if n.startswith("domain:"))),
                channels=channels,
                first_seen=dates[0] if dates else None, last_seen=dates[-1] if dates else None, families=fam,
                priority=priority, priority_reasons=reasons,
            )
            for p in pids:
                case_of.setdefault(p, key)
        return cases, case_of

    def cases(self) -> list[CaseSummary]:
        return sorted(self._cases.values(), key=lambda c: (-c.priority, -c.score, -len(c.post_ids)))

    def case(self, key: str) -> CaseSummary | None:
        return self._cases.get(key)

    def networks(self) -> list[dict[str, Any]]:
        # Считаем вне блокировки, чтобы не держать приём постов; граф после сборки не меняется
        with self._lock:
            if self._networks is not None:
                return self._networks
            graph, generation = self.graph, self._generation
        nets = network.networks(graph)
        with self._lock:
            if generation == self._generation:
                self._networks = nets
        return nets

    def case_network(self, key: str) -> dict[str, Any] | None:
        """Сеть каналов кейса и ключевые реквизиты: что заблокировать, чтобы отрезать схему от денег."""
        with self._lock:
            if key in self._case_networks:
                return self._case_networks[key]
            case, graph, generation = self._cases.get(key), self.graph, self._generation
        if not case:
            return None
        net = network.describe(network.money_graph(graph, case.post_ids), key)
        with self._lock:
            if generation == self._generation:
                self._case_networks[key] = net
        return net

    def case_for_post(self, post_id: int) -> str | None:
        return self._case_of_post.get(post_id)

    def subgraph(self, post_ids: tuple[int, ...]) -> dict[str, Any]:
        nodes = {f"post:{p}" for p in post_ids}
        extra = {n for p in nodes for n in self.graph.neighbors(p)} if nodes else set()
        sub = self.graph.subgraph(nodes | extra)
        return {
            "nodes": [{"id": n, **{k: v for k, v in d.items() if k in ("type", "label", "kind", "level", "score", "track", "channel")}}
                      for n, d in sub.nodes(data=True)],
            "edges": [{"source": u, "target": v, "type": d["type"]} for u, v, d in sub.edges(data=True)],
        }

    def related_posts(self, post_id: int, hops: int = 2) -> list[int]:
        start = f"post:{post_id}"
        if start not in self.graph:
            return []
        if start not in self._linking:
            return []
        reach = nx.single_source_shortest_path_length(self._linking, start, cutoff=hops * 2)
        return sorted(int(n[5:]) for n in reach if n.startswith("post:") and n != start)

    def families(self, post_ids: tuple[int, ...]) -> list[list[int]]:
        nodes = [f"post:{p}" for p in post_ids]
        reuse = nx.Graph((u, v) for u, v, d in self.graph.subgraph(nodes).edges(data=True) if d["type"] == "reuses")
        return [sorted(int(n[5:]) for n in c) for c in nx.connected_components(reuse) if len(c) > 1]


MAX_TIMELINE_DIFFS = 200


def artifact_timeline(db: Database, artifact_id: int, limit: int = 500) -> dict[str, Any]:
    """Все появления пруфа: обход рёбер совпадений от артефакта, по времени публикации.
    Дифф каждой копии считается относительно выбранного артефакта (а не предыдущей копии),
    поэтому правка видна и у копий, совпавших с ним только через другие копии."""
    seen = {artifact_id}
    frontier = [artifact_id]
    while frontier and len(seen) < limit:
        nxt = []
        for aid in frontier:
            for m in db.matches_for(aid):
                other = m["other_id"] if m["artifact_id"] == aid else m["artifact_id"]
                if other not in seen and len(seen) < limit:
                    seen.add(other)
                    nxt.append(other)
        frontier = nxt
    arts = db.artifacts_by_ids(seen)
    posts = {p["id"]: p for p in db.get_posts({a["post_id"] for a in arts.values()})}
    root = arts.get(artifact_id)
    root_tokens = tokens_from_json(root["ocr"]) if root and root["ocr"] else []
    items = []
    for aid, art in arts.items():
        post = posts.get(art["post_id"])
        if not post:
            continue
        post.pop("label", None)
        items.append({"artifact_id": aid, "kind": art["kind"], "post": post, "is_root": aid == artifact_id, "diff": None})
    items.sort(key=lambda i: (i["post"]["posted_at"] or "", i["artifact_id"]))
    for item in items[:MAX_TIMELINE_DIFFS]:
        ocr = arts[item["artifact_id"]]["ocr"]
        if not item["is_root"] and root_tokens and ocr:
            changes = diff_tokens(root_tokens, tokens_from_json(ocr))
            item["diff"] = {"changes": changes_to_json(changes)} if changes else None
    return {"artifact_id": artifact_id, "appearances": len(items), "items": items,
            "diffed": min(len(items), MAX_TIMELINE_DIFFS), "truncated": len(seen) >= limit}
