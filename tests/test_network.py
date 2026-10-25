"""Сети и ключевые реквизиты: что заблокировать, чтобы отрезать схему от денег."""

import networkx as nx
from fastapi.testclient import TestClient

from pruf.api.app import create_app
from pruf.pipeline import Pruf, Submission
from tests.helpers import CASINO_RU, KASPI_PHONE, LOTTERY_RU, make_settings

from pruf.graph import network

LOTTERY = LOTTERY_RU.format(phone=KASPI_PHONE)
CASINO = CASINO_RU.format(phone=KASPI_PHONE)


def _post(g, pid, channel, level="high", score=90.0, track="pyramid", money=()):
    g.add_node(f"post:{pid}", type="post", channel=channel, level=level, score=score, track=track)
    for m in money:
        kind = "domain" if m.startswith("domain:") else "phone"
        g.add_node(m, type="domain" if kind == "domain" else "requisite", label=m.split(":", 1)[1], kind=kind)
        g.add_edge(f"post:{pid}", m, type="mentions")


def _pyramid():
    """Четыре канала на одном номере, у одного есть запасной домен, плюс отдельное казино."""
    g = nx.Graph()
    _post(g, 1, "@kassa", money=["req:+77016550742"])
    _post(g, 2, "@bystryi", money=["req:+77016550742"])
    _post(g, 3, "@invest", money=["req:+77016550742"])
    _post(g, 4, "@crypto", money=["req:+77016550742", "domain:x2-crypto.top"])
    _post(g, 5, "@slots", track="casino", money=["domain:joy-slots-kz.top"])
    _post(g, 6, "@kazino", track="casino", money=["domain:joy-slots-kz.top"])
    return g


def test_key_node_is_the_number_that_cuts_most_channels_from_money():
    # Arrange
    h = network.money_graph(_pyramid())
    pyramid = h.subgraph(nx.node_connected_component(h, "req:+77016550742"))

    # Act
    keys = network.key_nodes(pyramid)

    # Assert
    top = keys[0]
    assert top.label == "+77016550742"
    assert set(top.cut_off) == {"@kassa", "@bystryi", "@invest"}  # у @crypto остаётся домен
    assert len(top.channels) == 4
    assert top.parts_after == 4  # три отрезанных канала и @crypto со своим доменом


def test_networks_split_unrelated_schemes_and_rank_bigger_first():
    nets = network.networks(_pyramid())

    assert [n["key"] for n in nets] == ["N-1", "N-2"]
    assert nets[0]["channels"] == ["@bystryi", "@crypto", "@invest", "@kassa"]
    assert nets[0]["tracks"] == ["pyramid"]
    assert nets[1]["key_nodes"][0]["label"] == "joy-slots-kz.top"
    assert ["@kassa", "req:+77016550742"] in nets[0]["edges"]


def test_low_risk_posts_and_hubs_do_not_build_networks():
    g = _pyramid()
    _post(g, 7, "@news", level="low", score=5, money=["req:+77016550742"])
    g.nodes["domain:joy-slots-kz.top"]["hub"] = True

    nets = network.networks(g)

    assert all("@news" not in n["channels"] for n in nets)
    assert all("@slots" not in n["channels"] for n in nets)  # хаб не связывает каналы


def test_promo_code_links_channels_but_is_never_a_key_requisite():
    g = nx.Graph()
    _post(g, 1, "@a", track="casino", money=["req:WIN777", "domain:a.top"])
    _post(g, 2, "@b", track="casino", money=["req:WIN777", "domain:b.top"])
    for n in ("req:WIN777",):
        g.nodes[n]["kind"] = "promo"

    nets = network.networks(g)

    assert nets[0]["channels"] == ["@a", "@b"]
    assert all(k["kind"] != "promo" for k in nets[0]["key_nodes"])
    assert nets[0]["key_nodes"][0]["cut_off"] in (["@a"], ["@b"])


def test_single_channel_is_not_a_network():
    g = nx.Graph()
    _post(g, 1, "@solo", money=["req:+77770000000", "domain:solo.top"])

    assert network.networks(g) == []


