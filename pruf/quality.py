"""Замер качества на свежих реальных постах для карточки «Как мы мерили» в дашборде.

Сами посты в git не лежат, поэтому цифры записаны здесь, а тест сверяет их с таблицей в README.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pruf.detect.prod_model import MANIFEST_FILE, PROD_DIR, _sha256

QUALITY: dict[str, Any] = {
    "set": "real_v4",
    "posts": 416,
    "channels": 24,
    "labels": "два независимых разметчика-ИИ, каппа 0,95",
    "rows": [
        {"name": "Модель, обученная с реальными постами real_v1–v3", "precision": 0.92, "recall": 0.83, "fpr": 0.031, "main": True},
        {"name": "Модель без реальных постов", "precision": 0.86, "recall": 0.77, "fpr": 0.055},
        {"name": "Только правила", "precision": 0.90, "recall": 0.56, "fpr": 0.027},
    ],
}


@lru_cache(maxsize=4)
def _model_info(model_path: Path, mtime: float) -> dict[str, Any]:
    manifest_path = PROD_DIR / MANIFEST_FILE
    if not model_path.exists() or not manifest_path.exists():
        return {"prod": False, "real_posts": 0, "trained_at": None}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("sha256") != _sha256(model_path):
        return {"prod": False, "real_posts": 0, "trained_at": None}
    return {"prod": True, "real_posts": int(manifest.get("real_posts", 0)), "trained_at": manifest.get("trained_at")}


def model_info(model_path: Path) -> dict[str, Any]:
    """Стоит ли на сервере модель из models/prod (сверка по хэшу) и на скольких реальных постах она обучена."""
    try:
        mtime = model_path.stat().st_mtime
    except OSError:
        mtime = 0.0
    try:
        return _model_info(model_path, mtime)
    except (OSError, ValueError):
        return {"prod": False, "real_posts": 0, "trained_at": None}


def quality_report(model_path: Path) -> dict[str, Any]:
    return {**QUALITY, "model": model_info(model_path)}
