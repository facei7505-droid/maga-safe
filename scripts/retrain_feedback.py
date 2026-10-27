"""Еженедельное дообучение на решениях аналитика с проверкой «чемпион и претендент» (pruf/detect/feedback_training.py).

Без --apply только отчёт. С --apply модель заменяется, если претендент прошёл ворота; прежняя
сохраняется рядом (.prev.joblib), чтобы откатиться одной командой. Сервер подхватит новую модель
после перезапуска. В отчёте и признаки, которые чаще всего оспаривают в боте: их правит человек.

Запуск: PRUF_DATA_DIR=data python scripts/retrain_feedback.py [--apply]
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pruf.config import Settings
from pruf.detect.classifier import TrackClassifier
from pruf.detect.feedback_training import (
    MIN_FEEDBACK,
    analyst_rows,
    compare,
    dev_rows,
    in_holdout,
    train_challenger,
)
from pruf.detect.training import dev_paths
from pruf.graph.builder import CaseGraph
from pruf.storage.db import Database
from pruf.synth.generator import Generator

DISPUTED_TOP = 10


def _fmt(name: str, s) -> str:
    return f"  {name:<26} полнота {s.recall:.3f}  ложные тревоги {s.fpr:.3f}  ошибок {s.errors}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="заменить модель, если претендент прошёл проверку")
    ap.add_argument("--min-feedback", type=int, default=MIN_FEEDBACK)
    args = ap.parse_args()

    settings = Settings(anthropic_api_key="")  # дообучение не тратит API
    db = Database(settings.db_path)
    graph = CaseGraph(db)
    graph.ensure(version=0, force=True)
    rows = analyst_rows(db, graph)
    print(f"решений аналитика: {len(rows)} постов ({sum(r.label == 'legit' for r in rows)} легальных)")

    disputed = [d for d in db.disputed_features() if d["reporters"] >= 2][:DISPUTED_TOP]
    if disputed:
        print("\nпризнаки, которые оспаривают в боте (ревью словаря вручную):")
        for d in disputed:
            print(f"  {d['feature_id']:<28} людей {d['reporters']:>3}  доля споров {d['rate']:.0%}  {d['label']}")

    if len(rows) < args.min_feedback:
        print(f"\nмало решений для дообучения (нужно от {args.min_feedback}): модель не меняется")
        return 0
    train = [r for r in rows if not in_holdout(r.post_id)]
    holdout = [r for r in rows if in_holdout(r.post_id)]
    synthetic = ((p.text, p.label) for p in Generator(seed=42).dataset(image_rate=0.0) if p.split == "train")
    challenger = train_challenger(synthetic, train)
    champion = TrackClassifier.load(settings.model_path)
    verdict = compare(settings, champion, challenger, holdout, dev_rows(dev_paths()))

    print(f"\nобучение: {len(train)} решений, отложено для проверки: {len(holdout)}")
    if verdict.champion_holdout:
        print(_fmt("чемпион, решения", verdict.champion_holdout))
        print(_fmt("претендент, решения", verdict.challenger_holdout))
        print(_fmt("чемпион, dev-наборы", verdict.champion_dev))
        print(_fmt("претендент, dev-наборы", verdict.challenger_dev))
        print(f"  модель без правил, ошибок на решениях: чемпион {verdict.champion_ml_errors}, претендент {verdict.challenger_ml_errors}")
    print(("\n✓ претендент принят: " if verdict.accept else "\n✗ претендент не принят: ") + verdict.reason)

    if args.apply and verdict.accept:
        target = settings.model_path
        if target.exists():
            shutil.copyfile(target, target.with_suffix(".prev.joblib"))
        challenger.save(target)
        db.audit("retrain", "model_swap", f"{len(train)}+{len(holdout)}")
        print(f"модель заменена: {target} (прежняя: {target.with_suffix('.prev.joblib').name}); перезапустите сервер")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
