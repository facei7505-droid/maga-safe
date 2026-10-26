"""E2E: дашборд в настоящем браузере (Playwright + Chromium). Пропускается, если браузера нет.

Путь аналитика: обзор → ранний сигнал → кейс (граф, семейства пруфов, подсветка) → таймлайн →
проверка текста → проверка реквизита банком → отчёт для печати. Ошибок JS в консоли быть не должно.
"""

from __future__ import annotations

import os
import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from pruf.api.app import create_app
from pruf.pipeline import Pruf, Submission, Upload
from tests.helpers import KASPI_PHONE, LOTTERY_RU, make_settings

playwright_api = pytest.importorskip("playwright.sync_api")
CHROMIUM = os.environ.get("PRUF_E2E_CHROMIUM", "/opt/pw-browsers/chromium")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory, original_jpeg: bytes, edited_jpeg: bytes):
    os.environ.pop("WEB_CONCURRENCY", None)
    settings = make_settings(tmp_path_factory.mktemp("e2e"))
    pruf = Pruf(settings)  # с OCR: таймлайн показывает правку суммы
    text = LOTTERY_RU.format(phone=KASPI_PHONE)
    for i, (ch, img) in enumerate([("@almaty_news", original_jpeg), ("@astana_life", edited_jpeg), ("@shymkent_today", original_jpeg)]):
        pruf.ingest(Submission(text=f"{text} #{i}", uploads=(Upload(img, "image", "jpg"),), channel=ch,
                               posted_at=f"2026-10-0{i + 1}T12:00:00+00:00"))
    port = _free_port()
    srv = uvicorn.Server(uvicorn.Config(create_app(settings, pruf=pruf), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not srv.started and time.time() < deadline:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(scope="module")
def browser():
    if not Path(CHROMIUM).exists():
        pytest.skip("Chromium для E2E не найден (PRUF_E2E_CHROMIUM)")
    with playwright_api.sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROMIUM)
        yield b
        b.close()


def test_analyst_flow_end_to_end(server: str, browser) -> None:
    # Arrange
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

    # Act + Assert: обзор с ранним сигналом
    page.goto(server, wait_until="networkidle")
    assert page.locator(".kpi").count() == 5
    assert "+77019998877" in page.locator(".surge").first.inner_text()
    # карточка «Как мы мерили»: цифры на свежих реальных постах видны жюри без README
    assert "Из 100 схем находит 83" in page.locator(".quality").inner_text()

    # кейс из раннего сигнала: граф, семейство пруфов, подсветка признаков
    page.locator(".surge button").first.click()
    page.wait_for_selector("svg.graph .n.post")
    assert page.locator("svg.graph .n.post").count() == 3
    assert page.locator(".family").count() >= 1
    assert page.locator("mark.hl").count() > 0
    page.locator("svg.graph .n.post").first.click()
    assert "#case/" in page.url

    # таймлайн пруфа с правкой суммы
    page.locator(".family").first.click()
    page.wait_for_selector(".tl-item")
    assert page.locator(".tl-item").count() >= 2
    assert page.locator(".tl-item.edited").count() >= 1
    page.keyboard.press("Escape")
    assert page.locator("#modal").is_hidden()

    # проверка текста из примера
    page.locator(".tab[data-view=check]").click()
    page.locator("#examples button").first.click()
    page.locator("#check-form button[type=submit]").click()
    page.wait_for_selector(".gauge")
    assert "высокий" in page.locator(".gauge").inner_text()
    # ход решения: правила, модель, реестр, Claude-арбитр, потолки, итог
    trace = page.locator(".trace").inner_text()
    assert "Как решала система" in trace and "Правила словаря" in trace and "Claude-арбитр" in trace and "Итог: высокий" in trace

    # банк проверяет номер
    page.locator(".tab[data-view=bank]").click()
    page.fill("#bank-value", KASPI_PHONE)
    page.locator("#bank-form button").click()
    page.wait_for_selector(".verdict")
    assert "встречается" in page.locator(".verdict").inner_text()
    page.wait_for_function("document.querySelector('#reports-total').textContent.includes('всего жалоб')")
    assert "Жалоб пока нет" in page.locator("#report-rows").inner_text()

    # отчёт для печати
    report = browser.new_page()
    report.on("pageerror", lambda e: errors.append("report: " + str(e)))
    case_key = page.locator("#bank-rows button.link").first.inner_text()
    report.goto(f"{server}/static/report.html#{case_key}", wait_until="networkidle")
    assert f"Кейс {case_key}" in report.locator("h1").inner_text()
    lead = report.locator(".r-lead").inner_text()
    assert "3 канала" in lead and "+77019998877" in lead and "приоритет" in lead

    # аналитик подтверждает кейс: номер становится чёрным на «Реквизитах»
    assert "серый" in page.locator("#bank-rows .list-badge").first.inner_text()
    dialogs: list[str] = []
    page.on("dialog", lambda d: (dialogs.append(d.message), d.accept()))
    page.locator("#bank-rows button.link").first.click()
    page.locator("select[aria-label='Статус кейса']").select_option("confirmed")
    page.get_by_role("button", name="Сохранить статус").click()
    page.wait_for_selector(".toast >> text=в чёрный список")
    assert dialogs and "чёрный список" in dialogs[0]
    page.keyboard.press("Escape")
    page.locator(".tab[data-view=bank]").click()
    page.wait_for_selector("#bank-rows .list-badge.black")
    assert "+77019998877" in page.locator("#bank-rows tr", has=page.locator(".list-badge.black")).first.inner_text()

    assert errors == []


def test_demo_tour_walks_every_step_without_errors(server: str, browser) -> None:
    # Arrange
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(server, wait_until="networkidle")

    # Act: пять шагов сценария показа
    page.locator("#tour-btn").click()
    views = []
    for step in range(1, 6):
        page.locator(".tour-n", has_text=f"Шаг {step} из 5").wait_for()
        page.wait_for_timeout(600)
        views.append(page.evaluate("() => [...document.querySelectorAll('.view')].find(v => !v.classList.contains('hidden')).id"))
        page.locator(".tour button.primary").click()

    # Assert: тур прошёл обзор, кейс, проверку, банк и разведку и закрылся
    assert views == ["view-overview", "view-queue", "view-check", "view-bank", "view-scout"]
    assert page.locator(".tour").is_hidden()
    assert errors == []
    page.close()


def test_kazakh_dashboard_translates_interface_but_not_posts(server: str, browser) -> None:
    # Arrange: язык выбран в боковой панели и запомнен
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(server, wait_until="networkidle")

    # Act
    with page.expect_navigation():
        page.select_option("#lang", "kk")
    page.wait_for_load_state("networkidle")

    # Assert: меню, обзор и карточка качества на казахском
    assert page.evaluate("document.documentElement.lang") == "kk"
    assert page.locator(".tab[data-view='overview']").inner_text().strip() == "Шолу"
    assert "100 схеманың ішінен 83 табады" in page.locator(".quality").inner_text()
    assert "Сапаны қалай өлшедік" in page.locator(".quality h3").inner_text()

    # проверка поста: ход решения переведён, текст поста и цитаты — как есть
    page.locator(".tab[data-view='check']").click()
    text = LOTTERY_RU.format(phone=KASPI_PHONE)
    page.fill("#check-text", text)
    page.locator("#check-form button[type=submit]").click()
    page.wait_for_selector(".trace")
    assert "Жүйе қалай шешті" in page.locator(".trace summary").inner_text()
    assert "Сөздік ережелері" in page.locator(".trace").inner_text()
    assert page.locator("#check-result .text").first.inner_text() == text
    assert page.locator("#lang").input_value() == "kk"
    assert errors == []

    # обратно на русский
    with page.expect_navigation():
        page.select_option("#lang", "ru")
    page.wait_for_load_state("networkidle")
    assert page.locator(".tab[data-view='overview']").inner_text().strip() == "Обзор"
    page.close()
