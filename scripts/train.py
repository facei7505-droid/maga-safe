"""Обучить ML-классификатор на train-сплите синтетики и ручных dev-наборах, сохранить в models/clf.joblib."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pruf.detect.classifier import TrackClassifier
from pruf.detect.training import training_rows
from pruf.synth.generator import read_jsonl


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, default=Path("data/synth/posts.jsonl"))
    ap.add_argument("--out", type=Path, default=Path("models/clf.joblib"))
    args = ap.parse_args()
    train = [p for p in read_jsonl(args.data) if p.split == "train"]
    texts, labels = training_rows((p.text, p.label) for p in train)
    clf = TrackClassifier.train(texts, labels)
    clf.save(args.out)
    print(f"обучено на {len(texts)} примерах ({len(train)} синтетических) → {args.out}")


if __name__ == "__main__":
    main()
