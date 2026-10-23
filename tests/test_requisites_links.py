"""Реквизиты (телефоны, карты, IBAN, Kaspi-ссылки, промокоды) и ссылки (извлечение, сокращатели, SSRF)."""

from __future__ import annotations

import httpx
import pytest

from pruf.normalize import links as links_mod
from pruf.normalize.links import (
    Link,
    _is_public_host,
    canonical_domain,
    extract_links,
    resolve_shortener,
)
from pruf.normalize.requisites import card_key, extract_requisites, normalize_phone

KEY = b"test-key"
VALID_CARD = "4400 4301 2345 6789"  # проходит Луна
INVALID_CARD = "4400 4301 2345 6788"


def _by_kind(text: str, key: bytes = KEY) -> dict[str, list]:
    out: dict[str, list] = {}
    for r in extract_requisites(text, key):
        out.setdefault(r.kind, []).append(r)
    return out


# ---------- телефоны ----------
@pytest.mark.parametrize(
    "raw",
    ["+7 701 234 56 78", "87012345678", "8 (701) 234-56-78", "+7(701)2345678", "+7-701-234-56-78"],
)
def test_phone_formats_normalize_to_same_key(raw: str) -> None:
    # Act
    found = _by_kind(f"Каспи {raw} переводи")

    # Assert
    assert [r.key for r in found["phone"]] == ["phone:+77012345678"]
    assert found["phone"][0].display == "+77012345678"


def test_phone_span_points_to_original_text() -> None:
    # Arrange
    text = "Номер: 8 701 234 56 78!"

    # Act
    phone = _by_kind(text)["phone"][0]

    # Assert
    assert text[phone.raw_span[0]:phone.raw_span[1]] == "8 701 234 56 78"


def test_non_kz_or_embedded_numbers_are_not_phones() -> None:
    # Arrange: российский код 495 и номер внутри длинного числа
    text = "Тел +7 495 123 45 67 и счёт 1287012345678999"

    # Act
    found = _by_kind(text)

    # Assert
    assert "phone" not in found


def test_duplicate_phones_are_reported_once() -> None:
    assert len(_by_kind("+77012345678 и снова 8 701 234 56 78")["phone"]) == 1


def test_normalize_phone_replaces_leading_eight() -> None:
    assert normalize_phone("8 (701) 234-56-78") == "+77012345678"
    assert normalize_phone("+7 701 234 56 78") == "+77012345678"


# ---------- карты ----------
def test_luhn_valid_card_is_masked_and_keyed_by_hmac() -> None:
    # Act
    card = _by_kind(f"Карта {VALID_CARD}")["card"][0]

    # Assert
    assert card.display == "440043******6789"
    assert card.key == card_key("4400430123456789", KEY)
    assert card.key.startswith("card:") and len(card.key) == 5 + 32
    assert "4400430123456789" not in card.key


def test_card_key_depends_on_hmac_key() -> None:
    # Act
    a = _by_kind(f"Карта {VALID_CARD}", b"key-a")["card"][0]
    b = _by_kind(f"Карта {VALID_CARD.replace(' ', '-')}", b"key-a")["card"][0]
    c = _by_kind(f"Карта {VALID_CARD}", b"key-b")["card"][0]

    # Assert
    assert a.key == b.key
    assert a.key != c.key


def test_luhn_invalid_card_is_ignored() -> None:
    assert "card" not in _by_kind(f"Карта {INVALID_CARD}")


# ---------- IBAN, Kaspi, промокоды ----------
def test_kz_iban_is_extracted_uppercase() -> None:
    # Act
    iban = _by_kind("Счёт kz86125kzt5004100100 для оплаты")["iban"][0]

    # Assert
    assert iban.display == "KZ86125KZT5004100100"
    assert iban.key == "iban:KZ86125KZT5004100100"


@pytest.mark.parametrize(
    ("raw", "display"),
    [
        ("https://pay.kaspi.kz/pay/abc123", "pay.kaspi.kz/pay/abc123"),
        ("kaspi.me/AbC-12/", "kaspi.me/abc-12"),
        ("http://kaspi.kz/pay/shop_1", "kaspi.kz/pay/shop_1"),
    ],
)
def test_kaspi_pay_links_are_canonicalized(raw: str, display: str) -> None:
    # Act
    link = _by_kind(f"Оплата по ссылке {raw} сегодня")["kaspi_link"][0]

    # Assert
    assert link.display == display
    assert link.key == f"kaspi:{display}"


