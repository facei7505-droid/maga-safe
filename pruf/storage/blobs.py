"""Хранилище файлов по SHA-256 (content-addressed). В пилоте заменяется на S3-совместимое."""

from __future__ import annotations

import re
from pathlib import Path

_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_EXT = frozenset({"jpg", "png", "webp", "ogg", "mp3", "m4a", "wav", "bin"})


class BlobStore:
    def __init__(self, root: Path):
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def path_for(self, sha256: str, ext: str) -> Path:
        if not _SHA_RE.match(sha256) or ext not in ALLOWED_EXT:
            raise ValueError("некорректный ключ blob")
        return self._root / sha256[:2] / f"{sha256}.{ext}"

    def put(self, sha256: str, ext: str, data: bytes) -> Path:
        path = self.path_for(sha256, ext)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(path)
        return path

    def get(self, sha256: str, ext: str) -> bytes | None:
        path = self.path_for(sha256, ext)
        return path.read_bytes() if path.exists() else None
