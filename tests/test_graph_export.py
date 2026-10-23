"""Граф кейсов (кейсы, хабы, семейства, связанные посты, таймлайн пруфа) и пакет доказательств."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest

from pruf.export import DISCLAIMER, build_evidence_package
from pruf.graph.builder import CaseGraph, artifact_timeline
from pruf.pipeline import Pruf, Submission, Upload
from tests.helpers import CASINO_RU, LOTTERY_RU, PYRAMID_RU, make_settings

SYNTH_LABEL = "synthetic-label-must-not-leak"


@pytest.fixture
def pruf(tmp_path: Path):
    p = Pruf(make_settings(tmp_path), ocr_enabled=False)
    yield p
    p.db.close()


def ingest(p: Pruf, text: str, *, image: bytes | None = None, channel: str | None = None,
           posted_at: str | None = None) -> int:
    uploads = (Upload(image, "image", "jpg"),) if image else ()
    return p.ingest(Submission(text=text, uploads=uploads, channel=channel, posted_at=posted_at, label=SYNTH_LABEL))["post_id"]


def built(p: Pruf) -> CaseGraph:
    g = CaseGraph(p.db)
    g.ensure(p.version)
    return g


def lottery(phone: str) -> str:
    return LOTTERY_RU.format(phone=phone)


# ---------- кейсы ----------
def test_shared_channel_does_not_link_cases(pruf: Pruf) -> None:
    # Arrange
    a = ingest(pruf, lottery("+7 701 111 11 11"), channel="same")
    b = ingest(pruf, CASINO_RU.format(phone="+7 702 222 22 22"), channel="same")

    # Act
    g = built(pruf)

    # Assert
    assert sorted(c.post_ids for c in g.cases()) == [(a,), (b,)]
    assert g.case_for_post(a) == f"C-{a}" and g.case_for_post(b) == f"C-{b}"


def test_case_summary_fields(pruf: Pruf) -> None:
    # Arrange
    a = ingest(pruf, lottery("+7 701 111 11 11") + " vulkan-kz.top", channel="ch1", posted_at="2026-10-01T00:00:00")
    b = ingest(pruf, PYRAMID_RU.format(phone="+7 701 111 11 11"), channel="ch2", posted_at="2026-10-03T00:00:00")

    # Act
    case = built(pruf).case(f"C-{a}")

    # Assert
    data = case.to_dict()
    assert data["post_ids"] == [a, b] and data["size"] == 2
    assert case.requisites == ("+77011111111",)
    assert case.domains == ("vulkan-kz.top",)
    assert case.channels == ("ch1", "ch2")
    assert (case.first_seen, case.last_seen) == ("2026-10-01T00:00:00", "2026-10-03T00:00:00")
    assert set(case.tracks) == {"lottery", "pyramid"}
    assert case.level == "high"


def test_low_posts_are_attached_as_context_but_do_not_bridge_cases(pruf: Pruf) -> None:
    # Arrange: обычный пост упоминает номера двух разных схем
    a = ingest(pruf, lottery("+7 701 111 11 11"))
    b = ingest(pruf, CASINO_RU.format(phone="+7 702 222 22 22"))
    low = ingest(pruf, "Мои номера: +7 701 111 11 11 и +7 702 222 22 22, звоните вечером")

    # Act
    g = built(pruf)

    # Assert
    assert len(g.cases()) == 2
    assert low in g.case(f"C-{a}").post_ids and low in g.case(f"C-{b}").post_ids
    assert g.case_for_post(low) in (f"C-{a}", f"C-{b}")


def test_hub_requisite_does_not_link_cases(pruf: Pruf) -> None:
    # Arrange: номер встречается в двух схемах и в пяти обычных постах (>70% без признаков)
    hub_phone = "+7 700 000 00 00"
    a = ingest(pruf, lottery(hub_phone))
    for i in range(6):
        ingest(pruf, f"Служба доставки, звоните {hub_phone}, заказ номер {i}")
    b = ingest(pruf, CASINO_RU.format(phone=hub_phone))

    # Act
    g = built(pruf)

    # Assert
    assert g.case_for_post(a) != g.case_for_post(b)
    assert g.graph.nodes["req:phone:+77000000000"].get("hub") is True


def test_case_key_with_status_survives_merge(pruf: Pruf) -> None:
    # Arrange: два отдельных кейса, у второго аналитик уже выставил статус
    a = ingest(pruf, lottery("+7 701 111 11 11"))
    b = ingest(pruf, CASINO_RU.format(phone="+7 702 222 22 22"))
    g = built(pruf)
    pruf.db.set_case_status(f"C-{b}", "in_review", "проверяю", "tester")

    # Act: новый рискованный пост связывает оба номера
    ingest(pruf, PYRAMID_RU.format(phone="+7 701 111 11 11") + " и +7 702 222 22 22")
    g.ensure(pruf.version, force=True)

    # Assert
    assert [c.key for c in g.cases()] == [f"C-{b}"]
    assert a in g.case(f"C-{b}").post_ids


def test_ensure_skips_rebuild_for_same_version(pruf: Pruf) -> None:
    # Arrange
    ingest(pruf, lottery("+7 701 111 11 11"))
    g = built(pruf)
    first_graph = g.graph

    # Act
    g.ensure(pruf.version)

    # Assert
    assert g.graph is first_graph


def test_reused_image_forms_campaign_family_and_related_posts(pruf: Pruf, original_jpeg: bytes) -> None:
    # Arrange
    a = ingest(pruf, lottery("+7 701 111 11 11"), image=original_jpeg)
    b = ingest(pruf, PYRAMID_RU.format(phone="+7 703 333 33 33"), image=original_jpeg)
    c = ingest(pruf, CASINO_RU.format(phone="+7 701 111 11 11"))

    # Act
    g = built(pruf)
    case = g.case(g.case_for_post(a))

    # Assert
    assert set(case.post_ids) == {a, b, c}
    assert case.families == 1
    assert g.families(case.post_ids) == [sorted([a, b])]
    assert g.related_posts(a) == sorted([b, c])
    assert g.related_posts(9999) == []
    sub = g.subgraph(case.post_ids)
    types = {n["type"] for n in sub["nodes"]}
    assert {"post", "requisite"} <= types
    assert any(e["type"] == "reuses" for e in sub["edges"])


def test_related_posts_of_isolated_post_is_empty(pruf: Pruf) -> None:
    # Arrange
    a = ingest(pruf, "Просто пост без реквизитов", channel="ch")

    # Act / Assert
    assert built(pruf).related_posts(a) == []


def test_artifact_timeline_lists_all_appearances(pruf: Pruf, original_jpeg: bytes) -> None:
    # Arrange
    a = ingest(pruf, lottery("+7 701 111 11 11"), image=original_jpeg, posted_at="2026-10-01T00:00:00")
    ingest(pruf, "Вот пруф", image=original_jpeg, posted_at="2026-10-02T00:00:00")
    ingest(pruf, "И ещё пруф", image=original_jpeg, posted_at="2026-09-30T00:00:00")
    root = pruf.db.artifacts_for_post(a)[0]["id"]

    # Act
    timeline = artifact_timeline(pruf.db, root)

    # Assert
    assert timeline["appearances"] == 3
    dates = [i["post"]["posted_at"] for i in timeline["items"]]
    assert dates == sorted(dates)
    assert [i["is_root"] for i in timeline["items"]].count(True) == 1
    assert all(i["kind"] == "image" for i in timeline["items"])


# ---------- пакет доказательств ----------
def _export(pruf: Pruf, post_id: int) -> tuple[zipfile.ZipFile, str, dict]:
    g = built(pruf)
    case = g.case(g.case_for_post(post_id))
    data, digest = build_evidence_package(pruf.db, pruf.blobs, g, case, "tester")
    zf = zipfile.ZipFile(io.BytesIO(data))
    return zf, digest, json.loads(zf.read("manifest.json"))


def test_export_manifest_hashes_match_zip_contents(pruf: Pruf, original_jpeg: bytes) -> None:
    # Arrange
    a = ingest(pruf, lottery("+7 701 111 11 11"), image=original_jpeg)
    ingest(pruf, CASINO_RU.format(phone="+7 701 111 11 11"))

    # Act
    zf, digest, manifest = _export(pruf, a)

    # Assert
    names = set(zf.namelist())
    assert {"manifest.json", "manifest.sha256", "report.html", "posts.json", "graph.json"} <= names
    assert set(manifest["files"]) == names - {"manifest.json", "manifest.sha256"}
    for name, sha in manifest["files"].items():
        assert hashlib.sha256(zf.read(name)).hexdigest() == sha
    assert hashlib.sha256(zf.read("manifest.json")).hexdigest() == digest
    assert zf.read("manifest.sha256").decode() == f"{digest}  manifest.json\n"
    assert zf.read(manifest["artifacts"][0]["file"]) == original_jpeg
    assert manifest["disclaimer"] == DISCLAIMER and manifest["exported_by"] == "tester"
    assert manifest["generated_at_utc"].endswith("+00:00")
    assert manifest["missing_artifacts"] == []


def test_export_does_not_leak_synthetic_label(pruf: Pruf, original_jpeg: bytes) -> None:
    # Arrange
    a = ingest(pruf, lottery("+7 701 111 11 11"), image=original_jpeg)

    # Act
    zf, _, _ = _export(pruf, a)

    # Assert
    posts = json.loads(zf.read("posts.json"))
    assert posts and all("label" not in p for p in posts)
    for name in zf.namelist():
        assert SYNTH_LABEL.encode() not in zf.read(name), name


def test_export_report_escapes_html_from_posts(pruf: Pruf) -> None:
    # Arrange
    a = ingest(pruf, lottery("+7 701 111 11 11") + " <script>alert(1)</script>")

    # Act
    zf, _, _ = _export(pruf, a)
    report = zf.read("report.html").decode()

    # Assert
    assert "<script>" not in report
    assert "&lt;script&gt;" in report
    assert DISCLAIMER in report


def test_export_lists_missing_blobs_and_writes_audit(pruf: Pruf, original_jpeg: bytes) -> None:
    # Arrange: файл артефакта пропал из хранилища
    a = ingest(pruf, lottery("+7 701 111 11 11"), image=original_jpeg)
    art = pruf.db.artifacts_for_post(a)[0]
    pruf.blobs.path_for(art["sha256"], art["ext"]).unlink()

    # Act
    zf, digest, manifest = _export(pruf, a)

    # Assert
    assert manifest["missing_artifacts"] == [{"post_id": a, "artifact_id": art["id"], "sha256": art["sha256"]}]
    assert not any(n.startswith("artifacts/") for n in zf.namelist())
    audit = pruf.db._all("SELECT actor, action, target FROM audit_log")
    assert audit[-1]["action"] == "export" and audit[-1]["target"].endswith(digest)
