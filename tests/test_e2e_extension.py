"""E2E: расширение ПРУФ Sentinel в настоящем Chromium. Пропускается, если браузера нет.

Страница Telegram Web подменяется локальной разметкой, сервер ПРУФ поднимается на свободном порту.
Проверяем: плашка над скам-постом (а над обычным нет), «Почему?», переадресация домена из чёрного
списка на страницу-предупреждение, счётчики popup, WhatsApp Web, жалобу, стоп на копировании засвеченного
номера и оценку без сервера.
"""

from __future__ import annotations

import json
import os
import re
import shutil
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


KNOWN_PHONE = "+7 776 902 33 18"  # в реестре из постов казино ниже
WHATSAPP_PAGE = f"""<!doctype html><html><head><meta charset="utf-8"><title>WhatsApp</title></head><body>
<div id="chat">
  <div class="copyable-text" data-pre-plain-text="[10:01, 25.10.2026] Касса: " id="wa-scam"><span>{SCAM}</span></div>
  <div class="copyable-text" data-pre-plain-text="[10:02, 25.10.2026] Мама: " id="wa-num"><span>Переведи на {KNOWN_PHONE}, это мой новый номер</span></div>
</div>
<footer><div class="copyable-text selectable-text" contenteditable="true" id="wa-input">{SCAM}</div></footer>
</body></html>"""


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


