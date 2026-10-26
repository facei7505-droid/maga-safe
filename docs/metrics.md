# ПРУФ: метрики на синтетическом тесте

Датасет: 1186 постов, тест: 505 ({'casino': 54, 'legit': 343, 'lottery': 54, 'pyramid': 54}). Разбиение по кампаниям, 1/4 шаблонов только в тесте.

Положительный прогноз: уровень «средний» или выше (строки ≥medium) либо только «высокий» (≥high).

Наборы `dev:*` используются для настройки правил, поэтому цифры на них завышены. Наборы `blind:*` пишет отдельный агент без доступа к коду, на них только измеряем; после публикации набор уходит в dev. Главная цифра качества — слепой набор и таблица истории в конце.

## text: rules

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | lottery | 1.0 | 1.0 | 1.0 | |
| ≥medium | casino | 1.0 | 1.0 | 1.0 | |
| ≥medium | pyramid | 1.0 | 1.0 | 1.0 | |
| ≥medium | язык kk | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык mix | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык ru | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык translit | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | все треки | 1.0 | 0.889 | 0.941 | 0.0 |
| ≥high | lottery | 1.0 | 1.0 | 1.0 | |
| ≥high | casino | 1.0 | 0.667 | 0.8 | |
| ≥high | pyramid | 1.0 | 1.0 | 1.0 | |
| ≥high | язык kk | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | язык mix | 1.0 | 0.625 | 0.769 | 0.0 |
| ≥high | язык ru | 1.0 | 0.957 | 0.978 | 0.0 |
| ≥high | язык translit | 1.0 | 0.815 | 0.898 | 0.0 |

## text: rules+ml

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | lottery | 1.0 | 1.0 | 1.0 | |
| ≥medium | casino | 1.0 | 1.0 | 1.0 | |
| ≥medium | pyramid | 1.0 | 1.0 | 1.0 | |
| ≥medium | язык kk | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык mix | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык ru | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык translit | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | все треки | 1.0 | 0.889 | 0.941 | 0.0 |
| ≥high | lottery | 1.0 | 1.0 | 1.0 | |
| ≥high | casino | 1.0 | 0.667 | 0.8 | |
| ≥high | pyramid | 1.0 | 1.0 | 1.0 | |
| ≥high | язык kk | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | язык mix | 1.0 | 0.625 | 0.769 | 0.0 |
| ≥high | язык ru | 1.0 | 0.957 | 0.978 | 0.0 |
| ≥high | язык translit | 1.0 | 0.815 | 0.898 | 0.0 |

## dev:handwritten: rules

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | lottery | 1.0 | 1.0 | 1.0 | |
| ≥medium | casino | 1.0 | 1.0 | 1.0 | |
| ≥medium | pyramid | 1.0 | 1.0 | 1.0 | |
| ≥medium | язык kk | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык mix | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык ru | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык translit | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | все треки | 1.0 | 0.7 | 0.824 | 0.0 |
| ≥high | lottery | 1.0 | 0.9 | 0.947 | |
| ≥high | casino | 1.0 | 0.4 | 0.571 | |
| ≥high | pyramid | 1.0 | 0.8 | 0.889 | |
| ≥high | язык kk | 1.0 | 0.75 | 0.857 | 0.0 |
| ≥high | язык mix | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | язык ru | 1.0 | 0.667 | 0.8 | 0.0 |
| ≥high | язык translit | 1.0 | 0.6 | 0.75 | 0.0 |

## dev:handwritten: rules+ml

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | lottery | 1.0 | 1.0 | 1.0 | |
| ≥medium | casino | 1.0 | 1.0 | 1.0 | |
| ≥medium | pyramid | 1.0 | 1.0 | 1.0 | |
| ≥medium | язык kk | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык mix | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык ru | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык translit | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | все треки | 1.0 | 0.8 | 0.889 | 0.0 |
| ≥high | lottery | 1.0 | 1.0 | 1.0 | |
| ≥high | casino | 1.0 | 0.6 | 0.75 | |
| ≥high | pyramid | 1.0 | 0.8 | 0.889 | |
| ≥high | язык kk | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | язык mix | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | язык ru | 1.0 | 0.778 | 0.875 | 0.0 |
| ≥high | язык translit | 1.0 | 0.6 | 0.75 | 0.0 |

## dev:dev_round2: rules

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | lottery | 1.0 | 1.0 | 1.0 | |
| ≥medium | casino | 1.0 | 1.0 | 1.0 | |
| ≥medium | pyramid | 1.0 | 1.0 | 1.0 | |
| ≥medium | язык kk | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык mix | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык ru | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык translit | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | все треки | 1.0 | 0.893 | 0.943 | 0.0 |
| ≥high | lottery | 1.0 | 1.0 | 1.0 | |
| ≥high | casino | 1.0 | 0.8 | 0.889 | |
| ≥high | pyramid | 1.0 | 0.9 | 0.947 | |
| ≥high | язык kk | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | язык mix | 1.0 | 0.75 | 0.857 | 0.0 |
| ≥high | язык ru | 1.0 | 0.889 | 0.941 | 0.0 |
| ≥high | язык translit | 1.0 | 1.0 | 1.0 | 0.0 |

## dev:dev_round2: rules+ml

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | lottery | 1.0 | 1.0 | 1.0 | |
| ≥medium | casino | 1.0 | 1.0 | 1.0 | |
| ≥medium | pyramid | 1.0 | 1.0 | 1.0 | |
| ≥medium | язык kk | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык mix | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык ru | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык translit | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | все треки | 1.0 | 0.893 | 0.943 | 0.0 |
| ≥high | lottery | 1.0 | 1.0 | 1.0 | |
| ≥high | casino | 1.0 | 0.8 | 0.889 | |
| ≥high | pyramid | 1.0 | 0.9 | 0.947 | |
| ≥high | язык kk | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | язык mix | 1.0 | 0.75 | 0.857 | 0.0 |
| ≥high | язык ru | 1.0 | 0.889 | 0.941 | 0.0 |
| ≥high | язык translit | 1.0 | 1.0 | 1.0 | 0.0 |

## dev:dev_round4: rules

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | lottery | 1.0 | 1.0 | 1.0 | |
| ≥medium | casino | 1.0 | 1.0 | 1.0 | |
| ≥medium | pyramid | 1.0 | 1.0 | 1.0 | |
| ≥medium | язык kk | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык mix | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык ru | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык translit | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | все треки | 1.0 | 0.947 | 0.973 | 0.0 |
| ≥high | lottery | 1.0 | 1.0 | 1.0 | |
| ≥high | casino | 1.0 | 0.857 | 0.923 | |
| ≥high | pyramid | 1.0 | 1.0 | 1.0 | |
| ≥high | язык kk | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | язык mix | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | язык ru | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | язык translit | 1.0 | 0.667 | 0.8 | 0.0 |

