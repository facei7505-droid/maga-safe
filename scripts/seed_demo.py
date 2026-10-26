"""Демо-данные для показа: фоновая синтетика + «вау»-сценарий.

Сценарий:
  1. Один базовый скрин выплаты (+150 000 T) расходится по каналам: 37 появлений за ~30 дней,
     в 5 копиях сумма перерисована. Таймлайн артефакта показывает все появления и правки.
  2. Один номер «оператора» (Kaspi-перевод) встречается в розыгрыше, казино и пирамиде,
     граф собирает их в один кейс на три трека.
  3. Фон: синтетические кампании и легальные посты (контроль ложных срабатываний).
  4. Списки для банков: кейс номера оператора подтверждён (номер чёрный), честный розыгрыш магазина,
     который детектор отправил на проверку, отклонён (номер «снят» и не блокируется).

Запуск: PRUF_DEV_MODE=1 PRUF_DATA_DIR=data/demo python scripts/seed_demo.py --reset
"""

from __future__ import annotations

import argparse
import hashlib
import os
import random
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("PRUF_DEV_MODE", "1")

from pruf.config import ROOT, Settings
from pruf.detect.classifier import TrackClassifier
from pruf.detect.training import training_rows
from pruf.graph.builder import CaseGraph
from pruf.inspect import Inspector
from pruf.lists import apply_case_decision
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
SYNTH_END = datetime(2026, 10, 31, tzinfo=timezone.utc)  # последний день фоновой синтетики


def demo_shift(now: datetime | None = None) -> timedelta:
    """Сдвиг дат демо так, чтобы фон заканчивался сегодня: на показе нет постов «из будущего»."""
    today = (now or datetime.now(timezone.utc)).replace(hour=0, minute=0, second=0, microsecond=0)
    return timedelta(days=(today - SYNTH_END).days)


def _shifted(iso: str, shift: timedelta) -> str:
    return (datetime.fromisoformat(iso) + shift).isoformat(timespec="seconds")


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
    _log(f"модели нет, обучаю на синтетике и ручных dev-наборах → {settings.model_path}")
    posts = Generator(seed=gen_seed).dataset(image_rate=0.0)
    clf = TrackClassifier.train(*training_rows((p.text, p.label) for p in posts if p.split == "train"))
    clf.save(settings.model_path)
    return clf


def seed_background(pruf: Pruf, tmp: Path, campaigns_per_track: int, legit: int, shift: timedelta = timedelta()) -> int:
    gen = Generator(seed=7, out_dir=tmp)
    posts = gen.dataset(campaigns_per_track=campaigns_per_track, posts_per_campaign=10, legit=legit, image_rate=0.3)
    posts.sort(key=lambda p: p.posted_at)
    for p in posts:
        uploads = ()
        if p.image:
            uploads = (Upload((tmp / p.image).read_bytes(), "image", "jpg"),)
        pruf.ingest(Submission(text=p.text, uploads=uploads, source="seed", channel=p.channel, posted_at=_shifted(p.posted_at, shift),
                               external_id=p.id, label=p.label), allow_llm=False)  # демо не тратит бюджет Claude
    return len(posts)


def seed_hero(pruf: Pruf, rng: random.Random, shift: timedelta = timedelta()) -> dict[str, int]:
    """37 появлений одного скрина выплаты, 5 из них с перерисованной суммой, один номер на три трека."""
    start = HERO_START + shift
    receipt_day = (start - timedelta(days=1)).strftime("%d.%m.%Y")  # чек «выплаты» за день до первого поста
    base_img = render_receipt(Receipt("150 000", "Айгерим С.", receipt_day, "14:35", "7740213"))
    base = to_jpeg(base_img, 90)
    edited_at = set(rng.sample(range(4, HERO_APPEARANCES), HERO_EDITED))
    fake_amounts = iter(["450 000", "1 150 000", "750 000", "350 000", "950 000"])
    tracks = ["lottery", "casino", "pyramid"]
    counts = {t: 0 for t in tracks}
    for i in range(HERO_APPEARANCES):
        track = tracks[i % 3]
        when = start + timedelta(minutes=int(i * HERO_DAYS * 24 * 60 / HERO_APPEARANCES) + rng.randint(0, 600))
        channel = HERO_CHANNELS[i % len(HERO_CHANNELS)]
        img = edit_amount(base, next(fake_amounts)) if i in edited_at else base_img
        data = to_jpeg(img, 90) if i == 0 else repost_variant(img, rng, channel)
        text = rng.choice(HERO_TEXTS[track]).format(phone=OPERATOR_PHONE)
        pruf.ingest(Submission(text=text, uploads=(Upload(data, "image", "jpg"),), source="seed", channel=channel,
                               posted_at=when.isoformat(timespec="seconds"), external_id=f"hero{i:02d}", label=track), allow_llm=False)
        counts[track] += 1
    return counts


