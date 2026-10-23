"""Граф связей и кейсы. NetworkX для MVP; узлы и рёбра один в один ложатся в Neo4j.

Узлы: post:<id>, req:<key>, domain:<host>, channel:<name>.
Рёбра: post—req (mentions), post—domain (links_to), post—post (reuses: общий пруф), post—channel (posted_in).
Кейс: компонента связности по рёбрам mentions/links_to/reuses, где есть пост со средним или высоким риском.
Каналы в связность не входят: один канал публикует и легальное, и нет, это атрибут, а не улика.
Семейство кампании: подкомпонента только по рёбрам reuses (один и тот же пруф).
"""

from __future__ import annotations

import threading
from collections import Counter
from dataclasses import dataclass
from typing import Any

import networkx as nx

from pruf.pipeline import ALLOWLIST_DOMAINS, RISKY_LEVELS
from pruf.storage.db import Database

LINK_EDGES = ("mentions", "links_to", "reuses")


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

    def to_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "post_ids": list(self.post_ids), "size": len(self.post_ids)}


class CaseGraph:
    def __init__(self, db: Database):
        self._db = db
        self._lock = threading.Lock()
        self._built_version = -1
        self.graph = nx.Graph()
        self._cases: dict[str, CaseSummary] = {}
        self._case_of_post: dict[int, str] = {}

    def ensure(self, version: int) -> None:
        with self._lock:
            if version != self._built_version:
                self._build()
                self._built_version = version

    def _build(self) -> None:
        g = nx.Graph()
        posts = {p["id"]: p for p in self._db.all_posts_brief()}
        for pid, p in posts.items():
            g.add_node(f"post:{pid}", type="post", **p)
            if p.get("channel"):
                g.add_node(f"channel:{p['channel']}", type="channel", label=p["channel"])
                g.add_edge(f"post:{pid}", f"channel:{p['channel']}", type="posted_in")
        for r in self._db.all_post_requisites():
            node = f"req:{r['key']}"
            g.add_node(node, type="requisite", kind=r["kind"], label=r["display"])
            g.add_edge(f"post:{r['post_id']}", node, type="mentions")
        for link in self._db.all_links():
            if link["domain"] in ALLOWLIST_DOMAINS:
                continue
            node = f"domain:{link['domain']}"
            g.add_node(node, type="domain", label=link["domain"])
            g.add_edge(f"post:{link['post_id']}", node, type="links_to")
        for m in self._db.all_matches():
            if m["post_a"] != m["post_b"]:
                g.add_edge(f"post:{m['post_a']}", f"post:{m['post_b']}", type="reuses", kind=m["kind"], distance=m["distance"])
        self.graph = g
        self._cases, self._case_of_post = self._compute_cases(g, posts)

    @staticmethod
    def _compute_cases(g: nx.Graph, posts: dict[int, dict]) -> tuple[dict[str, CaseSummary], dict[int, str]]:
        linking = g.edge_subgraph([(u, v) for u, v, d in g.edges(data=True) if d["type"] in LINK_EDGES]).copy()
        linking.add_nodes_from(n for n in g.nodes if n.startswith("post:"))
        reuse = nx.Graph([(u, v) for u, v, d in g.edges(data=True) if d["type"] == "reuses"])
        cases: dict[str, CaseSummary] = {}
        case_of: dict[int, str] = {}
        for comp in nx.connected_components(linking):
            pids = sorted(int(n[5:]) for n in comp if n.startswith("post:"))
            risky = [p for p in pids if posts[p]["level"] in RISKY_LEVELS]
            if not risky:
                continue
            key = f"C-{min(risky)}"
            top = max(risky, key=lambda p: posts[p]["score"])
            tracks = Counter(posts[p]["track"] for p in risky if posts[p]["track"])
            dates = sorted(posts[p]["posted_at"] for p in pids if posts[p]["posted_at"])
            fam = sum(1 for c in nx.connected_components(reuse.subgraph([f"post:{p}" for p in pids])) if len(c) > 1) if reuse else 0
            cases[key] = CaseSummary(
                key=key, post_ids=tuple(pids), score=posts[top]["score"], level=posts[top]["level"],
                tracks=tuple(t for t, _ in tracks.most_common()),
                requisites=tuple(sorted(g.nodes[n]["label"] for n in comp if n.startswith("req:"))),
                domains=tuple(sorted(g.nodes[n]["label"] for n in comp if n.startswith("domain:"))),
                channels=tuple(sorted({posts[p]["channel"] for p in pids if posts[p].get("channel")})),
                first_seen=dates[0] if dates else None, last_seen=dates[-1] if dates else None, families=fam,
            )
            for p in pids:
                case_of[p] = key
        return cases, case_of

    def cases(self) -> list[CaseSummary]:
        return sorted(self._cases.values(), key=lambda c: (-c.score, -len(c.post_ids)))

    def case(self, key: str) -> CaseSummary | None:
        return self._cases.get(key)

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
        linking = nx.Graph((u, v) for u, v, d in self.graph.edges(data=True) if d["type"] in LINK_EDGES)
        if start not in linking:
            return []
        reach = nx.single_source_shortest_path_length(linking, start, cutoff=hops * 2)
        return sorted(int(n[5:]) for n in reach if n.startswith("post:") and n != start)

    def families(self, post_ids: tuple[int, ...]) -> list[list[int]]:
        nodes = [f"post:{p}" for p in post_ids]
        reuse = nx.Graph((u, v) for u, v, d in self.graph.subgraph(nodes).edges(data=True) if d["type"] == "reuses")
        return [sorted(int(n[5:]) for n in c) for c in nx.connected_components(reuse) if len(c) > 1]


def artifact_timeline(db: Database, artifact_id: int, limit: int = 500) -> dict[str, Any]:
    """Все появления пруфа: обход рёбер совпадений от артефакта, по времени публикации."""
    seen = {artifact_id}
    frontier = [artifact_id]
    diffs: dict[int, Any] = {}
    while frontier and len(seen) < limit:
        nxt = []
        for aid in frontier:
            for m in db.matches_for(aid):
                other = m["other_id"] if m["artifact_id"] == aid else m["artifact_id"]
                if other not in seen:
                    seen.add(other)
                    nxt.append(other)
                if m["diff"] and (m["artifact_id"] == artifact_id or m["other_id"] == artifact_id):
                    diffs[other] = m["diff"]
        frontier = nxt
    post_of = db.artifact_post_ids(seen)
    posts = {p["id"]: p for p in db.get_posts(set(post_of.values()))}
    items = []
    for aid in seen:
        post = posts.get(post_of.get(aid, -1))
        if not post:
            continue
        art = db.get_artifact(aid)
        items.append({"artifact_id": aid, "kind": art["kind"] if art else None, "post": post,
                      "is_root": aid == artifact_id, "diff": diffs.get(aid)})
    items.sort(key=lambda i: (i["post"]["posted_at"] or "", i["artifact_id"]))
    return {"artifact_id": artifact_id, "appearances": len(items), "items": items}
