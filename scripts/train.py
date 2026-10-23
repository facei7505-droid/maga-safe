"""Обучить ML-классификатор на train-сплите синтетики и сохранить в models/clf.joblib."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pruf.detect.classifier import TrackClassifier  # noqa: E402
from pruf.synth.generator import read_jsonl  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", type=Path, default=Path("data/synth/posts.jsonl"))
    ap.add_argument("--out", type=Path, default=Path("models/clf.joblib"))
    args = ap.parse_args()
    train = [p for p in read_jsonl(args.data) if p.split == "train"]
    clf = TrackClassifier.train([p.text for p in train], [p.label for p in train])
    clf.save(args.out)
    print(f"обучено на {len(train)} постах → {args.out}")


if __name__ == "__main__":
    main()
