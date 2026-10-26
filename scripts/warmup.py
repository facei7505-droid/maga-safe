"""Разогрев демо перед питчем: разбудить сервер, дождаться демо-данных и пройти весь демо-путь.

На бесплатном Render сервер засыпает после простоя, а диска нет: после пробуждения он стартует и в фоне
заново создаёт демо-данные (до готовности API отвечает 503). Скрипт ждёт, пока появится кейс C-211, затем открывает всё,
что показывается на демо, и печатает время каждого шага. Код возврата 0 — демо готово.

Запуск (токен аналитика — часть после двоеточия в PRUF_ANALYST_TOKEN):
  PRUF_TOKEN=... python scripts/warmup.py --url https://pruf-bba7.onrender.com
  python scripts/warmup.py --url ... --keep-awake 120   # потом держать сервер бодрым 2 часа
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass

import httpx

HERO_CASE = "C-211"
HERO_PHONE = "+77473185264"
DEMO_TEXT = "Удвоим ваши деньги за неделю! 30% в день, приглашай друзей. Kaspi +7 747 318 52 64"
SLOW_MS = 3000  # шаг дольше 3 с на демо заметен
PING_EVERY = 600  # Render усыпляет после 15 минут без запросов


@dataclass
class Step:
    name: str
    ok: bool
    ms: int
    note: str = ""


def _timed(client: httpx.Client, name: str, method: str, path: str, check=None, **kw) -> Step:
    t0 = time.perf_counter()
    try:
        res = client.request(method, path, **kw)
        ms = round((time.perf_counter() - t0) * 1000)
        if res.status_code != 200:
            return Step(name, False, ms, f"HTTP {res.status_code}")
        note = check(res) if check else ""
        return Step(name, note is not None, ms, note or "")
    except Empty as exc:
        return Step(name, False, round((time.perf_counter() - t0) * 1000), str(exc))
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        return Step(name, False, round((time.perf_counter() - t0) * 1000), type(exc).__name__)


class Empty(Exception):
    """Шаг ответил, но показывать на демо нечего."""


def _need(count: int, what: str, fix: str = "") -> str:
    if count < 1:
        raise Empty(f"пусто: {what}" + (f" ({fix})" if fix else ""))
    return f"{what}: {count}"


def wait_ready(client: httpx.Client, timeout: float, poll: float = 10.0, log=print) -> bool:
    """Ждать, пока сервер ответит и демо-данные с кейсом C-211 будут готовы."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            res = client.get("/api/v1/cases/" + HERO_CASE)
            if res.status_code == 200:
                return True
            log(f"  сервер отвечает, демо-данных ещё нет (HTTP {res.status_code}), жду…")
        except httpx.HTTPError as exc:
            log(f"  сервер ещё просыпается ({type(exc).__name__}), жду…")
        time.sleep(poll)
    return False


def demo_path(client: httpx.Client) -> list[Step]:
    """Всё, что открывается на демо, в порядке сценария из README."""
    def data(res):
        return res.json()["data"]

    return [
        _timed(client, "Обзор", "GET", "/api/v1/overview", lambda r: _need(len(data(r)["surges"]), "ранних сигналов")),
        _timed(client, "Очередь кейсов", "GET", "/api/v1/cases", lambda r: _need(r.json()["meta"]["total"], "кейсов")),
        _timed(client, f"Кейс {HERO_CASE}", "GET", f"/api/v1/cases/{HERO_CASE}", lambda r: _need(len(data(r)["posts"]), "постов")),
        _timed(client, "Пакет доказательств ZIP", "GET", f"/api/v1/cases/{HERO_CASE}/export",
               lambda r: f"{len(r.content) // 1024} КБ"),
        _timed(client, "Проверка поста", "POST", "/api/v1/analyze/text", lambda r: f"риск: {data(r)['level']}",
               json={"text": DEMO_TEXT, "store": False}),
        _timed(client, "Реквизиты для банка", "GET", "/api/v1/bank/requisites?limit=50",
               lambda r: _need(len(data(r)), "строк")),
        _timed(client, "Проверка номера", "POST", "/api/v1/bank/check",
               lambda r: _need(data(r).get("posts", 0), "постов с номером"), json={"value": HERO_PHONE}),
        _timed(client, "Сети каналов", "GET", "/api/v1/networks", lambda r: _need(len(data(r)), "сетей")),
        _timed(client, "Разведка", "GET", "/api/v1/scout",
               lambda r: _need(len(data(r)["channels"]), "каналов", "python -m pruf.scout --demo --no-keywords")),
        _timed(client, "Что включено", "GET", "/api/v1/stats",
               lambda r: ", ".join(k for k, v in data(r)["capabilities"].items() if v is True or (isinstance(v, dict) and v.get("configured")))),
        _timed(client, "Дашборд", "GET", "/"),
    ]


def keep_awake(client: httpx.Client, minutes: float, every: float = PING_EVERY, log=print) -> None:
    end = time.monotonic() + minutes * 60
    while time.monotonic() < end:
        time.sleep(min(every, max(0.0, end - time.monotonic())))
        step = _timed(client, "health", "GET", "/api/v1/health")
        log(f"  пинг: {'ok' if step.ok else step.note} за {step.ms} мс")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=os.environ.get("PRUF_URL", "https://pruf-bba7.onrender.com"))
    ap.add_argument("--wait", type=float, default=600, help="сколько секунд ждать пробуждения и демо-данных")
    ap.add_argument("--keep-awake", type=float, default=0, help="после разогрева пинговать столько минут")
    args = ap.parse_args()
    token = os.environ.get("PRUF_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    with httpx.Client(base_url=args.url.rstrip("/"), headers=headers, timeout=90) as client:
        print(f"бужу {args.url} …")
        t0 = time.perf_counter()
        if not wait_ready(client, args.wait):
            print(f"✗ за {args.wait:.0f} с демо не поднялось (нет кейса {HERO_CASE}); проверьте логи Render и токен")
            return 1
        print(f"✓ сервер и демо-данные готовы за {time.perf_counter() - t0:.0f} с\n")
        steps = demo_path(client)
        for s in steps:
            mark = "✓" if s.ok else "✗"
            slow = "  ← медленно" if s.ok and s.ms > SLOW_MS else ""
            print(f"{mark} {s.name:<26} {s.ms:>6} мс  {s.note}{slow}")
        failed = [s.name for s in steps if not s.ok]
        print("\n" + ("демо готово" if not failed else "не работает: " + ", ".join(failed)))
        if args.keep_awake and not failed:
            print(f"держу сервер бодрым {args.keep_awake:.0f} мин (пинг каждые {PING_EVERY // 60} мин)")
            keep_awake(client, args.keep_awake)
        return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