@pytest.mark.parametrize("text", ["промокод: win777", "Promo code WIN777", "promokod WIN777", "Промо WIN777"])
def test_promo_codes_are_extracted_uppercase(text: str) -> None:
    # Act
    promo = _by_kind(text)["promo"][0]

    # Assert
    assert promo.display == "WIN777"
    assert promo.key == "promo:WIN777"


@pytest.mark.parametrize("text", ["100 фриспинов по промокоду WIN777", "freespin po promokodu WIN777"])
def test_promo_code_after_inflected_word_is_extracted(text: str) -> None:
    assert [r.display for r in _by_kind(text).get("promo", [])] == ["WIN777"]


def test_text_without_requisites_returns_empty_list() -> None:
    assert extract_requisites("Просто текст без реквизитов", KEY) == []


# ---------- ссылки ----------
def test_extract_links_finds_bare_domains_shorteners_and_messengers() -> None:
    # Arrange
    text = "Заходи на vulkan-kz.top, или https://bit.ly/3xYz9q! www.Example.com/path, пиши в t.me/chan."

    # Act
    found = {link.domain: link for link in extract_links(text)}

    # Assert
    assert set(found) == {"vulkan-kz.top", "bit.ly", "example.com", "t.me"}
    assert found["vulkan-kz.top"].url == "http://vulkan-kz.top"
    assert found["bit.ly"].is_shortener and not found["bit.ly"].is_messenger
    assert found["t.me"].is_messenger
    assert found["t.me"].url == "http://t.me/chan"  # хвостовая точка отрезана
    start, end = found["bit.ly"].raw_span
    assert text[start:end] == "https://bit.ly/3xYz9q"


def test_extract_links_deduplicates_case_insensitive() -> None:
    assert len(extract_links("vulkan-kz.top и VULKAN-KZ.TOP")) == 1


def test_extract_links_skips_unparsable_urls() -> None:
    # Arrange: битый IPv6-литерал даёт ValueError в urlsplit
    text = "http://[::1 и http://ok-site.kz"

    # Act
    domains = [link.domain for link in extract_links(text)]

    # Assert
    assert domains == ["ok-site.kz"]


def test_canonical_domain_strips_www_and_trailing_dot() -> None:
    assert canonical_domain("WWW.Example.COM.") == "example.com"


PUBLIC_DNS = {"example.com": "93.184.215.14", "bit.ly": "67.199.248.10", "cutt.ly": "104.21.0.1",
              "www.vulkan-kz.top": "104.21.0.2", "evil-rebind.example": "10.0.0.5"}