## dev:dev_round4: rules+ml

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | lottery | 1.0 | 1.0 | 1.0 | |
| ≥medium | casino | 1.0 | 1.0 | 1.0 | |
| ≥medium | pyramid | 1.0 | 1.0 | 1.0 | |
| ≥medium | язык kk | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык mix | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык ru | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык translit | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | все треки | 1.0 | 0.947 | 0.973 | 0.0 |
| ≥high | lottery | 1.0 | 1.0 | 1.0 | |
| ≥high | casino | 1.0 | 0.857 | 0.923 | |
| ≥high | pyramid | 1.0 | 1.0 | 1.0 | |
| ≥high | язык kk | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | язык mix | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | язык ru | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | язык translit | 1.0 | 0.667 | 0.8 | 0.0 |

## dev:dev_round5: rules

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | lottery | 1.0 | 1.0 | 1.0 | |
| ≥medium | casino | 1.0 | 1.0 | 1.0 | |
| ≥medium | pyramid | 1.0 | 1.0 | 1.0 | |
| ≥medium | язык kk | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык mix | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык ru | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык translit | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | все треки | 1.0 | 0.7 | 0.824 | 0.0 |
| ≥high | lottery | 1.0 | 1.0 | 1.0 | |
| ≥high | casino | 1.0 | 0.5 | 0.667 | |
| ≥high | pyramid | 1.0 | 1.0 | 1.0 | |
| ≥high | язык kk | 0.0 | 0.0 | 0.0 | 0.0 |
| ≥high | язык mix | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | язык ru | 1.0 | 0.714 | 0.833 | 0.0 |
| ≥high | язык translit | 1.0 | 1.0 | 1.0 | 0.0 |

## dev:dev_round5: rules+ml

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | lottery | 1.0 | 1.0 | 1.0 | |
| ≥medium | casino | 1.0 | 1.0 | 1.0 | |
| ≥medium | pyramid | 1.0 | 1.0 | 1.0 | |
| ≥medium | язык kk | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык mix | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык ru | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык translit | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | все треки | 1.0 | 0.9 | 0.947 | 0.0 |
| ≥high | lottery | 1.0 | 1.0 | 1.0 | |
| ≥high | casino | 1.0 | 0.833 | 0.909 | |
| ≥high | pyramid | 1.0 | 1.0 | 1.0 | |
| ≥high | язык kk | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | язык mix | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | язык ru | 1.0 | 0.857 | 0.923 | 0.0 |
| ≥high | язык translit | 1.0 | 1.0 | 1.0 | 0.0 |

## dev:dev_round6: rules

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 1.0 | 0.895 | 0.944 | 0.0 |
| ≥medium | lottery | 1.0 | 1.0 | 1.0 | |
| ≥medium | casino | 1.0 | 1.0 | 1.0 | |
| ≥medium | pyramid | 1.0 | 0.714 | 0.833 | |
| ≥medium | язык kk | 1.0 | 0.833 | 0.909 | 0.0 |
| ≥medium | язык ru | 1.0 | 0.9 | 0.947 | 0.0 |
| ≥medium | язык translit | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | все треки | 1.0 | 0.579 | 0.733 | 0.0 |
| ≥high | lottery | 1.0 | 0.8 | 0.889 | |
| ≥high | casino | 1.0 | 0.429 | 0.6 | |
| ≥high | pyramid | 1.0 | 0.571 | 0.727 | |
| ≥high | язык kk | 1.0 | 0.5 | 0.667 | 0.0 |
| ≥high | язык ru | 1.0 | 0.6 | 0.75 | 0.0 |
| ≥high | язык translit | 1.0 | 0.667 | 0.8 | 0.0 |

## dev:dev_round6: rules+ml

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | lottery | 1.0 | 1.0 | 1.0 | |
| ≥medium | casino | 1.0 | 1.0 | 1.0 | |
| ≥medium | pyramid | 1.0 | 1.0 | 1.0 | |
| ≥medium | язык kk | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык ru | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык translit | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | все треки | 1.0 | 0.737 | 0.848 | 0.0 |
| ≥high | lottery | 1.0 | 1.0 | 1.0 | |
| ≥high | casino | 1.0 | 0.714 | 0.833 | |
| ≥high | pyramid | 1.0 | 0.571 | 0.727 | |
| ≥high | язык kk | 1.0 | 0.833 | 0.909 | 0.0 |
| ≥high | язык ru | 1.0 | 0.7 | 0.824 | 0.0 |
| ≥high | язык translit | 1.0 | 0.667 | 0.8 | 0.0 |

## dev:handwritten_blind: rules

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | lottery | 1.0 | 1.0 | 1.0 | |
| ≥medium | casino | 1.0 | 1.0 | 1.0 | |
| ≥medium | pyramid | 1.0 | 1.0 | 1.0 | |
| ≥medium | язык kk | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык mix | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык ru | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык translit | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | все треки | 1.0 | 0.792 | 0.884 | 0.0 |
| ≥high | lottery | 1.0 | 0.875 | 0.933 | |
| ≥high | casino | 1.0 | 0.625 | 0.769 | |
| ≥high | pyramid | 1.0 | 0.875 | 0.933 | |
| ≥high | язык kk | 1.0 | 0.667 | 0.8 | 0.0 |
| ≥high | язык mix | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | язык ru | 1.0 | 0.8 | 0.889 | 0.0 |
| ≥high | язык translit | 1.0 | 0.667 | 0.8 | 0.0 |

## dev:handwritten_blind: rules+ml

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | lottery | 1.0 | 1.0 | 1.0 | |
| ≥medium | casino | 1.0 | 1.0 | 1.0 | |
| ≥medium | pyramid | 1.0 | 1.0 | 1.0 | |
| ≥medium | язык kk | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык mix | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык ru | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык translit | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | все треки | 1.0 | 0.833 | 0.909 | 0.0 |
| ≥high | lottery | 1.0 | 0.875 | 0.933 | |
| ≥high | casino | 1.0 | 0.75 | 0.857 | |
| ≥high | pyramid | 1.0 | 0.875 | 0.933 | |
| ≥high | язык kk | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | язык mix | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | язык ru | 1.0 | 0.8 | 0.889 | 0.0 |
| ≥high | язык translit | 1.0 | 0.667 | 0.8 | 0.0 |

## dev:handwritten_blind_v2: rules

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | lottery | 1.0 | 1.0 | 1.0 | |
| ≥medium | casino | 1.0 | 1.0 | 1.0 | |
| ≥medium | pyramid | 1.0 | 1.0 | 1.0 | |
| ≥medium | язык kk | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык mix | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык ru | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык translit | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | все треки | 1.0 | 0.833 | 0.909 | 0.0 |
| ≥high | lottery | 1.0 | 0.917 | 0.957 | |
| ≥high | casino | 1.0 | 0.583 | 0.737 | |
| ≥high | pyramid | 1.0 | 1.0 | 1.0 | |
| ≥high | язык kk | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | язык mix | 1.0 | 0.5 | 0.667 | 0.0 |
| ≥high | язык ru | 1.0 | 0.944 | 0.971 | 0.0 |
| ≥high | язык translit | 1.0 | 0.6 | 0.75 | 0.0 |

