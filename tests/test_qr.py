"""QR-коды на картинках: Kaspi Pay, домены казино и ссылки, спрятанные в изображение, попадают в анализ и реестр."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image, ImageFilter

from pruf.normalize.qr import decode_qr
from pruf.pipeline import Pruf, Submission, Upload
from tests.helpers import make_settings

cv2 = pytest.importorskip("cv2")
KASPI_PAY = "https://kaspi.kz/pay/LuckyDropKZ?amount=2000"
CASINO = "https://joy-slots-kz.top/?ref=777"


def _poster(payload: str | None, size: tuple[int, int] = (1080, 1350), module: int = 6, seed: int = 0) -> Image.Image:
    """Афиша: цветной фон и QR в углу, как у рекламы в Instagram."""
    img = Image.new("RGB", size, (40 + seed * 30 % 200, 90, 160))
    if payload:
        code = cv2.QRCodeEncoder.create().encode(payload)
        code = cv2.resize(code, None, fx=module, fy=module, interpolation=cv2.INTER_NEAREST)
        quiet = Image.new("RGB", (code.shape[1] + 8 * module, code.shape[0] + 8 * module), "white")
        quiet.paste(Image.fromarray(code).convert("RGB"), (4 * module, 4 * module))
        img.paste(quiet, (size[0] - quiet.width - 40, size[1] - quiet.height - 40))
    return img


def _jpeg(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return buf.getvalue()


@pytest.fixture
def pruf(tmp_path: Path):
    p = Pruf(make_settings(tmp_path), ocr_enabled=False)
    yield p
    p.db.close()


def test_decodes_qr_from_poster_and_jpeg() -> None:
    assert decode_qr(_poster(KASPI_PAY)) == [KASPI_PAY]
    assert decode_qr(Image.open(io.BytesIO(_jpeg(_poster(CASINO))))) == [CASINO]


def test_no_qr_and_unreadable_tiny_preview_give_nothing() -> None:
    assert decode_qr(_poster(None)) == []
    assert decode_qr(_poster(KASPI_PAY).resize((200, 250))) == []  # модуль меньше 2 пикселей не читается


def test_upscales_small_preview() -> None:
    assert decode_qr(_poster(KASPI_PAY).resize((400, 500))) == [KASPI_PAY]


def test_check_finds_kaspi_link_hidden_in_qr(pruf: Pruf) -> None:
    # Arrange: текст поста чистый, реквизит только в QR
    text = "🎁 Розыгрыш iPhone 15 среди подписчиков! Участие 2 000 тг, оплата по QR на картинке. Итоги в пятницу"

    # Act
    result = pruf.check(text, images=(_jpeg(_poster(KASPI_PAY)),))

    # Assert
    a = result["analysis"]
    assert [(r["kind"], r["display"]) for r in a["requisites"]] == [("kaspi_link", "kaspi.kz/pay/luckydropkz")]
    qr = [e for e in a["evidence"] if e["feature_id"] == "common.qr_code"]
    assert qr and qr[0]["source"] == "qr" and qr[0]["quote"] == KASPI_PAY
    assert a["level"] in ("medium", "high")


def test_two_posts_with_same_qr_share_the_requisite(pruf: Pruf) -> None:
    # Arrange: разные афиши и тексты, общий только QR — по нему посты свяжутся в кейс
    first = Submission(text="Розыгрыш! Участие 1000 тг, оплата по QR", source="test", channel="@a",
                       uploads=(Upload(data=_jpeg(_poster(KASPI_PAY, seed=1)), kind="image", ext="jpg"),))
    second = Submission(text="Только сегодня: большой гив, вход 1500 тг", source="test", channel="@b",
                        uploads=(Upload(data=_jpeg(_poster(KASPI_PAY, size=(1200, 1200), module=7, seed=4)), kind="image", ext="jpg"),))

    # Act
    ids = [pruf.ingest(sub, allow_llm=False)["post_id"] for sub in (first, second)]

    # Assert
    key = next(r["key"] for r in pruf.db.requisites_for_post(ids[0]) if r["kind"] == "kaspi_link")
    assert sorted(pruf.db.posts_with_requisite(key)) == sorted(ids)


def test_casino_domain_in_qr_is_a_link(pruf: Pruf) -> None:
    result = pruf.check("Новая игра, заходи по коду 👇", images=(_jpeg(_poster(CASINO)),))
    assert any(link["domain"] == "joy-slots-kz.top" for link in result["analysis"]["links"])


def test_qr_can_be_switched_off(tmp_path: Path) -> None:
    p = Pruf(make_settings(tmp_path, qr_enabled=False), ocr_enabled=False)
    try:
        result = p.check("Розыгрыш", images=(_jpeg(_poster(KASPI_PAY)),))
        assert not result["analysis"]["requisites"]
    finally:
        p.db.close()


def test_short_links_are_resolved_only_for_trusted_checks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange: раскрытие ссылок включено; анонимный бот не должен заставлять сервер ходить в сеть
    calls: list[str] = []
    monkeypatch.setattr("pruf.detect.detector.resolve_shortener", lambda link: calls.append(link.url) or link)
    p = Pruf(make_settings(tmp_path, resolve_links=True), ocr_enabled=False)
    text = "Розыгрыш! Участие 1000 тг, подробности bit.ly/abc123"
    try:
        # Act
        p.check(text, public=True)
        anonymous = len(calls)
        p.check(text)

        # Assert
        assert anonymous == 0
        assert calls == ["http://bit.ly/abc123"]
    finally:
        p.db.close()


def _jpeg_roundtrip(img: Image.Image, quality: int) -> Image.Image:
    return Image.open(io.BytesIO(_jpeg_q(img, quality))).convert("RGB")


def _jpeg_q(img: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def _perspective(img: Image.Image, k: float) -> Image.Image:
    import numpy as np

    a = np.asarray(img)
    h, w = a.shape[:2]
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([[w * k, h * k / 2], [w * (1 - k * 0.3), 0], [w, h], [0, h * (1 - k)]])
    return Image.fromarray(cv2.warpPerspective(a, cv2.getPerspectiveTransform(src, dst), (w, h), borderValue=(255, 255, 255)))


def _noisy(img: Image.Image, sigma: float) -> Image.Image:
    import numpy as np

    a = np.asarray(img).astype(np.int16) + np.random.default_rng(0).normal(0, sigma, (img.height, img.width, 3)).astype(np.int16)
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


@pytest.mark.parametrize("name, make", [
    ("поворот 25°", lambda img: img.rotate(25, expand=True, fillcolor="white")),
    ("перспектива: афиша снята сбоку", lambda img: _perspective(img, 0.3)),
    ("размытие", lambda img: img.filter(ImageFilter.GaussianBlur(2.5))),
    ("JPEG качества 10", lambda img: _jpeg_roundtrip(img, 10)),
    ("шум сенсора", lambda img: _noisy(img, 40)),
    ("тёмный снимок", lambda img: Image.eval(img, lambda v: v // 3)),
    ("пересжатие Telegram 640 px", lambda img: _jpeg_roundtrip(img.resize((512, 640)), 70)),
    ("всё вместе: фото с рук", lambda img: _jpeg_roundtrip(_noisy(_perspective(img.rotate(6, expand=True, fillcolor="white"), 0.12)
                                                                  .filter(ImageFilter.GaussianBlur(1)), 12), 40)),
])
def test_qr_survives_photo_like_distortions(name: str, make) -> None:
    assert decode_qr(make(_poster(KASPI_PAY))) == [KASPI_PAY], name


def test_ingest_resolves_links_once_outside_the_lock_and_stores_final_domain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange: раскрытие ссылки «медленное»; под общей блокировкой приёма его быть не должно
    from pruf.normalize.links import Link

    p = Pruf(make_settings(tmp_path, resolve_links=True), ocr_enabled=False)
    held: list[bool] = []

    def fake_resolve(link: Link) -> Link:
        held.append(p._ingest_lock.locked())
        return Link(url=link.url, domain="joy-slots-kz.top", is_shortener=True, is_messenger=False,
                    raw_span=link.raw_span, resolved="https://joy-slots-kz.top/?ref=1")

    monkeypatch.setattr("pruf.detect.detector.resolve_shortener", fake_resolve)
    try:
        # Act
        post = p.ingest(Submission(text="Новая игра, бонус 200% на депозит, заходи bit.ly/abc123", source="t"), allow_llm=False)

        # Assert
        assert held == [False]
        assert [link["domain"] for link in p.db.links_for_post(post["post_id"])] == ["joy-slots-kz.top"]
    finally:
        p.db.close()
