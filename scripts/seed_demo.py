"""Демо-данные для показа: фоновая синтетика + «вау»-сценарий.

Сценарий:
  1. Один базовый скрин выплаты (+150 000 T) расходится по каналам: 37 появлений за ~30 дней,
     в 5 копиях сумма перерисована. Таймлайн артефакта показывает все появления и правки.
  2. Один номер «оператора» (Kaspi-перевод) встречается в розыгрыше, казино и пирамиде,
     граф собирает их в один кейс на три трека.
  3. Фон: синтетические кампании и легальные посты (контроль ложных срабатываний).

Запуск: PRUF_DEV_MODE=1 PRUF_DATA_DIR=data/demo python scripts/seed_demo.py --reset
"""

from __future__ import annotations

import argparse
import os
import random
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("PRUF_DEV_MODE", "1")

from pruf.config import Settings
from pruf.detect.classifier import TrackClassifier
from pruf.pipeline import Pruf, Submission, Upload
from pruf.synth.generator import Generator
from pruf.synth.screens import (
    Receipt,
    edit_amount,
    render_receipt,
    repost_variant,
    to_jpeg,
)

HERO_APPEARANCES = 37
HERO_EDITED = 5
HERO_DAYS = 30
OPERATOR_PHONE = "+7 747 318 52 64"
HERO_START = datetime(2026, 9, 20, 9, 0, tzinfo=timezone.utc)
HERO_CHANNELS = ["@aktobe_konkurs", "@almaty_priz", "@kz_lucky_drop", "@shymkent_giveaway", "@astana_bonus",
                 "@vyplaty_kz", "@karaganda_razdacha", "@taraz_kz_win", "@atyrau_priz", "@pavlodar_bonus",
                 "@semey_lucky", "@kostanay_drop"]
HERO_TEXTS = {
    "lottery": [
        "🎁 РОЗЫГРЫШ iPhone 17 Pro! Участие всего 1000 тг на каспи {phone}. Победитель уже получил выплату, смотрите пруф 👇",
        "Итоги розыгрыша! Ещё один победитель забрал 150 000 тг. Для участия в новом переведи 2000 на {phone} и пиши в лс",
        "Ұтыс ойыны! Қатысу 1000 тг, каспи {phone}. Жеңімпаз ақшасын алды, міне дәлел",
    ],
    "casino": [
        "Поднял 150 000 за вечер 🔥 Слоты дают, вывод за 5 минут. Ссылка на зеркало в профиле, промокод BONUS777. Пополнение через {phone}",
        "Бонус 200% на первый депозит! Казино платит, вот выплата подписчику. Пополняй каспи {phone}, ссылка в закрепе",
    ],
    "pyramid": [
        "Вложил 50 000 — через неделю вывел 150 000! Доход 3% в день, пассивный заработок без вложений времени. Вход через {phone}, пиши в лс",
        "Закрытый клуб инвесторов: приглашаешь 3 друзей и получаешь 30% с каждого. Взнос 10 000 на каспи {phone}. Вот выплата участнице",
    ],
}


def _log(msg: str) -> None:
    print(f"[seed] {msg}", flush=True)


def ensure_model(settings: Settings, gen_seed: int = 42) -> TrackClassifier:
    clf = TrackClassifier.load(settings.model_path)
    if clf is not None:
        return clf
    _log(f"модели нет, обучаю на синтетике → {settings.model_path}")
    posts = Generator(seed=gen_seed).dataset(image_rate=0.0)
    train = [p for p in posts if p.split == "train"]
    clf = TrackClassifier.train([p.text for p in train], [p.label for p in train])
    clf.save(settings.model_path)
    return clf