## dev:handwritten_blind_v2: rules+ml

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | lottery | 1.0 | 1.0 | 1.0 | |
| ≥medium | casino | 1.0 | 1.0 | 1.0 | |
| ≥medium | pyramid | 1.0 | 1.0 | 1.0 | |
| ≥medium | язык kk | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык mix | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык ru | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык translit | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | все треки | 1.0 | 0.833 | 0.909 | 0.0 |
| ≥high | lottery | 1.0 | 0.917 | 0.957 | |
| ≥high | casino | 1.0 | 0.583 | 0.737 | |
| ≥high | pyramid | 1.0 | 1.0 | 1.0 | |
| ≥high | язык kk | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | язык mix | 1.0 | 0.5 | 0.667 | 0.0 |
| ≥high | язык ru | 1.0 | 0.944 | 0.971 | 0.0 |
| ≥high | язык translit | 1.0 | 0.6 | 0.75 | 0.0 |

## dev:handwritten_blind_v3: rules

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | lottery | 1.0 | 1.0 | 1.0 | |
| ≥medium | casino | 1.0 | 1.0 | 1.0 | |
| ≥medium | pyramid | 1.0 | 1.0 | 1.0 | |
| ≥medium | язык kk | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык mix | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык ru | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык translit | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | все треки | 1.0 | 0.85 | 0.919 | 0.0 |
| ≥high | lottery | 1.0 | 0.917 | 0.957 | |
| ≥high | casino | 1.0 | 0.75 | 0.857 | |
| ≥high | pyramid | 1.0 | 0.875 | 0.933 | |
| ≥high | язык kk | 1.0 | 0.857 | 0.923 | 0.0 |
| ≥high | язык mix | 1.0 | 0.857 | 0.923 | 0.0 |
| ≥high | язык ru | 1.0 | 0.85 | 0.919 | 0.0 |
| ≥high | язык translit | 1.0 | 0.833 | 0.909 | 0.0 |

## dev:handwritten_blind_v3: rules+ml

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | lottery | 1.0 | 1.0 | 1.0 | |
| ≥medium | casino | 1.0 | 1.0 | 1.0 | |
| ≥medium | pyramid | 1.0 | 1.0 | 1.0 | |
| ≥medium | язык kk | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык mix | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык ru | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык translit | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | все треки | 1.0 | 0.875 | 0.933 | 0.0 |
| ≥high | lottery | 1.0 | 1.0 | 1.0 | |
| ≥high | casino | 1.0 | 0.75 | 0.857 | |
| ≥high | pyramid | 1.0 | 0.875 | 0.933 | |
| ≥high | язык kk | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | язык mix | 1.0 | 0.857 | 0.923 | 0.0 |
| ≥high | язык ru | 1.0 | 0.85 | 0.919 | 0.0 |
| ≥high | язык translit | 1.0 | 0.833 | 0.909 | 0.0 |

## dev:handwritten_blind_v4: rules

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 1.0 | 0.975 | 0.987 | 0.0 |
| ≥medium | lottery | 1.0 | 1.0 | 1.0 | |
| ≥medium | casino | 1.0 | 1.0 | 1.0 | |
| ≥medium | pyramid | 1.0 | 0.933 | 0.966 | |
| ≥medium | язык kk | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык mix | 1.0 | 0.933 | 0.966 | 0.0 |
| ≥medium | язык ru | 1.0 | 0.971 | 0.985 | 0.0 |
| ≥medium | язык translit | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | все треки | 1.0 | 0.825 | 0.904 | 0.0 |
| ≥high | lottery | 1.0 | 0.88 | 0.936 | |
| ≥high | casino | 1.0 | 0.68 | 0.81 | |
| ≥high | pyramid | 1.0 | 0.9 | 0.947 | |
| ≥high | язык kk | 1.0 | 0.824 | 0.903 | 0.0 |
| ≥high | язык mix | 1.0 | 0.8 | 0.889 | 0.0 |
| ≥high | язык ru | 1.0 | 0.765 | 0.867 | 0.0 |
| ≥high | язык translit | 1.0 | 1.0 | 1.0 | 0.0 |

## dev:handwritten_blind_v4: rules+ml

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | lottery | 1.0 | 1.0 | 1.0 | |
| ≥medium | casino | 1.0 | 1.0 | 1.0 | |
| ≥medium | pyramid | 1.0 | 1.0 | 1.0 | |
| ≥medium | язык kk | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык mix | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык ru | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык translit | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | все треки | 1.0 | 0.875 | 0.933 | 0.0 |
| ≥high | lottery | 1.0 | 0.96 | 0.98 | |
| ≥high | casino | 1.0 | 0.76 | 0.864 | |
| ≥high | pyramid | 1.0 | 0.9 | 0.947 | |
| ≥high | язык kk | 1.0 | 0.882 | 0.938 | 0.0 |
| ≥high | язык mix | 1.0 | 0.867 | 0.929 | 0.0 |
| ≥high | язык ru | 1.0 | 0.824 | 0.903 | 0.0 |
| ≥high | язык translit | 1.0 | 1.0 | 1.0 | 0.0 |

## dev:handwritten_blind_v5: rules

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 1.0 | 0.822 | 0.902 | 0.0 |
| ≥medium | lottery | 1.0 | 0.821 | 0.902 | |
| ≥medium | casino | 1.0 | 0.821 | 0.902 | |
| ≥medium | pyramid | 1.0 | 0.824 | 0.903 | |
| ≥medium | язык kk | 1.0 | 0.75 | 0.857 | 0.0 |
| ≥medium | язык mix | 1.0 | 0.842 | 0.914 | 0.0 |
| ≥medium | язык ru | 1.0 | 0.806 | 0.892 | 0.0 |
| ≥medium | язык translit | 1.0 | 0.933 | 0.966 | 0.0 |
| ≥high | все треки | 1.0 | 0.6 | 0.75 | 0.0 |
| ≥high | lottery | 1.0 | 0.5 | 0.667 | |
| ≥high | casino | 1.0 | 0.5 | 0.667 | |
| ≥high | pyramid | 1.0 | 0.765 | 0.867 | |
| ≥high | язык kk | 1.0 | 0.55 | 0.71 | 0.0 |
| ≥high | язык mix | 1.0 | 0.579 | 0.733 | 0.0 |
| ≥high | язык ru | 1.0 | 0.611 | 0.759 | 0.0 |
| ≥high | язык translit | 1.0 | 0.667 | 0.8 | 0.0 |

## dev:handwritten_blind_v5: rules+ml

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | lottery | 1.0 | 1.0 | 1.0 | |
| ≥medium | casino | 1.0 | 1.0 | 1.0 | |
| ≥medium | pyramid | 1.0 | 1.0 | 1.0 | |
| ≥medium | язык kk | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык mix | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык ru | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык translit | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | все треки | 1.0 | 0.722 | 0.839 | 0.0 |
| ≥high | lottery | 1.0 | 0.75 | 0.857 | |
| ≥high | casino | 1.0 | 0.607 | 0.756 | |
| ≥high | pyramid | 1.0 | 0.794 | 0.885 | |
| ≥high | язык kk | 1.0 | 0.7 | 0.824 | 0.0 |
| ≥high | язык mix | 1.0 | 0.684 | 0.813 | 0.0 |
| ≥high | язык ru | 1.0 | 0.694 | 0.82 | 0.0 |
| ≥high | язык translit | 1.0 | 0.867 | 0.929 | 0.0 |

