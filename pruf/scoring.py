"""Итоговый балл 0–100 по трекам: признаки + ML + сигналы реестра и графа.

Правила расчёта (они же «методика» для жюри):
1. Баллы признаков трека суммируются (каждый признак один раз). Общие признаки
   добавляются, только если у трека есть свой положительный признак.
2. rule_score = 100 * (1 - exp(-points / SATURATION)).
3. Если есть ML: score = max(rule_score, 0.65 * rule_score + 0.35 * 100 * p(track)),
   то есть модель может только поднять балл. Без признаков ML даёт максимум ML_ONLY_CAP,
   это ниже среднего риска. Исключение: модель уверена (p ≥ ML_ALONE), нет предупреждения,
   стоп-признака и вето LLM. Тогда пост получает ML_ALONE_SCORE («средний», только ручная проверка),
   а аналитик видит слова, на которые опиралась модель.
4. Один-единственный признак трека без общих признаков даёт не больше низкого риска:
   риск строится на сочетании сигналов.
5. Высокий риск только при обязательном сочетании: два «ядровых» признака трека
   или ядровой признак + просьба перевести деньги (или ввести данные карты). Иначе потолок HIGH_THRESHOLD - 1.
6. Стоп-признаки (бесплатное участие, правила, антиреклама) вычитают баллы и
   опускают потолок до среднего. Предупреждение или новость о схеме действует на все
   треки; если при нём нет просьбы о деньгах, реквизита или ссылки, потолок — низкий риск,
   а если есть — это маскировка: стоп-признаки баллы не снимают, потолок «средний».
   Новостью пост считается по двум новостным маркерам, одно слово «приговор» рекламу не прячет.
   Признаки-действия под отрицанием («не переводите») и фразы в кавычках внутри
   предупреждения не считаются.
7. Контекст (повтор пруфа в рискованных постах, правка пруфа, реквизит из рискованных
   кейсов) добавляется после, отдельной строкой объяснения. Без признаков в тексте он
   учитывается, только если это сильный сигнал своего трека (повтор пруфа или реквизит
   из рискованных постов), то есть повтор сам по себе риском не считается; такой пост
   получает не больше среднего риска. Потолки из пп. 4–6 применяются уже после контекста.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence

from pruf.detect.lexicon import TRACK_LABELS, TRACKS
from pruf.models import (
    HIGH_THRESHOLD,
    MEDIUM_THRESHOLD,
    Analysis,
    Evidence,
    TrackScore,
    level_for,
)

SATURATION = 35.0
ML_WEIGHT = 0.35
ML_ONLY_CAP = 30.0  # ниже порога «средний»: неуверенная модель без признаков не поднимает пост в очередь
# Уверенная модель без признаков правил: живой сленг и казахский, которых нет в словаре. Только «средний»:
# пост идёт аналитику на ручную проверку со словами, на которые опиралась модель (scripts/eval.py, слепой v9).
ML_ALONE = 0.6
ML_ALONE_SCORE = MEDIUM_THRESHOLD + 5.0
STOP_CAP = HIGH_THRESHOLD - 1
SINGLE_CAP = MEDIUM_THRESHOLD - 1
CONTEXT_ONLY_CAP = HIGH_THRESHOLD - 1
NO_COMBO_CAP = HIGH_THRESHOLD - 1
AWARENESS_SUFFIX = ".awareness"
NEWS_WARNING = "common.news.awareness"
SHARED_WARNINGS = frozenset({"common.awareness", NEWS_WARNING, "common.question.awareness"})  # на все треки; «рейд», «подпольн» — только казино
# Реквизит или ссылка: у настоящей рекламы схемы есть куда платить или переходить, у новости и предупреждения обычно нет
CONTACT_EVIDENCE = frozenset({"common.requisite", "common.kaspi_pay_link", "common.shortener", "common.brand_lookalike", "casino.domain"})
# «Пиши в лс», «ссылка в шапке» — призыв к действию в рекламе, но в новости это описание схемы
SOFT_CONTACT = frozenset({"common.dm_redirect", "casino.hidden_promo"})
# Вспомогательные признаки сами трек не открывают: «3,5 млн» в сборе на операцию — не розыгрыш
AUX_FEATURES = frozenset({"lottery.big_prize", "pyramid.closed_group", "pyramid.regular_payout"})
MONEY_ASKS = frozenset({"common.kaspi_transfer", "common.card_phish", "common.paid_access"})  # просьба отдать деньги или данные карты
# Модель уверена в треке: вместе с одним признаком в тексте это уже сочетание сигналов, а не «один признак»
ML_CONFIRM = 0.5
DENIAL = "common.denial"  # «бұл scam емес», «мы работаем честно»: предупреждение рядом с этим — маскировка
LLM_LEGIT = "llm.legit"  # LLM: пост целиком похож на легальный, своих признаков схемы не нашла
STRONG_CONTEXT = 15.0
CONTACT_COMBO_FEATURES = frozenset({"casino.fixed_match", "casino.money_game", "pyramid.high_return", "pyramid.mutual_aid",
                                    "lottery.entry_fee", "lottery.prize_fee"})
ML_CONTACT_COMBO = 0.3  # сигнал реестра/графа такой силы учитывается даже без признаков в тексте


def _unique_by_feature(items: Iterable[Evidence]) -> dict[str, Evidence]:
    best: dict[str, Evidence] = {}
    for ev in items:
        if ev.feature_id not in best:
            best[ev.feature_id] = ev
    return best


def score_track(track: str, evidence: list[Evidence], ml: Mapping[str, float] | None,
                context: list[Evidence]) -> TrackScore:
    own = _unique_by_feature(e for e in evidence if e.track == track)
    # Предупреждение или новость о схеме относится ко всем трекам: разбор пирамиды не делает пост розыгрышем
    warning = next((e for e in evidence if e.feature_id in SHARED_WARNINGS), None)
    # одно слово «сотында» в рекламе пирамиды новостью её не делает: нужны два новостных маркера
    is_news = sum(1 for e in evidence if e.feature_id == NEWS_WARNING) >= 2
    if warning and not any(f.endswith(AWARENESS_SUFFIX) for f in own):
        own[f"{track}{AWARENESS_SUFFIX}"] = warning
    common = _unique_by_feature(e for e in evidence if e.track == "common" and not e.stop)
    has_positive = any(e.weight > 0 and e.feature_id not in AUX_FEATURES for e in own.values())
    has_transfer = bool(MONEY_ASKS & common.keys())
    contacts = CONTACT_EVIDENCE if is_news else CONTACT_EVIDENCE | SOFT_CONTACT
    has_contact = bool(contacts & (common.keys() | own.keys()))
    hard_contact = bool(CONTACT_EVIDENCE & (common.keys() | own.keys()))
    # «Осторожно, мошенники!» рядом с реквизитом или просьбой заплатить — маскировка, а не предупреждение:
    # баллы оно не снимает, остаётся только потолок «средний»
    disguise = has_transfer or has_contact or DENIAL in common
    # «Итоги тиража» рядом с реквизитом или просьбой заплатить баллы тоже не снимают; потолок «средний» остаётся.
    # «Запись в лс» у турнира — не маскировка: мягкий призыв снимает только скидку предупреждения.
    unmasked = has_transfer or hard_contact
    points = sum(e.weight for e in own.values()
                 if not e.stop or not (unmasked or (disguise and e.feature_id.endswith(AWARENESS_SUFFIX))))
    if has_positive:
        points += sum(e.weight for e in common.values())
    rule_score = 100.0 * (1.0 - math.exp(-max(points, 0.0) / SATURATION))

    p_track = ml.get(track) if ml else None
    if p_track is None:
        score = rule_score
    elif has_positive:
        score = max(rule_score, (1 - ML_WEIGHT) * rule_score + ML_WEIGHT * 100.0 * p_track)
    else:
        score = min(ML_ONLY_CAP, 100.0 * p_track * ML_WEIGHT * 2)

    capped: str | None = None
    ml_alone = (not has_positive and p_track is not None and p_track >= ML_ALONE and not warning
                and not any(e.stop or e.feature_id == LLM_LEGIT for e in evidence))
    if ml_alone:
        score, capped = ML_ALONE_SCORE, "признаков из словаря нет, сигнал только модели — нужна ручная проверка"
    track_context = [c for c in _unique_by_feature(c for c in context if c.track in (track, "common")).values() if c.weight > 0]
    strong_own = any(c.track == track and c.weight >= STRONG_CONTEXT for c in track_context)
    if has_positive or score >= MEDIUM_THRESHOLD or strong_own:
        score += sum(c.weight for c in track_context)

    # Потолки применяются после контекста: связи с другими постами не отменяют правила методики.
    positives = [e for e in own.values() if e.weight > 0]
    if not has_positive and track_context and score > CONTEXT_ONLY_CAP:
        score, capped = CONTEXT_ONLY_CAP, "собственных признаков нет, только связь с рискованными постами"
    ml_confirms = p_track is not None and p_track >= ML_CONFIRM
    # признак схемы + реквизит или просьба заплатить — уже сочетание: куда переводить, тоже сигнал
    # узкий признак схемы + «пиши в лс» без предупреждения рядом — тоже сочетание: есть куда идти.
    # Широкие признаки («приглашаю», «пакет от», «слоты», «розыгрыш») с «пишите в лс» — обычная реклама услуг.
    contact_combo = (has_contact and len(positives) == 1 and positives[0].feature_id in CONTACT_COMBO_FEATURES
                     and not warning and not any(e.stop for e in evidence) and (p_track is None or p_track >= ML_CONTACT_COMBO))
    if len(positives) == 1 and not (unmasked or track_context or ml_confirms or contact_combo) and score > SINGLE_CAP:
        score, capped = SINGLE_CAP, "найден только один признак, нужен хотя бы ещё один"
    core_count = sum(1 for e in own.values() if e.core)
    if score >= HIGH_THRESHOLD and not (core_count >= 2 or (core_count >= 1 and (has_transfer or track_context))):
        score, capped = NO_COMBO_CAP, "нет обязательного сочетания признаков для высокого риска"
    if warning and not disguise and (is_news or core_count < 2) and score > SINGLE_CAP:
        score, capped = SINGLE_CAP, "похоже на предупреждение или новость о схеме"
    elif (any(e.feature_id == LLM_LEGIT for e in evidence) and score > SINGLE_CAP
          and not (has_transfer or has_contact or hard_contact or ml_confirms or track_context)):
        # текст недоверенный: при просьбе о деньгах, контакте, уверенной модели или связях «это легально» балл не снижает
        score, capped = SINGLE_CAP, "LLM считает контекст легальным; ссылок, контактов и просьб о деньгах нет"
    elif any(e.stop for e in own.values()) and score > STOP_CAP:
        score, capped = STOP_CAP, "есть признаки легальности"
    score = max(0.0, min(100.0, score))
    return TrackScore(track=track, score=round(score, 1), level=level_for(score), rule_points=round(points, 1),
                      ml_probability=None if p_track is None else round(p_track, 3), capped_reason=capped)


def summarize(level: str, track: str | None, evidence: list[Evidence], capped: str | None = None) -> str:
    legit = list(dict.fromkeys(e.label for e in evidence if e.stop))
    if track is None or level == "low":
        out = "Существенных признаков схем не найдено."
        if legit:
            out = "Существенных признаков схем не найдено. Найдены признаки легальности: " + "; ".join(legit) + "."
        return out + (f" Балл ограничен: {capped}." if capped else "")
    labels = [e.label for e in evidence if (e.weight > 0 or e.source == "ml") and e.track in (track, "common")]
    joined = "; ".join(dict.fromkeys(labels)) or "только косвенные сигналы"
    out = f"Найдены признаки: {TRACK_LABELS[track].lower()}. {joined}."
    if legit:
        out += " Есть и признаки легальности: " + "; ".join(legit) + "."
    if capped:
        out += f" Балл ограничен: {capped}."
    return out + " Решение принимает аналитик."


def combine(evidence: list[Evidence], ml: Mapping[str, float] | None = None,
            context: list[Evidence] | None = None, requisites: tuple = (), links: tuple = (),
            llm_status: str = "off", ml_words: Mapping[str, Sequence[str]] | None = None) -> Analysis:
    context = context or []
    tracks = tuple(score_track(t, evidence, ml, context) for t in TRACKS)
    top = max(tracks, key=lambda t: t.score)
    track = top.track if top.score >= MEDIUM_THRESHOLD else None
    # Контекст реестра и графа показывается всегда: номер из лотереи в посте казино аналитик должен видеть,
    # хотя в балл казино он не идёт (иначе один признак + чужой трек давал бы высокий риск).
    relevant = [e for e in evidence if track is None or e.track in (track, "common") or e.stop] + \
               [c for c in context if track is None or c.track in (track, "common") or c.weight > 0]
    if track and top.ml_probability is not None:
        words = list((ml_words or {}).get(track, ()))
        label = f"Модель на n-граммах текста: вероятность трека {top.ml_probability:.0%}"
        if words:
            label += ", опирается на слова " + ", ".join(f"«{w}»" for w in words)
        relevant.append(Evidence(f"ml.{track}", track, label, 0, "ml", quote=", ".join(words)))
    return Analysis(
        score=top.score, level=top.level, track=track, tracks=tracks,
        evidence=tuple(sorted(relevant, key=lambda e: -abs(e.weight))),
        summary=summarize(top.level, track, relevant, top.capped_reason),
        requisites=requisites, links=links, llm_status=llm_status,
    )