# Жалобы из расширения: номер оператора из реестра и новый номер пирамиды из WhatsApp-групп, которого
# в постах ещё нет. Так видно, что пользователи приносят реквизиты, до которых разведчик не дошёл.
DEMO_REPORTS = (
    (OPERATOR_PHONE, ("telegram", "telegram", "whatsapp", "instagram"), ["giveaway", "paid_entry", "kaspi_transfer"]),
    ("+7 708 400 12 90", ("whatsapp", "whatsapp", "whatsapp"), ["income_promise", "referral", "kaspi_transfer"]),
    ("+7 771 555 23 41", ("telegram",), ["casino", "promo_code"]),
)


def seed_reports(pruf: Pruf) -> int:
    inspector = Inspector(pruf.db, pruf.settings.effective_hmac_key())
    n = 0
    for phone, platforms, cues in DEMO_REPORTS:
        for i, platform in enumerate(platforms):
            reporter = hashlib.sha256(f"demo-reporter-{i}".encode()).hexdigest()[:24]
            digest = hashlib.sha256(f"{phone}|{i}".encode()).hexdigest()
            n += inspector.report(reporter, platform, [phone], [], digest, cues)
    return n


# Честный розыгрыш: бесплатное участие, но приз и номер в тексте — детектор ставит «средний», аналитик снимает.
HONEST_GIVEAWAY = ("@dala_textile_kz", "🎁 РОЗЫГРЫШ от магазина «Дала Текстиль»! Разыгрываем 3 сертификата по 20 000 ₸. "
                   "Условия: подписка и репост. Итоги 5 ноября в прямом эфире. Доставка приза бесплатно. "
                   "Вопросы: +7 702 640 18 33")


def seed_trusted_history(pruf: Pruf) -> int:
    """Двое жалобщиков раньше уже жаловались на номера, которые аналитик подтвердил: у них есть история,
    и их жалобы поднимают номер в очереди. Номера берём из чёрного списка демо-заливки."""
    inspector = Inspector(pruf.db, pruf.settings.effective_hmac_key())
    black = [r["display"] for r in pruf.db.requisite_feed(None, "medium", 50, 0, "black") if r["kind"] in ("phone", "kaspi_link")]
    n = 0
    for value in black:
        for i in (0, 1):
            reporter = hashlib.sha256(f"demo-reporter-{i}".encode()).hexdigest()[:24]
            digest = hashlib.sha256(f"history|{value}|{i}".encode()).hexdigest()
            n += inspector.report(reporter, "telegram", [value], [], digest, ["kaspi_transfer"])
    return n


class _SilentTelegram:
    """Заглушка Bot API для демо: ответы бота никуда не отправляются, нужна только кнопка под ответом."""

    def __init__(self) -> None:
        self.buttons: list[list[tuple[str, str]] | None] = []

    def send_message(self, chat_id, text, reply_to=None, buttons=None) -> None:
        self.buttons.append(buttons)

    def answer_callback(self, callback_id, text) -> None:
        pass

    def clear_buttons(self, chat_id, message_id) -> None:
        pass


# Кто сколько раз переслал пост боту и сколько из них нажали «Это не мошенничество»: честный розыгрыш
# оспаривают почти все, скам-розыгрыш почти никто. Так на демо видно, какие признаки стоит пересмотреть.
DEMO_BOT_CHECKS = ((HONEST_GIVEAWAY[1], 6, 4), ("🎁 РОЗЫГРЫШ iPhone 15 Pro! Участие всего 2000 тг, "
                    "переводите на Kaspi 8 701 999 88 77. Итоги в пятницу, осталось 5 мест!", 9, 1))