## dev:handwritten_blind_v6: rules

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 1.0 | 0.87 | 0.93 | 0.0 |
| ≥medium | lottery | 1.0 | 0.848 | 0.918 | |
| ≥medium | casino | 1.0 | 0.909 | 0.952 | |
| ≥medium | pyramid | 0.966 | 0.824 | 0.889 | |
| ≥medium | язык kk | 1.0 | 0.833 | 0.909 | 0.0 |
| ≥medium | язык mix | 1.0 | 0.81 | 0.895 | 0.0 |
| ≥medium | язык ru | 1.0 | 0.9 | 0.947 | 0.0 |
| ≥medium | язык translit | 1.0 | 0.933 | 0.966 | 0.0 |
| ≥high | все треки | 1.0 | 0.7 | 0.824 | 0.0 |
| ≥high | lottery | 1.0 | 0.636 | 0.778 | |
| ≥high | casino | 1.0 | 0.667 | 0.8 | |
| ≥high | pyramid | 0.963 | 0.765 | 0.852 | |
| ≥high | язык kk | 1.0 | 0.625 | 0.769 | 0.0 |
| ≥high | язык mix | 1.0 | 0.714 | 0.833 | 0.0 |
| ≥high | язык ru | 1.0 | 0.7 | 0.824 | 0.0 |
| ≥high | язык translit | 1.0 | 0.8 | 0.889 | 0.0 |

## dev:handwritten_blind_v6: rules+ml

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | lottery | 1.0 | 0.97 | 0.985 | |
| ≥medium | casino | 1.0 | 1.0 | 1.0 | |
| ≥medium | pyramid | 0.971 | 1.0 | 0.986 | |
| ≥medium | язык kk | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык mix | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык ru | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык translit | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | все треки | 1.0 | 0.79 | 0.883 | 0.0 |
| ≥high | lottery | 1.0 | 0.788 | 0.881 | |
| ≥high | casino | 1.0 | 0.788 | 0.881 | |
| ≥high | pyramid | 0.963 | 0.765 | 0.852 | |
| ≥high | язык kk | 1.0 | 0.75 | 0.857 | 0.0 |
| ≥high | язык mix | 1.0 | 0.762 | 0.865 | 0.0 |
| ≥high | язык ru | 1.0 | 0.775 | 0.873 | 0.0 |
| ≥high | язык translit | 1.0 | 0.933 | 0.966 | 0.0 |

## dev:handwritten_blind_v7: rules

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 0.971 | 0.68 | 0.8 | 0.02 |
| ≥medium | lottery | 0.96 | 0.706 | 0.814 | |
| ≥medium | casino | 0.955 | 0.636 | 0.764 | |
| ≥medium | pyramid | 0.913 | 0.636 | 0.75 | |
| ≥medium | язык kk | 1.0 | 0.76 | 0.864 | 0.0 |
| ≥medium | язык mix | 1.0 | 0.733 | 0.846 | 0.0 |
| ≥medium | язык ru | 0.966 | 0.622 | 0.757 | 0.022 |
| ≥medium | язык translit | 0.909 | 0.667 | 0.769 | 0.067 |
| ≥high | все треки | 1.0 | 0.48 | 0.649 | 0.0 |
| ≥high | lottery | 1.0 | 0.529 | 0.692 | |
| ≥high | casino | 1.0 | 0.333 | 0.5 | |
| ≥high | pyramid | 0.947 | 0.545 | 0.692 | |
| ≥high | язык kk | 1.0 | 0.48 | 0.649 | 0.0 |
| ≥high | язык mix | 1.0 | 0.667 | 0.8 | 0.0 |
| ≥high | язык ru | 1.0 | 0.4 | 0.571 | 0.0 |
| ≥high | язык translit | 1.0 | 0.533 | 0.696 | 0.0 |

## dev:handwritten_blind_v7: rules+ml

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 0.98 | 0.99 | 0.985 | 0.02 |
| ≥medium | lottery | 0.971 | 0.971 | 0.971 | |
| ≥medium | casino | 0.969 | 0.939 | 0.954 | |
| ≥medium | pyramid | 0.943 | 1.0 | 0.971 | |
| ≥medium | язык kk | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык mix | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык ru | 0.978 | 0.978 | 0.978 | 0.022 |
| ≥medium | язык translit | 0.938 | 1.0 | 0.968 | 0.067 |
| ≥high | все треки | 1.0 | 0.52 | 0.684 | 0.0 |
| ≥high | lottery | 1.0 | 0.588 | 0.741 | |
| ≥high | casino | 1.0 | 0.394 | 0.565 | |
| ≥high | pyramid | 0.947 | 0.545 | 0.692 | |
| ≥high | язык kk | 1.0 | 0.56 | 0.718 | 0.0 |
| ≥high | язык mix | 1.0 | 0.733 | 0.846 | 0.0 |
| ≥high | язык ru | 1.0 | 0.422 | 0.594 | 0.0 |
| ≥high | язык translit | 1.0 | 0.533 | 0.696 | 0.0 |

## dev:handwritten_blind_v8: rules

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 1.0 | 0.53 | 0.693 | 0.0 |
| ≥medium | lottery | 1.0 | 0.618 | 0.764 | |
| ≥medium | casino | 1.0 | 0.545 | 0.706 | |
| ≥medium | pyramid | 1.0 | 0.424 | 0.596 | |
| ≥medium | язык kk | 1.0 | 0.56 | 0.718 | 0.0 |
| ≥medium | язык mix | 1.0 | 0.533 | 0.696 | 0.0 |
| ≥medium | язык ru | 1.0 | 0.467 | 0.636 | 0.0 |
| ≥medium | язык translit | 1.0 | 0.667 | 0.8 | 0.0 |
| ≥high | все треки | 1.0 | 0.34 | 0.507 | 0.0 |
| ≥high | lottery | 1.0 | 0.529 | 0.692 | |
| ≥high | casino | 1.0 | 0.182 | 0.308 | |
| ≥high | pyramid | 1.0 | 0.303 | 0.465 | |
| ≥high | язык kk | 1.0 | 0.4 | 0.571 | 0.0 |
| ≥high | язык mix | 1.0 | 0.4 | 0.571 | 0.0 |
| ≥high | язык ru | 1.0 | 0.244 | 0.393 | 0.0 |
| ≥high | язык translit | 1.0 | 0.467 | 0.636 | 0.0 |

## dev:handwritten_blind_v8: rules+ml

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | lottery | 1.0 | 1.0 | 1.0 | |
| ≥medium | casino | 1.0 | 1.0 | 1.0 | |
| ≥medium | pyramid | 1.0 | 1.0 | 1.0 | |
| ≥medium | язык kk | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык mix | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык ru | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык translit | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | все треки | 1.0 | 0.36 | 0.529 | 0.0 |
| ≥high | lottery | 1.0 | 0.529 | 0.692 | |
| ≥high | casino | 1.0 | 0.242 | 0.39 | |
| ≥high | pyramid | 1.0 | 0.303 | 0.465 | |
| ≥high | язык kk | 1.0 | 0.4 | 0.571 | 0.0 |
| ≥high | язык mix | 1.0 | 0.4 | 0.571 | 0.0 |
| ≥high | язык ru | 1.0 | 0.267 | 0.421 | 0.0 |
| ≥high | язык translit | 1.0 | 0.533 | 0.696 | 0.0 |

