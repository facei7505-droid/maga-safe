"""Регрессии по находкам аудита: обход маскирования, форматы реквизитов, ложные «казино»,
ReDoS, отказ LLM, анонимный бот, лимиты тела и экспорта, очередь вебхука."""

from __future__ import annotations

import json
import time
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import pruf.export as export_mod
from pruf.api.app import create_app
from pruf.bot.telegram import HttpTelegramApi
from pruf.detect.detector import Detector, SourceText
from pruf.detect.llm import LlmArbiter
from pruf.normalize.links import extract_links
from pruf.normalize.requisites import extract_requisites, redact_cards
from pruf.pipeline import Pruf, Submission, Upload
from tests.helpers import KASPI_PHONE, LOTTERY_RU, fastest, make_settings

KEY = b"k" * 32
CARD = "4400 4301 2345 6789"  # верная контрольная сумма Луна


@pytest.fixture(autouse=True)
def _single_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)


# ---------- реквизиты ----------
@pytest.mark.parametrize("text", [
    "4400​4301​2345​6789",  # нулевая ширина между группами
    "４４００ ４３０１ ２３４５ ６７８９",  # полноширинные цифры
    "4400­4301­2345­6789",  # мягкий перенос
], ids=["zero-width", "fullwidth", "soft-hyphen"])
def test_hidden_or_unicode_digits_do_not_bypass_card_redaction(text: str) -> None:
    # Act
    redacted = redact_cards("Карта " + text)
    reqs = extract_requisites("Карта " + text, KEY)

    # Assert
    assert "2345" not in redacted and "440043******6789" in redacted
    assert [(r.kind, r.display) for r in reqs] == [("card", "440043******6789")]
    assert reqs[0].key == extract_requisites(CARD, KEY)[0].key  # тот же ключ, что у ASCII-записи


@pytest.mark.parametrize("text", [
    "7 747 318 52 64", "77473185264", "+７ ７４７ ３１８ ５２ ６４", "8 ٧٤٧ ٣١٨ ٥٢ ٦٤", "+7 747​318 52 64",
])
def test_phone_formats_without_plus_or_with_unicode_digits_are_found(text: str) -> None:
    assert [r.display for r in extract_requisites(text, KEY)] == ["+77473185264"]


def test_iban_written_in_groups_of_four_is_found_and_keyed_without_spaces() -> None:
    reqs = extract_requisites("Счёт KZ86 125K ZT50 0410 0100", KEY)
    assert [(r.kind, r.key) for r in reqs] == [("iban", "iban:KZ86125KZT5004100100")]


def test_twelve_digit_iin_is_not_a_phone() -> None:
    assert extract_requisites("ИИН 770101300123", KEY) == []


# ---------- ссылки и домены ----------
def test_bare_domain_regex_is_linear_on_adversarial_input() -> None:
    # Раньше «a.» × 10000 разбиралось 11 с и блокировало приём
    for text in ("a." * 10_000, "1-" * 10_000, "a-" * 10_000 + ".kz"):
        assert fastest(lambda: extract_links(text)) < 1.0, text[:4]


def _casino_hits(tmp_path: Path, text: str) -> list[str]:
    det = Detector(make_settings(tmp_path))
    analysis = det.detect([SourceText("text", text)], allow_llm=False).analysis
    return [e.quote for e in analysis.evidence if e.feature_id == "casino.domain"]


@pytest.mark.parametrize("text", [
    "Тарифы на alphabet.com", "Тур в tibet.kz", "Новость gov.kz/news/kazino-zapret", "egov.kz/services",
])
def test_ordinary_domains_and_url_paths_are_not_casino(tmp_path: Path, text: str) -> None:
    assert _casino_hits(tmp_path, text) == []


@pytest.mark.parametrize("domain", ["jet-casino.bet", "1xslot-kz.online", "pinup-win.site", "bet-777.top", "joycasino.com"])
def test_casino_domains_are_still_detected(tmp_path: Path, domain: str) -> None:
    assert _casino_hits(tmp_path, f"Заходи {domain}")


