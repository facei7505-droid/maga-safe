"""Проверка для расширения ПРУФ Sentinel без текста поста.

Расширение присылает только то, что вытащило из поста само: реквизиты, ссылки, SHA-256 текста
и номера сработавших локальных признаков (cues). Сам текст на сервер не уходит.
Балл складывается из признаков и того, что уже знает реестр: засвеченный реквизит, домен из
чёрного списка, точная копия текста известной рассылки.
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
import unicodedata
from dataclasses import dataclass
from typing import Any

from pruf.models import HIGH_THRESHOLD, LEVEL_LABELS, level_for
from pruf.normalize.links import ALLOWLIST_DOMAINS, MESSENGER_HOSTS, SHORTENERS, extract_links
from pruf.normalize.requisites import extract_requisites
from pruf.storage.db import Database

TRACK_TITLES = {"lottery": "платного розыгрыша", "casino": "скрытой рекламы казино", "pyramid": "финансовой пирамиды"}


@dataclass(frozen=True)
class Cue:
    track: str  # lottery | casino | pyramid | common
    short: str  # для плашки: «перевод на Kaspi»
    label: str  # для «Почему?»
    weight: int


# Те же номера признаков ищет у себя extension/lib/extract.js; неизвестные номера сервер отбрасывает.
CUES: dict[str, Cue] = {
    "paid_entry": Cue("common", "платный вход", "Платное участие или вход: взнос в тенге", 30),
    "delivery_fee": Cue("lottery", "оплата доставки приза", "Просят оплатить «доставку» или «комиссию» за приз", 30),
    "giveaway": Cue("lottery", "розыгрыш", "Розыгрыш или приз", 10),
    "casino": Cue("casino", "реклама казино", "Реклама казино, слотов или ставок", 25),
    "big_win": Cue("casino", "«поднял x500»", "Хвастовство выигрышем: «поднял x500», «занос»", 20),
    "promo_code": Cue("casino", "промокод на бонус", "Промокод или бонус на депозит", 15),
    "income_promise": Cue("pyramid", "обещание дохода", "Обещание дохода: % в день, «удвоим за неделю»", 35),
    "referral": Cue("pyramid", "доход за приглашённых", "Доход за приглашённых друзей", 25),
    "guarantee": Cue("pyramid", "гарантия выплат", "«Гарантия выплат», «без риска»", 15),
    "kaspi_transfer": Cue("common", "перевод на Kaspi", "Просят перевести деньги на Kaspi или карту", 15),
    "urgency": Cue("common", "давление срочностью", "Давление срочностью: «осталось 5 мест», «только сегодня»", 10),
}
REQUISITE_WEIGHT = 35
DOMAIN_WEIGHT = 40
TEXT_COPY_WEIGHT = 50
MAX_SCORE = 100
INDEX_MAX_AGE = 600.0  # разведчик пишет в базу из своего процесса: раз в 10 минут перечитываем
INDEX_MIN_AGE = 30.0  # при потоке приёма индекс пересобирается не чаще раза в 30 секунд
BLACKLIST_MIN_CHANNELS = 2  # один канал не может сам внести домен в чёрный список
# Публичные суффиксы: под ними сайты разных владельцев, блокировать суффикс целиком нельзя
PUBLIC_SUFFIXES = frozenset({
    "com.kz", "org.kz", "net.kz", "edu.kz", "mil.kz", "gov.kz", "co.uk", "com.ru", "org.ru", "net.ru", "github.io",
    "pages.dev", "vercel.app", "netlify.app", "web.app", "firebaseapp.com", "herokuapp.com", "blogspot.com",
    "appspot.com", "workers.dev", "glitch.me", "onrender.com",
})
# Популярные площадки: ссылка на них в скам-посте («как на apple.com») не делает их опасными
POPULAR_DOMAINS = frozenset({
    "apple.com", "wikipedia.org", "facebook.com", "x.com", "twitter.com", "whatsapp.com", "telegram.org", "github.com",
    "microsoft.com", "yandex.kz", "yandex.ru", "mail.ru", "olx.kz", "kolesa.kz", "krisha.kz", "wildberries.kz", "ozon.kz",
    "binance.com", "bybit.com", "forte.kz", "jusan.kz", "bcc.kz", "homecredit.kz", "freedombank.kz", "kase.kz",
})
_DOMAIN_RE = re.compile(r"^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9\-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def text_hash(text: str) -> str:
    """Тот же хэш считает расширение: NFKC, нижний регистр, всё кроме букв и цифр → один пробел.
    Хэшируется текст в том виде, как он хранится в реестре (redact_cards: карты маской 6+4)."""
    folded = re.sub(r"[\W_]+", " ", unicodedata.normalize("NFKC", text).lower()).strip()
    return hashlib.sha256(folded.encode()).hexdigest()


def blacklist_domain(domain: str) -> bool:
    """Домен можно отдать в чёрный список: валидное имя, не публичный суффикс, не банк, не госсайт,
    не соцсеть и не сокращатель, включая их поддомены (kgd.gov.kz, pay.kaspi.kz)."""
    if not _DOMAIN_RE.match(domain) or domain in PUBLIC_SUFFIXES:
        return False
    protected = ALLOWLIST_DOMAINS | MESSENGER_HOSTS | SHORTENERS | POPULAR_DOMAINS
    return not any(domain == p or domain.endswith("." + p) for p in protected)


class Inspector:
    def __init__(self, db: Database, hmac_key: bytes):
        self._db = db
        self._key = hmac_key
        self._lock = threading.Lock()
        self._version = -1
        self._built_at = -INDEX_MAX_AGE
        self._hashes: frozenset[str] = frozenset()
        self._domains: frozenset[str] = frozenset()

    def refresh(self, version: int) -> None:
        """Индексы рискованных текстов и доменов пересобираются после приёма или раз в INDEX_MAX_AGE."""
        with self._lock:
            age = time.monotonic() - self._built_at
            if age < INDEX_MIN_AGE or (version == self._version and age < INDEX_MAX_AGE):
                return
            self._hashes = frozenset(text_hash(t) for t in self._db.risky_texts())
            self._domains = frozenset(d["domain"] for d in self._db.risky_domains()
                                      if d["channels"] >= BLACKLIST_MIN_CHANNELS and blacklist_domain(d["domain"]))
            self._version = version
            self._built_at = time.monotonic()

    def blacklist(self) -> list[str]:
        return sorted(self._domains)

    def inspect(self, requisites: list[str], links: list[str], digest: str | None, cues: list[str]) -> dict[str, Any]:
        reasons: list[dict[str, Any]] = []
        track_points: dict[str, int] = {}
        for cue_id in dict.fromkeys(cues):
            cue = CUES.get(cue_id)
            if cue is None:
                continue
            reasons.append({"id": cue_id, "short": cue.short, "label": cue.label, "weight": cue.weight})
            if cue.track != "common":
                track_points[cue.track] = track_points.get(cue.track, 0) + cue.weight
        checked = self._check_requisites(requisites)
        if any(r["found"] for r in checked):
            tracks = sorted({t for r in checked for t in r["tracks"]})
            reasons.append({"id": "registry.requisite", "short": "реквизит засвечен в схемах",
                            "label": "Этот номер или реквизит уже встречался в постах с признаками схем", "weight": REQUISITE_WEIGHT})
            for t in tracks:
                track_points[t] = track_points.get(t, 0) + REQUISITE_WEIGHT // max(len(tracks), 1)
        bad_domains = sorted({link.domain for link in extract_links(" ".join(links)) if link.domain in self._domains})
        if bad_domains:
            reasons.append({"id": "registry.domain", "short": "сайт в чёрном списке",
                            "label": "Ссылка ведёт на домен из чёрного списка ПРУФ: " + ", ".join(bad_domains), "weight": DOMAIN_WEIGHT})
        if digest and digest in self._hashes:
            reasons.append({"id": "registry.text_copy", "short": "копия известной рассылки",
                            "label": "Текст дословно совпадает с постом, где ПРУФ нашёл признаки схемы", "weight": TEXT_COPY_WEIGHT})
        score = min(sum(r["weight"] for r in reasons), MAX_SCORE)
        level = level_for(score)
        track = max(track_points, key=track_points.get) if track_points else None
        return {"score": score, "level": level, "level_label": LEVEL_LABELS[level], "track": track,
                "show_banner": score >= HIGH_THRESHOLD, "title": _title(track, reasons), "reasons": reasons,
                "requisites": checked, "blacklisted_domains": bad_domains}

    def _check_requisites(self, values: list[str]) -> list[dict[str, Any]]:
        out = []
        for req in extract_requisites("\n".join(values), self._key):
            if req.kind == "promo":
                continue
            found = self._db.lookup_requisite(req.key)
            # Без счётчиков и каналов: расширение отвечает «засвечен или нет», а не раскрывает базу
            out.append({"type": req.kind, "value": req.display, "found": bool(found),
                        "tracks": sorted(set((found["tracks"] or "").split(",")) - {""}) if found else []})
        return out


def _title(track: str | None, reasons: list[dict[str, Any]]) -> str:
    head = f"Признаки {TRACK_TITLES[track]}" if track else "Признаки мошеннической схемы"
    top = [r["short"] for r in sorted(reasons, key=lambda r: -r["weight"])[:3]]
    return head + (": " + ", ".join(top) if top else "")
