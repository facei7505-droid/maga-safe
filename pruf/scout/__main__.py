"""Запуск разведчика.

  python -m pruf.scout --demo                    # офлайн-демо на фикстуре, без аккаунта Telegram
  python -m pruf.scout --seed @канал --telegram  # живой Telegram (только чтение), ключи из окружения

Семена по умолчанию: каналы постов высокого риска из реестра ПРУФ.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from pruf.config import load_settings
from pruf.pipeline import Pruf
from pruf.scout.scout import Scout, ScoutConfig
from pruf.scout.sources import DEMO_FIXTURE, FixtureSource, Throttle, ThrottledSource

DEMO_SEED = "iphone_razdacha_kz"  # «жалоба», с которой начинается демо
TELEGRAM_INTERVAL = 1.5  # секунд между запросами к Telegram
FIXTURE_INTERVAL = 0.0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python -m pruf.scout", description="Агент-Разведчик ПРУФ (только чтение)")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--demo", action="store_true", help="офлайн-фикстура вместо Telegram")
    src.add_argument("--fixture", type=Path, help="свой JSON в формате демо-фикстуры")
    src.add_argument("--telegram", action="store_true", help="живой Telegram через Telethon (TG_API_ID, TG_API_HASH)")
    ap.add_argument("--seed", action="append", default=[], help="канал-семя (@имя или t.me/имя), можно несколько")
    ap.add_argument("--max-channels", type=int, default=40)
    ap.add_argument("--max-depth", type=int, default=4)
    ap.add_argument("--max-requests", type=int, default=400, help="лимит запросов к источнику за запуск")
    ap.add_argument("--no-keywords", action="store_true", help="не искать каналы по ключевым фразам")
    ap.add_argument("--no-store", action="store_true", help="только проверить, не писать посты в реестр")
    ap.add_argument("--llm", action="store_true", help="разрешить Claude для спорных постов (тратит бюджет API)")
    ap.add_argument("--out", type=Path, help="куда сохранить отчёт JSON")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if args.telegram:
        from pruf.scout.telegram import TelethonSource

        source, interval = TelethonSource.from_env(), TELEGRAM_INTERVAL
    else:
        source, interval = FixtureSource(args.fixture or DEMO_FIXTURE), FIXTURE_INTERVAL
    pruf = Pruf(load_settings())
    seeds = args.seed or ([DEMO_SEED] if args.demo or not (args.fixture or args.telegram) else pruf.db.risky_channels())
    config = ScoutConfig(max_channels=args.max_channels, max_depth=args.max_depth, store=not args.no_store,
                         allow_llm=args.llm, keywords=() if args.no_keywords else ScoutConfig.keywords)
    scout = Scout(pruf, ThrottledSource(source, Throttle(interval, args.max_requests)), config)
    report = scout.run(seeds)
    pruf.db.close()
    print_summary(report, seeds)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def print_summary(report: dict, seeds: list[str]) -> None:
    risky = report["risky_channels"]
    related = [r for r in risky if r["via"] != "seed"]
    phones = [s for s in report["shared_requisites"] if s["type"] == "phone"]
    out = sys.stdout
    out.write(f"\nСемена: {', '.join(seeds) or '—'}. Проверено каналов: {report['channels_checked']}, "
              f"запросов к источнику: {report['requests_used']}\n")
    out.write(f"Найдено связанных каналов с признаками схем: {len(related)}; общих номеров Kaspi: {len(phones)}\n\n")
    for r in risky:
        how = "семя" if r["via"] == "seed" else f"{r['via']} ← {r['parent'] or 'поиск'}"
        out.write(f"  @{r['username']:<24} риск {r['risk']:>5}  {r['track'] or '—':<8} {how}\n")
    if report["shared_requisites"]:
        out.write("\nОбщие реквизиты:\n")
        for s in report["shared_requisites"]:
            out.write(f"  {s['value']:<30} {len(s['channels'])} канала: {', '.join('@' + c for c in s['channels'])}\n")
    if report["clean_channels"]:
        out.write(f"\nПроверены и чистые (дальше не идём): {', '.join('@' + c for c in report['clean_channels'])}\n")
    if report["stopped"]:
        out.write(f"\nОстановлено: {report['stopped']}\n")


if __name__ == "__main__":
    raise SystemExit(main())
