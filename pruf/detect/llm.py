"""LLM-арбитр (Claude) для спорной зоны. Возвращает признаки с дословными цитатами.

Вызывается только когда балл попал в средний диапазон и задан ANTHROPIC_API_KEY.
Цитаты, которых нет в исходном тексте, отбрасываются: LLM не может «придумать» улику.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from pruf.detect.lexicon import TRACKS
from pruf.models import Evidence

log = logging.getLogger(__name__)
MAX_INPUT_CHARS = 4000
LLM_WEIGHT = 12.0

_SYSTEM = (
    "Ты помогаешь аналитику по финансовой безопасности Казахстана. Тебе дают сообщение из соцсети или мессенджера "
    "(русский, казахский, транслит, сленг). Найди признаки трёх схем: lottery (платный розыгрыш или лотерея, участие за деньги), "
    "casino (скрытая реклама онлайн-казино или букмекера), pyramid (финансовая пирамида: доход за привлечение людей, "
    "нереальная доходность, взносы). Не выноси вердиктов. Легальный бесплатный конкурс, обычная реклама бренда, новости "
    "и предупреждения о мошенниках не являются признаками. Каждая цитата должна дословно совпадать с фрагментом сообщения."
)

_SCHEMA = {
    "type": "object",
    "properties": {
        "signals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "track": {"type": "string", "enum": list(TRACKS)},
                    "label": {"type": "string"},
                    "quote": {"type": "string"},
                },
                "required": ["track", "label", "quote"],
                "additionalProperties": False,
            },
        },
        "legit_context": {"type": "boolean"},
    },
    "required": ["signals", "legit_context"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class LlmVerdict:
    evidence: tuple[Evidence, ...]
    legit_context: bool


class LlmArbiter:
    def __init__(self, api_key: str, model: str):
        import anthropic

        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=api_key, timeout=20.0, max_retries=1)
        self._model = model

    def review(self, text: str) -> LlmVerdict | None:
        snippet = text[:MAX_INPUT_CHARS]
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=2000,
                system=_SYSTEM,
                output_config={"effort": "low", "format": {"type": "json_schema", "schema": _SCHEMA}},
                messages=[{"role": "user", "content": f"Сообщение:\n<<<\n{snippet}\n>>>"}],
            )
        except self._anthropic.RateLimitError as exc:
            log.warning("LLM: лимит запросов: %s", exc)
            return None
        except self._anthropic.APIStatusError as exc:
            log.warning("LLM: ошибка API %s", exc.status_code)
            return None
        except self._anthropic.APIConnectionError as exc:
            log.warning("LLM: нет соединения: %s", exc)
            return None
        if response.stop_reason == "refusal":
            log.info("LLM отказался обрабатывать сообщение")
            return None
        raw = next((b.text for b in response.content if b.type == "text"), "")
        return parse_llm_output(raw, snippet)


def parse_llm_output(raw: str, source_text: str) -> LlmVerdict | None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("LLM вернул невалидный JSON")
        return None
    evidence: list[Evidence] = []
    lower_source = source_text.lower()
    for item in data.get("signals", []):
        quote = str(item.get("quote", "")).strip()
        track = item.get("track")
        if not quote or track not in TRACKS:
            continue
        pos = lower_source.find(quote.lower())
        if pos < 0:
            continue  # цитаты нет в тексте, не доверяем
        evidence.append(Evidence(
            feature_id=f"llm.{track}", track=track, label="LLM: " + str(item.get("label", ""))[:160],
            weight=LLM_WEIGHT, source="llm", quote=source_text[pos:pos + len(quote)], span=(pos, pos + len(quote)),
        ))
    return LlmVerdict(evidence=tuple(evidence), legit_context=bool(data.get("legit_context", False)))