@pytest.fixture
def fake_dns(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Детерминированный резолвер: имена из PUBLIC_DNS, числовые формы через настоящий getaddrinfo (без сети)."""
    import socket

    real = socket.getaddrinfo

    def resolver(host, port, *args, **kwargs):
        if host in PUBLIC_DNS:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (PUBLIC_DNS[host], port or 0))]
        if any(ch.isalpha() for ch in host.replace("0x", "")) and ":" not in host:
            raise socket.gaierror("имя не найдено")
        return real(host, port, *args, **kwargs)

    monkeypatch.setattr(links_mod.socket, "getaddrinfo", resolver)
    return PUBLIC_DNS


@pytest.mark.parametrize(
    ("host", "public"),
    [
        ("example.com", True),
        ("8.8.8.8", True),
        ("", False),
        ("localhost", False),
        ("printer.local", False),
        ("db.internal", False),
        ("10.0.0.1", False),
        ("192.168.1.10", False),
        ("127.0.0.1", False),
        ("169.254.169.254", False),
        ("::1", False),
        ("evil-rebind.example", False),  # имя, указывающее на внутренний адрес
        ("no-such-host.invalid", False),  # не резолвится
    ],
)
def test_is_public_host_blocks_private_and_local_targets(fake_dns, host: str, public: bool) -> None:
    assert _is_public_host(host) is public


@pytest.mark.parametrize("host", ["127.1", "2130706433", "0", "0x7f.1"])
def test_is_public_host_blocks_alternative_loopback_notations(fake_dns, host: str) -> None:
    """Регрессия SSRF: числовые записи loopback, которые getaddrinfo разрешает в 127.0.0.1/0.0.0.0."""
    assert _is_public_host(host) is False


# ---------- раскрытие сокращателей (httpx и DNS замоканы) ----------
@pytest.fixture
def mock_http(monkeypatch: pytest.MonkeyPatch, fake_dns):
    """Подменяет httpx.Client на клиент с MockTransport; возвращает список запрошенных URL и таблицу ответов."""
    requested: list[str] = []
    routes: dict[str, httpx.Response] = {}
    real_client = httpx.Client

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return routes.get(str(request.url), httpx.Response(200))

    def factory(*args, **kwargs):
        return real_client(*args, transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "Client", factory)
    return requested, routes


def _short(url: str = "https://bit.ly/abc") -> Link:
    return extract_links(url)[0]


def test_resolve_shortener_follows_redirect_chain(mock_http) -> None:
    # Arrange
    requested, routes = mock_http
    routes["https://bit.ly/abc"] = httpx.Response(301, headers={"location": "https://cutt.ly/x"})
    routes["https://cutt.ly/x"] = httpx.Response(302, headers={"location": "/landing"})
    routes["https://cutt.ly/landing"] = httpx.Response(302, headers={"location": "https://www.vulkan-kz.top/reg"})

    # Act
    resolved = resolve_shortener(_short())

    # Assert
    assert resolved.resolved == "https://www.vulkan-kz.top/reg"
    assert resolved.domain == "vulkan-kz.top"
    assert resolved.url == "https://bit.ly/abc"
    assert resolved.is_shortener
    assert requested[:3] == ["https://bit.ly/abc", "https://cutt.ly/x", "https://cutt.ly/landing"]


def test_resolve_shortener_does_not_request_private_hosts(mock_http) -> None:
    # Arrange
    requested, routes = mock_http
    routes["https://bit.ly/abc"] = httpx.Response(302, headers={"location": "http://169.254.169.254/latest/meta-data"})

    # Act
    resolved = resolve_shortener(_short())

    # Assert: на внутренний адрес запрос не уходит
    assert requested == ["https://bit.ly/abc"]
    assert "169.254.169.254" not in "".join(requested[1:])
    assert resolved.url == "https://bit.ly/abc"


def test_resolve_shortener_does_not_follow_non_http_schemes(mock_http) -> None:
    # Arrange
    requested, routes = mock_http
    routes["https://bit.ly/abc"] = httpx.Response(302, headers={"location": "file:///etc/passwd"})

    # Act
    resolved = resolve_shortener(_short())

    # Assert
    assert requested == ["https://bit.ly/abc"]
    assert not (resolved.resolved or "").startswith("file:")


def test_resolve_shortener_stops_after_max_redirects(mock_http) -> None:
    # Arrange: бесконечная петля редиректов
    requested, routes = mock_http
    routes["https://bit.ly/abc"] = httpx.Response(302, headers={"location": "https://bit.ly/loop"})
    routes["https://bit.ly/loop"] = httpx.Response(302, headers={"location": "https://bit.ly/abc"})

    # Act
    resolve_shortener(_short())

    # Assert
    assert len(requested) == links_mod._MAX_REDIRECTS


def test_resolve_shortener_without_redirect_returns_same_link(mock_http) -> None:
    # Arrange
    link = _short()

    # Act
    resolved = resolve_shortener(link)

    # Assert
    assert resolved is link


def test_resolve_shortener_returns_original_on_network_error(monkeypatch: pytest.MonkeyPatch, fake_dns) -> None:
    # Arrange
    real_client = httpx.Client

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("нет сети", request=request)

    monkeypatch.setattr(httpx, "Client", lambda *a, **kw: real_client(*a, transport=httpx.MockTransport(boom), **kw))
    link = _short()

    # Act
    resolved = resolve_shortener(link)

    # Assert
    assert resolved is link


def test_resolve_shortener_ignores_regular_links(monkeypatch: pytest.MonkeyPatch) -> None:
    # Arrange: любой сетевой вызов провалит тест
    monkeypatch.setattr(httpx, "Client", lambda *a, **kw: pytest.fail("сеть не должна вызываться"))
    link = extract_links("https://vulkan-kz.top/reg")[0]

    # Act / Assert
    assert resolve_shortener(link) is link
