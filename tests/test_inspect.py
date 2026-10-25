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
from pruf import inspect as inspect_mod
from pruf.inspect import CUES, Inspector, blacklist_domain, text_hash
from pruf.normalize.requisites import redact_cards
from pruf.pipeline import Pruf, Submission
from tests.helpers import TEST_HMAC_KEY, make_settings

SCAM = "Пассивный доход 5% в день! Пригласи друзей, вход 5000 тг на каспи +7 701 655 07 42, сайт joy-slots-kz.top"


@pytest.fixture
def pruf(tmp_path: Path, detector):
    p = Pruf(make_settings(tmp_path), detector=detector, ocr_enabled=False)
    p.ingest(Submission(text=SCAM, channel="@kassa_demo"))
    p.ingest(Submission(text=SCAM + " Ждём вас!", channel="@invest_demo"))
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
    assert res["requisites"] == [{"type": "phone", "value": "+77016550742", "found": True, "tracks": ["pyramid"], "reported": False}]


def test_unknown_requisite_is_reported_without_counts(inspector: Inspector) -> None:
    res = inspector.inspect(["+7 777 000 11 22"], [], None, [])
    assert res["requisites"] == [{"type": "phone", "value": "+77770001122", "found": False, "tracks": [], "reported": False}]
    assert res["score"] == 0


def test_blacklist_has_only_risky_non_brand_domains(inspector: Inspector) -> None:
    assert inspector.blacklist() == ["joy-slots-kz.top"]


@pytest.mark.parametrize("domain,ok", [("joy-slots-kz.top", True), ("kaspi.kz", False), ("t.me", False),
                                       ("bit.ly", False), ("bad domain.kz", False), ("a.b", False),
                                       ("com.kz", False), ("kgd.gov.kz", False), ("pay.kaspi.kz", False),
                                       ("github.io", False), ("scam.github.io", True), ("www.halykbank.kz", False)])
def test_blacklist_domain_filter(domain: str, ok: bool) -> None:
    assert blacklist_domain(domain) is ok


def test_index_refreshes_after_new_ingest(pruf: Pruf, inspector: Inspector, monkeypatch: pytest.MonkeyPatch) -> None:
    casino = "Казино с выводом! Поднял x500, промокод WIN777, зеркало lucky-win-kz.bet, каспи +7 776 902 33 18"
    pruf.ingest(Submission(text=casino, channel="@slots_a"))
    inspector.refresh(pruf.version)
    assert "lucky-win-kz.bet" not in inspector.blacklist()  # один канал: мало, и индекс ещё не устарел
    pruf.ingest(Submission(text=casino + "!", channel="@slots_b"))
    inspector.refresh(pruf.version)
    assert "lucky-win-kz.bet" not in inspector.blacklist()  # пересборка не чаще INDEX_MIN_AGE
    monkeypatch.setattr(inspect_mod, "INDEX_MIN_AGE", 0.0)
    inspector.refresh(pruf.version)
    assert "lucky-win-kz.bet" in inspector.blacklist()


def test_single_channel_cannot_blacklist_a_domain(tmp_path: Path, detector) -> None:
    p = Pruf(make_settings(tmp_path / "one"), detector=detector, ocr_enabled=False)
    for i in range(3):
        p.ingest(Submission(text=f"{SCAM} #{i}", channel="@one_channel"))
    ins = Inspector(p.db, TEST_HMAC_KEY.encode())
    ins.refresh(p.version)
    assert ins.blacklist() == []
    p.db.close()


def test_text_hash_normalizes_case_and_punctuation() -> None:
    assert text_hash("Пассивный ДОХОД, 5% в день!") == text_hash("пассивный доход 5 в день")


@pytest.mark.skipif(shutil.which("node") is None, reason="нужен Node.js")
def test_text_hash_matches_extension() -> None:
    samples = ["Пассивный доход 5% в день!", "Күніне 3% табыс! Достарыңды шақыр", "ÉCOLE_ｆｕｌｌ　width ١٢٣", "ё и Ё",
               "Взнос на карту 4111 1111 1111 1111, итоги завтра", "Карта 4400\u200b4301 2345 6781 не по Луну"]
    script = ("const X=require(process.argv[1]);Promise.all(JSON.parse(process.argv[2]).map(X.textHash))"
              ".then(h=>console.log(JSON.stringify(h)))")
    out = subprocess.run(["node", "-e", script, str(ROOT / "extension/lib/extract.js"), json.dumps(samples)],
                         capture_output=True, text=True, check=True, timeout=30).stdout
    assert json.loads(out) == [text_hash(redact_cards(s)) for s in samples]  # сервер хэширует текст из реестра


@pytest.mark.skipif(shutil.which("node") is None, reason="нужен Node.js")
def test_extension_cue_ids_are_known_to_server() -> None:
    script = "const s=require('fs').readFileSync(process.argv[1],'utf8');console.log(JSON.stringify([...s.matchAll(/^    (\\w+): \\//gm)].map(m=>m[1])))"
    out = subprocess.run(["node", "-e", script, str(ROOT / "extension/lib/extract.js")], capture_output=True, text=True,
                         check=True, timeout=30).stdout
    assert sorted(json.loads(out)) == sorted(CUES)


