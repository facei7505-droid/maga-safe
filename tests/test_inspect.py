"""Расширение ПРУФ Sentinel: /api/v1/inspect без текста поста и чёрный список доменов."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pruf.api.app import create_app
from pruf.config import ROOT
from pruf.inspect import CUES, Inspector, blacklist_domain, text_hash
from pruf.pipeline import Pruf, Submission
from tests.helpers import TEST_HMAC_KEY, make_settings

SCAM = "Пассивный доход 5% в день! Пригласи друзей, вход 5000 тг на каспи +7 701 655 07 42, сайт joy-slots-kz.top"


@pytest.fixture
def pruf(tmp_path: Path, detector):
    p = Pruf(make_settings(tmp_path), detector=detector, ocr_enabled=False)
    p.ingest(Submission(text=SCAM, channel="@kassa_demo"))
    p.ingest(Submission(text="Бешбармак по-домашнему, заходите на recepty.kz", channel="@food_demo"))
    yield p
    p.db.close()


@pytest.fixture
def inspector(pruf: Pruf) -> Inspector:
    ins = Inspector(pruf.db, TEST_HMAC_KEY.encode())
    ins.refresh(pruf.version)
    return ins


def _client(tmp_path: Path, pruf: Pruf | None = None, **overrides) -> TestClient:
    settings = make_settings(tmp_path, **overrides)
    return TestClient(create_app(settings, pruf=pruf or Pruf(settings, ocr_enabled=False)), raise_server_exceptions=False)


def test_cues_alone_raise_banner_with_readable_title(inspector: Inspector) -> None:
    res = inspector.inspect([], [], None, ["income_promise", "referral", "kaspi_transfer", "unknown_cue"])
    assert res["score"] == 75 and res["show_banner"] and res["track"] == "pyramid"
    assert res["title"] == "Признаки финансовой пирамиды: обещание дохода, доход за приглашённых, перевод на Kaspi"
    assert "unknown_cue" not in {r["id"] for r in res["reasons"]}


def test_weak_cue_does_not_raise_banner(inspector: Inspector) -> None:
    res = inspector.inspect([], [], None, ["giveaway"])
    assert not res["show_banner"] and res["level"] == "low"


def test_registry_requisite_domain_and_text_copy(inspector: Inspector) -> None:
    res = inspector.inspect(["8 701 655 07 42"], ["https://www.joy-slots-kz.top/promo"], text_hash(SCAM), [])
    ids = {r["id"] for r in res["reasons"]}
    assert ids == {"registry.requisite", "registry.domain", "registry.text_copy"}
    assert res["score"] == 100 and res["blacklisted_domains"] == ["joy-slots-kz.top"]
    assert res["requisites"] == [{"type": "phone", "value": "+77016550742", "found": True, "tracks": ["pyramid"]}]


def test_unknown_requisite_is_reported_without_counts(inspector: Inspector) -> None:
    res = inspector.inspect(["+7 777 000 11 22"], [], None, [])
    assert res["requisites"] == [{"type": "phone", "value": "+77770001122", "found": False, "tracks": []}]
    assert res["score"] == 0


def test_blacklist_has_only_risky_non_brand_domains(inspector: Inspector) -> None:
    assert inspector.blacklist() == ["joy-slots-kz.top"]


@pytest.mark.parametrize("domain,ok", [("joy-slots-kz.top", True), ("kaspi.kz", False), ("t.me", False),
                                       ("bit.ly", False), ("bad domain.kz", False), ("a.b", False)])
def test_blacklist_domain_filter(domain: str, ok: bool) -> None:
    assert blacklist_domain(domain) is ok


def test_index_refreshes_after_new_ingest(pruf: Pruf, inspector: Inspector) -> None:
    pruf.ingest(Submission(text="Казино с выводом! Поднял x500, промокод WIN777, зеркало lucky-win-kz.bet, каспи +7 776 902 33 18"))
    inspector.refresh(pruf.version)
    assert "lucky-win-kz.bet" in inspector.blacklist()


def test_text_hash_normalizes_case_and_punctuation() -> None:
    assert text_hash("Пассивный ДОХОД, 5% в день!") == text_hash("пассивный доход 5 в день")


@pytest.mark.skipif(shutil.which("node") is None, reason="нужен Node.js")
def test_text_hash_matches_extension() -> None:
    samples = ["Пассивный доход 5% в день!", "Күніне 3% табыс! Достарыңды шақыр", "ÉCOLE_ｆｕｌｌ　width ١٢٣", "ё и Ё"]
    script = ("const X=require(process.argv[1]);Promise.all(JSON.parse(process.argv[2]).map(X.textHash))"
              ".then(h=>console.log(JSON.stringify(h)))")
    out = subprocess.run(["node", "-e", script, str(ROOT / "extension/lib/extract.js"), json.dumps(samples)],
                         capture_output=True, text=True, check=True, timeout=30).stdout
    assert json.loads(out) == [text_hash(s) for s in samples]


@pytest.mark.skipif(shutil.which("node") is None, reason="нужен Node.js")
def test_extension_cue_ids_are_known_to_server() -> None:
    script = "const s=require('fs').readFileSync(process.argv[1],'utf8');console.log(JSON.stringify([...s.matchAll(/^    (\\w+): \\//gm)].map(m=>m[1])))"
    out = subprocess.run(["node", "-e", script, str(ROOT / "extension/lib/extract.js")], capture_output=True, text=True,
                         check=True, timeout=30).stdout
    assert sorted(json.loads(out)) == sorted(CUES)


@pytest.mark.skipif(shutil.which("node") is None, reason="нужен Node.js")
def test_extension_unit_tests_pass() -> None:
    res = subprocess.run(["node", "--test", *map(str, sorted((ROOT / "extension/test").glob("*.test.js")))],
                         capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stdout[-2000:]


# ---------- API ----------
def test_inspect_endpoint_in_dev_mode(tmp_path: Path, pruf: Pruf) -> None:
    with _client(tmp_path, pruf) as client:
        r = client.post("/api/v1/inspect", json={"requisites": ["+77016550742"], "links": [], "cues": ["income_promise"],
                                                  "text_hash": text_hash(SCAM)})
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["show_banner"] and data["score"] == 100
        assert client.get("/api/v1/blacklist/domains").json()["data"] == ["joy-slots-kz.top"]
        assert pruf.db.count_posts() == 2  # проверка ничего не сохраняет


def test_inspect_rejects_post_text_and_oversized_fields(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        assert client.post("/api/v1/inspect", json={"text_hash": "not-a-hash"}).status_code == 422
        assert client.post("/api/v1/inspect", json={"requisites": ["1" * 65]}).status_code == 422
        assert client.post("/api/v1/inspect", json={"links": ["x"] * 21}).status_code == 422
        assert client.post("/api/v1/inspect", json={"links": ["http://a.kz/" + "a" * 2050]}).status_code == 422
        r = client.post("/api/v1/inspect", json={"text": SCAM})  # лишнее поле игнорируется, текст не анализируется
        assert r.status_code == 200 and r.json()["data"]["score"] == 0


def test_extension_token_is_required_outside_dev(tmp_path: Path) -> None:
    with _client(tmp_path, dev_mode=False, analyst_token="a:" + "x" * 32, extension_tokens=("chrome:" + "e" * 32,)) as client:
        assert client.post("/api/v1/inspect", json={}).status_code == 401
        assert client.get("/api/v1/blacklist/domains").status_code == 401
        # токен аналитика не подходит расширению, и наоборот
        assert client.get("/api/v1/blacklist/domains", headers={"Authorization": "Bearer " + "x" * 32}).status_code == 401
        ok = {"Authorization": "Bearer " + "e" * 32}
        assert client.get("/api/v1/blacklist/domains", headers=ok).status_code == 200
        assert client.get("/api/v1/scout", headers=ok).status_code == 401


def test_extension_endpoints_need_configured_tokens(tmp_path: Path) -> None:
    with _client(tmp_path, dev_mode=False, analyst_token="a:" + "x" * 32) as client:
        assert client.post("/api/v1/inspect", json={}).status_code == 503


def test_scout_view_lists_channels_and_edges(tmp_path: Path, pruf: Pruf) -> None:
    pruf.db.scout_save_channel({"username": "kassa_demo", "title": "Касса", "risk": 90.0, "level": "high", "status": "risky",
                                "found_via": "seed", "depth": 0, "last_checked": "2026-10-25T12:00:00+00:00"})
    pruf.db.scout_add_edge("kassa_demo", "invest_demo", "requisite", "+77016550742")
    with _client(tmp_path, pruf) as client:
        data = client.get("/api/v1/scout").json()["data"]
    assert data["channels"][0]["username"] == "kassa_demo"
    assert data["edges"][0]["via"] == "requisite"