# ---------- казахский на русской раскладке ----------
def test_kazakh_typed_on_russian_keyboard_scores_like_kazakh_letters(tmp_path: Path) -> None:
    # Arrange
    det = Detector(make_settings(tmp_path))
    kazakh = "Ұтыс ойыны! Қатысу 1000 тг, жеңімпаз ертең. Каспиге аударыңыз"
    russian_keys = "Утыс ойыны! Катысу 1000 тг, женимпаз ертен. Каспиге аударыныз"

    # Act
    a = det.detect([SourceText("text", kazakh)], allow_llm=False).analysis
    b = det.detect([SourceText("text", russian_keys)], allow_llm=False).analysis

    # Assert
    assert b.level == a.level == "high"
    assert b.score == pytest.approx(a.score)


# ---------- LLM ----------
def test_unexpected_llm_exception_is_contained(tmp_path: Path) -> None:
    # Arrange: любая ошибка SDK (например, несовместимая версия) не должна ронять приём
    arbiter = LlmArbiter(api_key="test-key-not-used", model="claude-test")

    class Broken:
        def create(self, **_kw):
            raise TypeError("unexpected keyword argument 'output_config'")

    arbiter._client = type("C", (), {"messages": Broken()})()

    # Act / Assert
    assert arbiter.review("Казино бонус 100% на депозит") is None
    assert arbiter.stats()["last_error"] == "unexpected"


# ---------- анонимный бот ----------
class _SpyLlm:
    def __init__(self) -> None:
        self.calls = 0

    def review(self, text: str):
        self.calls += 1
        return None


def _pruf_with_known_card(tmp_path: Path) -> Pruf:
    pruf = Pruf(make_settings(tmp_path), ocr_enabled=False)
    for i in range(2):
        pruf.ingest(Submission(text=LOTTERY_RU.format(phone=f"на карту {CARD}") + f" #{i}", channel=f"@ch{i}"))
    return pruf


def test_anonymous_bot_does_not_confirm_bare_requisite_in_registry(tmp_path: Path) -> None:
    # Arrange
    pruf = _pruf_with_known_card(tmp_path)

    # Act: голый номер карты без признаков схемы
    public = pruf.check(f"Карта {CARD}", public=True)["analysis"]
    analyst = pruf.check(f"Карта {CARD}")["analysis"]

    # Assert: аналитик видит связь с реестром, анонимный бот нет, и балл одинаков с «чистой» картой
    assert any(e["source"] == "graph" for e in analyst["evidence"])
    assert not any(e["source"] in ("graph", "registry") for e in public["evidence"])
    clean = pruf.check("Карта 4400 4301 2345 6797", public=True)["analysis"]
    assert public["score"] == clean["score"]


def test_anonymous_bot_still_links_requisite_when_text_itself_is_risky(tmp_path: Path) -> None:
    pruf = _pruf_with_known_card(tmp_path)
    public = pruf.check(LOTTERY_RU.format(phone=f"на карту {CARD}"), public=True)["analysis"]
    assert any(e["source"] == "graph" for e in public["evidence"])


def test_anonymous_bot_never_calls_llm(tmp_path: Path) -> None:
    # Arrange: текст в спорной зоне, где аналитику LLM помогает
    pruf = Pruf(make_settings(tmp_path), ocr_enabled=False)
    spy = _SpyLlm()
    pruf.detector._llm = spy
    text = "Казино бонус 100% на депозит"
    pruf.check(text)
    analyst_calls = spy.calls

    # Act
    pruf.check(text, public=True)

    # Assert
    assert analyst_calls >= 1 and spy.calls == analyst_calls


# ---------- API: лимиты и вебхук ----------
def _client(tmp_path: Path, **overrides) -> TestClient:
    settings = make_settings(tmp_path, **overrides)
    return TestClient(create_app(settings, pruf=Pruf(settings, ocr_enabled=False)), raise_server_exceptions=False)


def test_json_routes_reject_large_bodies_before_parsing_and_auth(tmp_path: Path) -> None:
    # Arrange: без токена, тело 300 КБ (для JSON больше 256 КБ не нужно)
    with _client(tmp_path, dev_mode=False, analyst_token="a:" + "t" * 20) as client:
        # Act
        resp = client.post("/api/v1/analyze/text", content=b"[" + b"{}," * 100_000 + b"{}]",
                           headers={"content-type": "application/json"})

    # Assert
    assert resp.status_code == 413