def _granted_copy(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Копия расширения, где доступ ко всем сайтам уже выдан — как после галочки «Предупреждать на сайтах казино»:
    необязательное разрешение в headless-браузере без нажатия человека не запросить."""
    dst = tmp_path_factory.mktemp("ext") / "extension"
    shutil.copytree(EXTENSION, dst, ignore=shutil.ignore_patterns("test"))
    manifest = json.loads((dst / "manifest.json").read_text(encoding="utf-8"))
    manifest["host_permissions"] = manifest["host_permissions"] + ["<all_urls>"]
    (dst / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return dst


@pytest.fixture(scope="module")
def pw():
    """Один экземпляр Playwright на модуль: второй sync_playwright внутри первого не запускается."""
    if not Path(CHROMIUM).exists():
        pytest.skip("Chromium для E2E не найден (PRUF_E2E_CHROMIUM)")
    with playwright_api.sync_playwright() as p:
        yield p


@pytest.fixture(scope="module")
def context(pw, server: str, tmp_path_factory: pytest.TempPathFactory):
    ext = _granted_copy(tmp_path_factory)
    ctx = pw.chromium.launch_persistent_context(
        str(tmp_path_factory.mktemp("profile")), executable_path=CHROMIUM, headless=True,
        args=[f"--disable-extensions-except={ext}", f"--load-extension={ext}"])
    worker = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker", timeout=10_000)
    worker.evaluate("url => chrome.storage.local.set({apiUrl: url})", server)
    worker.evaluate("() => refreshBlacklist()")
    ctx.route("https://web.telegram.org/**", lambda route: route.fulfill(
        status=200, content_type="text/html; charset=utf-8", body=TELEGRAM_PAGE))
    ctx.route("https://web.whatsapp.com/**", lambda route: route.fulfill(
        status=200, content_type="text/html; charset=utf-8", body=WHATSAPP_PAGE))
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


def test_whatsapp_message_gets_banner_and_report_is_sent(context) -> None:
    ctx, _ = context
    page = ctx.new_page()
    page.goto("https://web.whatsapp.com/")
    banner = page.locator("#wa-scam .pruf-host")
    banner.wait_for(state="attached", timeout=10_000)
    assert page.locator("#wa-input .pruf-host").count() == 0  # поле ввода не сообщение
    status = banner.evaluate("""async h => {
        const r = h.shadowRoot;
        r.querySelector('button').click();
        const report = [...r.querySelectorAll('button')].find(b => b.textContent === 'Сообщить в ПРУФ');
        report.click();
        for (let i = 0; i < 100 && report.disabled && report.textContent === 'Сообщить в ПРУФ'; i++) await new Promise(f => setTimeout(f, 50));
        return report.textContent;
    }""")
    assert status == "Спасибо, жалоба отправлена"
    page.close()


def test_copying_known_number_shows_warning(context) -> None:
    ctx, _ = context
    page = ctx.new_page()
    page.goto("https://web.whatsapp.com/")
    page.locator("#wa-num").wait_for()
    page.evaluate("""() => {
        const span = document.querySelector('#wa-num span');
        const range = document.createRange();
        range.selectNodeContents(span);
        getSelection().removeAllRanges();
        getSelection().addRange(range);
        document.dispatchEvent(new ClipboardEvent('copy', { bubbles: true }));
    }""")
    toast = page.locator("body > .pruf-host")
    toast.wait_for(state="attached", timeout=10_000)
    assert "+77769023318 уже встречался в постах" in toast.evaluate("h => h.shadowRoot.textContent")
    page.close()


def test_banner_works_offline_with_local_verdict(context, server: str) -> None:
    ctx, worker = context
    worker.evaluate("() => chrome.storage.local.set({apiUrl: 'http://127.0.0.1:9'})")  # сервер недоступен
    try:
        page = ctx.new_page()
        page.goto("https://web.telegram.org/k/")
        banner = page.locator("#scam .pruf-host")
        banner.wait_for(state="attached", timeout=15_000)
        text = banner.evaluate("h => h.shadowRoot.textContent")
        assert "Признаки финансовой пирамиды" in text and "оценка браузера без сервера" in text
        assert "Сообщить в ПРУФ" not in text  # без сервера жалобу отправить некуда
        assert page.locator("#chat .pruf-host").count() == 0
        page.close()
    finally:
        worker.evaluate("url => chrome.storage.local.set({apiUrl: url})", server)


def test_kazakh_interface_for_banner_copy_warning_and_block_page(context) -> None:
    ctx, worker = context
    worker.evaluate("() => chrome.storage.local.set({lang: 'kk'})")
    try:
        page = ctx.new_page()
        page.goto("https://web.telegram.org/k/")
        banner = page.locator("#scam .pruf-host")
        banner.wait_for(state="attached", timeout=10_000)
        text = banner.evaluate("h => h.shadowRoot.textContent")
        assert "Қаржы пирамидасының белгілері" in text and "табыс уәдесі" in text and "Неге?" in text
        reasons = banner.evaluate("h => { h.shadowRoot.querySelector('button').click(); "
                                  "return h.shadowRoot.textContent }")
        assert "Шақырылған достар үшін табыс" in reasons and "ақша аудармаңыз" in reasons

        page.goto("https://web.whatsapp.com/")
        page.locator("#wa-num").wait_for()
        page.evaluate("""() => {
            const range = document.createRange();
            range.selectNodeContents(document.querySelector('#wa-num span'));
            getSelection().removeAllRanges();
            getSelection().addRange(range);
            document.dispatchEvent(new ClipboardEvent('copy', { bubbles: true }));
        }""")
        toast = page.locator("body > .pruf-host")
        toast.wait_for(state="attached", timeout=10_000)
        assert "алаяқтық белгілері бар посттарда кездескен" in toast.evaluate("h => h.shadowRoot.textContent")

        try:
            page.goto("https://joy-slots-kz.top/x")  # не promo.: тому домену раньше разрешили «всё равно перейти»
        except playwright_api.Error:
            pass
        page.wait_for_url(re.compile(r"^chrome-extension://[a-z]+/warning\.html#"), timeout=10_000)
        page.wait_for_function("document.documentElement.lang === 'kk'")
        assert page.locator("h1").text_content() == "Бұл сайт ПРУФ қара тізімінде"
        assert page.locator("#back").text_content() == "Артқа қайту"
        page.close()
    finally:
        worker.evaluate("() => chrome.storage.local.set({lang: 'auto'})")


def test_shipped_manifest_asks_only_for_messengers() -> None:
    manifest = json.loads((EXTENSION / "manifest.json").read_text(encoding="utf-8"))
    assert "<all_urls>" not in manifest["host_permissions"]
    assert manifest["optional_host_permissions"] == ["<all_urls>"]


def test_shipped_extension_blocks_nothing_by_default(pw, server: str, tmp_path_factory) -> None:
    # Arrange: расширение как в магазине — доступ ко всем сайтам необязательный и не выдан
    ctx = pw.chromium.launch_persistent_context(
        str(tmp_path_factory.mktemp("profile-default")), executable_path=CHROMIUM, headless=True,
        args=[f"--disable-extensions-except={EXTENSION}", f"--load-extension={EXTENSION}"])
    try:
        worker = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker", timeout=10_000)
        worker.evaluate("url => chrome.storage.local.set({apiUrl: url})", server)

        # Act
        worker.evaluate("() => refreshBlacklist()")

        # Assert: правил перенаправления нет, popup говорит, что предупреждения выключены
        assert worker.evaluate("() => chrome.declarativeNetRequest.getDynamicRules()") == []
        page = ctx.new_page()
        page.goto(f"chrome-extension://{worker.url.split('/')[2]}/popup.html")
        page.wait_for_function("document.getElementById('blacklist').textContent.includes('выключены')", timeout=10_000)
        assert page.locator("#siteGuard").is_checked() is False
    finally:
        ctx.close()
