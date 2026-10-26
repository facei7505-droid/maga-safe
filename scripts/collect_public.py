"""Сбор постов с открытых страниц t.me/s для проверки ПРУФ на реальных данных.

Только чтение публичных каналов, без аккаунта. Берём последние посты каналов целиком, а не отбираем
«самые скамные»: так проверка честнее. Файл каналов: одна строка на канал, через пробел группа
(legit или suspect), например «tengrinews legit». Строки с # пропускаются.

Запуск: python scripts/collect_public.py --channels channels.txt --per-channel 20 --out data/real/raw.jsonl
Сырые посты содержат настоящие номера и имена каналов: в git они не идут, перед публикацией
набор обезличивается (scripts/anonymize_real.py).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pruf.scout.public_web import PublicWebSource, _http_fetch  # noqa: E402
from pruf.scout.refs import normalize_username  # noqa: E402

GROUPS = ("legit", "suspect")
PAUSE = 2.0  # секунд между страницами


def read_channels(path: Path) -> list[tuple[str, str]]:
    channels: list[tuple[str, str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        name, _, group = line.partition(" ")
        username, group = normalize_username(name), group.strip() or "suspect"
        if not username or group not in GROUPS:
            raise SystemExit(f"Не понял строку каналов: {line!r} (ожидаю «имя legit|suspect»)")
        channels.append((username, group))
    return channels


def polite_fetch(pause: float = PAUSE):
    fetch = _http_fetch()
    last = [0.0]

    def run(url: str) -> str:
        wait = last[0] + pause - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            return fetch(url)
        finally:
            last[0] = time.monotonic()

    return run


def collect(source: PublicWebSource, channels: list[tuple[str, str]], per_channel: int) -> tuple[list[dict], list[dict]]:
    rows: list[dict] = []
    summary: list[dict] = []
    for username, group in channels:
        try:
            info = source.channel_info(username)
            if info is None:
                summary.append({"channel": username, "group": group, "posts": 0, "note": "не публичный или не найден"})
                continue
            posts = source.recent_posts_with_media(username, per_channel)
        except Exception as exc:
            summary.append({"channel": username, "group": group, "posts": 0, "note": f"ошибка: {exc}"})
            continue
        for post, has_media in posts:
            rows.append({"channel": username, "group": group, "message_id": post.message_id,
                         "posted_at": post.posted_at, "text": post.text, "has_media": has_media,
                         "forwarded_from": post.forwarded_from, "url": f"https://t.me/{username}/{post.message_id}"})
        summary.append({"channel": username, "group": group, "title": info.title, "subscribers": info.subscribers,
                        "posts": len(posts)})
        print(f"{username:32} {group:8} {len(posts):3} постов", flush=True)
    return rows, summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--channels", type=Path, required=True)
    ap.add_argument("--per-channel", type=int, default=20)
    ap.add_argument("--out", type=Path, default=Path("data/real/raw.jsonl"))
    args = ap.parse_args()
    source = PublicWebSource(fetch=polite_fetch())
    rows, summary = collect(source, read_channels(args.channels), args.per_channel)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    args.out.with_suffix(".summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    by_group = {g: sum(1 for r in rows if r["group"] == g) for g in GROUPS}
    print(f"Всего {len(rows)} постов: {by_group} → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
