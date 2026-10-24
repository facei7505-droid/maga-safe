"""Метрики на тестовом сплите: precision / recall / FPR, по трекам и в целом.

Режимы:
  text  — только текст: правила, затем правила + ML (быстро, как тест жюри без картинок);
  full  — полный пайплайн: все посты по времени проходят через реестр ПРУФ и граф,
          метрики считаются по тестовым постам (как тест с изображениями).
Положительный прогноз: уровень риска «средний» или «высокий» (и отдельно только «высокий»).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("PRUF_DEV_MODE", "1")

from pruf.config import Settings
from pruf.detect.classifier import TrackClassifier
from pruf.detect.detector import Detector, SourceText
from pruf.detect.lexicon import TRACKS
from pruf.detect.training import dev_paths
from pruf.synth.generator import SynthPost, read_jsonl

LEVELS_POS = {"medium": ("medium", "high"), "high": ("high",)}
# Каждый слепой набор пишет отдельный агент без доступа к коду; на нём только измеряем. После отчёта набор
# считается «потраченным»: он переходит в dev, его ошибки можно разбирать, а следующий раунд проверяется
# на новом наборе. v1–v3 уже в dev; v4 опубликован в раунде 4, следующий раунд требует v5.
BLIND_HISTORY = (
    ("handwritten_blind (v1)", "раунд 1, первый замер", "0,913", "0,875", "0,125"),
    ("handwritten_blind_v2", "раунд 2, до правок", "0,793", "0,639", "0,250"),
    ("handwritten_blind_v2", "раунд 2, после правок по своему dev-набору", "0,765", "0,722", "0,333"),
    ("handwritten_blind_v3", "код раунда 1 на этом наборе, для сравнения", "0,692", "0,450", "0,200"),
    ("handwritten_blind_v3", "раунд 3, первый замер", "0,857", "0,750", "0,125"),
    ("handwritten_blind_v4", "код до раунда 2, для сравнения", "0,761", "0,438", "0,138"),
    ("handwritten_blind_v4", "код раунда 3, для сравнения", "0,852", "0,650", "0,113"),
    ("handwritten_blind_v4", "раунд 4, первый замер", "0,969", "0,775", "0,025"),
    ("handwritten_blind_v4", "раунд 4, после правила против маскировки «осторожно, мошенники» + реквизит", "0,954", "0,775", "0,037"),
    ("handwritten_blind_v4", "раунд 4, после исправлений ревью (уклонения через вопрос, кавычки, «не переживайте»)", "0,939", "0,775", "0,050"),
    ("handwritten_blind_v5", "код до раунда 2, для сравнения", "0,848", "0,433", "0,078"),
    ("handwritten_blind_v5", "код раунда 4, для сравнения", "0,909", "0,667", "0,067"),
    ("handwritten_blind_v5", "раунд 5, первый замер (после ревью)", "0,917", "0,733", "0,067"),
    ("handwritten_blind_v6", "код до раунда 2, для сравнения", "0,840", "0,420", "0,080"),
    ("handwritten_blind_v6", "код раунда 5, для сравнения", "0,907", "0,680", "0,070"),
    ("handwritten_blind_v6", "раунд 6, первый замер (ML на ручной разметке + новые шаблоны)", "0,903", "0,840", "0,090"),
    ("handwritten_blind_v7", "код до раунда 2, для сравнения", "0,792", "0,380", "0,100"),
    ("handwritten_blind_v7", "код раунда 5, для сравнения", "0,853", "0,640", "0,110"),
    ("handwritten_blind_v7", "код раунда 6, для сравнения", "0,886", "0,780", "0,100"),
    ("handwritten_blind_v7", "раунд 7, первый замер (шаблоны по ошибкам v6 и ревью): прироста нет", "0,876", "0,780", "0,110"),
    ("handwritten_blind_v7", "оценка: + LLM-арбитр в зоне 20–74 с вето только без контактов и просьб о деньгах, ответы записаны тем же промптом (scripts/llm_sim.py), нужен ANTHROPIC_API_KEY", "0,948", "0,920", "0,050"),
    ("handwritten_blind_v8", "код до раунда 2, для сравнения", "0,708", "0,170", "0,070"),
    ("handwritten_blind_v8", "код раунда 5, для сравнения", "0,738", "0,310", "0,110"),
    ("handwritten_blind_v8", "код раунда 6, для сравнения", "0,918", "0,560", "0,050"),
    ("handwritten_blind_v8", "раунд 8, первый замер: правила + ML (v7 в обучении)", "0,940", "0,630", "0,040"),
    ("handwritten_blind_v8", "оценка: + LLM-арбитр с вето, ответы записаны тем же промптом (eval/llm_verdicts_v8.json)", "1,000", "0,890", "0,000"),
    ("handwritten_blind_v9", "код до раунда 2, для сравнения", "0,794", "0,270", "0,070"),
    ("handwritten_blind_v9", "код раунда 6, для сравнения", "0,869", "0,530", "0,080"),
    ("handwritten_blind_v9", "раунд 8, первый замер: правила + ML (v8 в обучении)", "0,918", "0,670", "0,060"),
    ("handwritten_blind_v9", "оценка: + LLM-арбитр с вето, ответы записаны тем же промптом (eval/llm_verdicts_v9.json)", "0,947", "0,890", "0,050"),
    ("handwritten_blind_v10", "код до раунда 2, для сравнения", "0,781", "0,250", "0,070"),
    ("handwritten_blind_v10", "код раунда 6, для сравнения", "0,883", "0,530", "0,070"),
    ("handwritten_blind_v10", "код раунда 8 с моделью раунда 9, для сравнения", "0,928", "0,640", "0,050"),
    ("handwritten_blind_v10", "раунд 9, первый замер: правила + ML, уверенная модель ставит «средний» со своими словами", "0,940", "0,780", "0,050"),
)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% доверительный интервал Уилсона для доли k из n: на 160 постах ±5–9 п.п. — это честнее точки."""
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return round(max(0.0, c - h), 3), round(min(1.0, c + h), 3)


