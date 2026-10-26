"""Модель для прода, обученная там, где лежат реальные посты.

Реальные посты (eval/real_v*.jsonl) в git не попадают, поэтому Docker на Render обучает модель без них и
она слабее, чем в замерах. Решение: обучить модель на машине с реальными постами (scripts/train.py --publish)
и положить в git только саму модель. Это TF-IDF по символьным 2–5-граммам с min_df=2: кусок текста попадает
в словарь, только если встречается хотя бы в двух постах, восстановить пост из модели нельзя.

Рядом с моделью лежит манифест: SHA-256 файла, версия scikit-learn, на каких наборах и скольких примерах
обучено. При сборке (scripts/install_model.py) модель ставится, только если хэш сошёлся, версия scikit-learn
та же (pickle между версиями не переносим) и модель загружается и предсказывает. Иначе сборка обучает
модель сама, как раньше: прод не падает, а в логе сборки видно почему.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import sklearn

from pruf.config import ROOT
from pruf.detect.classifier import TrackClassifier
from pruf.detect.training import DEV_SETS, read_handwritten

PROD_DIR = ROOT / "models" / "prod"
MODEL_FILE = "clf.joblib"
MANIFEST_FILE = "clf.json"
REAL_PREFIX = "real_"
SMOKE_TEXT = "розыгрыш айфона участие 2000 тг переводите на каспи"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _minor(version: str) -> str:
    return ".".join(version.split(".")[:2])


def missing_sets(eval_dir: Path) -> list[str]:
    return [name for name in DEV_SETS if not (eval_dir / f"{name}.jsonl").exists()]


def publish(clf: TrackClassifier, synthetic_rows: int, eval_dir: Path, out_dir: Path = PROD_DIR) -> dict:
    """Сохранить модель и манифест. Без всех dev-наборов (в том числе реальных) не публикуем:
    иначе в git уйдёт модель не лучше той, что Docker и так обучает сам."""
    missing = missing_sets(eval_dir)
    if missing:
        raise ValueError("нет наборов: " + ", ".join(missing) + ". Модель для прода обучается только на всех наборах")
    out_dir.mkdir(parents=True, exist_ok=True)
    model = out_dir / MODEL_FILE
    clf.save(model)
    sets = {name: len(read_handwritten(eval_dir / f"{name}.jsonl")) for name in DEV_SETS}
    manifest = {
        "sha256": _sha256(model),
        "sklearn": sklearn.__version__,
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "synthetic_rows": synthetic_rows,
        "sets": sets,
        "real_posts": sum(n for name, n in sets.items() if name.startswith(REAL_PREFIX)),
    }
    (out_dir / MANIFEST_FILE).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


@dataclass(frozen=True)
class InstallResult:
    installed: bool
    reason: str


def install(target: Path, src_dir: Path = PROD_DIR) -> InstallResult:
    """Поставить опубликованную модель в target, если ей можно доверять; иначе объяснить, почему нет."""
    model, manifest_path = src_dir / MODEL_FILE, src_dir / MANIFEST_FILE
    if not model.exists() or not manifest_path.exists():
        return InstallResult(False, "опубликованной модели нет")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except ValueError:
        return InstallResult(False, "манифест модели не читается")
    if manifest.get("sha256") != _sha256(model):
        return InstallResult(False, "SHA-256 модели не совпадает с манифестом")
    if _minor(str(manifest.get("sklearn", ""))) != _minor(sklearn.__version__):
        return InstallResult(False, f"модель обучена на scikit-learn {manifest.get('sklearn')}, установлен {sklearn.__version__}")
    clf = TrackClassifier.load(model)
    if clf is None:
        return InstallResult(False, "модель не загружается")
    try:
        clf.predict_folded(SMOKE_TEXT)
    except Exception as exc:  # noqa: BLE001 — любая ошибка предсказания значит «не ставим»
        return InstallResult(False, f"модель не предсказывает: {type(exc).__name__}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(model, target)
    return InstallResult(True, f"обучена {manifest.get('trained_at')}, реальных постов: {manifest.get('real_posts', 0)}")