def test_money_graph_respects_case_posts():
    h = network.money_graph(_pyramid(), post_ids=[5, 6])

    assert sorted(h.nodes[n]["label"] for n in h if h.nodes[n]["type"] == "channel") == ["@kazino", "@slots"]


def test_large_component_is_split_into_communities():
    # Две плотные группы по 25 каналов, связанные одним общим доменом
    g = nx.Graph()
    pid = 0
    for group, phone in (("a", "req:+77000000001"), ("b", "req:+77000000002")):
        for i in range(25):
            pid += 1
            _post(g, pid, f"@{group}{i}", money=[phone])
    pid += 1
    _post(g, pid, "@bridge", money=["req:+77000000001", "req:+77000000002"])

    nets = network.networks(g)

    assert len(nets) >= 2
    assert all(len(n["channels"]) < 51 for n in nets)


def test_backup_number_in_another_community_is_not_cut_off():
    # Канал @x принимает деньги на номера обеих больших групп: блокировка одного его не отрезает
    g = nx.Graph()
    pid = 0
    for group, phone in (("a", "req:+77000000001"), ("b", "req:+77000000002")):
        for i in range(25):
            pid += 1
            _post(g, pid, f"@{group}{i}", money=[phone])
    _post(g, pid + 1, "@x", money=["req:+77000000001", "req:+77000000002"])

    nets = network.networks(g)

    for net in nets:
        for key in net["key_nodes"]:
            assert "@x" not in key["cut_off"]


def test_post_counts_once_even_with_several_requisites():
    g = nx.Graph()
    _post(g, 1, "@a", money=["req:+77000000001", "domain:a.top", "req:+77000000003"])
    _post(g, 2, "@b", money=["req:+77000000001"])

    net = network.networks(g)[0]

    assert net["posts"] == 2


def test_case_card_and_networks_endpoint_show_key_requisite(tmp_path):
    # Arrange: два канала просят перевести на один номер Kaspi
    settings = make_settings(tmp_path)
    p = Pruf(settings, ocr_enabled=False)
    first = p.ingest(Submission(text=LOTTERY, channel="@loto1"))
    p.ingest(Submission(text=CASINO, channel="@slots2"))
    with TestClient(create_app(settings, pruf=p)) as client:
        # Act
        card = client.get(f"/api/v1/cases/C-{first['post_id']}").json()["data"]
        nets = client.get("/api/v1/networks").json()

    # Assert
    net = card["network"]
    assert net["channels"] == ["@loto1", "@slots2"]
    assert net["key_nodes"][0]["kind"] == "phone"
    assert sorted(net["key_nodes"][0]["cut_off"]) == ["@loto1", "@slots2"]
    assert nets["success"] is True and nets["meta"]["total"] == 1
    assert nets["data"][0]["key_nodes"][0]["label"] == net["key_nodes"][0]["label"]


def test_requisite_added_later_is_reported_as_rotation():
    # Сеть началась с одного номера, через неделю два канала перешли на новый
    g = nx.Graph()
    _post(g, 1, "@a", money=["req:+77000000001"])
    _post(g, 2, "@b", money=["req:+77000000001"])
    _post(g, 3, "@a", money=["req:+77000000009"])
    _post(g, 4, "@b", money=["req:+77000000009", "domain:new-site.top"])
    for pid, when in ((1, "2026-10-01T10:00:00"), (2, "2026-10-02T10:00:00"), (3, "2026-10-08T09:00:00"), (4, "2026-10-09T09:00:00")):
        g.nodes[f"post:{pid}"]["posted_at"] = when

    net = network.networks(g)[0]

    assert net["since"] == "2026-10-01"
    assert [(f["label"], f["first_seen"]) for f in net["fresh"]] == [("new-site.top", "2026-10-09"), ("+77000000009", "2026-10-08")]
    assert net["fresh"][1]["channels"] == ["@a", "@b"]


def test_network_without_dates_has_no_rotation():
    net = network.networks(_pyramid())[0]

    assert net["since"] is None and net["fresh"] == []
