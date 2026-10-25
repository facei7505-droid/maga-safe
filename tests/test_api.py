"""HTTP API: авторизация, конверт ответа, приём, кейсы, экспорт, артефакты, лента банков, лимиты."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pruf.api.app import MAX_FILES, create_app
from pruf.api.security import sniff_upload
from pruf.config import Settings
from pruf.pipeline import Pruf, Submission
from tests.helpers import CASINO_RU, KASPI_PHONE, LOTTERY_RU, make_settings

ANALYST = "analyst-secret-token"
BANK = "bank-secret-token"
LOTTERY = LOTTERY_RU.format(phone=KASPI_PHONE)
CASINO = CASINO_RU.format(phone=KASPI_PHONE)


@pytest.fixture(autouse=True)
def _single_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)


def _client(tmp_path: Path, **overrides) -> TestClient:
    settings = make_settings(tmp_path, **overrides)
    app = create_app(settings, pruf=Pruf(settings, ocr_enabled=False))
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def dev(tmp_path: Path):
    with _client(tmp_path) as client:
        yield client


@pytest.fixture
def secured(tmp_path: Path):
    with _client(tmp_path, dev_mode=False, analyst_token=f"alice:{ANALYST}", bank_tokens=(f"halyk:{BANK}",)) as client:
        yield client


def _auth(token: str = ANALYST) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _post_text(client: TestClient, text: str, headers: dict | None = None, **extra):
    return client.post("/api/v1/analyze/text", json={"text": text, **extra}, headers=headers or {})


def _assert_envelope(body: dict, success: bool) -> None:
    assert set(body) == {"success", "data", "error", "meta"}
    assert body["success"] is success
    if success:
        assert body["error"] is None
    else:
        assert body["data"] is None and isinstance(body["error"], str)


# ---------- авторизация ----------
def test_health_is_public_and_has_security_headers(secured: TestClient) -> None:
    # Act
    resp = secured.get("/api/v1/health")

    # Assert
    assert resp.status_code == 200
    _assert_envelope(resp.json(), True)
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert "frame-ancestors 'none'" in resp.headers["content-security-policy"]


def test_analyst_endpoints_require_token(secured: TestClient) -> None:
    # Act
    missing = _post_text(secured, LOTTERY)
    wrong = _post_text(secured, LOTTERY, headers=_auth("wrong-token"))
    api_key = secured.post("/api/v1/analyze/text", json={"text": LOTTERY}, headers={"X-API-Key": ANALYST})

    # Assert
    assert missing.status_code == 401 and wrong.status_code == 401
    _assert_envelope(missing.json(), False)
    assert api_key.status_code == 200


def test_valid_token_is_audited_by_name(secured: TestClient) -> None:
    # Arrange
    key = _post_text(secured, LOTTERY, headers=_auth()).json()["data"]["post_id"]
    case_key = secured.get("/api/v1/cases", headers=_auth()).json()["data"][0]["key"]

    # Act
    resp = secured.patch(f"/api/v1/cases/{case_key}", json={"status": "confirmed"}, headers=_auth())
    status = secured.get(f"/api/v1/cases/{case_key}", headers=_auth()).json()["data"]["status"]

    # Assert
    assert key and resp.status_code == 200
    assert status["updated_by"] == "analyst:alice"


def test_dev_mode_without_token_is_open(dev: TestClient) -> None:
    resp = _post_text(dev, LOTTERY)
    assert resp.status_code == 200


def test_server_without_analyst_token_outside_dev_refuses(tmp_path: Path) -> None:
    # Arrange
    with _client(tmp_path, dev_mode=False, analyst_token="") as client:
        # Act
        resp = _post_text(client, LOTTERY, headers=_auth())

    # Assert
    assert resp.status_code == 503


def test_settings_from_env_drive_auth(env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("PRUF_DEV_MODE", "0")
    monkeypatch.setenv("PRUF_ANALYST_TOKEN", ANALYST)
    settings = Settings()
    app = create_app(settings, pruf=Pruf(settings, ocr_enabled=False))

    # Act
    with TestClient(app) as client:
        no_token = _post_text(client, LOTTERY)
        ok = _post_text(client, LOTTERY, headers=_auth())

    # Assert
    assert no_token.status_code == 401 and ok.status_code == 200


def test_rate_limit_returns_429(tmp_path: Path) -> None:
    # Arrange
    with _client(tmp_path, rate_limit_per_minute=3) as client:
        # Act
        codes = [client.get("/api/v1/stats").status_code for _ in range(4)]

    # Assert
    assert codes == [200, 200, 200, 429]


def test_rate_limit_cannot_be_bypassed_by_rotating_bad_tokens(tmp_path: Path) -> None:
    # Arrange
    with _client(tmp_path, dev_mode=False, analyst_token=ANALYST, rate_limit_per_minute=3) as client:
        # Act
        codes = [client.get("/api/v1/stats", headers=_auth(f"guess-{i:08d}")).status_code for i in range(4)]

    # Assert
    assert codes == [401, 401, 401, 429]


def test_webconcurrency_above_one_refuses_startup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    settings = make_settings(tmp_path)
    core = Pruf(settings, ocr_enabled=False)

    # Act / Assert
    with pytest.raises(RuntimeError), TestClient(create_app(settings, pruf=core)):
        pass
    core.db.close()


# ---------- приём ----------
def test_analyze_text_returns_analysis_in_envelope(dev: TestClient) -> None:
    # Act
    resp = _post_text(dev, LOTTERY, channel="@chan", posted_at="2026-10-01T00:00:00")

    # Assert
    body = resp.json()
    _assert_envelope(body, True)
    data = body["data"]
    assert data["analysis"]["level"] == "high" and data["analysis"]["track"] == "lottery"
    assert data["analysis"]["level_label"] == "высокий"
    assert isinstance(data["post_id"], int)


def test_analyze_text_without_store_does_not_save(dev: TestClient) -> None:
    # Act
    resp = _post_text(dev, LOTTERY, store=False)
    stats = dev.get("/api/v1/stats").json()["data"]

    # Assert
    assert resp.json()["data"]["level"] == "high"
    assert stats["posts"] == 0


def test_analyze_text_validation_error_uses_envelope(dev: TestClient) -> None:
    # Act
    resp = _post_text(dev, "")

    # Assert
    assert resp.status_code == 422
    _assert_envelope(resp.json(), False)
    assert "text" in resp.json()["error"]


def test_multipart_analyze_with_image(dev: TestClient, original_jpeg: bytes) -> None:
    # Act
    resp = dev.post("/api/v1/analyze", data={"text": LOTTERY, "channel": "@c"},
                    files=[("files", ("screen.png", original_jpeg, "image/png"))])  # имя и тип врут: важна сигнатура

    # Assert
    assert resp.status_code == 200
    proof = resp.json()["data"]["proofs"][0]
    art = dev.get(f"/api/v1/artifacts/{proof['artifact_id']}").json()["data"]
    assert art["ext"] == "jpg" and art["kind"] == "image"


def test_multipart_analyze_with_audio_and_transcript(dev: TestClient) -> None:
    # Act
    resp = dev.post("/api/v1/analyze", data={"transcript": CASINO},
                    files=[("files", ("voice.ogg", b"OggS" + b"\x00" * 40, "audio/ogg"))])

    # Assert
    assert resp.status_code == 200
    assert resp.json()["data"]["analysis"]["track"] == "casino"


def test_multipart_rejects_unknown_file_type(dev: TestClient) -> None:
    # Act
    resp = dev.post("/api/v1/analyze", data={"text": "x"}, files=[("files", ("doc.jpg", b"%PDF-1.7 fake", "image/jpeg"))])

    # Assert
    assert resp.status_code == 415
    _assert_envelope(resp.json(), False)


def test_multipart_rejects_oversized_file(tmp_path: Path) -> None:
    # Arrange
    with _client(tmp_path, max_upload_bytes=1000) as client:
        # Act
        resp = client.post("/api/v1/analyze", files=[("files", ("a.jpg", b"\xff\xd8\xff" + b"0" * 1500, "image/jpeg"))])

    # Assert
    assert resp.status_code == 413


def test_oversized_request_body_is_rejected_by_middleware(tmp_path: Path) -> None:
    # Arrange: тело больше MAX_FILES × лимит + запас
    with _client(tmp_path, max_upload_bytes=1000) as client:
        # Act
        resp = client.post("/api/v1/analyze/text", content=b"x" * (MAX_FILES * 1000 + 300 * 1024),
                           headers={"content-type": "application/json"})

    # Assert
    assert resp.status_code == 413
    _assert_envelope(resp.json(), False)


def test_multipart_rejects_too_many_files(dev: TestClient) -> None:
    # Act
    files = [("files", (f"{i}.ogg", b"OggS" + bytes([i]), "audio/ogg")) for i in range(MAX_FILES + 1)]
    resp = dev.post("/api/v1/analyze", files=files)

    # Assert
    assert resp.status_code == 413


def test_multipart_requires_some_content(dev: TestClient) -> None:
    assert dev.post("/api/v1/analyze", data={"channel": "x"}).status_code == 400


def test_multipart_image_with_valid_magic_but_garbage_is_422(dev: TestClient) -> None:
    # Act
    resp = dev.post("/api/v1/analyze", files=[("files", ("a.jpg", b"\xff\xd8\xff" + b"garbage" * 10, "image/jpeg"))])

    # Assert
    assert resp.status_code == 422
    _assert_envelope(resp.json(), False)
    assert dev.get("/api/v1/stats").json()["data"]["posts"] == 0


@pytest.mark.parametrize("kind", ["truncated_jpeg", "garbage_png"])
def test_multipart_corrupted_image_is_422_not_500(dev: TestClient, original_jpeg: bytes, kind: str) -> None:
    # Arrange
    payload = original_jpeg[:2000] if kind == "truncated_jpeg" else b"\x89PNG\r\n\x1a\n" + b"garbage" * 10

    # Act
    resp = dev.post("/api/v1/analyze", files=[("files", ("a.img", payload, "image/jpeg"))])

    # Assert
    assert resp.status_code == 422


def test_multipart_decompression_bomb_is_rejected(dev: TestClient) -> None:
    # Arrange: PNG-заголовок 20000×20000 без данных
    from tests.test_registry_units import _png_header_only

    # Act
    resp = dev.post("/api/v1/analyze", files=[("files", ("bomb.png", _png_header_only(20000, 20000), "image/png"))])

    # Assert
    assert resp.status_code in (413, 422)


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (b"\xff\xd8\xff\xe0", ("image", "jpg")),
        (b"\x89PNG\r\n\x1a\n", ("image", "png")),
        (b"RIFF\x00\x00\x00\x00WEBPVP8 ", ("image", "webp")),
        (b"OggS\x00", ("audio", "ogg")),
        (b"ID3\x04", ("audio", "mp3")),
        (b"\xff\xfb\x90", ("audio", "mp3")),
        (b"RIFF\x00\x00\x00\x00WAVEfmt ", ("audio", "wav")),
        (b"\x00\x00\x00\x20ftypM4A ", ("audio", "m4a")),
    ],
)
def test_sniff_upload_by_signature(data: bytes, expected: tuple[str, str]) -> None:
    assert sniff_upload(data, "whatever.bin", "application/octet-stream") == expected


# ---------- кейсы ----------
@pytest.fixture
def with_case(dev: TestClient, original_jpeg: bytes):
    first = dev.post("/api/v1/analyze", data={"text": LOTTERY, "posted_at": "2026-10-01T00:00:00"},
                     files=[("files", ("a.jpg", original_jpeg, "image/jpeg"))]).json()["data"]
    second = dev.post("/api/v1/analyze", data={"text": CASINO, "posted_at": "2026-10-02T00:00:00"},
                      files=[("files", ("b.jpg", original_jpeg, "image/jpeg"))]).json()["data"]
    _post_text(dev, "Привет, просто пост без признаков")
    return dev, first, second


def test_cases_list_filters_and_pagination(with_case) -> None:
    # Arrange
    dev, first, _ = with_case

    # Act
    body = dev.get("/api/v1/cases").json()
    by_track = dev.get("/api/v1/cases", params={"track": "casino", "level": "high"}).json()
    other_status = dev.get("/api/v1/cases", params={"status": "dismissed"}).json()
    paged = dev.get("/api/v1/cases", params={"limit": 1, "offset": 1}).json()
    bad = dev.get("/api/v1/cases", params={"level": "low"})

    # Assert
    _assert_envelope(body, True)
    assert body["meta"] == {"total": 1, "limit": 50, "offset": 0}
    case = body["data"][0]
    assert case["key"] == f"C-{first['post_id']}" and case["status"] == "new" and case["size"] == 2
    assert len(by_track["data"]) == 1
    assert other_status["data"] == []
    assert paged["data"] == [] and paged["meta"]["total"] == 1
    assert bad.status_code == 422


def test_case_card_patch_and_export(with_case) -> None:
    # Arrange
    dev, first, second = with_case
    key = f"C-{first['post_id']}"

    # Act
    card = dev.get(f"/api/v1/cases/{key}").json()["data"]
    patched = dev.patch(f"/api/v1/cases/{key}", json={"status": "in_review", "note": "проверка"})
    status = dev.get("/api/v1/cases", params={"status": "in_review"}).json()["data"]
    export = dev.get(f"/api/v1/cases/{key}/export")

    # Assert
    assert {p["id"] for p in card["posts"]} == {first["post_id"], second["post_id"]}
    assert all("label" not in p for p in card["posts"])
    assert card["posts"][0]["artifacts"] and card["posts"][0]["requisites"]
    assert card["families"] == [sorted([first["post_id"], second["post_id"]])]
    assert card["graph"]["nodes"]
    assert patched.status_code == 200 and patched.json()["data"] == {"key": key, "status": "in_review"}
    assert [c["key"] for c in status] == [key]
    assert export.status_code == 200 and export.headers["content-type"] == "application/zip"
    zf = zipfile.ZipFile(io.BytesIO(export.content))
    manifest = json.loads(zf.read("manifest.json"))
    assert export.headers["x-manifest-sha256"] == zf.read("manifest.sha256").decode().split()[0]
    assert manifest["case"]["key"] == key and manifest["exported_by"] == "dev"


def test_case_patch_validates_status(with_case) -> None:
    dev, first, _ = with_case
    resp = dev.patch(f"/api/v1/cases/C-{first['post_id']}", json={"status": "guilty"})
    assert resp.status_code == 400


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", "/api/v1/cases/C-999", None),
        ("patch", "/api/v1/cases/C-999", {"status": "new"}),
        ("get", "/api/v1/cases/C-999/export", None),
        ("get", "/api/v1/posts/999", None),
        ("get", "/api/v1/artifacts/999", None),
        ("get", "/api/v1/artifacts/999/file", None),
        ("get", "/api/v1/artifacts/999/ela", None),
        ("get", "/api/v1/artifacts/999/timeline", None),
    ],
)
def test_missing_objects_return_404_envelope(dev: TestClient, method: str, path: str, body) -> None:
    # Act
    resp = getattr(dev, method)(path, **({"json": body} if body else {}))

    # Assert
    assert resp.status_code == 404
    _assert_envelope(resp.json(), False)


# ---------- посты и артефакты ----------
def test_post_related_artifact_file_ela_and_timeline(with_case, original_jpeg: bytes) -> None:
    # Arrange
    dev, first, second = with_case
    art_id = first["proofs"][0]["artifact_id"]

    # Act
    post = dev.get(f"/api/v1/posts/{first['post_id']}").json()["data"]
    related = dev.get(f"/api/v1/posts/{first['post_id']}/related").json()
    file_resp = dev.get(f"/api/v1/artifacts/{art_id}/file")
    ela = dev.get(f"/api/v1/artifacts/{art_id}/ela")
    timeline = dev.get(f"/api/v1/artifacts/{art_id}/timeline").json()["data"]

    # Assert
    assert post["case"] == f"C-{first['post_id']}" and "label" not in post
    assert [p["id"] for p in related["data"]] == [second["post_id"]] and related["meta"]["total"] == 1
    assert file_resp.content == original_jpeg and file_resp.headers["content-type"] == "image/jpeg"
    assert ela.status_code == 200 and ela.content.startswith(b"\x89PNG")
    assert timeline["appearances"] == 2
    assert all("label" not in item["post"] for item in timeline["items"])


def test_audio_artifact_file_and_ela_rejected(dev: TestClient) -> None:
    # Arrange
    voice = b"OggS" + b"\x02" * 30
    data = dev.post("/api/v1/analyze", data={"transcript": CASINO}, files=[("files", ("v.ogg", voice, "audio/ogg"))]).json()["data"]
    art_id = dev.get(f"/api/v1/posts/{data['post_id']}").json()["data"]["artifacts"][0]["id"]

    # Act
    file_resp = dev.get(f"/api/v1/artifacts/{art_id}/file")
    ela = dev.get(f"/api/v1/artifacts/{art_id}/ela")

    # Assert
    assert file_resp.content == voice and file_resp.headers["content-type"] == "audio/ogg"
    assert ela.status_code == 400


def test_related_posts_do_not_leak_label(tmp_path: Path) -> None:
    # Arrange
    settings = make_settings(tmp_path)
    p = Pruf(settings, ocr_enabled=False)
    first = p.ingest(Submission(text=LOTTERY, label="lottery-synthetic"))["post_id"]
    p.ingest(Submission(text=CASINO, label="casino-synthetic"))
    with TestClient(create_app(settings, pruf=p)) as client:
        # Act
        related = client.get(f"/api/v1/posts/{first}/related").json()["data"]

    # Assert
    assert related and all("label" not in r for r in related)


def test_stats_report_capabilities(dev: TestClient) -> None:
    # Act
    _post_text(dev, LOTTERY)
    data = dev.get("/api/v1/stats").json()["data"]

    # Assert
    assert data["posts"] == 1 and data["levels"] == {"high": 1}
    assert data["cases"] == 1 and data["texts_indexed"] == 1
    assert set(data["capabilities"]) == {"ocr", "ocr_off", "whisper", "ml", "llm", "link_resolution"}
    assert data["capabilities"]["ml"] is False and data["capabilities"]["link_resolution"] is False


# ---------- банки ----------
def test_bank_feed_requires_bank_token(secured: TestClient) -> None:
    # Arrange
    _post_text(secured, LOTTERY, headers=_auth())

    # Act
    analyst_token = secured.get("/api/v1/bank/requisites", headers=_auth(ANALYST))
    bank_token = secured.get("/api/v1/bank/requisites", headers=_auth(BANK))

    # Assert
    assert analyst_token.status_code == 401
    assert bank_token.status_code == 200
    row = bank_token.json()["data"][0]
    assert row["type"] == "phone" and row["value"] == "+77019998877"
    assert row["tracks"] == ["lottery"] and row["cases"] and "match_key" not in row


def test_bank_feed_without_any_tokens_outside_dev_is_503(tmp_path: Path) -> None:
    with _client(tmp_path, dev_mode=False, analyst_token="", bank_tokens=()) as client:
        assert client.get("/api/v1/bank/requisites", headers=_auth(BANK)).status_code == 503


def test_analyst_token_opens_bank_feed_when_bank_tokens_are_not_set(tmp_path: Path) -> None:
    # Сайт аналитика показывает ленту реквизитов даже без выданных банкам токенов
    with _client(tmp_path, dev_mode=False, analyst_token=ANALYST, bank_tokens=()) as client:
        assert client.get("/api/v1/bank/requisites", headers=_auth(ANALYST)).status_code == 200
        assert client.get("/api/v1/bank/requisites", headers=_auth(BANK)).status_code == 401


def test_bank_feed_filters_level_and_since(dev: TestClient) -> None:
    # Arrange
    _post_text(dev, LOTTERY)
    _post_text(dev, "Розыгрыш iPhone! Выиграй приз, номер +7 705 555 55 55")  # средний риск

    # Act
    medium = dev.get("/api/v1/bank/requisites").json()["data"]
    high = dev.get("/api/v1/bank/requisites", params={"min_level": "high"}).json()["data"]
    future = dev.get("/api/v1/bank/requisites", params={"since": "2999-01-01"}).json()["data"]
    low = dev.get("/api/v1/bank/requisites", params={"min_level": "low"})

    # Assert
    assert {r["value"] for r in medium} == {"+77019998877", "+77055555555"}
    assert [r["value"] for r in high] == ["+77019998877"]
    assert future == []
    assert low.status_code == 422


def test_bank_check_finds_known_requisite(dev: TestClient) -> None:
    # Arrange
    _post_text(dev, LOTTERY)

    # Act
    found = dev.post("/api/v1/bank/check", json={"value": "8 701 999 88 77"}).json()["data"]
    unknown = dev.post("/api/v1/bank/check", json={"value": "+7 707 000 00 01"}).json()["data"]
    garbage = dev.post("/api/v1/bank/check", json={"value": "hello world"})

    # Assert
    assert found["found"] is True and found["posts"] == 1 and found["tracks"] == ["lottery"]
    assert unknown == {"found": False, "type": "phone"}
    assert garbage.status_code == 400
