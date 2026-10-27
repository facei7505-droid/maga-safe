"""Серый, чёрный и «снят» список реквизитов для банков и Антифрод-центра.

Серый: реквизит встречается в постах с признаками схем, кейс ещё не проверен. Банку: проверить перевод.
Чёрный: аналитик подтвердил кейс. Банку: приостановить перевод до проверки.
Снят: аналитик отклонил кейс (например, честный розыгрыш). Банку: не блокировать.

Решение пишется на реквизит, а не на кейс: ключ кейса может смениться при пересборке графа, а решение
аналитика должно остаться. Если номер есть в подтверждённом и в отклонённом кейсе, побеждает чёрный.
"""

from __future__ import annotations

import csv
import hmac
import io
from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone
from typing import Any

from pruf.storage.db import Database

LISTS = ("grey", "black", "cleared")
LIST_TITLES = {"grey": "серый", "black": "чёрный", "cleared": "снят"}
DECISIONS = {"confirmed": "black", "dismissed": "cleared"}
MONEY_KINDS = frozenset({"phone", "card", "iban", "kaspi_link"})  # промокод не платёжный реквизит
REVIEW_WORKING_DAYS = 3  # срок проверки серого номера, как у Антифрод-центра; праздники не учитываются
ADVICE = {
    "grey": "Номер замечен в постах с признаками схем, кейс не проверен: проверить получателя и усилить контроль перевода",
    "black": "Аналитик подтвердил схему: приостановить перевод до проверки",
    "cleared": "Кейс отклонён аналитиком: не блокировать",
}
EXCHANGE_CONTEXT = b"pruf-exchange-v1"
CSV_COLUMNS = ("ref", "type", "value_masked", "list", "cases", "first_seen", "last_seen", "review_due", "reason")


def review_due(grey_since: str) -> str:
    """Дата, с которой номер серый (первый пост среднего или высокого риска), плюс REVIEW_WORKING_DAYS
    рабочих дней; суббота и воскресенье пропускаются."""
    day = datetime.fromisoformat(grey_since).date()
    left = REVIEW_WORKING_DAYS
    while left:
        day += timedelta(days=1)
        if day.weekday() < 5:
            left -= 1
    return day.isoformat()


def parse_decided(decided: str | None) -> list[dict[str, str]]:
    """«N-1:confirmed,C-7:dismissed» из базы → [{"case": "N-1", "decision": "confirmed"}, ...]."""
    out = []
    for item in sorted(filter(None, (decided or "").split(","))):
        case, _, decision = item.rpartition(":")
        out.append({"case": case, "decision": decision})
    return out


def list_info(status: str | None, decided: str | None, grey_since: str, today: date | None = None) -> dict[str, Any]:
    """Поля списка для ответа банку: статус, совет, срок проверки серого номера и кейсы-основания."""
    status = status or "grey"
    due = review_due(grey_since) if status == "grey" else None
    today = today or datetime.now(timezone.utc).date()
    decisions = parse_decided(decided)
    reason = "; ".join(f"кейс {d['case']} {'подтверждён' if d['decision'] == 'confirmed' else 'отклонён'}"
                       for d in decisions) or "кейс ещё не проверен"
    return {"list": status, "advice": ADVICE[status], "review_due": due,
            "overdue": bool(due and date.fromisoformat(due) < today), "list_reason": reason}


def case_money_keys(db: Database, post_ids: Iterable[int]) -> list[str]:
    """Платёжные реквизиты из постов среднего и высокого риска кейса. Посты-контекст низкого риска
    (предупреждение, где назван номер схемы и номер поддержки банка) в списки ничего не добавляют."""
    levels = db.post_levels(post_ids)
    core = [pid for pid, (level, _track, _score) in levels.items() if level in ("medium", "high")]
    keys = {r["key"] for pid in core for r in db.requisites_for_post(pid) if r["kind"] in MONEY_KINDS}
    return sorted(keys)


def apply_case_decision(db: Database, case_key: str, post_ids: Iterable[int], status: str, actor: str,
                        live_cases: Iterable[str] = ()) -> int:
    """Статус кейса → списки: подтверждён — реквизиты в чёрный, отклонён — «снят», иначе решение снимается.
    Решения по этим же реквизитам от кейсов, которых больше нет в графе (слились при пересборке), заменяются
    новым решением аналитика. Возвращает число реквизитов, получивших решение."""
    decision = status if status in DECISIONS else None
    keys = case_money_keys(db, post_ids)
    db.drop_stale_decisions(keys, {*live_cases, case_key})
    db.set_case_decision(case_key, keys if decision else [], decision, actor)
    if decision:
        db.audit(actor, "requisite_list", f"{case_key}:{DECISIONS[decision]}:{len(keys)}")
    return len(keys) if decision else 0


def mask(kind: str, display: str) -> str:
    """Для выгрузки: видны только последние 4 знака (у карты маска 6+4, как в базе)."""
    if kind == "card" or len(display) < 8:
        return display
    if kind == "kaspi_link":
        head, _, tail = display.rpartition("/")
        return f"{head}/{tail[:2]}***" if head else display[:4] + "***"
    return display[:2] + "*" * (len(display) - 6) + display[-4:]


def exchange_key(hmac_key: bytes) -> bytes:
    """Ключ обмена выводится из ключа сервера: его можно отдать участникам обмена, а ключ сервера,
    которым обезличены карты в базе, остаётся только у ПРУФ."""
    return hmac.new(hmac_key, EXCHANGE_CONTEXT, "sha256").digest()


def export_ref(key: str, hmac_key: bytes) -> str:
    """Ссылка на реквизит в выгрузке: HMAC ключом обмена. Участник обмена посчитает её у себя
    для своих получателей и сверит, а сам файл номеров не раскрывает."""
    return hmac.new(exchange_key(hmac_key), key.encode(), "sha256").hexdigest()


def _cell(value: Any) -> str:
    text = "" if value is None else str(value)
    # Формулы в CSV: Excel выполнит ячейку, начинающуюся с = + - @, поэтому экранируем апострофом
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def to_csv(rows: Iterable[dict[str, Any]]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(CSV_COLUMNS)
    for row in rows:
        writer.writerow([_cell(row.get(c)) for c in CSV_COLUMNS])
    return buf.getvalue()
