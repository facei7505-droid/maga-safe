"""E2E: расширение ПРУФ Sentinel в настоящем Chromium. Пропускается, если браузера нет.

Страница Telegram Web подменяется локальной разметкой, сервер ПРУФ поднимается на свободном порту.
Проверяем: плашка над скам-постом (а над обычным нет), «Почему?», переадресация домена из чёрного
списка на страницу-предупреждение и счётчики popup.
"""

from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from pruf.api.app import create_app
from pruf.config import ROOT
from pruf.pipeline import Pruf, Submission
from tests.helpers import make_settings
from tests.test_e2e_dashboard import CHROMIUM, _free_port

playwright_api = pytest.importorskip("playwright.sync_api")
EXTENSION = ROOT / "extension"
SCAM = "Пассивный доход 5% в день! Пригласи друзей и получай бонус с каждого, вход от 5000 тг, каспи +7 701 655 07 42"
TELEGRAM_PAGE = f"""<!doctype html><html><head><meta charset="utf-8"><title>Telegram</title></head><body>
<div class="bubbles">
  <div class="bubble" id="scam"><div class="message">{SCAM}</div></div>
  <div class="bubble" id="chat"><div class="message">Привет! Встречаемся вечером у фонтана, захвати зонт, обещали дождь</div></div>
  <div class="bubble" id="grow"><div class="message">Загрузка…</div></div>
</div>
<script>
  setTimeout(() => {{
    const b = document.createElement('div'); b.className = 'bubble'; b.id = 'late';
    b.innerHTML = '<div class="message">Казино бонус 200% на депозит! Поднял x500 на слотах, промокод WIN777, зеркало <a href="https://joy-slots-kz.top">joy-slots-kz.top</a></div>';
    document.querySelector('.bubbles').appendChild(b);
    document.querySelector('#grow .message').textContent = 'Касса взаимопомощи: удвоим вклад за неделю, гарантия выплат, пригласи друзей и получай 10%';
  }}, 300);
</script></body></html>"""


@pytest.fixture(scope="module")
def server(tmp_path_factory: pytest.TempPathFactory, detector):
    os.environ.pop("WEB_CONCURRENCY", None)
    settings = make_settings(tmp_path_factory.mktemp("e2e-ext"))
    pruf = Pruf(settings, detector=detector, ocr_enabled=False)
    for ch in ("@kazino_demo", "@slots_demo"):
        pruf.ingest(Submission(text=f"Казино с выводом! Поднял x500, промокод WIN777, зеркало joy-slots-kz.top, каспи +7 776 902 33 18 {ch}",
                               channel=ch))
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
def context(server: str, tmp_path_factory: pytest.TempPathFactory):
    if not Path(CHROMIUM).exists():
        pytest.skip("Chromium для E2E не найден (PRUF_E2E_CHROMIUM)")
    with playwright_api.sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(tmp_path_factory.mktemp("profile")), executable_path=CHROMIUM, headless=True,
            args=[f"--disable-extensions-except={EXTENSION}", f"--load-extension={EXTENSION}"])
        worker = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker", timeout=10_000)
        worker.evaluate("url => chrome.storage.local.set({apiUrl: url})", server)
        worker.evaluate("() => refreshBlacklist()")
        ctx.route("https://web.telegram.org/**", lambda route: route.fulfill(
            status=200, content_type="text/html; charset=utf-8", body=TELEGRAM_PAGE))
        yield ctx, worker
        ctx.close()


def test_banner_appears_over_scam_post_only(context) -> None:
    ctx, _ = context
    page = ctx.new_page()
    page.goto("https://web.telegram.org/k/")
    banner = page.locator("#scam .pruf-host")
    banner.wait_for(state="attached", timeout=10_000)
    text = banner.evaluate("h => h.shadowRoot.textContent")
    assert "Признаки финансовой пирамиды" in text and "обещание дохода" in text
    page.locator("#late .pruf-host").wait_for(state="attached", timeout=10_000)  # пост, пришедший позже
    page.locator("#grow .pruf-host").wait_for(state="attached", timeout=10_000)  # пост дописался после первой проверки
    assert page.locator("#chat .pruf-host").count() == 0
    assert page.locator("#scam .pruf-host").count() == 1
    reasons = banner.evaluate("h => { h.shadowRoot.querySelector('button').click(); "
                              "return [...h.shadowRoot.querySelectorAll('li')].map(li => li.textContent) }")
    assert any("Доход за приглашённых" in r for r in reasons)
    page.close()


def test_blacklisted_domain_redirects_to_warning(context) -> None:
    ctx, worker = context
    rules = worker.evaluate("() => chrome.declarativeNetRequest.getDynamicRules()")
    assert len(rules) == 1 and "joy-slots-kz" in rules[0]["condition"]["regexFilter"]
    page = ctx.new_page()
    try:
        page.goto("https://promo.joy-slots-kz.top/bonus?ref=1")
    except playwright_api.Error:
        pass  # переадресация прерывает исходную навигацию
    page.wait_for_url(re.compile(r"^chrome-extension://[a-z]+/warning\.html#"), timeout=10_000)
    assert page.url.endswith("#https://promo.joy-slots-kz.top/bonus?ref=1")
    assert page.locator("#domain").text_content() == "promo.joy-slots-kz.top"
    # «Всё равно перейти»: разрешение только этому домену до конца сессии
    ctx.route("https://promo.joy-slots-kz.top/**", lambda route: route.fulfill(status=200, body="landing"))
    page.click("#proceed")
    page.wait_for_url("https://promo.joy-slots-kz.top/bonus?ref=1", timeout=10_000)
    page.close()


def test_trailing_dot_hostname_is_also_redirected(context) -> None:
    ctx, _ = context
    page = ctx.new_page()
    try:
        page.goto("https://joy-slots-kz.top./")
    except playwright_api.Error:
        pass
    page.wait_for_url(re.compile(r"^chrome-extension://[a-z]+/warning\.html#"), timeout=10_000)
    page.close()


def test_popup_shows_counters(context) -> None:
    ctx, worker = context
    ext_id = worker.url.split("/")[2]
    page = ctx.new_page()
    page.goto(f"chrome-extension://{ext_id}/popup.html")
    page.wait_for_function("Number(document.getElementById('threats').textContent) >= 2", timeout=10_000)
    assert int(page.locator("#checked").text_content()) >= 2
    assert "1 доменов" in page.locator("#blacklist").text_content()
    page.close()