## dev:handwritten_blind_v9: rules

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 1.0 | 0.52 | 0.684 | 0.0 |
| ≥medium | lottery | 0.95 | 0.559 | 0.704 | |
| ≥medium | casino | 0.933 | 0.424 | 0.583 | |
| ≥medium | pyramid | 0.882 | 0.455 | 0.6 | |
| ≥medium | язык kk | 1.0 | 0.56 | 0.718 | 0.0 |
| ≥medium | язык mix | 1.0 | 0.6 | 0.75 | 0.0 |
| ≥medium | язык ru | 1.0 | 0.467 | 0.636 | 0.0 |
| ≥medium | язык translit | 1.0 | 0.533 | 0.696 | 0.0 |
| ≥high | все треки | 1.0 | 0.37 | 0.54 | 0.0 |
| ≥high | lottery | 1.0 | 0.353 | 0.522 | |
| ≥high | casino | 1.0 | 0.273 | 0.429 | |
| ≥high | pyramid | 0.875 | 0.424 | 0.571 | |
| ≥high | язык kk | 1.0 | 0.44 | 0.611 | 0.0 |
| ≥high | язык mix | 1.0 | 0.267 | 0.421 | 0.0 |
| ≥high | язык ru | 1.0 | 0.356 | 0.525 | 0.0 |
| ≥high | язык translit | 1.0 | 0.4 | 0.571 | 0.0 |

## dev:handwritten_blind_v9: rules+ml

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | lottery | 0.971 | 1.0 | 0.986 | |
| ≥medium | casino | 1.0 | 0.909 | 0.952 | |
| ≥medium | pyramid | 0.943 | 1.0 | 0.971 | |
| ≥medium | язык kk | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык mix | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык ru | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык translit | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | все треки | 1.0 | 0.42 | 0.592 | 0.0 |
| ≥high | lottery | 1.0 | 0.471 | 0.64 | |
| ≥high | casino | 1.0 | 0.303 | 0.465 | |
| ≥high | pyramid | 0.875 | 0.424 | 0.571 | |
| ≥high | язык kk | 1.0 | 0.48 | 0.649 | 0.0 |
| ≥high | язык mix | 1.0 | 0.333 | 0.5 | 0.0 |
| ≥high | язык ru | 1.0 | 0.4 | 0.571 | 0.0 |
| ≥high | язык translit | 1.0 | 0.467 | 0.636 | 0.0 |

## dev:handwritten_blind_v10: rules

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 0.982 | 0.54 | 0.697 | 0.01 |
| ≥medium | lottery | 0.95 | 0.559 | 0.704 | |
| ≥medium | casino | 0.933 | 0.424 | 0.583 | |
| ≥medium | pyramid | 0.95 | 0.576 | 0.717 | |
| ≥medium | язык kk | 1.0 | 0.64 | 0.78 | 0.0 |
| ≥medium | язык mix | 1.0 | 0.4 | 0.571 | 0.0 |
| ≥medium | язык ru | 0.963 | 0.578 | 0.722 | 0.022 |
| ≥medium | язык translit | 1.0 | 0.4 | 0.571 | 0.0 |
| ≥high | все треки | 0.971 | 0.34 | 0.504 | 0.01 |
| ≥high | lottery | 1.0 | 0.324 | 0.489 | |
| ≥high | casino | 0.889 | 0.242 | 0.381 | |
| ≥high | pyramid | 1.0 | 0.455 | 0.625 | |
| ≥high | язык kk | 1.0 | 0.36 | 0.529 | 0.0 |
| ≥high | язык mix | 1.0 | 0.267 | 0.421 | 0.0 |
| ≥high | язык ru | 0.944 | 0.378 | 0.54 | 0.022 |
| ≥high | язык translit | 1.0 | 0.267 | 0.421 | 0.0 |

## dev:handwritten_blind_v10: rules+ml

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 0.99 | 1.0 | 0.995 | 0.01 |
| ≥medium | lottery | 1.0 | 1.0 | 1.0 | |
| ≥medium | casino | 0.971 | 1.0 | 0.985 | |
| ≥medium | pyramid | 1.0 | 1.0 | 1.0 | |
| ≥medium | язык kk | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык mix | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык ru | 0.978 | 1.0 | 0.989 | 0.022 |
| ≥medium | язык translit | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | все треки | 0.976 | 0.41 | 0.577 | 0.01 |
| ≥high | lottery | 1.0 | 0.471 | 0.64 | |
| ≥high | casino | 0.909 | 0.303 | 0.455 | |
| ≥high | pyramid | 1.0 | 0.455 | 0.625 | |
| ≥high | язык kk | 1.0 | 0.52 | 0.684 | 0.0 |
| ≥high | язык mix | 1.0 | 0.267 | 0.421 | 0.0 |
| ≥high | язык ru | 0.95 | 0.422 | 0.585 | 0.022 |
| ≥high | язык translit | 1.0 | 0.333 | 0.5 | 0.0 |

## dev:handwritten_blind_v11: rules

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 1.0 | 0.64 | 0.78 | 0.0 |
| ≥medium | lottery | 1.0 | 0.545 | 0.706 | |
| ≥medium | casino | 1.0 | 0.788 | 0.881 | |
| ≥medium | pyramid | 1.0 | 0.588 | 0.741 | |
| ≥medium | язык kk | 1.0 | 0.75 | 0.857 | 0.0 |
| ≥medium | язык mix | 1.0 | 0.524 | 0.688 | 0.0 |
| ≥medium | язык ru | 1.0 | 0.625 | 0.769 | 0.0 |
| ≥medium | язык translit | 1.0 | 0.667 | 0.8 | 0.0 |
| ≥high | все треки | 1.0 | 0.43 | 0.601 | 0.0 |
| ≥high | lottery | 1.0 | 0.303 | 0.465 | |
| ≥high | casino | 1.0 | 0.485 | 0.653 | |
| ≥high | pyramid | 1.0 | 0.5 | 0.667 | |
| ≥high | язык kk | 1.0 | 0.375 | 0.545 | 0.0 |
| ≥high | язык mix | 1.0 | 0.333 | 0.5 | 0.0 |
| ≥high | язык ru | 1.0 | 0.475 | 0.644 | 0.0 |
| ≥high | язык translit | 1.0 | 0.533 | 0.696 | 0.0 |