def metrics(rows: list[tuple[SynthPost, str, str | None]], min_level: str) -> dict:
    pos_levels = LEVELS_POS[min_level]
    out: dict = {}
    tp = sum(1 for p, lvl, _ in rows if p.label != "legit" and lvl in pos_levels)
    fn = sum(1 for p, lvl, _ in rows if p.label != "legit" and lvl not in pos_levels)
    fp = sum(1 for p, lvl, _ in rows if p.label == "legit" and lvl in pos_levels)
    tn = sum(1 for p, lvl, _ in rows if p.label == "legit" and lvl not in pos_levels)
    out["overall"] = _prf(tp, fp, fn, tn)
    for track in TRACKS:
        ttp = sum(1 for p, lvl, t in rows if p.label == track and lvl in pos_levels and t == track)
        tfn = sum(1 for p, lvl, t in rows if p.label == track and not (lvl in pos_levels and t == track))
        tfp = sum(1 for p, lvl, t in rows if p.label != track and lvl in pos_levels and t == track)
        out[track] = _prf(ttp, tfp, tfn, None)
    by_lang: dict = {}
    for lang in sorted({p.lang for p, _, _ in rows}):
        sub = [r for r in rows if r[0].lang == lang]
        ltp = sum(1 for p, lvl, _ in sub if p.label != "legit" and lvl in pos_levels)
        lfn = sum(1 for p, lvl, _ in sub if p.label != "legit" and lvl not in pos_levels)
        lfp = sum(1 for p, lvl, _ in sub if p.label == "legit" and lvl in pos_levels)
        ltn = sum(1 for p, lvl, _ in sub if p.label == "legit" and lvl not in pos_levels)
        by_lang[lang] = _prf(ltp, lfp, lfn, ltn)
    out["by_lang"] = by_lang
    out["false_positives"] = [p.text[:140] for p, lvl, _ in rows if p.label == "legit" and lvl in pos_levels][:15]
    out["missed"] = [f"[{p.label}] {p.text[:140]}" for p, lvl, _ in rows if p.label != "legit" and lvl not in pos_levels][:15]
    return out


