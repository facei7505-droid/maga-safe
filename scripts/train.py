"""Обучить ML-классификатор на train-сплите синтетики и ручных dev-наборах, сохранить в models/clf.joblib.

--publish: модель для прода в models/prod (с манифестом), только если есть все наборы, включая реальные
посты eval/real_v*.jsonl, которых нет в git. Запускать там, где они лежат, и закоммитить models/prod:
сборка Docker поставит эту модель вместо обученной без реальных постов (pruf/detect/prod_model.py).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pruf.config import ROOT
from pruf.detect.classifier import TrackClassifier
from pruf.detect.prod_model import missing_sets, publish
from pruf.detect.training import training_rows
from pruf.synth.generator import read_jsonl


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, default=Path("data/synth/posts.jsonl"))
    ap.add_argument("--out", type=Path, default=Path("models/clf.joblib"))
    ap.add_argument("--publish", action="store_true", help="модель для прода в models/prod: нужны все наборы, включая реальные")
    args = ap.parse_args()
    if args.publish and missing_sets(ROOT / "eval"):
        sys.exit("--publish: нет наборов " + ", ".join(missing_sets(ROOT / "eval")) + " в eval/")
    train = [p for p in read_jsonl(args.data) if p.split == "train"]
    texts, labels = training_rows((p.text, p.label) for p in train)
    clf = TrackClassifier.train(texts, labels)
    if args.publish:
        manifest = publish(clf, len(train), ROOT / "eval")
        print(f"модель для прода: {len(texts)} примеров, реальных постов {manifest['real_posts']}, "
              f"scikit-learn {manifest['sklearn']} → models/prod (закоммитьте clf.joblib и clf.json)")
        return
    clf.save(args.out)
    print(f"обучено на {len(texts)} примерах ({len(train)} синтетических) → {args.out}")


if __name__ == "__main__":
    main()