## dev:handwritten_blind_v11: rules+ml

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | lottery | 1.0 | 1.0 | 1.0 | |
| ≥medium | casino | 1.0 | 1.0 | 1.0 | |
| ≥medium | pyramid | 1.0 | 1.0 | 1.0 | |
| ≥medium | язык kk | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык mix | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык ru | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык translit | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | все треки | 1.0 | 0.52 | 0.684 | 0.0 |
| ≥high | lottery | 1.0 | 0.455 | 0.625 | |
| ≥high | casino | 1.0 | 0.606 | 0.755 | |
| ≥high | pyramid | 1.0 | 0.5 | 0.667 | |
| ≥high | язык kk | 1.0 | 0.5 | 0.667 | 0.0 |
| ≥high | язык mix | 1.0 | 0.381 | 0.552 | 0.0 |
| ≥high | язык ru | 1.0 | 0.55 | 0.71 | 0.0 |
| ≥high | язык translit | 1.0 | 0.667 | 0.8 | 0.0 |

## dev:handwritten_blind_v12: rules

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 0.973 | 0.71 | 0.821 | 0.02 |
| ≥medium | lottery | 1.0 | 0.727 | 0.842 | |
| ≥medium | casino | 1.0 | 0.697 | 0.821 | |
| ≥medium | pyramid | 0.885 | 0.676 | 0.767 | |
| ≥medium | язык kk | 0.923 | 0.5 | 0.649 | 0.038 |
| ≥medium | язык mix | 1.0 | 0.905 | 0.95 | 0.0 |
| ≥medium | язык ru | 0.966 | 0.7 | 0.812 | 0.025 |
| ≥medium | язык translit | 1.0 | 0.8 | 0.889 | 0.0 |
| ≥high | все треки | 1.0 | 0.49 | 0.658 | 0.0 |
| ≥high | lottery | 1.0 | 0.576 | 0.731 | |
| ≥high | casino | 1.0 | 0.394 | 0.565 | |
| ≥high | pyramid | 0.941 | 0.471 | 0.627 | |
| ≥high | язык kk | 1.0 | 0.292 | 0.452 | 0.0 |
| ≥high | язык mix | 1.0 | 0.619 | 0.765 | 0.0 |
| ≥high | язык ru | 1.0 | 0.5 | 0.667 | 0.0 |
| ≥high | язык translit | 1.0 | 0.6 | 0.75 | 0.0 |

## dev:handwritten_blind_v12: rules+ml

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 0.98 | 1.0 | 0.99 | 0.02 |
| ≥medium | lottery | 1.0 | 1.0 | 1.0 | |
| ≥medium | casino | 1.0 | 1.0 | 1.0 | |
| ≥medium | pyramid | 0.944 | 1.0 | 0.971 | |
| ≥medium | язык kk | 0.96 | 1.0 | 0.98 | 0.038 |
| ≥medium | язык mix | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык ru | 0.976 | 1.0 | 0.988 | 0.025 |
| ≥medium | язык translit | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | все треки | 1.0 | 0.51 | 0.675 | 0.0 |
| ≥high | lottery | 1.0 | 0.606 | 0.755 | |
| ≥high | casino | 1.0 | 0.455 | 0.625 | |
| ≥high | pyramid | 1.0 | 0.471 | 0.64 | |
| ≥high | язык kk | 1.0 | 0.292 | 0.452 | 0.0 |
| ≥high | язык mix | 1.0 | 0.667 | 0.8 | 0.0 |
| ≥high | язык ru | 1.0 | 0.525 | 0.689 | 0.0 |
| ≥high | язык translit | 1.0 | 0.6 | 0.75 | 0.0 |

## dev:handwritten_blind_v13: rules

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 0.974 | 0.74 | 0.841 | 0.02 |
| ≥medium | lottery | 0.962 | 0.758 | 0.847 | |
| ≥medium | casino | 0.909 | 0.606 | 0.727 | |
| ≥medium | pyramid | 0.857 | 0.706 | 0.774 | |
| ≥medium | язык kk | 1.0 | 0.68 | 0.81 | 0.0 |
| ≥medium | язык mix | 1.0 | 0.6 | 0.75 | 0.0 |
| ≥medium | язык ru | 0.938 | 0.75 | 0.833 | 0.05 |
| ≥medium | язык translit | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | все треки | 0.978 | 0.44 | 0.607 | 0.01 |
| ≥high | lottery | 1.0 | 0.636 | 0.778 | |
| ≥high | casino | 0.857 | 0.182 | 0.3 | |
| ≥high | pyramid | 0.941 | 0.471 | 0.627 | |
| ≥high | язык kk | 1.0 | 0.4 | 0.571 | 0.0 |
| ≥high | язык mix | 1.0 | 0.25 | 0.4 | 0.0 |
| ≥high | язык ru | 0.944 | 0.425 | 0.586 | 0.025 |
| ≥high | язык translit | 1.0 | 0.8 | 0.889 | 0.0 |

## dev:handwritten_blind_v13: rules+ml

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 0.98 | 1.0 | 0.99 | 0.02 |
| ≥medium | lottery | 0.97 | 0.97 | 0.97 | |
| ≥medium | casino | 0.939 | 0.939 | 0.939 | |
| ≥medium | pyramid | 0.944 | 1.0 | 0.971 | |
| ≥medium | язык kk | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык mix | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык ru | 0.952 | 1.0 | 0.976 | 0.05 |
| ≥medium | язык translit | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | все треки | 0.98 | 0.49 | 0.653 | 0.01 |
| ≥high | lottery | 1.0 | 0.636 | 0.778 | |
| ≥high | casino | 0.917 | 0.333 | 0.489 | |
| ≥high | pyramid | 0.941 | 0.471 | 0.627 | |
| ≥high | язык kk | 1.0 | 0.4 | 0.571 | 0.0 |
| ≥high | язык mix | 1.0 | 0.25 | 0.4 | 0.0 |
| ≥high | язык ru | 0.955 | 0.525 | 0.677 | 0.025 |
| ≥high | язык translit | 1.0 | 0.867 | 0.929 | 0.0 |

## dev:handwritten_blind_v14: rules

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 0.952 | 0.6 | 0.736 | 0.03 |
| ≥medium | lottery | 0.9 | 0.545 | 0.679 | |
| ≥medium | casino | 0.92 | 0.697 | 0.793 | |
| ≥medium | pyramid | 0.944 | 0.5 | 0.654 | |
| ≥medium | язык kk | 1.0 | 0.44 | 0.611 | 0.0 |
| ≥medium | язык mix | 0.9 | 0.45 | 0.6 | 0.05 |
| ≥medium | язык ru | 0.938 | 0.75 | 0.833 | 0.05 |
| ≥medium | язык translit | 1.0 | 0.667 | 0.8 | 0.0 |
| ≥high | все треки | 1.0 | 0.38 | 0.551 | 0.0 |
| ≥high | lottery | 0.917 | 0.333 | 0.489 | |
| ≥high | casino | 1.0 | 0.364 | 0.533 | |
| ≥high | pyramid | 1.0 | 0.412 | 0.583 | |
| ≥high | язык kk | 1.0 | 0.24 | 0.387 | 0.0 |
| ≥high | язык mix | 1.0 | 0.3 | 0.462 | 0.0 |
| ≥high | язык ru | 1.0 | 0.5 | 0.667 | 0.0 |
| ≥high | язык translit | 1.0 | 0.4 | 0.571 | 0.0 |

