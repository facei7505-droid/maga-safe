"""Записать демо-видео дашборда без звука: сценарий кликов в Edge/Chromium, кадры по CDP, H.264 MP4.

Запуск: сервер с демо-данными на --url (без ANTHROPIC_API_KEY, чтобы не тратить LLM), затем
    python scripts/record_demo.py --url http://127.0.0.1:8010 --out docs/demo/pruf-demo.mp4
Рядом пишется <out>.timeline.json: на какой секунде какой шаг, для сценария озвучки.
Нужны playwright (браузер: --channel msedge или установленный Chromium) и imageio-ffmpeg.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import time
from pathlib import Path

import imageio_ffmpeg
from PIL import Image
from playwright.sync_api import Page, sync_playwright

W, H, SCALE = 1440, 810, 4 / 3  # кадр 1920×1080
FPS = 30

# Курсор и «пульс» клика: в записи экрана системного курсора нет, рисуем свой.
CURSOR_JS = """
window.addEventListener('DOMContentLoaded', () => {
  const c = document.createElement('div');
  Object.assign(c.style, {position: 'fixed', left: '0', top: '0', width: '22px', height: '22px', zIndex: 2147483647,
    pointerEvents: 'none', transform: 'translate(-3px,-2px)', transition: 'none'});
  c.innerHTML = '<svg viewBox="0 0 24 24" width="22" height="22"><path d="M4 2l15 11-6.5 1.2L9.8 21z" fill="#111827" stroke="#fff" stroke-width="1.6" stroke-linejoin="round"/></svg>';
  document.body.appendChild(c);
  document.addEventListener('mousemove', (e) => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
  document.addEventListener('mousedown', (e) => {
    const r = document.createElement('div');
    Object.assign(r.style, {position: 'fixed', left: (e.clientX - 18) + 'px', top: (e.clientY - 18) + 'px', width: '36px', height: '36px',
      borderRadius: '50%', background: 'rgba(37,99,235,.28)', zIndex: 2147483646, pointerEvents: 'none', transition: 'transform .45s, opacity .45s'});
    document.body.appendChild(r);
    requestAnimationFrame(() => { r.style.transform = 'scale(1.8)'; r.style.opacity = '0'; });
    setTimeout(() => r.remove(), 500);
  }, true);
});
"""


class Recorder:
    def __init__(self, page: Page):
        self.page = page
        self.frames: list[tuple[float, bytes]] = []
        self.steps: list[dict] = []
        self.t0 = time.monotonic()
        self.mouse = (W / 2, H / 2)
        self.cdp = page.context.new_cdp_session(page)
        self.cdp.on("Page.screencastFrame", self._on_frame)

    def _on_frame(self, ev: dict) -> None:
        self.frames.append((time.monotonic() - self.t0, base64.b64decode(ev["data"])))
        self.cdp.send("Page.screencastFrameAck", {"sessionId": ev["sessionId"]})

    def start(self) -> None:
        self.cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 92, "maxWidth": 1920, "maxHeight": 1080, "everyNthFrame": 1})
        self.t0 = time.monotonic()

    def stop(self) -> None:
        self.cdp.send("Page.stopScreencast")

    def step(self, title: str) -> None:
        self.steps.append({"t": round(time.monotonic() - self.t0, 1), "step": title})
        print(f"[{self.steps[-1]['t']:6.1f}s] {title}", flush=True)

    def wait(self, sec: float) -> None:
        # Держим страницу «живой», чтобы скринкаст слал кадры и в паузах
        end = time.monotonic() + sec
        while time.monotonic() < end:
            self.page.mouse.move(self.mouse[0] + 0.01, self.mouse[1])
            self.page.wait_for_timeout(100)

    def move(self, x: float, y: float, dur: float = 0.7) -> None:
        steps = max(8, int(dur * 40))
        x0, y0 = self.mouse
        for i in range(1, steps + 1):
            k = i / steps
            k = k * k * (3 - 2 * k)  # плавный старт и остановка
            self.page.mouse.move(x0 + (x - x0) * k, y0 + (y - y0) * k)
            self.page.wait_for_timeout(dur * 1000 / steps)
        self.mouse = (x, y)

    def to(self, selector: str, dur: float = 0.7) -> None:
        loc = self.page.locator(selector).first
        loc.scroll_into_view_if_needed()
        box = loc.bounding_box()
        self.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, dur)

    def click(self, selector: str, pause: float = 0.6) -> None:
        self.to(selector)
        self.page.mouse.down()
        self.page.wait_for_timeout(90)
        self.page.mouse.up()
        self.wait(pause)

    def type(self, selector: str, text: str, delay: float = 0.035) -> None:
        self.click(selector, 0.2)
        self.page.locator(selector).first.fill("")
        self.page.keyboard.type(text, delay=delay * 1000)

    def scroll(self, dy: int, dur: float = 1.2, selector: str | None = None) -> None:
        if selector:
            self.to(selector, 0.4)
        steps = max(6, int(dur * 30))
        for _ in range(steps):
            self.page.mouse.wheel(0, dy / steps)
            self.page.wait_for_timeout(dur * 1000 / steps)

    def encode(self, out: Path) -> None:
        if not self.frames:
            raise SystemExit("кадров нет: скринкаст не запустился")
        total = self.frames[-1][0] + 1.0
        writer = imageio_ffmpeg.write_frames(str(out), (1920, 1080), fps=FPS, codec="libx264", quality=None, macro_block_size=1,
                                             pix_fmt_out="yuv420p", output_params=["-crf", "26", "-preset", "slow", "-movflags", "+faststart"])
        writer.send(None)
        idx, last = 0, None
        for n in range(int(total * FPS)):
            t = n / FPS
            while idx < len(self.frames) and self.frames[idx][0] <= t:
                last = self.frames[idx][1]
                idx += 1
            if last is None:
                continue
            img = Image.open(io.BytesIO(last)).convert("RGB")
            if img.size != (1920, 1080):
                img = img.resize((1920, 1080), Image.LANCZOS)
            writer.send(img.tobytes())
        writer.close()


def scenario(r: Recorder, url: str) -> None:
    p = r.page
    p.goto(f"{url}/#overview")
    p.wait_for_selector(".kpi")
    r.start()
    r.step("Обзор: поток постов и ключевые цифры")
    r.wait(3)
    for i in range(5):
        r.to(f".kpi:nth-child({i + 1})", 0.5)
        r.wait(0.8)
    r.step("Ранний сигнал: один номер за 70 часов в 5 каналах")
    r.to(".surge-main b")
    r.wait(4)
    r.step("Динамика по дням и треки")
    r.scroll(420, selector=".kpi:nth-child(3)")
    for x in (0.25, 0.4, 0.55):
        r.move(W * x * 0.62 + 280, 470)
        r.wait(1.2)
    r.wait(2)
    r.scroll(-420)
    r.wait(1)

    r.step("Открываем кейс C-211")
    r.click(".surge button", 2.5)
    r.wait(3)
    r.step("Факты кейса: 37 постов, 12 каналов, 3 трека")
    r.to(".facts", 0.6)
    r.wait(4)
    r.step("Граф связей: посты, номер, промокод")
    r.scroll(380, selector=".case-head")
    nodes = p.locator("svg.graph .n.post")
    for i in (0, 5, 12):
        box = nodes.nth(i).bounding_box()
        if box:
            r.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, 0.6)
            r.wait(1.6)
    r.step("Посты с подсветкой признаков в тексте")
    r.to("mark.hl", 0.7)
    r.wait(4)

    r.step("Пруфы по семействам: один скрин, 37 копий")
    p.locator(".family").first.scroll_into_view_if_needed()
    r.wait(1)
    r.to(".family", 0.7)
    r.wait(2)
    r.click(".family", 2.5)
    r.step("Таймлайн появлений скрина")
    r.wait(4)
    r.step("Только копии с правками: суммы обведены красным")
    r.click("#modal-content label.inline", 2)
    r.wait(2)
    r.to(".tl-item.edited .shot", 0.8)
    r.wait(4)
    r.scroll(300, selector=".tl-item.edited")
    r.wait(2)
    p.keyboard.press("Escape")
    r.wait(1.2)

    r.step("Отчёт по кейсу для печати и PDF")
    p.goto(f"{url}/static/report.html#C-211")
    p.wait_for_selector(".r-head", timeout=15000)
    r.wait(3)
    r.scroll(700, 2.5)
    r.wait(2.5)
    r.scroll(-700, 1)
    p.goto(f"{url}/#check")
    p.wait_for_selector("#check-text")
    r.wait(1)

    r.step("Проверить: пост на русском")
    for label, pause in (("Розыгрыш", 5), ("Казино (kk)", 4), ("Пирамида (translit)", 4), ("Легальный", 4)):
        if label != "Розыгрыш":
            r.step(f"Проверить: {label}")
        r.click(f"#examples button:has-text('{label}')", 0.8)
        r.click("#check-form button[type=submit]", 1.5)
        p.wait_for_selector(".gauge")
        r.to(".gauge", 0.6)
        r.wait(pause)
    r.step("Замаскированный пост: Л@кий Дж3т")
    r.type("#check-text", "Л@кий Дж3т крутит 🚀 ставка 500, вывод 18 000. Пиши + в лс, дам бонус-код на первый деп и покажу стратегию")
    if p.locator("#check-store").is_checked():
        r.click("#check-store", 0.3)
    r.click("#check-form button[type=submit]", 1.5)
    r.to(".gauge", 0.6)
    r.wait(3)
    r.scroll(420, 1.5, selector=".check-head")
    r.wait(3)
    r.scroll(-420, 1)

    r.step("Реквизиты: проверка номера банком")
    r.click(".tab[data-view=bank]", 1.2)
    r.type("#bank-value", "+7 747 318 52 64", 0.06)
    r.click("#bank-form button[type=submit]", 1.5)
    r.wait(4)
    r.step("Лента засвеченных реквизитов")
    r.to("#bank-rows tr:nth-child(3)", 0.8)
    r.wait(2)
    r.scroll(360, 1.5)
    r.wait(2.5)

    r.step("Финал: обзор")
    r.click(".tab[data-view=overview]", 1.5)
    r.wait(4)
    r.stop()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default="http://127.0.0.1:8010")
    ap.add_argument("--out", type=Path, default=Path("docs/demo/pruf-demo.mp4"))
    ap.add_argument("--channel", default="msedge", help="msedge, chrome или пусто для Chromium Playwright")
    args = ap.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel=args.channel or None, headless=True)
        ctx = browser.new_context(viewport={"width": W, "height": H}, device_scale_factor=SCALE, color_scheme="light", locale="ru-RU")
        ctx.add_init_script(CURSOR_JS)
        page = ctx.new_page()
        rec = Recorder(page)
        try:
            scenario(rec, args.url.rstrip("/"))
        finally:
            browser.close()
    rec.encode(args.out)
    timeline = args.out.with_suffix(".timeline.json")
    timeline.write_text(json.dumps(rec.steps, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"готово: {args.out} ({args.out.stat().st_size / 1e6:.1f} МБ, {rec.steps[-1]['t'] + 4:.0f} с), шаги → {timeline}")


if __name__ == "__main__":
    main()
