"""Поиск признаков из словаря в нормализованном тексте, с цитатами из оригинала."""

from __future__ import annotations

import re
from functools import lru_cache

from pruf.detect.lexicon import FEATURES, Feature
from pruf.models import Evidence
from pruf.normalize.text import KK_TO_RU, NormText

QUOTE_CONTEXT = 25
MAX_QUOTES_PER_FEATURE = 2
# Цитата внутри поста: «вы выиграли iPhone, оплатите доставку». В предупреждении это пересказ схемы, а не сама схема
# Совет «не переводите деньги» и «ақша аудармаңыз» — не просьба о деньгах. Касается только признаков-действий.
# «Не регистрируйтесь по таким ссылкам» — тоже совет, а не скрытая реклама.
NEGATABLE = frozenset({"common.kaspi_transfer", "common.card_phish", "common.author_ask", "lottery.entry_fee", "lottery.prize_fee", "pyramid.entry",
                       "casino.hidden_promo"})
NEGATION_WINDOW = 45  # «не просят код из СМС или CVV»: отрицание покрывает перечисление
REPORTED_TAIL = 30
REPORTED_WINDOW = 90  # «Блогеры, которые показывают «…» и дают ссылку в шапке» — описание длиннее отрицания
_NEGATED_VERB_RE = re.compile(
    # «мошенники просят оплатить» — пересказ, а не просьба
    # «никогда не звонят с просьбой продиктовать код», «там украдут данные карты» — описание кражи, а не просьба
    r"(?<!\w)(?:не|никогда не|нельзя|просят|требуют|предлагают|заставляют|уговаривают)\s+"
    # после «звонят с просьбой» — только инфинитив: «не звонит с просьбой, оплатите» остаётся просьбой
    r"(?:(?:надо|нужно|стоит|следует|спешите|просит|просят|требует|будет|(?:звон|пиш)\w*\s+с\s+просьбой(?=\s+\w+ть(?!\w)))\s+)?"
    r"(?:переве|перевод|перечисл|переда|перекид|опла|запла|скидыв|скин|кидай|отправ|плат|внос|внес|покуп|куп|вводи|введ|сообща|сообш|диктов|продикт|назыв"
    r"|код|cvv|свв|данные|пароль|регистр|переход|провод|ввест|ввод|спраш|запраш)"
    # кража описывает только объект: «украдут данные карты»; «у нас не крадут, оплатите» не отрицание
    r"|(?<!\w)(?:украдут|крадут|воруют|похитят)\s+(?:ваши\s+|ваш\s+)?(?:данные|код|cvv|свв|пароль)")
# Отрицание управляет признаком, только если между ними не больше NEGATION_GAP_WORDS слов и нет утвердительной просьбы:
# «ничего не платите за сам телефон, только оплатите доставку» — просьба остаётся
NEGATION_GAP_WORDS = 3
# текст свёрнут (KK_TO_RU), поэтому казахские буквы в шаблонах сворачиваются так же
_AFFIRMATIVE_ASK_RE = re.compile(r"(?<!не )(?<!\w)(?:оплатите|переведите|внесите|отправьте|скиньте|киньте|аударыңыз|төлеңіз)(?!\w)".translate(KK_TO_RU))
# «если вам в директ пишут…» — пересказ чужого сообщения, а не призыв автора
_REPORTED_RE = re.compile(
    # нужен глагол пересказа: голое «если вам интересно — вход от 20к» пересказом не считается
    r"(?<!\w)(?:вам|тебе)\s+(?:\w+\s+){0,2}?(?:пишут|написал\w*|предлагают|присылают|звонят)(?!\w)"
    r"|(?<!\w)(?:если|когда)\s+(?:\w+\s+){0,3}?(?:пишут|предлагают|присылают|обещают|зовут)(?!\w)"
    # «Блогеры, которые … дают ссылку в шапке»: описание чужой схемы, а не призыв
    r"|(?<!\w)(?:блогер|стример|мошенник|аферист|алаяқ)\w*,?\s+(?:котор|кто)"
    # казахская косвенная речь: «салық төлеңіз деп келді»
    r"|\w\s+деп\s+(?:\w+\s+){0,2}?(?:келди|жазды|жазып|айтты|айтып|хабарла|жиберди|звон|сурап|сурады|деди|дейди)"
    r"|(?:смс|хабарлама|сообщени|звон|конырау)\w*[^.!?]{0,80}?\w\s+деп(?!\w)(?!\s*\d)"
    # «… аласың дейді», «… қайтарамын деді»: косвенная речь стоит сразу после пересказанной фразы
    r"|\w\s+(?:дейди|деди|дейдi|дейт\w*|деген)(?!\w)".translate(KK_TO_RU))