## dev:handwritten_blind_v14: rules+ml

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 0.971 | 1.0 | 0.985 | 0.03 |
| ≥medium | lottery | 0.943 | 1.0 | 0.971 | |
| ≥medium | casino | 0.943 | 1.0 | 0.971 | |
| ≥medium | pyramid | 0.97 | 0.941 | 0.955 | |
| ≥medium | язык kk | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык mix | 0.952 | 1.0 | 0.976 | 0.05 |
| ≥medium | язык ru | 0.952 | 1.0 | 0.976 | 0.05 |
| ≥medium | язык translit | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | все треки | 1.0 | 0.44 | 0.611 | 0.0 |
| ≥high | lottery | 0.944 | 0.515 | 0.667 | |
| ≥high | casino | 1.0 | 0.364 | 0.533 | |
| ≥high | pyramid | 1.0 | 0.412 | 0.583 | |
| ≥high | язык kk | 1.0 | 0.24 | 0.387 | 0.0 |
| ≥high | язык mix | 1.0 | 0.35 | 0.519 | 0.0 |
| ≥high | язык ru | 1.0 | 0.6 | 0.75 | 0.0 |
| ≥high | язык translit | 1.0 | 0.467 | 0.636 | 0.0 |

## dev:handwritten_blind_v15: rules

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 0.855 | 0.71 | 0.776 | 0.12 |
| ≥medium | lottery | 0.743 | 0.788 | 0.765 | |
| ≥medium | casino | 0.926 | 0.758 | 0.833 | |
| ≥medium | pyramid | 0.857 | 0.529 | 0.655 | |
| ≥medium | язык kk | 0.875 | 0.56 | 0.683 | 0.08 |
| ≥medium | язык mix | 0.938 | 0.75 | 0.833 | 0.05 |
| ≥medium | язык ru | 0.816 | 0.775 | 0.795 | 0.175 |
| ≥medium | язык translit | 0.846 | 0.733 | 0.786 | 0.133 |
| ≥high | все треки | 0.868 | 0.46 | 0.601 | 0.07 |
| ≥high | lottery | 0.778 | 0.636 | 0.7 | |
| ≥high | casino | 1.0 | 0.303 | 0.465 | |
| ≥high | pyramid | 0.938 | 0.441 | 0.6 | |
| ≥high | язык kk | 0.889 | 0.32 | 0.471 | 0.04 |
| ≥high | язык mix | 0.909 | 0.5 | 0.645 | 0.05 |
| ≥high | язык ru | 0.875 | 0.525 | 0.656 | 0.075 |
| ≥high | язык translit | 0.778 | 0.467 | 0.583 | 0.133 |

## dev:handwritten_blind_v15: rules+ml

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 0.9 | 0.99 | 0.943 | 0.11 |
| ≥medium | lottery | 0.786 | 1.0 | 0.88 | |
| ≥medium | casino | 0.943 | 1.0 | 0.971 | |
| ≥medium | pyramid | 0.939 | 0.912 | 0.925 | |
| ≥medium | язык kk | 0.923 | 0.96 | 0.941 | 0.08 |
| ≥medium | язык mix | 0.952 | 1.0 | 0.976 | 0.05 |
| ≥medium | язык ru | 0.87 | 1.0 | 0.93 | 0.15 |
| ≥medium | язык translit | 0.882 | 1.0 | 0.938 | 0.133 |
| ≥high | все треки | 0.881 | 0.52 | 0.654 | 0.07 |
| ≥high | lottery | 0.806 | 0.758 | 0.781 | |
| ≥high | casino | 1.0 | 0.364 | 0.533 | |
| ≥high | pyramid | 0.938 | 0.441 | 0.6 | |
| ≥high | язык kk | 0.909 | 0.4 | 0.556 | 0.04 |
| ≥high | язык mix | 0.917 | 0.55 | 0.687 | 0.05 |
| ≥high | язык ru | 0.885 | 0.575 | 0.697 | 0.075 |
| ≥high | язык translit | 0.8 | 0.533 | 0.64 | 0.133 |

## dev:real_v1: rules

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 0.87 | 0.47 | 0.61 | 0.028 |
| ≥medium | lottery | 0.0 | 0.0 | 0.0 | |
| ≥medium | casino | 0.978 | 0.455 | 0.621 | |
| ≥medium | pyramid | 0.5 | 1.0 | 0.667 | |
| ≥medium | язык kk | 0.875 | 0.35 | 0.5 | 0.03 |
| ≥medium | язык mix | 0.0 | 0.0 | 0.0 | 0.0 |
| ≥medium | язык other | 1.0 | 0.5 | 0.667 | 0.0 |
| ≥medium | язык ru | 0.867 | 0.5 | 0.634 | 0.031 |
| ≥high | все треки | 0.5 | 0.01 | 0.02 | 0.004 |
| ≥high | lottery | 0.0 | 0.0 | 0.0 | |
| ≥high | casino | 1.0 | 0.01 | 0.02 | |
| ≥high | pyramid | 0.0 | 0.0 | 0.0 | |
| ≥high | язык kk | 1.0 | 0.05 | 0.095 | 0.0 |
| ≥high | язык mix | 0.0 | 0.0 | 0.0 | 0.0 |
| ≥high | язык other | 0.0 | 0.0 | 0.0 | 0.0 |
| ≥high | язык ru | 0.0 | 0.0 | 0.0 | 0.005 |

## dev:real_v1: rules+ml

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 0.935 | 1.0 | 0.966 | 0.028 |
| ≥medium | lottery | 0.0 | 0.0 | 0.0 | |
| ≥medium | casino | 0.99 | 0.99 | 0.99 | |
| ≥medium | pyramid | 0.5 | 1.0 | 0.667 | |
| ≥medium | язык kk | 0.952 | 1.0 | 0.976 | 0.03 |
| ≥medium | язык mix | 0.0 | 0.0 | 0.0 | 0.0 |
| ≥medium | язык other | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык ru | 0.929 | 1.0 | 0.963 | 0.031 |
| ≥high | все треки | 0.5 | 0.01 | 0.02 | 0.004 |
| ≥high | lottery | 0.0 | 0.0 | 0.0 | |
| ≥high | casino | 1.0 | 0.01 | 0.02 | |
| ≥high | pyramid | 0.0 | 0.0 | 0.0 | |
| ≥high | язык kk | 1.0 | 0.05 | 0.095 | 0.0 |
| ≥high | язык mix | 0.0 | 0.0 | 0.0 | 0.0 |
| ≥high | язык other | 0.0 | 0.0 | 0.0 | 0.0 |
| ≥high | язык ru | 0.0 | 0.0 | 0.0 | 0.005 |

## full: full

| Порог | Срез | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|
| ≥medium | все треки | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | lottery | 1.0 | 1.0 | 1.0 | |
| ≥medium | casino | 1.0 | 1.0 | 1.0 | |
| ≥medium | pyramid | 1.0 | 1.0 | 1.0 | |
| ≥medium | язык kk | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык mix | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык ru | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥medium | язык translit | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | все треки | 1.0 | 0.994 | 0.997 | 0.0 |
| ≥high | lottery | 1.0 | 1.0 | 1.0 | |
| ≥high | casino | 1.0 | 0.981 | 0.991 | |
| ≥high | pyramid | 1.0 | 1.0 | 1.0 | |
| ≥high | язык kk | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | язык mix | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | язык ru | 1.0 | 1.0 | 1.0 | 0.0 |
| ≥high | язык translit | 1.0 | 0.985 | 0.992 | 0.0 |

