"""Оценка LLM-арбитра без API-ключа: ответы арбитра на посты спорной зоны записаны заранее тем же промптом.

Ответы для слепого v7 лежат в eval/llm_verdicts_v7.json (id → {"signals", "legit_context"}). Их дала модель
того же семейства, что и в бою, поэтому оценка оптимистична: посты набора писал тоже Claude.
Запуск: PRUF_DEV_MODE=1 python scripts/llm_sim.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pruf.detect.detector as detector_module
import pruf.scoring as scoring
from pruf.config import Settings
from pruf.detect.detector import Detector, SourceText
from pruf.detect.llm import LlmVerdict, parse_llm_output
from pruf.normalize.requisites import redact_cards


class RecordedLlm:
    """Арбитр, который отвечает записанными вердиктами по тексту поста."""

    def __init__(self, by_text: dict[str, dict]):
        self._by_text = by_text
        self.missing = 0

    def review(self, text: str) -> LlmVerdict | None:
        verdict = self._by_text.get(text)
        if verdict is None:
            self.missing += 1
            return None
        return parse_llm_output(json.dumps(verdict, ensure_ascii=False), text)

    def stats(self) -> dict[str, object]:
        return {"model": "recorded", "missing": self.missing}


def measure(rows: list[dict], det: Detector) -> str:
    tp = fp = fn = tn = 0
    for r in rows:
        positive = det.detect([SourceText("text", r["text"])]).analysis.level != "low"
        scam = r["label"] != "legit"
        tp += positive and scam
        fp += positive and not scam
        fn += scam and not positive
        tn += not scam and not positive
    return f"precision {tp / max(1, tp + fp):.3f}, recall {tp / max(1, tp + fn):.3f}, FPR {fp / max(1, fp + tn):.3f}"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--set", type=Path, default=Path("eval/handwritten_blind_v7.jsonl"))
    ap.add_argument("--verdicts", type=Path, default=Path("eval/llm_verdicts_v7.json"))
    ap.add_argument("--model", type=Path, default=Path("models/clf.joblib"))
    args = ap.parse_args()
    rows = [json.loads(line) for line in args.set.read_text(encoding="utf-8").splitlines() if line.strip()]
    verdicts = json.loads(args.verdicts.read_text(encoding="utf-8"))
    by_text = {redact_cards(r["text"]): verdicts[r["id"]] for r in rows if r["id"] in verdicts}
    settings = Settings(model_path=args.model)
    print("без LLM:                ", measure(rows, Detector(settings)))
    zone = detector_module.LLM_ZONE
    detector_module.LLM_ZONE = (scoring.MEDIUM_THRESHOLD, scoring.HIGH_THRESHOLD)
    legit_flag, scoring.LLM_LEGIT = scoring.LLM_LEGIT, "llm.legit.disabled"
    print("старая зона 35–64:      ", measure(rows, Detector(settings, llm=RecordedLlm(by_text))))
    scoring.LLM_LEGIT = legit_flag
    detector_module.LLM_ZONE = zone
    print("зона 20–74 и вето:      ", measure(rows, Detector(settings, llm=RecordedLlm(by_text))))


if __name__ == "__main__":
    main()