def _prf(tp: int, fp: int, fn: int, tn: int | None) -> dict:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    res = {"tp": tp, "fp": fp, "fn": fn, "precision": round(precision, 3), "recall": round(recall, 3),
           "f1": round(2 * precision * recall / (precision + recall), 3) if precision + recall else 0.0}
    if tn is not None:
        res["tn"] = tn
        res["fpr"] = round(fp / (fp + tn), 3) if fp + tn else 0.0
    return res


def eval_text(posts: list[SynthPost], settings: Settings, model: Path | None) -> dict:
    test = [p for p in posts if p.split == "test"]
    results = {}
    variants = [("rules", None)]
    if model and model.exists():
        variants.append(("rules+ml", TrackClassifier.load(model)))
    for name, clf in variants:
        det = Detector(settings, classifier=clf) if clf else Detector(settings, classifier=_NoModel())
        rows = []
        for p in test:
            a = det.detect([SourceText("text", p.text)]).analysis
            rows.append((p, a.level, a.track))
        results[name] = {lvl: metrics(rows, lvl) for lvl in LEVELS_POS}
    return results


class _NoModel:
    """Заглушка: детектор без ML (TrackClassifier.load вернул бы модель из models/)."""

    def predict_folded(self, folded: str) -> None:
        return None

    def __bool__(self) -> bool:
        return False


def eval_full(posts: list[SynthPost], data_root: Path, model: Path | None) -> dict:
    from pruf.pipeline import Pruf, Submission, Upload

    tmp = Path(tempfile.mkdtemp(prefix="pruf_eval_"))
    try:
        settings = Settings(data_dir=tmp, model_path=model or Path("/nonexistent"))
        pruf = Pruf(settings)
        rows = []
        started = time.time()
        for p in sorted(posts, key=lambda x: x.posted_at):
            uploads = ()
            if p.image:
                uploads = (Upload((data_root / p.image).read_bytes(), "image", "jpg"),)
            res = pruf.ingest(Submission(text=p.text, uploads=uploads, channel=p.channel, posted_at=p.posted_at,
                                         external_id=p.id, label=p.label, source="synthetic"))
            if p.split == "test":
                a = res["analysis"]
                rows.append((p, a["level"], a["track"]))
        elapsed = time.time() - started
        res = {lvl: metrics(rows, lvl) for lvl in LEVELS_POS}
        res["throughput_posts_per_sec"] = round(len(posts) / elapsed, 1)
        with_img = [r for r in rows if r[0].image]
        res["image_posts"] = {lvl: metrics(with_img, lvl)["overall"] for lvl in LEVELS_POS}
        return res
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def load_handwritten(path: Path) -> list[SynthPost]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [SynthPost(id=r["id"], text=r["text"], label=r["label"], lang=r["lang"], template="handwritten",
                      split="test", channel="", posted_at="") for r in rows]