@pytest.mark.skipif(shutil.which("node") is None, reason="нужен Node.js")
def test_extension_offline_verdict_matches_server_for_cues(inspector: Inspector) -> None:
    # Без сервера расширение считает балл само: веса, трек и заголовок должны совпасть с сервером
    cases = [["income_promise", "referral", "kaspi_transfer"], ["giveaway", "paid_entry", "urgency"], ["casino", "big_win"], ["urgency"]]
    script = ("const X=require(process.argv[1]);console.log(JSON.stringify(JSON.parse(process.argv[2]).map(c=>X.localVerdict(c))))")
    out = subprocess.run(["node", "-e", script, str(ROOT / "extension/lib/extract.js"), json.dumps(cases)],
                         capture_output=True, text=True, check=True, timeout=30).stdout
    for cues, local in zip(cases, json.loads(out)):
        server = inspector.inspect([], [], None, cues)
        for field in ("score", "level", "level_label", "track", "show_banner", "title"):
            assert local[field] == server[field], (cues, field)
        assert local["reasons"] == server["reasons"]


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
        assert pruf.db.count_posts() == 3  # проверка ничего не сохраняет


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


# ---------- жалобы пользователей ----------
FRESH = "+77051112233"  # номер, которого нет в реестре


def _report(client: TestClient, install_id: str, digest: str = "a" * 64, **extra):
    body = {"requisites": [FRESH], "links": ["https://new-casino-kz.top/x"], "text_hash": digest, "cues": ["casino"],
            "platform": "whatsapp", "install_id": install_id, **extra}
    return client.post("/api/v1/reports", json=body)


def test_reports_from_three_people_add_weight_to_requisite(tmp_path: Path, pruf: Pruf) -> None:
    with _client(tmp_path, pruf) as client:
        # Arrange: двое пожаловались, третий дважды нажал кнопку на один и тот же пост
        before = client.post("/api/v1/inspect", json={"requisites": [FRESH], "links": [], "cues": []}).json()["data"]
        accepted = [_report(client, f"install-{i}").json()["data"]["accepted"] for i in (1, 2)]
        two = client.post("/api/v1/inspect", json={"requisites": [FRESH], "links": [], "cues": []}).json()["data"]
        accepted.append(_report(client, "install-3").json()["data"]["accepted"])
        duplicate = _report(client, "install-3").json()["data"]["accepted"]

        # Act
        after = client.post("/api/v1/inspect", json={"requisites": [FRESH], "links": [], "cues": []}).json()["data"]

    # Assert
    assert accepted == [True, True, True] and duplicate is False
    assert before["score"] == two["score"] == 0  # одного-двух человек мало, чтобы оговорить номер
    assert [r["id"] for r in after["reasons"]] == ["registry.reports"]
    assert after["requisites"][0]["reported"] is True


def test_report_requires_something_to_report(tmp_path: Path, pruf: Pruf) -> None:
    with _client(tmp_path, pruf) as client:
        resp = _report(client, "install-1", requisites=[], links=[], cues=[])

    assert resp.status_code == 422


def test_analyst_sees_reported_requisites_without_reporters(tmp_path: Path, pruf: Pruf) -> None:
    with _client(tmp_path, pruf) as client:
        _report(client, "install-1")
        _report(client, "install-2", digest="b" * 64, platform="telegram", requisites=["+7 701 655 07 42"])

        body = client.get("/api/v1/reports").json()

    assert body["meta"]["total"] == 2
    rows = {r["value"]: r for r in body["data"]}
    assert rows["+77051112233"]["platforms"] == ["whatsapp"] and rows["+77051112233"]["in_registry"] is False
    assert rows["+77016550742"]["in_registry"] is True  # этот номер уже в реестре из постов
    assert all("reporter" not in r and "key" not in r for r in body["data"])


def test_report_needs_extension_token_outside_dev(tmp_path: Path, pruf: Pruf) -> None:
    with _client(tmp_path, pruf, dev_mode=False, extension_tokens=("ext:secret",), analyst_token="an") as client:
        denied = _report(client, "install-1")
        allowed = client.post("/api/v1/reports", headers={"Authorization": "Bearer secret"},
                              json={"requisites": [FRESH], "links": [], "text_hash": "c" * 64, "cues": [], "install_id": "install-9"})

    assert denied.status_code == 401
    assert allowed.status_code == 200 and allowed.json()["data"]["accepted"] is True


def test_demo_reports_mark_new_whatsapp_number_as_reported(pruf: Pruf) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("seed_demo", ROOT / "scripts/seed_demo.py")
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)

    assert seed.seed_reports(pruf) == 8
    ins = Inspector(pruf.db, pruf.settings.effective_hmac_key())
    res = ins.inspect(["+7 708 400 12 90", "+7 771 555 23 41"], [], None, [])
    assert [r["reported"] for r in res["requisites"]] == [True, False]  # три человека против одного
