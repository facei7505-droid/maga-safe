"""QR-коды на картинках: Kaspi Pay, домены казино и ссылки, спрятанные в изображение, попадают в анализ и реестр."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

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