def test_voice_only_check_without_whisper_reports_degraded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange: голосовое без сохранения и без расшифровки раньше давало «низкий риск» молча
    monkeypatch.setattr("pruf.api.app.transcribe", lambda data, suffix: None)
    with _client(tmp_path) as client:
        # Act
        resp = client.post("/api/v1/analyze", data={"store": "0"}, files={"files": ("v.ogg", b"OggS" + b"\0" * 100, "audio/ogg")})

    # Assert
    assert resp.status_code == 200
    assert any(d["component"] == "whisper" for d in resp.json()["data"]["analysis"]["degraded"])


SECRET = "s3cret-" + "x" * 32


def test_webhook_busy_returns_503_so_telegram_retries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.setattr(HttpTelegramApi, "send_message", lambda self, chat, text, reply_to=None: None)
    monkeypatch.setattr("pruf.api.app.BOT_MAX_PENDING", 0)
    update = {"update_id": 77, "message": {"message_id": 1, "chat": {"id": 5, "type": "private"}, "text": "привет"}}
    headers = {"X-Telegram-Bot-Api-Secret-Token": SECRET}
    with _client(tmp_path, telegram_token="1:abc", telegram_secret=SECRET) as client:
        # Act
        busy = client.post("/api/v1/telegram/webhook", json=update, headers=headers)
        monkeypatch.setattr("pruf.api.app.BOT_MAX_PENDING", 10)
        retry = client.post("/api/v1/telegram/webhook", json=update, headers=headers)

    # Assert: повтор той же доставки после 503 обрабатывается, а не считается дублем
    assert busy.status_code == 503
    assert retry.json()["data"] == {"queued": True}


# ---------- экспорт и реестр ----------
def test_export_over_budget_lists_skipped_artifacts_by_hash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                            original_jpeg: bytes) -> None:
    # Arrange
    monkeypatch.setattr(export_mod, "MAX_EXPORT_ARTIFACT_BYTES", 1)
    with _client(tmp_path) as client:
        for i in range(2):
            client.post("/api/v1/analyze", data={"text": LOTTERY_RU.format(phone=KASPI_PHONE), "channel": f"@c{i}"},
                        files={"files": (f"p{i}.jpg", original_jpeg, "image/jpeg")})
        key = client.get("/api/v1/cases").json()["data"][0]["key"]

        # Act
        resp = client.get(f"/api/v1/cases/{key}/export")

    # Assert: первый файл влез, второй только хешем
    manifest = json.loads(zipfile.ZipFile(BytesIO(resp.content)).read("manifest.json"))
    assert len(manifest["artifacts"]) == 1
    assert len(manifest["skipped_artifacts"]) == 1 and len(manifest["skipped_artifacts"][0]["sha256"]) == 64


def test_identical_audio_twice_in_one_post_does_not_match_itself(tmp_path: Path) -> None:
    # Arrange
    pruf = Pruf(make_settings(tmp_path), ocr_enabled=False)
    voice = Upload(b"OggS" + b"\1" * 64, "audio", "ogg")

    # Act
    result = pruf.ingest(Submission(text="голосовое", uploads=(voice, voice), transcript="текст"))

    # Assert
    assert result["post_id"]
    assert all(m["post_a"] != m["post_b"] for m in pruf.db.all_matches())



def test_slow_ocr_does_not_block_other_ingests(tmp_path: Path, original_jpeg: bytes, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange: OCR первого поста «висит», пока второй (текстовый) не будет принят
    import threading

    pruf = Pruf(make_settings(tmp_path), ocr_enabled=False)
    release = threading.Event()
    real_read = pruf.registry.read_ocr

    def slow_read(img):
        release.wait(5)
        return real_read(img)

    monkeypatch.setattr(pruf.registry, "read_ocr", slow_read)
    slow = threading.Thread(target=pruf.ingest,
                            args=(Submission(text="скрин", uploads=(Upload(original_jpeg, "image", "jpg"),)),))
    slow.start()

    # Act
    started = time.perf_counter()
    fast = pruf.ingest(Submission(text=LOTTERY_RU.format(phone=KASPI_PHONE)))
    elapsed = time.perf_counter() - started
    release.set()
    slow.join(5)

    # Assert
    assert fast["analysis"]["level"] == "high"
    assert elapsed < 3  # медленный приём держит OCR 5 с
    assert pruf.db.count_posts() == 2