Посты с изображениями (≥medium): precision 1.0, recall 1.0, FPR 0.0.
Скорость полного пайплайна (с OCR): 8.6 постов/с на 1 CPU.

## История слепых замеров (≥medium)

| Набор | Когда | Precision | Recall | FPR |
|---|---|---|---|---|
| handwritten_blind (v1) | раунд 1, первый замер | 0,913 | 0,875 | 0,125 |
| handwritten_blind_v2 | раунд 2, до правок | 0,793 | 0,639 | 0,250 |
| handwritten_blind_v2 | раунд 2, после правок по своему dev-набору | 0,765 | 0,722 | 0,333 |
| handwritten_blind_v3 | код раунда 1 на этом наборе, для сравнения | 0,692 | 0,450 | 0,200 |
| handwritten_blind_v3 | раунд 3, первый замер | 0,857 | 0,750 | 0,125 |
| handwritten_blind_v4 | код до раунда 2, для сравнения | 0,761 | 0,438 | 0,138 |
| handwritten_blind_v4 | код раунда 3, для сравнения | 0,852 | 0,650 | 0,113 |
| handwritten_blind_v4 | раунд 4, первый замер | 0,969 | 0,775 | 0,025 |
| handwritten_blind_v4 | раунд 4, после правила против маскировки «осторожно, мошенники» + реквизит | 0,954 | 0,775 | 0,037 |
| handwritten_blind_v4 | раунд 4, после исправлений ревью (уклонения через вопрос, кавычки, «не переживайте») | 0,939 | 0,775 | 0,050 |
| handwritten_blind_v5 | код до раунда 2, для сравнения | 0,848 | 0,433 | 0,078 |
| handwritten_blind_v5 | код раунда 4, для сравнения | 0,909 | 0,667 | 0,067 |
| handwritten_blind_v5 | раунд 5, первый замер (после ревью) | 0,917 | 0,733 | 0,067 |
| handwritten_blind_v6 | код до раунда 2, для сравнения | 0,840 | 0,420 | 0,080 |
| handwritten_blind_v6 | код раунда 5, для сравнения | 0,907 | 0,680 | 0,070 |
| handwritten_blind_v6 | раунд 6, первый замер (ML на ручной разметке + новые шаблоны) | 0,903 | 0,840 | 0,090 |
| handwritten_blind_v7 | код до раунда 2, для сравнения | 0,792 | 0,380 | 0,100 |
| handwritten_blind_v7 | код раунда 5, для сравнения | 0,853 | 0,640 | 0,110 |
| handwritten_blind_v7 | код раунда 6, для сравнения | 0,886 | 0,780 | 0,100 |
| handwritten_blind_v7 | раунд 7, первый замер (шаблоны по ошибкам v6 и ревью): прироста нет | 0,876 | 0,780 | 0,110 |
| handwritten_blind_v7 | оценка: + LLM-арбитр в зоне 20–74 с вето только без контактов и просьб о деньгах, ответы записаны тем же промптом (scripts/llm_sim.py), нужен ANTHROPIC_API_KEY | 0,948 | 0,920 | 0,050 |
| handwritten_blind_v8 | код до раунда 2, для сравнения | 0,708 | 0,170 | 0,070 |
| handwritten_blind_v8 | код раунда 5, для сравнения | 0,738 | 0,310 | 0,110 |
| handwritten_blind_v8 | код раунда 6, для сравнения | 0,918 | 0,560 | 0,050 |
| handwritten_blind_v8 | раунд 8, первый замер: правила + ML (v7 в обучении) | 0,940 | 0,630 | 0,040 |
| handwritten_blind_v8 | оценка: + LLM-арбитр с вето, ответы записаны тем же промптом (eval/llm_verdicts_v8.json) | 1,000 | 0,890 | 0,000 |
| handwritten_blind_v9 | код до раунда 2, для сравнения | 0,794 | 0,270 | 0,070 |
| handwritten_blind_v9 | код раунда 6, для сравнения | 0,869 | 0,530 | 0,080 |
| handwritten_blind_v9 | раунд 8, первый замер: правила + ML (v8 в обучении) | 0,918 | 0,670 | 0,060 |
| handwritten_blind_v9 | оценка: + LLM-арбитр с вето, ответы записаны тем же промптом (eval/llm_verdicts_v9.json) | 0,947 | 0,890 | 0,050 |
| handwritten_blind_v10 | код до раунда 2, для сравнения | 0,781 | 0,250 | 0,070 |
| handwritten_blind_v10 | код раунда 6, для сравнения | 0,883 | 0,530 | 0,070 |
| handwritten_blind_v10 | код раунда 8 с моделью раунда 9, для сравнения | 0,928 | 0,640 | 0,050 |
| handwritten_blind_v10 | раунд 9, первый замер: правила + ML, уверенная модель ставит «средний» со своими словами | 0,940 | 0,780 | 0,050 |
| handwritten_blind_v10 | раунд 9 + живой LLM-арбитр (Sonnet 5.5, effort low, два прогона по 103 вызова) | 0,956 | 0,860–0,870 | 0,040 |
| handwritten_blind_v11 | код раунда 9 со своей моделью, для сравнения | 0,942 | 0,810 | 0,050 |
| handwritten_blind_v11 | раунд 10, первый замер: правила + ML | 0,944 | 0,850 | 0,050 |
| handwritten_blind_v11 | раунд 10, только правила | 0,921 | 0,580 | 0,050 |
| handwritten_blind_v12 | код раунда 10, для сравнения | 0,863 | 0,880 | 0,140 |
| handwritten_blind_v12 | раунд 11, первый замер: правила + ML | 0,880 | 0,880 | 0,120 |
| handwritten_blind_v12 | раунд 11, только правила | 0,836 | 0,610 | 0,120 |
| handwritten_blind_v13 | раунд 12, первый замер: правила + ML | 0,910 | 0,910 | 0,090 |
| handwritten_blind_v13 | раунд 12, только правила | 0,919 | 0,680 | 0,060 |
| handwritten_blind_v14 | раунд 12 после правок по v13, первый замер: правила + ML (правки на v14 не повлияли) | 0,895 | 0,940 | 0,110 |
| handwritten_blind_v14 | раунд 12 после правок по v13, только правила | 0,857 | 0,600 | 0,100 |
| handwritten_blind_v15 | раунд 13 (правки по v14 и реальным постам real_v1), первый замер: правила + ML | 0,896 | 0,950 | 0,110 |
| handwritten_blind_v15 | раунд 13, только правила | 0,855 | 0,710 | 0,120 |
| real_v1 (349 реальных постов, 19 каналов) | код раунда 12, первый замер: правила + ML | 0,812 | 0,390 | 0,036 |

В скобках 95% интервал Уилсона.


Синтетика сгенерирована нашим генератором, поэтому цифры оптимистичны; главное в них — FPR на трудных легальных примерах (бесплатные конкурсы, депозиты, предупреждения, личные переводы, сборы).
