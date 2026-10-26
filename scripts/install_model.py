"""Сборка Docker: поставить модель из models/prod (обучена с реальными постами), если ей можно доверять.

Код возврата 0 — модель поставлена; 1 — нет, сборка обучает модель сама (scripts/train.py).
Запуск: python scripts/install_model.py --target models/clf.joblib
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pruf.detect.prod_model import install


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", type=Path, default=Path("models/clf.joblib"))
    args = ap.parse_args()
    result = install(args.target)
    print(("модель для прода поставлена: " if result.installed else "модель для прода не поставлена: ") + result.reason)
    return 0 if result.installed else 1


if __name__ == "__main__":
    sys.exit(main())