def seed_bot_feedback(pruf: Pruf) -> int:
    from pruf.bot.telegram import BotLogic

    api = _SilentTelegram()
    bot = BotLogic(pruf, api, pruf.settings.max_upload_bytes)
    uid = 0
    for text, asked, disputed in DEMO_BOT_CHECKS:
        for user in range(asked):
            uid += 1
            bot.handle({"update_id": uid, "message": {"message_id": 1, "chat": {"id": 9000 + user, "type": "private"}, "text": text}})
            buttons = api.buttons[-1]
            if buttons and user < disputed:
                bot.handle({"update_id": 10_000 + uid, "callback_query": {
                    "id": str(uid), "from": {"id": 9000 + user}, "data": buttons[0][1],
                    "message": {"message_id": 2, "chat": {"id": 9000 + user, "type": "private"}}}})
    return pruf.db.bot_feedback_count()


def seed_decisions(pruf: Pruf) -> dict[str, int]:
    """Решения аналитика для демо: кейс оператора подтверждён, честный розыгрыш отклонён."""
    channel, text = HONEST_GIVEAWAY
    honest = pruf.ingest(Submission(text=text, source="seed", channel=channel, external_id="honest00", label="legit"), allow_llm=False)
    graph = CaseGraph(pruf.db)
    graph.ensure(pruf.version)
    hero = pruf.db.find_post_by_external_id("hero00")
    plan = (("confirmed", hero["id"] if hero else None, "Сеть подтверждена: один номер в трёх схемах"),
            ("dismissed", honest.get("post_id"), "Честный розыгрыш магазина: бесплатное участие"))
    listed: dict[str, int] = {}
    for status, post_id, note in plan:
        key = graph.case_for_post(post_id) if post_id else None
        case = graph.case(key) if key else None
        if case is None:
            _log(f"демо-решение {status}: кейс не найден, пропускаю")
            continue
        pruf.db.set_case_status(key, status, note, "seed")
        listed[status] = apply_case_decision(pruf.db, key, case.post_ids, status, "seed", (c.key for c in graph.cases()))
    return listed


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reset", action="store_true", help="удалить PRUF_DATA_DIR перед заливкой")
    ap.add_argument("--campaigns", type=int, default=3, help="кампаний фоновой синтетики на трек")
    ap.add_argument("--legit", type=int, default=120, help="легальных постов в фоне")
    ap.add_argument("--no-ocr", action="store_true", help="без OCR (быстро, но без диффа сумм)")
    args = ap.parse_args()

    settings = Settings(anthropic_api_key="")  # заливка демо не тратит API: арбитр зовётся только для новых постов на сайте
    if args.reset and (not os.environ.get("PRUF_DATA_DIR") or settings.data_dir.resolve() == (ROOT / "data").resolve()):
        sys.exit("--reset удаляет каталог данных: задайте отдельный PRUF_DATA_DIR (например data/demo), не основной data/")
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
        shift = demo_shift()
        n = seed_background(pruf, tmp, args.campaigns, args.legit, shift)
        _log(f"фон: {n} постов за {time.perf_counter() - t0:.1f} с")
        counts = seed_hero(pruf, random.Random(2026), shift)
        _log(f"вау-сценарий: {HERO_APPEARANCES} появлений пруфа, {HERO_EDITED} с правкой суммы, треки {counts}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    _log(f"жалобы из расширения: {seed_reports(pruf)}")
    _log(f"списки: {seed_decisions(pruf)} (confirmed → чёрный, dismissed → снят)")
    _log(f"история проверенных жалобщиков: {seed_trusted_history(pruf)} жалоб")
    _log(f"отметки «Это не мошенничество» из бота: {seed_bot_feedback(pruf)}")
    hero = pruf.db.find_post_by_external_id("hero00")
    if hero:
        arts = pruf.db.artifacts_for_post(hero["id"])
        _log(f"таймлайн: GET /api/v1/artifacts/{arts[0]['id']}/timeline (пост #{hero['id']})")
    _log(f"готово за {time.perf_counter() - t0:.1f} с, данные в {settings.data_dir}")


if __name__ == "__main__":
    main()
