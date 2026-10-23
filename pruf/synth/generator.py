"""Генератор синтетического датасета со связями между постами и треками.

- Кампании: у каждой свои реквизиты, домены, каналы и базовый «скрин выплаты».
- Перекрёстные связи: часть кампаний разных треков делит один номер «оператора».
- Контроль: легальные конкурсы, реклама, предупреждения, личные переводы, сборы, чеки магазинов.
- Обфускация: гомоглифы, leet, эмодзи, капс.
- Разбиение train/test по кампаниям и по шаблонам (отложенные шаблоны только в тесте).
"""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pruf.synth import templates as T
from pruf.synth.screens import (
    Receipt,
    edit_amount,
    render_receipt,
    repost_variant,
    to_jpeg,
)

TRACK_TEMPLATES = {"lottery": T.LOTTERY, "casino": T.CASINO, "pyramid": T.PYRAMID}
HELD_OUT_EVERY = 4  # каждый 4-й шаблон отложен для теста
_HOMO = {"а": "a", "о": "o", "е": "e", "р": "p", "с": "c", "х": "x"}
_EMOJI = ["🔥", "💰", "✅", "👇", "🎁", "💸", "⚡", "😱"]
_NAMES = ["Айгерим С.", "Нурлан К.", "Дана Б.", "Ерлан Т.", "Асель М.", "Тимур Ж.", "Мадина Р."]
START = datetime(2026, 9, 1, tzinfo=timezone.utc)


def _luhn_complete(prefix: str, rng: random.Random) -> str:
    body = prefix + "".join(str(rng.randint(0, 9)) for _ in range(15 - len(prefix)))
    total = 0
    for i, ch in enumerate(reversed(body)):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return body + str((10 - total % 10) % 10)


def fake_phone(rng: random.Random) -> str:
    return f"+7 7{rng.choice(['01', '02', '05', '07', '47', '75', '77'])} {rng.randint(100, 999)} {rng.randint(10, 99)} {rng.randint(10, 99)}"


def fake_card(rng: random.Random) -> str:
    num = _luhn_complete("400303", rng)
    return " ".join(num[i:i + 4] for i in range(0, 16, 4))


@dataclass
class Campaign:
    id: str
    track: str
    phone: str
    card: str
    kaspi: str
    domain: str
    promo: str
    channels: list[str]
    receipt: Receipt
    split: str


@dataclass
class SynthPost:
    id: str
    text: str
    label: str  # lottery | casino | pyramid | legit
    lang: str
    template: str
    split: str
    channel: str
    posted_at: str
    campaign: str | None = None
    image: str | None = None  # путь к файлу
    image_edited: bool = False
    shared_operator: bool = False
    tags: list[str] = field(default_factory=list)


def obfuscate(text: str, rng: random.Random) -> str:
    out = []
    for ch in text:
        low = ch.lower()
        if low in _HOMO and rng.random() < 0.12:
            out.append(_HOMO[low].upper() if ch.isupper() else _HOMO[low])
        elif low == "о" and rng.random() < 0.05:
            out.append("0")
        else:
            out.append(ch)
    text = "".join(out)
    if rng.random() < 0.4:
        text = rng.choice(_EMOJI) + " " + text + " " + rng.choice(_EMOJI)
    if rng.random() < 0.15:
        text = text.upper()
    return text


def _fill(template: str, c: Campaign | None, rng: random.Random, kk: bool = False) -> str:
    prizes = T.PRIZES_KK if kk else T.PRIZES
    slots = {
        "prize": rng.choice(prizes), "fee": rng.choice(["500", "1000", "1 500", "2000", "3 000", "5000"]),
        "phone": c.phone if c else fake_phone(rng), "card": c.card if c else fake_card(rng),
        "kaspi": c.kaspi if c else f"kaspi.kz/pay/{rng.randint(10000, 99999)}",
        "domain": c.domain if c else rng.choice(T.CASINO_DOMAINS), "promo": c.promo if c else "WIN" + str(rng.randint(10, 999)),
        "pct": rng.choice(["2", "3", "5", "7", "1.5"]), "amount": f"{rng.randint(50, 900)} 000",
        "n": str(rng.randint(3, 15)), "mult": f"x{rng.choice([50, 100, 150, 500, 1000])}",
        "start": rng.choice(["5000", "10 000", "20 000", "50 000"]),
    }
    return template.format(**slots)


