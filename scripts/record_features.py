"""Записать видео новых функций: агент-разведчик, сети и ключевой реквизит, расширение ПРУФ Sentinel.

Запуск: сервер с демо-данными и прогоном разведчика (seed_demo.py, затем python -m pruf.scout --demo --no-keywords)
    python scripts/record_features.py --url http://127.0.0.1:8010 --out docs/demo/pruf-features.mp4
Расширение грузится из extension/, страница Telegram Web подменяется локальной лентой.
Рядом пишется <out>.timeline.json для озвучки. Нужен Chromium (--chromium) и imageio-ffmpeg.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from record_demo import CURSOR_JS, H, SCALE, W, Recorder  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
EXTENSION = ROOT / "extension"

# Лента «Telegram Web»: разметка как у Web K (.bubble .message), чтобы сработал content script
FEED = """<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>Telegram Web</title><style>
body{margin:0;background:#8fb98a;font:17px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif;color:#111}
.bubbles{max-width:760px;margin:24px auto;display:flex;flex-direction:column;gap:14px}
.head{background:#fff;border-radius:16px;padding:14px 22px;font-weight:700;font-size:18px}
.bubble{background:#fff;border-radius:16px;padding:12px 18px;box-shadow:0 1px 2px rgba(0,0,0,.12)}
.chan{color:#3a8fd6;font-weight:600;font-size:15px;margin-bottom:6px}
.message a{color:#3a8fd6}
</style></head><body><div class="bubbles">
<div class="head">Лента каналов · Telegram Web</div>
<div class="bubble"><div class="chan">Пассивный доход KZ 💰</div><div class="message">Пассивный доход 5% в день! Пригласи друзей и получай бонус с каждого, вход от 5000 тг, каспи +7 701 655 07 42</div></div>
<div class="bubble"><div class="chan">Шымкент жаңалықтары</div><div class="message">Сегодня в городе +12, ожидается дождь. Пробки на проспекте Тауке хана, объезжайте через Республики.</div></div>
<div class="bubble"><div class="chan">Казино с выводом 24/7</div><div class="message">Вчера поднял x500 на слотах 🔥 промокод WIN777 на бонус 200%, пополнение через каспи +7 776 902 33 18. Зеркало: <a href="https://joy-slots-kz.top/">joy-slots-kz.top</a></div></div>
<div class="bubble"><div class="chan">Розыгрыш iPhone 16 | Казахстан</div><div class="message">🎁 РОЗЫГРЫШ iPhone 16 Pro! Участие всего 2000 тг, переводите на Kaspi +7 747 318 52 64. Итоги в пятницу, осталось 5 мест!</div></div>
</div></body></html>"""


def check(r: Recorder, selector: str, pause: float = 2.5) -> None:
    r.click(selector, pause)


def resume(r: Recorder) -> None:
    """Новый процесс страницы (другой сайт) обрывает скринкаст: запускаем заново, время не сбрасываем."""
    try:
        r.cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 92, "maxWidth": 1920, "maxHeight": 1080, "everyNthFrame": 1})
    except PlaywrightError:
        pass  # скринкаст пережил переход


def scenario(r: Recorder, url: str) -> None:
    p = r.page
    p.goto(f"{url}/#scout")
    p.wait_for_selector(".scout-kpis")
    p.wait_for_selector(".net-key")
    r.start()
    r.step("Разведка: каналы, которые агент нашёл сам")
    r.wait(3)
    for i in range(4):
        r.to(f".scout-kpis .kpi:nth-child({i + 1})", 0.5)
        r.wait(1.0)
    r.step("Общие реквизиты: одна сеть за разными каналами")
    r.scroll(300, selector=".scout-kpis")
    r.to(".scout-shared li", 0.6)
    r.wait(3)

    r.step("Сеть из 19 каналов и её ключевой реквизит")
    r.scroll(360, selector=".scout-shared")
    r.to(".nets-list summary", 0.6)
    r.wait(3)
    r.to("#scout .net-key.top", 0.6)
    r.wait(2)
    r.step("Что если заблокировать главный номер")
    check(r, "#scout .net-key.top input", 1.5)
    r.to("#scout .net-effect b", 0.6)
    r.wait(4)
    r.to("#scout .net-svg .nm.off", 0.8)
    r.wait(3)
    r.step("Добавляем второй номер: от денег отрезана почти вся сеть")
    check(r, "#scout .net-key:nth-child(2) input", 1.5)
    r.to("#scout .net-effect b", 0.6)
    r.wait(4)

    r.step("Таблица каналов: как и откуда агент нашёл каждый")
    r.scroll(700, 1.6, selector="#scout .net-effect")
    p.locator("#scout .table-panel").first.scroll_into_view_if_needed()
    r.wait(1)
    r.to("#scout .table-panel tbody tr:nth-child(2) td:nth-child(4)", 0.7)
    r.wait(2.5)
    r.to("#scout .table-panel tbody tr:nth-child(2) td:nth-child(5)", 0.6)
    r.wait(2.5)

    r.step("Кейс: блок «Что заблокировать» в карточке")
    r.click(".tab[data-view=queue]", 1.5)
    r.click("li[data-key]", 2.5)
    p.locator("#case .net").first.scroll_into_view_if_needed()
    r.wait(1)
    r.to("#case .net-key.top", 0.7)
    r.wait(2)
    check(r, "#case .net-key.top input", 1.5)
    r.to("#case .net-effect b", 0.6)
    r.wait(4)

    r.step("Расширение Sentinel: лента Telegram Web")
    p.goto("https://web.telegram.org/k/")
    resume(r)
    p.locator(".pruf-host").first.wait_for(state="attached", timeout=15_000)
    r.wait(3)
    r.to(".bubble:nth-child(2) .message", 0.8)
    r.wait(3)
    r.step("«Почему?»: причины простыми словами")
    host = p.locator(".bubble:nth-child(2) .pruf-host")
    rect = host.evaluate("h => { const r = h.shadowRoot.querySelector('button').getBoundingClientRect();"
                         " return {x: r.x + r.width / 2, y: r.y + r.height / 2}; }")
    r.move(rect["x"], rect["y"], 0.7)
    p.mouse.down()
    p.mouse.up()
    r.wait(5)
    r.step("Обычная новость без плашки, казино и розыгрыш с плашками")
    r.to(".bubble:nth-child(3) .message", 0.7)
    r.wait(2)
    r.to(".bubble:nth-child(4) .message", 0.7)
    r.wait(2.5)
    r.to(".bubble:nth-child(5) .message", 0.7)
    r.wait(2.5)

    r.step("Клик по сайту из чёрного списка: страница-предупреждение")
    r.to(".bubble:nth-child(4) a", 0.7)
    p.mouse.down()
    p.mouse.up()
    try:
        p.wait_for_url("chrome-extension://**", timeout=10_000)
    except PlaywrightError:
        pass
    resume(r)
    r.wait(3)
    r.to("#back", 0.7)
    r.wait(2)
    r.to("#proceed", 0.7)
    r.wait(2.5)
    r.stop()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default="http://127.0.0.1:8010")
    ap.add_argument("--out", type=Path, default=Path("docs/demo/pruf-features.mp4"))
    ap.add_argument("--chromium", default="/opt/pw-browsers/chromium", help="путь к Chromium (брендовый Chrome не грузит расширения из папки)")
    args = ap.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    url = args.url.rstrip("/")
    with sync_playwright() as pw, tempfile.TemporaryDirectory() as profile:
        ctx = pw.chromium.launch_persistent_context(
            profile, executable_path=args.chromium, headless=True, viewport={"width": W, "height": H},
            device_scale_factor=SCALE, color_scheme="light", locale="ru-RU",
            args=[f"--disable-extensions-except={EXTENSION}", f"--load-extension={EXTENSION}"])
        worker = ctx.service_workers[0] if ctx.service_workers else ctx.wait_for_event("serviceworker", timeout=10_000)
        worker.evaluate("u => chrome.storage.local.set({apiUrl: u})", url)
        worker.evaluate("() => refreshBlacklist()")
        ctx.route("https://web.telegram.org/**", lambda route: route.fulfill(
            status=200, content_type="text/html; charset=utf-8", body=FEED))
        ctx.add_init_script(CURSOR_JS)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        rec = Recorder(page)
        try:
            scenario(rec, url)
        finally:
            ctx.close()
    rec.encode(args.out)
    timeline = args.out.with_suffix(".timeline.json")
    timeline.write_text(json.dumps(rec.steps, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"готово: {args.out} ({rec.steps[-1]['t'] if rec.steps else 0:.0f} с), шаги: {timeline}")


if __name__ == "__main__":
    main()
