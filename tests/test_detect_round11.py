"""Раунд 11: фальшивые «остерегайтесь фейков», разборы сигналов и зеркал, Отбасы банк, вопрос «это пирамида?», ошибки слепого v12."""

from __future__ import annotations

import pytest

from pruf.detect.detector import Detector, SourceText
from pruf.models import Analysis


def _analyze(detector: Detector, text: str) -> Analysis:
    return detector.detect([SourceText("text", text)]).analysis


@pytest.mark.parametrize("text", [
    # фальшивое предупреждение от самих мошенников: «официальный бот только наш»
    "Р О З Ы Г Р Ы Ш от Telegram Premium 🎉 3 месяца бесплатно каждому, кто оплатит активацию 500 ₸ через бота. "
    "Осторожно, много фейков! Официальный бот только наш, остальные мошенники",
    "Розыгрыш iPhone 15 среди подписчиков, участие 1 000 тг. Осторожно, мошенники копируют страницу, настоящий канал только у нас",
    "С Л О Т Т А Р 🎰 Тегін айналдыру 200 рет! Тіркелгенде бонус 50 000 ₸. Біз алаяқтар емеспіз, ұтысты бірден картаға шығарамыз",
    "Лаки Джет x100 signals күн сайын. Алгоритм hacked, joining fee 5000 тг. Остерегайтесь фейков, наш канал единственный official",
])
def test_scammer_fake_warnings_reach_medium(detector: Detector, text: str) -> None:
    # Act
    analysis = _analyze(detector, text)

    # Assert
    assert analysis.level in ("medium", "high"), (analysis.score, [e.feature_id for e in analysis.evidence])


@pytest.mark.parametrize("text", [
    "Отбасы банкте депозит ашсаңыз, мемлекет жыл сайын сыйлықақы қосады. Жинақты пәтер алуға пайдалануға болады",
    "Ұлттық лотереяның official app-ынан 3 билет алдым, total 600 ₸. Тираж сенбіде, wish me luck 🍀",
    "Aviator сигналдары деген — алдау. Раунд нәтижесін ешкім болжай алмайды, сигнал сататын каналдар казиноның серіктесі",
    "Объясню по-простому: легальны только букмекеры с лицензией. Сайты-зеркала без лицензии вне закона, выигрыш там могут не выплатить",
    "Курбым шакырып жатыр, 50 мын салсан айына 15 мын тусип турады деди, досынды экелсен бонус. Бул пирамида ма?",
])
def test_round11_legit_posts_stay_low(detector: Detector, text: str) -> None:
    # Act
    analysis = _analyze(detector, text)

    # Assert
    assert analysis.level == "low", (analysis.score, [e.feature_id for e in analysis.evidence])


def test_question_with_contact_is_still_an_ad(detector: Detector) -> None:
    # Act: «скажете, пирамида?» и сразу «пиши в лс» — приём рекламы, а не вопрос
    analysis = _analyze(detector, "Вход 50 000, каждую неделю 15 000 на Kaspi, за друга бонус 10%. Скажете, пирамида? Пиши в лс, всё объясню")

    # Assert
    assert analysis.level in ("medium", "high"), (analysis.score, [e.feature_id for e in analysis.evidence])


@pytest.mark.parametrize("text", [
    # разбор ошибок слепого набора v12
    "Your withdrawal of 2 300 000 ₸ is on hold. Разблокировать можно только после оплаты tax fee 18%. Шұғыл төлеңіз",
    "Siz shygargan 1 200 000 tg toktatyldy. Ony ashu ushin 10% saqtandyru zharnasyn toleniz. Uakyty 12 sagat",
    "сторис: кто хочет айфон? Скидываемся по 2к на каспи, в пятницу рандомайзер выбирает одного счастливчика",
    "🔥GIVEAWAY🔥 1 000 000 ₸ разыгрываем среди тех, кто закинет 1500 на каспи. Барлығына сәттілік! 🍀",
    "Апайлар, Каспиден ақша беріп жатыр екен, just click и введи данные карты, мне уже 20к пришло!",
    "Девочки, «Цветок» снова открылся 🌸 Входишь в стол с даром 100 000 и выходишь с 800 000. Это не пирамида",
    "Lost money in crypto scam? Біз қайтарамыз ✅ Our lawyers return up to 95%. Предоплата 40 000 ₸, остальное после возврата",
    "Жоғалған ақшаңызды қайтарамыз ⚖️ Пирамидаға, алаяқтарға ақша салдыңыз ба? Біздің заңгерлер қайтарады. Алдын ала төлем — 50 000 ₸ қана",
    "Подработка на телефоне 📱 Нужно только запускать раунды в приложении и вовремя жать «забрать», пока коэффициент растёт. Старт — 3 000",
])
def test_v12_misses_reach_medium(detector: Detector, text: str) -> None:
    # Act
    analysis = _analyze(detector, text)

    # Assert
    assert analysis.level in ("medium", "high"), (analysis.score, [e.feature_id for e in analysis.evidence])