def to_markdown(report: dict) -> str:
    lines = ["# ПРУФ: метрики на синтетическом тесте", "",
             f"Датасет: {report['dataset']['posts']} постов, тест: {report['dataset']['test']} "
             f"({report['dataset']['test_labels']}). Разбиение по кампаниям, 1/4 шаблонов только в тесте.", "",
             "Положительный прогноз: уровень «средний» или выше (строки ≥medium) либо только «высокий» (≥high).", "",
             "Наборы `dev:*` используются для настройки правил, поэтому цифры на них завышены. Наборы `blind:*` пишет "
             "отдельный агент без доступа к коду, на них только измеряем; после публикации набор уходит в dev. "
             "Главная цифра качества — слепой набор и таблица истории в конце.", ""]
    for mode, variants in report["results"].items():
        blocks = variants.items() if mode != "full" else [("full", variants)]
        for name, res in blocks:
            lines += [f"## {mode}: {name}", "", "| Порог | Срез | Precision | Recall | F1 | FPR |", "|---|---|---|---|---|---|"]
            for lvl in LEVELS_POS:
                r = res[lvl]
                o = r["overall"]
                lines.append(f"| ≥{lvl} | все треки | {o['precision']} | {o['recall']} | {o['f1']} | {o['fpr']} |")
                for t in TRACKS:
                    m = r[t]
                    lines.append(f"| ≥{lvl} | {t} | {m['precision']} | {m['recall']} | {m['f1']} | |")
                for lang, m in r["by_lang"].items():
                    lines.append(f"| ≥{lvl} | язык {lang} | {m['precision']} | {m['recall']} | {m['f1']} | {m.get('fpr', '')} |")
            if mode.startswith("blind:"):
                med = res["medium"]
                lines += ["", "Ошибки на слепом наборе (≥medium), показаны как есть:"]
                lines += [f"- ложное срабатывание: {t}" for t in med["false_positives"]]
                lines += [f"- пропуск: {t}" for t in med["missed"]]
            if "image_posts" in res:
                ip = res["image_posts"]["medium"]
                lines.append(f"\nПосты с изображениями (≥medium): precision {ip['precision']}, recall {ip['recall']}, FPR {ip.get('fpr')}.")
                lines.append(f"Скорость полного пайплайна (с OCR): {res['throughput_posts_per_sec']} постов/с на 1 CPU.")
            lines.append("")
    lines += ["## История слепых замеров (≥medium)", "", "| Набор | Когда | Precision | Recall | FPR |", "|---|---|---|---|---|"]
    lines += [f"| {name} | {when} | {p} | {r} | {f} |" for name, when, p, r, f in BLIND_HISTORY]
    for mode, variants in report["results"].items():
        if mode.startswith("blind:"):
            o = variants["rules+ml"]["medium"]["overall"]
            ci = (wilson(o["tp"], o["tp"] + o["fp"]), wilson(o["tp"], o["tp"] + o["fn"]), wilson(o["fp"], o["fp"] + o["tn"]))
            lines.append(f"| {mode[6:]} | сейчас | {o['precision']} ({ci[0][0]}–{ci[0][1]}) | {o['recall']} ({ci[1][0]}–{ci[1][1]}) "
                         f"| {o['fpr']} ({ci[2][0]}–{ci[2][1]}) |")
    lines += ["", "В скобках 95% интервал Уилсона.", ""]
    lines.append("")
    lines += ["Синтетика сгенерирована нашим генератором, поэтому цифры оптимистичны; главное в них — FPR на "
              "трудных легальных примерах (бесплатные конкурсы, депозиты, предупреждения, личные переводы, сборы)."]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, default=Path("data/synth/posts.jsonl"))
    ap.add_argument("--model", type=Path, default=Path("models/clf.joblib"))
    ap.add_argument("--mode", choices=["text", "full", "both"], default="both")
    ap.add_argument("--handwritten", type=Path, nargs="*",
                    default=dev_paths(),
                    help="ручные dev-наборы, не из генератора: на них правила настраиваются")
    ap.add_argument("--blind", type=Path, nargs="*",
                    default=[Path("eval/handwritten_blind_v10.jsonl")],
                    help="слепые наборы: написаны до правок агентом без доступа к коду, на них только измеряем")
    ap.add_argument("--report", type=Path, default=Path("reports/eval.json"))
    ap.add_argument("--markdown", type=Path, default=Path("docs/metrics.md"))
    args = ap.parse_args()
    posts = read_jsonl(args.data)
    test = [p for p in posts if p.split == "test"]
    settings = Settings(model_path=args.model)
    report = {"dataset": {"posts": len(posts), "test": len(test), "test_labels": dict(Counter(p.label for p in test))},
              "results": {}}
    if args.mode in ("text", "both"):
        report["results"]["text"] = eval_text(posts, settings, args.model)
    for kind, paths in (("dev", args.handwritten), ("blind", args.blind)):
        for path in paths:
            if path.exists():
                report["results"][f"{kind}:{path.stem}"] = eval_text(load_handwritten(path), settings, args.model)
    if args.mode in ("full", "both"):
        report["results"]["full"] = eval_full(posts, args.data.parent, args.model)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    args.markdown.write_text(to_markdown(report), encoding="utf-8")
    print(to_markdown(report))


if __name__ == "__main__":
    main()