class Generator:
    def __init__(self, seed: int = 42, out_dir: Path | None = None):
        self.rng = random.Random(seed)
        self.out_dir = out_dir
        self._n = 0

    def _next_id(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}{self._n:05d}"

    def _when(self, days: int = 60) -> str:
        return (START + timedelta(minutes=self.rng.randint(0, days * 24 * 60))).isoformat(timespec="seconds")

    def _save_image(self, data: bytes, name: str) -> str | None:
        if not self.out_dir:
            return None
        path = self.out_dir / "images" / f"{name}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return str(path.relative_to(self.out_dir))

    def campaigns(self, per_track: int) -> list[Campaign]:
        rng = self.rng
        out = []
        for track in TRACK_TEMPLATES:
            for i in range(per_track):
                cid = f"{track[:3]}{i:02d}"
                out.append(Campaign(
                    id=cid, track=track, phone=fake_phone(rng), card=fake_card(rng),
                    kaspi=f"kaspi.kz/pay/{rng.choice(['bonus', 'shop', 'invest', 'lucky'])}{rng.randint(100, 9999)}",
                    domain=rng.choice(T.CASINO_DOMAINS if track == "casino" else T.SCAM_DOMAINS),
                    promo=rng.choice(["BONUS", "WIN", "KZ", "LUCKY", "TOP"]) + str(rng.randint(100, 999)),
                    channels=[f"@{track}_{cid}_{k}" for k in range(rng.randint(2, 5))],
                    receipt=Receipt(f"{rng.randint(50, 900)} 000", rng.choice(_NAMES), f"{rng.randint(1, 28):02d}.10.2026",
                                    f"{rng.randint(8, 23)}:{rng.randint(10, 59)}", str(rng.randint(1_000_000, 9_999_999))),
                    split="test" if i % 3 == 2 else "train",
                ))
        # Перекрёстные связи: каждая третья кампания делит номер «оператора» с кампанией другого трека
        by_track = {t: [c for c in out if c.track == t] for t in TRACK_TEMPLATES}
        for i in range(0, per_track, 3):
            operator = fake_phone(rng)
            for t in TRACK_TEMPLATES:
                if i < len(by_track[t]):
                    by_track[t][i].phone = operator
        return out

    def scheme_posts(self, c: Campaign, count: int, image_rate: float = 0.35) -> list[SynthPost]:
        rng = self.rng
        tmpl = TRACK_TEMPLATES[c.track]
        base_jpeg = to_jpeg(render_receipt(c.receipt), 88)
        posts = []
        for _ in range(count):
            held_out = [i for i in range(len(tmpl)) if i % HELD_OUT_EVERY == HELD_OUT_EVERY - 1]
            seen = [i for i in range(len(tmpl)) if i not in held_out]
            # train видит только «открытые» шаблоны; test наполовину из отложенных, наполовину из открытых
            allowed = held_out if c.split == "test" and rng.random() < 0.5 else seen
            idx = rng.choice(allowed)
            lang, template = tmpl[idx]
            text = _fill(template, c, rng, kk=lang == "kk")
            if rng.random() < 0.45:
                text = obfuscate(text, rng)
            pid = self._next_id("s")
            post = SynthPost(id=pid, text=text, label=c.track, lang=lang, template=f"{c.track}:{idx}", split=c.split,
                             channel=rng.choice(c.channels), posted_at=self._when(), campaign=c.id)
            if rng.random() < image_rate:
                edited = rng.random() < 0.25
                img = edit_amount(base_jpeg, f"{rng.randint(100, 990)} 000") if edited else render_receipt(c.receipt)
                post.image = self._save_image(repost_variant(img, rng, post.channel), pid)
                post.image_edited = edited
            posts.append(post)
        return posts

    def legit_posts(self, count: int, image_rate: float = 0.1) -> list[SynthPost]:
        rng = self.rng
        posts = []
        for k in range(count):
            idx = rng.randrange(len(T.LEGIT))
            lang, template = T.LEGIT[idx]
            split = "test" if idx % HELD_OUT_EVERY == HELD_OUT_EVERY - 1 or k % 3 == 2 else "train"
            text = _fill(template, None, rng, kk=lang == "kk")
            if rng.random() < 0.2:
                text = obfuscate(text, rng)
            pid = self._next_id("l")
            post = SynthPost(id=pid, text=text, label="legit", lang=lang, template=f"legit:{idx}", split=split,
                             channel=f"@city_{rng.randint(1, 40)}", posted_at=self._when())
            if rng.random() < image_rate:
                r = Receipt(f"{rng.randint(1, 99)} {rng.randint(100, 999)}", "Магазин " + str(rng.randint(1, 50)),
                            f"{rng.randint(1, 28):02d}.10.2026", f"{rng.randint(8, 23)}:{rng.randint(10, 59)}",
                            str(rng.randint(1_000_000, 9_999_999)), accent=(40, 120, 200))
                post.image = self._save_image(repost_variant(render_receipt(r), rng), pid)
                post.tags.append("receipt_control")
            posts.append(post)
        return posts

    def dataset(self, campaigns_per_track: int = 9, posts_per_campaign: int = 18, legit: int = 700,
                image_rate: float = 0.35) -> list[SynthPost]:
        camps = self.campaigns(campaigns_per_track)
        operators = {}
        for c in camps:
            operators.setdefault(c.phone, set()).add(c.track)
        shared = {p for p, tracks in operators.items() if len(tracks) > 1}
        posts: list[SynthPost] = []
        for c in camps:
            for post in self.scheme_posts(c, posts_per_campaign, image_rate):
                post.shared_operator = c.phone in shared
                posts.append(post)
        posts.extend(self.legit_posts(legit, image_rate=image_rate / 3))
        self.rng.shuffle(posts)
        return posts


def write_jsonl(posts: list[SynthPost], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for p in posts:
            fh.write(json.dumps(asdict(p), ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[SynthPost]:
    with path.open(encoding="utf-8") as fh:
        return [SynthPost(**json.loads(line)) for line in fh if line.strip()]