@pytest.mark.parametrize("text", [
    "Mama, ne perevodi nikomu dengi! Esli zvonyat i govoryat, chto ty vyigrala loteryu ili nuzhno oplatit nalog — eto moshenniki",
    "Kupil bilet gos loterei, vyigral 500 tg 😂 hot by na kofe hvatilo",
    "Ostorozhno! Mne prishlo sms 'vy vyigrali priz ot Kaspi, oplatite dostavku'. Eto moshenniki, Kaspi takoe ne rassylaet",
    "Бұл пирамида ма, guys? Знакомая зовёт в «AI trading», вход 100$, обещают 5% в день + бонус за друзей",
    "Казино жарнамасын қалай танимыз: «ұтыспен ойын», «ұшақ», «айна», бірінші депозитке бонус. Мұндай постты көрсеңіз — шағым жіберіңіз.",
    "Мне сегодня пришло смс, что я якобы выиграла машину и надо оплатить госпошлину. Я ни в каком розыгрыше не участвовала. Будьте осторожны",
    "Rozygrysh bez vsyakih oplat 🎁 podpishis i otmet druga, 3 pobeditelya poluchat sertifikaty v nash salon",
    "Папа двадцать лет покупает лотерейные билеты по воскресеньям в одном и том же киоске. Самый крупный выигрыш был 15 тысяч",
    "Guys, осторожно! Маған да «вы выиграли iPhone, оплатите доставку» деген message келді. Это fake, ешкімге ақша жібермеңдер",
    "⚠️ Абай болыңыз! Алаяқтар «Сіз 500 000 теңге ұттыңыз, комиссия төлеңіз» деген хабарлама таратуда. Банктер карта деректерін сұрамайды.",
    "Кеше маган смс келди, машина уттыныз, салык толениз деп. Мен ешкандай утыска катыспадым 😂 Ата-аналарга айтып койыныздар",
    "Классика скама: «вывод заморожен, оплатите 15%». Ешқашан unlock fee төлемеңіз — деньги уже потеряны",
    "Частая схема: при выводе пишут, что средства заморожены и нужно оплатить страховку. Не платите — денег там никогда не было",
    "Вчерашний тираж Сәттілік: павлодарлық тұрғын 10 млн теңге ұтып алды 🎉 Жеңімпаз ұтысты салықты ұстағаннан кейін алды",
])
def test_v12_false_positives_stay_low(detector: Detector, text: str) -> None:
    # Act
    analysis = _analyze(detector, text)

    # Assert
    assert analysis.level == "low", (analysis.score, [e.feature_id for e in analysis.evidence])


def test_card_ask_before_kazakh_denial_still_counts(detector: Detector) -> None:
    # Act: «введите данные карты, банк ешқашан код сұрамайды» — просьба стоит раньше, отрицание её не снимает
    analysis = _analyze(detector, "Компенсация 70 000 тг! Введите данные карты в боте, біз ешқашан басқа ештеңе сұрамаймыз")

    # Assert
    assert analysis.level in ("medium", "high"), (analysis.score, [e.feature_id for e in analysis.evidence])


@pytest.mark.parametrize("text", [
    # ревью раунда 11: новые предупреждения не должны прятать рекламу
    "Касса взаимопомощи: вносишь 20к, через 10 дней 40к, 1-2-4-8. Скам, скажете? Проверено, 3 выплаты уже",
    "Слоты, бонус на депозит 200%, вывод на каспи за 5 минут. Лохотрон, говорите? Мой вывод 500к",
    "Вступительный взнос 50 000 тг, через неделю 100 000 тг. Кто не верит — это мошенники вам наговорили",
    "Вход 30 000 тг, через неделю 90 000 тг, приведи двоих друзей. Частая схема заработка у умных людей",
    "Казино онлайн, бонус 200% на первый депозит, вывод на каспи. Ставки вне закона? Нет, у нас всё легально",
    "Ұтыс! iPhone 15 ойнатамыз, қатысу 2000 тг каспиге. Бұл ақпаратты ешкімге жібермеңіз",
    # «деп» — ещё и сленг депозита
    "Казино слоты: минимальный деп 5000 тг, переведите на каспи 87011234567, бонус 100%",
])
def test_round11_review_evasions_stay_flagged(detector: Detector, text: str) -> None:
    # Act
    analysis = _analyze(detector, text)

    # Assert
    assert analysis.level in ("medium", "high"), (analysis.score, [e.feature_id for e in analysis.evidence])


@pytest.mark.parametrize("text", [
    # ревью раунда 11: обычные посты с новыми словами
    "Головкин заработал победу в третьем раунде, коэффициент был 2.5",
    "Новый раунд переговоров по зарплатам: ставки поднимут на 20%, учителя заработают больше",
    "Однокурсники, скидываемся по 2000 тг на подарок куратору, победителя конкурса тоже поздравим",
    "Акция «Подари тепло»: дарители могут оставить пакеты у входа, вопросы на каспи 87011234567",
    "Кондитерская: торты от 8000 тг, предоплата 3000 тг на каспи 87011234567",
    "Вывод средств приостановлен банком по решению суда, разблокировать после оплаты долга 120 000 тг",
])
def test_round11_review_false_positives_stay_low(detector: Detector, text: str) -> None:
    # Act
    analysis = _analyze(detector, text)

    # Assert
    assert analysis.level == "low", (analysis.score, [e.feature_id for e in analysis.evidence])
