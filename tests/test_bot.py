"""Telegram-бот: логика ответа офлайн (поддельный клиент Bot API) и webhook в API."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from pruf.api.app import create_app
from pruf.api.security import RateLimiter
from pruf.bot.telegram import (
    HELP,
    BotLogic,
    HttpTelegramApi,
    _best_photo,
    format_result,
)
from pruf.bot.texts import reply_lang, say
from pruf.pipeline import Pruf, Submission, Upload
from tests.helpers import CASINO_RU, KASPI_PHONE, LOTTERY_RU, make_settings

MAX_BYTES = 8 * 1024 * 1024


class FakeApi:
    def __init__(self, files: dict[str, bytes] | None = None):
        self.sent: list[tuple[int, str, int | None]] = []
        self.files = files or {}

    def send_message(self, chat_id: int, text: str, reply_to: int | None = None) -> None:
        self.sent.append((chat_id, text, reply_to))

    def file_size_and_path(self, file_id: str) -> tuple[int, str]:
        return len(self.files[file_id]), file_id

    def download(self, file_path: str, max_bytes: int) -> bytes:
        return self.files[file_path]


@pytest.fixture
def pruf(tmp_path: Path):
    p = Pruf(make_settings(tmp_path))
    yield p
    p.db.close()


def _msg(text: str | None = None, **extra) -> dict:
    msg = {"message_id": 7, "chat": {"id": 42, "type": "private"}, **extra}
    if text is not None:
        msg["text"] = text
    return {"update_id": 1, "message": msg}


def test_start_command_replies_with_help(pruf: Pruf) -> None:
    # Arrange
    api = FakeApi()

    # Act
    BotLogic(pruf, api, MAX_BYTES).handle(_msg("/start"))

    # Assert
    assert api.sent == [(42, HELP, None)]


def test_scam_text_gets_risk_and_quotes_without_storing(pruf: Pruf) -> None:
    # Arrange
    api = FakeApi()
    posts_before = pruf.db.count_posts()

    # Act
    reply = BotLogic(pruf, api, MAX_BYTES).handle(_msg(LOTTERY_RU.format(phone=KASPI_PHONE)))

    # Assert
    assert reply is not None and "Риск: высокий" in reply.text
    assert "платный розыгрыш" in reply.text
    assert "«" in reply.text  # цитата из поста
    assert "не вердикт" in reply.text
    assert pruf.db.count_posts() == posts_before  # бот только читает реестр


LOTTERY_KK = "Ұтыс ойыны! iPhone 15 ұтып алыңыз. Қатысу 1000 теңге, каспиге аударыңыз {phone}. Жеңімпаз жұмада"


def test_kazakh_post_gets_kazakh_reply(pruf: Pruf) -> None:
    # Arrange
    api = FakeApi()

    # Act
    reply = BotLogic(pruf, api, MAX_BYTES).handle(_msg(LOTTERY_KK.format(phone=KASPI_PHONE)))

    # Assert
    assert reply is not None and "Тәуекел: жоғары" in reply.text
    assert "ақылы ұтыс ойыны" in reply.text
    assert "Бейтаныс ұйымдастырушыларға ақша аудармаңыз" in reply.text
    assert "Риск:" not in reply.text


def test_start_with_kazakh_telegram_language_gets_kazakh_help(pruf: Pruf) -> None:
    # Arrange
    api = FakeApi()

    # Act
    BotLogic(pruf, api, MAX_BYTES).handle(_msg("/start", **{"from": {"id": 5, "language_code": "kk"}}))

    # Assert
    assert api.sent == [(42, say("kk", "help"), None)]


def test_russian_post_from_kazakh_user_stays_russian(pruf: Pruf) -> None:
    # Arrange
    api = FakeApi()

    # Act
    reply = BotLogic(pruf, api, MAX_BYTES).handle(
        _msg(LOTTERY_RU.format(phone=KASPI_PHONE), **{"from": {"id": 5, "language_code": "kk"}}))

    # Assert
    assert reply is not None and "Риск: высокий" in reply.text


@pytest.mark.parametrize(("text", "user_lang", "expected"), [
    ("Ұтыс ойыны! Қатысу тегін", None, "kk"),
    ("Розыгрыш, участие 2000 тг", "kk", "ru"),
    ("Розыгрыш с опечаткой і", None, "ru"),  # одна казахская буква не делает текст казахским
    ("", "kk-KZ", "kk"),
    ("", "ru", "ru"),
    ("", None, "ru"),
])
def test_reply_lang(text: str, user_lang: str | None, expected: str) -> None:
    assert reply_lang(text, user_lang) == expected


def test_known_requisite_from_other_track_is_reported(pruf: Pruf) -> None:
    # Arrange: номер уже засвечен в посте-лотерее
    pruf.ingest(Submission(text=LOTTERY_RU.format(phone=KASPI_PHONE)))

    # Act
    reply = BotLogic(pruf, FakeApi(), MAX_BYTES).handle(_msg(CASINO_RU.format(phone=KASPI_PHONE)))

    # Assert: факт есть, а счётчиков, треков и самого номера из реестра нет
    assert "Этот реквизит уже встречался в постах с признаками схем" in reply.text
    assert "треки" not in reply.text


def test_reposted_screenshot_reports_registry_matches_and_edits(pruf: Pruf, original_jpeg: bytes, edited_jpeg: bytes) -> None:
    # Arrange: оригинал «выплаты» уже в реестре в рискованном посте
    pruf.ingest(Submission(text=LOTTERY_RU.format(phone=KASPI_PHONE), uploads=(Upload(original_jpeg, "image", "jpg"),)))
    api = FakeApi({"big": edited_jpeg})
    photo = [{"file_id": "small", "width": 90, "height": 160, "file_size": 1000},
             {"file_id": "big", "width": 540, "height": 960, "file_size": len(edited_jpeg)}]

    # Act
    reply = BotLogic(pruf, api, MAX_BYTES).handle(_msg(photo=photo, caption="Вот выплата победителю!"))

    # Assert
    assert "Этот скрин уже встречался в постах с признаками схем" in reply.text
    assert "На копиях этого скрина отличаются суммы или даты" in reply.text
    assert "150 000" not in reply.text and "950 000" not in reply.text  # суммы с чужих скринов не раскрываются


def test_non_image_document_is_rejected(pruf: Pruf) -> None:
    # Arrange
    api = FakeApi({"doc": b"%PDF-1.7 not an image"})

    # Act
    reply = BotLogic(pruf, api, MAX_BYTES).handle(_msg(document={"file_id": "doc", "mime_type": "image/jpeg"}))

    # Assert
    assert "Поддерживаются JPEG" in reply.text


def test_oversized_file_is_rejected_before_download(pruf: Pruf) -> None:
    # Arrange
    api = FakeApi({"doc": b"\xff\xd8\xff" + b"0" * 100})

    # Act
    reply = BotLogic(pruf, api, max_bytes=10).handle(_msg(document={"file_id": "doc", "mime_type": "image/jpeg"}))

    # Assert
    assert "слишком большой" in reply.text


def test_voice_without_whisper_explains_degradation(pruf: Pruf) -> None:
    # Arrange
    api = FakeApi()  # файла нет: без Whisper голосовое даже не скачивается

    # Act
    reply = BotLogic(pruf, api, MAX_BYTES).handle(_msg(voice={"file_id": "v", "duration": 5}))

    # Assert
    assert "Расшифровка голосовых" in reply.text


def test_chat_rate_limit(pruf: Pruf) -> None:
    # Arrange
    api = FakeApi()
    bot = BotLogic(pruf, api, MAX_BYTES, limiter=RateLimiter(1))
    bot.handle(_msg("обычное сообщение"))

    # Act
    reply = bot.handle(_msg("ещё одно"))

    # Assert
    assert "Слишком много сообщений" in reply.text


def test_update_without_chat_is_ignored(pruf: Pruf) -> None:
    assert BotLogic(pruf, FakeApi(), MAX_BYTES).handle({"update_id": 3, "edited_message": {}}) is None


def test_groups_and_channels_are_ignored(pruf: Pruf) -> None:
    # Arrange
    api = FakeApi()
    bot = BotLogic(pruf, api, MAX_BYTES)
    group = {"update_id": 4, "message": {"message_id": 1, "chat": {"id": -100, "type": "group"}, "text": "розыгрыш"}}
    channel = {"update_id": 5, "channel_post": {"message_id": 1, "chat": {"id": -200, "type": "channel"}, "text": "x"}}

    # Act / Assert
    assert bot.handle(group) is None and bot.handle(channel) is None
    assert api.sent == []


def test_internal_error_still_gets_a_reply(pruf: Pruf, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    def boom(*_a, **_k):
        raise RuntimeError("ocr died")

    monkeypatch.setattr(pruf, "check", boom)
    api = FakeApi()

    # Act
    reply = BotLogic(pruf, api, MAX_BYTES).handle(_msg("розыгрыш"))

    # Assert
    assert "Не удалось проверить" in reply.text and api.sent


def test_start_is_rate_limited_too(pruf: Pruf) -> None:
    bot = BotLogic(pruf, FakeApi(), MAX_BYTES, limiter=RateLimiter(1))
    bot.handle(_msg("/start"))
    assert "Слишком много" in bot.handle(_msg("/start")).text


def test_best_photo_takes_largest_that_fits() -> None:
    sizes = [{"file_id": "a", "width": 90, "height": 90, "file_size": 10},
             {"file_id": "b", "width": 800, "height": 800, "file_size": 50},
             {"file_id": "c", "width": 2000, "height": 2000, "file_size": 500}]
    assert _best_photo(sizes, 100)["file_id"] == "b"
    assert _best_photo([], 100) is None


def test_format_result_for_low_risk_is_not_a_guarantee() -> None:
    result = {"analysis": {"level": "low", "score": 3, "track": None, "evidence": [], "degraded": []}, "proofs": []}
    assert "Это не гарантия" in format_result(result)


def test_format_result_low_with_signals_does_not_say_nothing_found() -> None:
    ev = [{"feature_id": "graph.requisite.phone", "label": "Этот реквизит уже встречался", "weight": 20, "source": "graph"}]
    result = {"analysis": {"level": "low", "score": 20, "track": None, "evidence": ev, "degraded": []}, "proofs": []}
    text = format_result(result)
    assert "Явных признаков схем не нашёл" not in text and "будьте осторожны" in text


def test_http_api_hides_token_on_errors() -> None:
    # Arrange
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "description": "Unauthorized"})

    api = HttpTelegramApi("123:SECRET", client=httpx.Client(transport=httpx.MockTransport(handler)))

    # Act / Assert
    with pytest.raises(RuntimeError) as exc:
        api.send_message(1, "hi", reply_to=5)
    assert "SECRET" not in str(exc.value)


def test_http_api_get_file_and_download_limit() -> None:
    # Arrange
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/getFile"):
            return httpx.Response(200, json={"ok": True, "result": {"file_size": 3, "file_path": "photos/a.jpg"}})
        if "/file/" in request.url.path:
            return httpx.Response(200, content=b"x" * 50)
        return httpx.Response(200, json={"ok": True, "result": []})

    api = HttpTelegramApi("t", client=httpx.Client(transport=httpx.MockTransport(handler)))

    # Act / Assert
    assert api.file_size_and_path("f") == (3, "photos/a.jpg")
    assert api.get_updates(5) == []
    assert api.download("photos/a.jpg", 100) == b"x" * 50
    with pytest.raises(Exception, match="слишком большой"):
        api.download("photos/a.jpg", 10)


# ---------- webhook ----------
def _client(tmp_path: Path, **overrides) -> TestClient:
    settings = make_settings(tmp_path, **overrides)
    return TestClient(create_app(settings, pruf=Pruf(settings, ocr_enabled=False)), raise_server_exceptions=False)


def test_webhook_is_404_when_bot_not_configured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    with _client(tmp_path) as client:
        assert client.post("/api/v1/telegram/webhook", json=_msg("hi")).status_code == 404


SECRET = "s3cret-" + "x" * 32


def test_webhook_checks_secret_dedupes_and_answers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    sent = []
    monkeypatch.setattr(HttpTelegramApi, "send_message", lambda self, chat, text, reply_to=None: sent.append(text))
    update = _msg(LOTTERY_RU.format(phone=KASPI_PHONE))
    with _client(tmp_path, telegram_token="1:abc", telegram_secret=SECRET) as client:
        # Act
        bad = client.post("/api/v1/telegram/webhook", json=update, headers={"X-Telegram-Bot-Api-Secret-Token": "nope"})
        good = client.post("/api/v1/telegram/webhook", json=update, headers={"X-Telegram-Bot-Api-Secret-Token": SECRET})
        again = client.post("/api/v1/telegram/webhook", json=update, headers={"X-Telegram-Bot-Api-Secret-Token": SECRET})

    # Assert: ответ уходит из фонового воркера, повтор той же доставки не обрабатывается
    assert bad.status_code == 404
    assert good.json()["data"] == {"queued": True}
    assert again.json()["data"]["reason"] == "duplicate"
    assert len(sent) == 1 and "Риск: высокий" in sent[0]


def test_webhook_rejects_short_secret_and_big_body(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    with _client(tmp_path, telegram_token="1:abc", telegram_secret="short") as client:
        assert client.post("/api/v1/telegram/webhook", json=_msg("hi"),
                           headers={"X-Telegram-Bot-Api-Secret-Token": "short"}).status_code == 404
    with _client(tmp_path / "b", telegram_token="1:abc", telegram_secret=SECRET) as client:
        big = client.post("/api/v1/telegram/webhook", content=b"{" + b" " * (1024 * 1024 + 10) + b"}",
                          headers={"X-Telegram-Bot-Api-Secret-Token": SECRET, "Content-Type": "application/json"})
        assert big.status_code == 413
        bad_json = client.post("/api/v1/telegram/webhook", content=b"[1]",
                               headers={"X-Telegram-Bot-Api-Secret-Token": SECRET, "Content-Type": "application/json"})
        assert bad_json.status_code == 400
