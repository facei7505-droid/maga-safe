"""Сети и ключевые реквизиты: от обнаружения к действию.

Граф «канал — реквизит/домен» строится по постам с признаками схем: ребро значит, что канал
просил перевести деньги на этот номер или вёл на этот домен. Сеть — компонента связности
этого графа; большую компоненту (больше LOUVAIN_MIN_NODES узлов) делим на сообщества Louvain,
чтобы аналитик видел отдельные кампании, а не один ком.

Ключевой реквизит — узел, после блокировки которого больше всего каналов сети остаются без
единого способа принять деньги. При равенстве выше тот, что сильнее связывает сеть
(betweenness). Это подсказка для банка и регулятора, а не вердикт: решает аналитик.

Ротация: схемы меняют номер после блокировки. Реквизит считается сменой, если канал перестал
публиковать старый реквизит и только после этого начал публиковать новый, и так сделали хотя бы
ROTATION_MIN_CHANNELS каналов. Новый номер тоже нужно
заблокировать, иначе сеть продолжит принимать деньги.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

import networkx as nx

from pruf.pipeline import RISKY_LEVELS

MONEY_TYPES = ("requisite", "domain")
LINK_ONLY_KINDS = ("promo",)  # промокод связывает каналы в сеть, но заблокировать его банк не может
MIN_NETWORK_CHANNELS = 2
TOP_KEYS = 3
LOUVAIN_MIN_NODES = 40
LOUVAIN_SEED = 7  # одинаковое разбиение при каждой пересборке
EXACT_BETWEENNESS_MAX = 300  # выше считаем betweenness по выборке узлов: точный расчёт O(V·E)
MAX_FRESH = 5
ROTATION_MIN_CHANNELS = 2  # смена в одном канале бывает случайностью; после блокировки номер меняет вся сеть


@dataclass(frozen=True)
class KeyNode:
    node: str
    label: str
    kind: str
    channels: tuple[str, ...]  # каналы, которые принимают деньги через этот узел
    cut_off: tuple[str, ...]  # каналы, у которых это единственный способ принять деньги
    parts_after: int  # на сколько частей распадётся сеть без этого узла
    centrality: float

    def to_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "channels": list(self.channels), "cut_off": list(self.cut_off)}


def money_graph(g: nx.Graph, post_ids: Iterable[int] | None = None) -> nx.Graph:
    """Двудольный граф канал — реквизит/домен по постам с признаками схем.
    Хабы (общий номер колл-центра, популярный домен) пропускаем: их блокировка ничего не говорит о сети."""
    only = set(post_ids) if post_ids is not None else None
    h = nx.Graph()
    for node, data in g.nodes(data=True):
        if data.get("type") != "post" or data.get("level") not in RISKY_LEVELS or not data.get("channel"):
            continue
        if only is not None and int(node[5:]) not in only:
            continue
        chan = f"channel:{data['channel']}"
        money = [nb for nb in g.neighbors(node) if g.nodes[nb].get("type") in MONEY_TYPES and not g.nodes[nb].get("hub")]
        if not money:
            continue
        if chan not in h:
            h.add_node(chan, type="channel", label=data["channel"], posts=0, tracks=Counter(), score=0.0)
        info = h.nodes[chan]
        info["posts"] += 1
        info["score"] = max(info["score"], float(data.get("score") or 0))
        if data.get("track"):
            info["tracks"][data["track"]] += 1
        posted = utc_day(data.get("posted_at"))
        for nb in money:
            nd = g.nodes[nb]
            h.add_node(nb, type=nd["type"], label=nd.get("label", nb[nb.index(":") + 1:]), kind=nd.get("kind", "domain"))
            edge = h.edges[chan, nb] if h.has_edge(chan, nb) else {"weight": 0, "first": None, "last": None}
            # Когда канал впервые и в последний раз публиковал этот реквизит: по ним видна смена номера
            h.add_edge(chan, nb, weight=edge["weight"] + 1,
                       first=min(filter(None, (edge["first"], posted)), default=None),
                       last=max(filter(None, (edge["last"], posted)), default=None))
    return h


def _channels(h: nx.Graph) -> list[str]:
    return [n for n, d in h.nodes(data=True) if d["type"] == "channel"]


def channel_parts(h: nx.Graph) -> int:
    """Сколько отдельных групп каналов: компоненты связности, где есть хотя бы один канал."""
    return sum(1 for comp in nx.connected_components(h) if any(h.nodes[n]["type"] == "channel" for n in comp))


def _blockable(h: nx.Graph, node: str) -> bool:
    data = h.nodes[node]
    return data["type"] in MONEY_TYPES and data.get("kind") not in LINK_ONLY_KINDS


def key_nodes(h: nx.Graph, limit: int = TOP_KEYS) -> list[KeyNode]:
    money = [n for n in h if _blockable(h, n)]
    if not money:
        return []
    if len(h) <= 2:
        between = dict.fromkeys(h, 0.0)
    elif len(h) <= EXACT_BETWEENNESS_MAX:
        between = nx.betweenness_centrality(h, normalized=True)
    else:
        between = nx.betweenness_centrality(h, k=EXACT_BETWEENNESS_MAX, normalized=True, seed=LOUVAIN_SEED)
    routes = {c: {m for m in h.neighbors(c) if _blockable(h, m)} for c in _channels(h)}
    ranked = []
    for m in money:
        users = sorted(h.neighbors(m))
        cut = [c for c in users if routes.get(c) == {m}]  # у канала нет другого реквизита или домена для денег
        ranked.append((m, users, cut))
    ranked.sort(key=lambda r: (-len(r[2]), -between.get(r[0], 0.0), -len(r[1]), h.nodes[r[0]]["label"]))
    # «На сколько частей распадётся» считаем только для показанных узлов: это обход всего графа
    return [KeyNode(node=m, label=h.nodes[m]["label"], kind=h.nodes[m]["kind"],
                    channels=tuple(h.nodes[c]["label"] for c in users), cut_off=tuple(h.nodes[c]["label"] for c in cut),
                    parts_after=channel_parts(nx.restricted_view(h, [m], [])), centrality=round(between.get(m, 0.0), 3))
            for m, users, cut in ranked[:limit]]


def utc_day(stamp: str | None) -> str | None:
    """Дата поста в UTC (ГГГГ-ММ-ДД). Время с часовым поясом приводится к UTC, нераспознанное отбрасывается."""
    if not stamp:
        return None
    try:
        moment = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc)
    return moment.date().isoformat()


def fresh_requisites(h: nx.Graph) -> tuple[str | None, list[dict[str, Any]]]:
    """Начало сети и смены реквизитов: канал перестал публиковать старый реквизит и после этого
    начал публиковать новый. Свежие смены первыми."""
    firsts = [d["first"] for _, _, d in h.edges(data=True) if d.get("first")]
    if not firsts:
        return None, []
    fresh: dict[str, dict[str, Any]] = {}
    for chan in _channels(h):
        routes = [(m, h.edges[chan, m]) for m in h.neighbors(chan) if _blockable(h, m) and h.edges[chan, m].get("first")]
        for new, new_edge in routes:
            replaced = [old for old, old_edge in routes if old != new and old_edge["last"] < new_edge["first"]]
            if not replaced:
                continue
            item = fresh.setdefault(new, {"node": new, "label": h.nodes[new]["label"], "kind": h.nodes[new]["kind"],
                                          "first_seen": new_edge["first"], "channels": set(), "replaces": set()})
            item["first_seen"] = min(item["first_seen"], new_edge["first"])
            item["channels"].add(h.nodes[chan]["label"])
            item["replaces"].update(h.nodes[old]["label"] for old in replaced)
    ranked = sorted((f for f in fresh.values() if len(f["channels"]) >= ROTATION_MIN_CHANNELS),
                    key=lambda f: (f["first_seen"], f["label"]), reverse=True)
    return min(firsts), [{**f, "channels": sorted(f["channels"]), "replaces": sorted(f["replaces"])} for f in ranked[:MAX_FRESH]]


def describe(h: nx.Graph, key: str | None = None) -> dict[str, Any]:
    """Сеть для API: каналы, реквизиты, рёбра (для «что если заблокировать» в браузере) и ключевые узлы."""
    chans = _channels(h)
    tracks: Counter = Counter()
    for c in chans:
        tracks.update(h.nodes[c]["tracks"])
    money = [n for n, d in h.nodes(data=True) if d["type"] in MONEY_TYPES]
    since, fresh = fresh_requisites(h)
    return {
        "key": key,
        "channels": sorted(h.nodes[c]["label"] for c in chans),
        "money": sorted(({"node": m, "label": h.nodes[m]["label"], "kind": h.nodes[m]["kind"],
                          "blockable": _blockable(h, m)} for m in money),
                        key=lambda m: m["label"]),
        "edges": sorted([h.nodes[c]["label"], m] for c in chans for m in h.neighbors(c)),
        "posts": sum(h.nodes[c]["posts"] for c in chans),
        "score": max((h.nodes[c]["score"] for c in chans), default=0.0),
        "tracks": [t for t, _ in tracks.most_common()],
        "parts": channel_parts(h),
        "key_nodes": [k.to_dict() for k in key_nodes(h)],
        "since": since,
        "fresh": fresh,
    }


def networks(g: nx.Graph, min_channels: int = MIN_NETWORK_CHANNELS) -> list[dict[str, Any]]:
    """Все сети в базе, крупные первыми."""
    h = money_graph(g)
    groups: list[set[str]] = []
    for comp in nx.connected_components(h):
        if len(comp) <= LOUVAIN_MIN_NODES:
            groups.append(comp)
            continue
        for community in nx.community.louvain_communities(h.subgraph(comp), weight="weight", seed=LOUVAIN_SEED):
            # Каналы сообщества вместе со всеми их реквизитами: иначе запасной номер в соседнем
            # сообществе пропадёт и канал ошибочно попадёт в «отрезанные от денег»
            chans = {n for n in community if h.nodes[n]["type"] == "channel"}
            with_money = chans | {m for c in chans for m in h.neighbors(c)}
            groups.extend(nx.connected_components(h.subgraph(with_money)))
    out = []
    for group in groups:
        sub = h.subgraph(group)
        if len(_channels(sub)) < min_channels:
            continue
        out.append(describe(sub))
    out.sort(key=lambda n: (-len(n["channels"]), -n["posts"], n["channels"]))
    for i, net in enumerate(out, 1):
        net["key"] = f"N-{i}"
    return out
