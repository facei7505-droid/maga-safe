"""Манифест реальных наборов: состав и хэши без постов, сверка ловит подменённый файл."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import real_manifest  # noqa: E402


def test_manifest_describes_sets_and_verify_catches_changes(tmp_path: Path) -> None:
    # Arrange
    rows = [{"id": "r1", "label": "pyramid", "lang": "kk", "text": "секрет"}, {"id": "r2", "label": "legit", "lang": "ru", "text": "x"}]
    path = tmp_path / "real_v9.jsonl"
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")

    # Act
    manifest = real_manifest.build(tmp_path)

    # Assert: текстов в манифесте нет, состав есть
    assert manifest["real_v9"]["posts"] == 2 and manifest["real_v9"]["labels"] == {"legit": 1, "pyramid": 1}
    assert "секрет" not in json.dumps(manifest, ensure_ascii=False)
    assert real_manifest.verify(tmp_path, manifest) == []
    path.write_text(path.read_text(encoding="utf-8").replace("legit", "casino"), encoding="utf-8")
    assert "хэш не совпадает" in real_manifest.verify(tmp_path, manifest)[0]
    assert "файла нет" in real_manifest.verify(tmp_path, {"real_v1": {"sha256": "0"}})[0]