def seed_background(pruf: Pruf, tmp: Path, campaigns_per_track: int, legit: int) -> int:
    gen = Generator(seed=7, out_dir=tmp)
    posts = gen.dataset(campaigns_per_track=campaigns_per_track, posts_per_campaign=10, legit=legit, image_rate=0.3)
    posts.sort(key=lambda p: p.posted_at)
    for p in posts:
        uploads = ()
        if p.image:
            uploads = (Upload((tmp / p.image).read_bytes(), "image", "jpg"),)
        pruf.ingest(Submission(text=p.text, uploads=uploads, source="seed", channel=p.channel, posted_at=p.posted_at,
                               external_id=p.id, label=p.label))
    return len(posts)


def seed_hero(pruf: Pruf, rng: random.Random) -> dict[str, int]:
    """37 появлений одного скрина выплаты, 5 из них с перерисованной суммой, один номер на три трека."""
    base_img = render_receipt(Receipt("150 000", "Айгерим С.", "19.09.2026", "14:35", "7740213"))
    base = to_jpeg(base_img, 90)
    edited_at = set(rng.sample(range(4, HERO_APPEARANCES), HERO_EDITED))
    fake_amounts = iter(["450 000", "1 150 000", "750 000", "350 000", "950 000"])
    tracks = ["lottery", "casino", "pyramid"]
    counts = {t: 0 for t in tracks}
    for i in range(HERO_APPEARANCES):
        track = tracks[i % 3]
        when = HERO_START + timedelta(minutes=int(i * HERO_DAYS * 24 * 60 / HERO_APPEARANCES) + rng.randint(0, 600))
        channel = HERO_CHANNELS[i % len(HERO_CHANNELS)]
        img = edit_amount(base, next(fake_amounts)) if i in edited_at else base_img
        data = to_jpeg(img, 90) if i == 0 else repost_variant(img, rng, channel)
        text = rng.choice(HERO_TEXTS[track]).format(phone=OPERATOR_PHONE)
        pruf.ingest(Submission(text=text, uploads=(Upload(data, "image", "jpg"),), source="seed", channel=channel,
                               posted_at=when.isoformat(timespec="seconds"), external_id=f"hero{i:02d}", label=track))
        counts[track] += 1
    return counts


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reset", action="store_true", help="удалить PRUF_DATA_DIR перед заливкой")
    ap.add_argument("--campaigns", type=int, default=3, help="кампаний фоновой синтетики на трек")
    ap.add_argument("--legit", type=int, default=120, help="легальных постов в фоне")
    ap.add_argument("--no-ocr", action="store_true", help="без OCR (быстро, но без диффа сумм)")
    args = ap.parse_args()

    settings = Settings()
    if args.reset and settings.data_dir.exists():
        if not (settings.data_dir / "pruf.db").exists() and any(settings.data_dir.iterdir()):
            sys.exit(f"{settings.data_dir} не похож на каталог данных ПРУФ, удалите вручную")
        shutil.rmtree(settings.data_dir)
    from pruf.detect.detector import Detector  # импорт после настройки env

    clf = ensure_model(settings)
    pruf = Pruf(settings, detector=Detector(settings, classifier=clf), ocr_enabled=not args.no_ocr)
    t0 = time.perf_counter()
    tmp = settings.data_dir / "_seed_tmp"
    try:
        n = seed_background(pruf, tmp, args.campaigns, args.legit)
        _log(f"фон: {n} постов за {time.perf_counter() - t0:.1f} с")
        counts = seed_hero(pruf, random.Random(2026))
        _log(f"вау-сценарий: {HERO_APPEARANCES} появлений пруфа, {HERO_EDITED} с правкой суммы, треки {counts}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    hero = pruf.db.find_post_by_external_id("hero00")
    if hero:
        arts = pruf.db.artifacts_for_post(hero["id"])
        _log(f"таймлайн: GET /api/v1/artifacts/{arts[0]['id']}/timeline (пост #{hero['id']})")
    _log(f"готово за {time.perf_counter() - t0:.1f} с, данные в {settings.data_dir}")


if __name__ == "__main__":
    main()