# пересказ не переходит через конец предложения, двоеточие или тире: «…, уже на плюсе: ссылка в шапке» — уже призыв
_REPORTED_SPLIT_RE = re.compile(r"[.!?;:\n—–]")
_NEGATION_SPLIT_RE = re.compile(r"[,.!?;:\n—–]|\s-\s")
# «50 мың салсаң 400 мың аласың дейді» — пересказ чужого обещания, а не обещание автора
REPORTABLE = NEGATABLE | {"common.dm_redirect", "casino.hidden_promo", "pyramid.doubling"}
# «банктер карта деректерін сұрамайды»: казахское отрицание в утвердительной форме глагола
_KK_NEG_DECL_RE = re.compile(r"\w*\s+(?:\w+\s+)?(?:сурамайды|сурамаймыз|талап етпейди|талап етпеиди)(?!\w)")
_KK_NEG_IMPERATIVE_RE = re.compile(r"\w(?:ма|ме|ба|бе|па|пе)(?:ныз|низ|ндар)(?!\w)")
# «данные карты никому не сообщайте»: запрет стоит сразу после дополнения
# «никому не говорите» — требование тайны, а не предупреждение, поэтому «говор» сюда не входит
_RU_NEG_AFTER_RE = re.compile(r"\w*\s+(?:никому\s+|никогда\s+)?(?:не|нельзя)\s+(?:сообща|называ|передава|диктуй|вводи|отправля|сообщ|пересыла)\w*")
# просьба автора раньше в посте: «введите данные карты. Код никому не сообщайте» — подражание банку
_DATA_ASK_BEFORE_RE = re.compile(r"(?<!не )(?<!\w)(?:введите|укажите|отправьте|пришлите|продиктуйте|скиньте|напишите|заполните|переведите|оплатите"
                                 r"|енгізіңіз|жіберіңіз|жазыңыз|толтырыңыз)(?!\w)".translate(KK_TO_RU))
_QUOTED_RE = re.compile(r"«[^»\n]{1,300}»|“[^”\n]{1,300}”|„[^“\n]{1,300}“|\"[^\"\n]{1,300}\"|(?<!\w)'[^'\n]{1,300}'(?!\w)")


@lru_cache(maxsize=1)
def _compiled() -> tuple[tuple[Feature, tuple], ...]:
    return tuple((f, f.compiled()) for f in FEATURES)


def find_features(text: NormText, source: str = "text", keep_quoted: bool = False) -> list[Evidence]:
    """Все срабатывания признаков; один признак может дать до двух цитат."""
    found: list[Evidence] = []
    if not text.folded.strip():
        return found
    for feature, patterns in _compiled():
        hits = 0
        seen_spans: set[tuple[int, int]] = set()
        for pattern in patterns:
            for match in pattern.finditer(text.folded):
                if hits >= MAX_QUOTES_PER_FEATURE:
                    break
                if feature.id in NEGATABLE and _negated(text.folded, match.start(), match.end()):
                    continue
                if feature.id in REPORTABLE and _reported(text.folded, match.start()):
                    continue
                span = text.original_span(match.start(), match.end())
                if span in seen_spans:
                    continue
                seen_spans.add(span)
                found.append(Evidence(
                    feature_id=feature.id, track=feature.track, label=feature.label, weight=feature.weight,
                    source=source, quote=text.quote(match.start(), match.end(), QUOTE_CONTEXT), span=span,
                    stop=feature.stop, core=feature.core,
                ))
                hits += 1
    if keep_quoted:
        return found
    # Если в посте есть реквизит или ссылка, кавычки не спасают: «Наш «розыгрыш, участие 500 тг» настоящий» — реклама
    return _drop_quoted_in_warnings(found, text.original)


def _quoted_spans(original: str) -> list[tuple[int, int]]:
    return [m.span() for m in _QUOTED_RE.finditer(original)]


def _inside(span: tuple[int, int] | None, quoted: list[tuple[int, int]]) -> bool:
    return bool(span) and any(qs <= span[0] and span[1] <= qe for qs, qe in quoted)


def _reported(folded: str, start: int) -> bool:
    left = _REPORTED_SPLIT_RE.split(folded[max(0, start - REPORTED_WINDOW):start])[-1]
    # «в директ пишут»: глагол пересказа может стоять сразу после самого признака
    right = _REPORTED_SPLIT_RE.split(folded[start:start + REPORTED_TAIL])[0]
    return bool(_REPORTED_RE.search(left + right))


def _negated(folded: str, start: int, end: int) -> bool:
    """Действие под отрицанием: «не переводите на каспи», «каспиге аудармаңыз»."""
    # окно не переходит через знак препинания: «не переживайте, переведите» — не отрицание перевода
    left = folded[max(0, start - NEGATION_WINDOW):start]
    left = _NEGATION_SPLIT_RE.split(left)[-1]
    for neg in _NEGATED_VERB_RE.finditer(left + folded[start:end]):
        gap = left[neg.end():]
        if len(gap.split()) <= NEGATION_GAP_WORDS and not _AFFIRMATIVE_ASK_RE.search(gap + folded[start:end]):
            return True
    # казахское отрицание стоит в глаголе после дополнения: «деректерін енгізбеңіз», «каспиге аудармаңыз»
    if (_RU_NEG_AFTER_RE.match(folded[end:end + NEGATION_WINDOW]) or _KK_NEG_DECL_RE.match(folded[end:end + NEGATION_WINDOW])) \
            and not _DATA_ASK_BEFORE_RE.search(folded[:start]):
        return True
    tail = re.match(r"\w*(?:\s+\w+){0,2}", folded[end:])
    return bool(_KK_NEG_IMPERATIVE_RE.search(folded[max(0, start - NEGATION_WINDOW):end + tail.end()]))


def _drop_quoted_in_warnings(found: list[Evidence], original: str) -> list[Evidence]:
    """В посте-предупреждении признаки, целиком попавшие в кавычки, не считаются: это цитата мошенников."""
    if not any(e.stop and e.feature_id.endswith(".awareness") for e in found):
        return found
    quoted = _quoted_spans(original)
    if not quoted:
        return found
    return [e for e in found if e.stop or not _inside(e.span, quoted)]
