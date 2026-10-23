"""Индексы почти-дубликатов в памяти, рассчитанные на миллионы элементов.

- ImageIndex: точный поиск по расстоянию Хэмминга между PDQ-хэшами, векторно через numpy
  (4 × uint64 на элемент, 1 млн ≈ 32 МБ, линейный проход занимает десятки миллисекунд).
- TextIndex: MinHash LSH. Ключи полос лежат в отсортированных массивах, поиск через searchsorted;
  новые элементы копятся в буфере и сливаются пачкой.
"""

from __future__ import annotations

import threading

import numpy as np

from pruf.registry.hashing import MINHASH_BANDS, MINHASH_PERM, PDQ_WORDS, band_keys, band_keys_batch

PDQ_MATCH_DISTANCE = 40
TEXT_MATCH_SIMILARITY = 0.55
_GROW = 1024
_MERGE_EVERY = 4096


class ImageIndex:
    def __init__(self) -> None:
        self._hashes = np.zeros((0, PDQ_WORDS), dtype=np.uint64)
        self._ids = np.zeros(0, dtype=np.int64)
        self._size = 0
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return self._size

    def add(self, item_id: int, words: np.ndarray) -> None:
        self.add_many(np.array([item_id], dtype=np.int64), words.reshape(1, PDQ_WORDS))

    def add_many(self, ids: np.ndarray, hashes: np.ndarray) -> None:
        with self._lock:
            need = self._size + len(ids)
            if need > len(self._ids):
                cap = max(need, len(self._ids) * 2, _GROW)
                self._hashes = np.resize(self._hashes, (cap, PDQ_WORDS))
                self._ids = np.resize(self._ids, cap)
            self._hashes[self._size:need] = hashes
            self._ids[self._size:need] = ids
            self._size = need

    def query(self, words: np.ndarray, max_distance: int = PDQ_MATCH_DISTANCE, limit: int = 500) -> list[tuple[int, int]]:
        """Список (id, расстояние) по возрастанию расстояния."""
        with self._lock:
            hashes = self._hashes[:self._size]
            ids = self._ids[:self._size]
            if not self._size:
                return []
            dist = np.bitwise_count(np.bitwise_xor(hashes, words[None, :])).sum(axis=1)
        hit = np.nonzero(dist <= max_distance)[0]
        if hit.size > limit:
            hit = hit[np.argpartition(dist[hit], limit)[:limit]]
        order = hit[np.argsort(dist[hit], kind="stable")]
        return [(int(ids[i]), int(dist[i])) for i in order]


class TextIndex:
    def __init__(self) -> None:
        self._sigs = np.zeros((0, MINHASH_PERM), dtype=np.uint64)
        self._ids = np.zeros(0, dtype=np.int64)
        self._size = 0
        self._sorted_keys: list[np.ndarray] = [np.zeros(0, dtype=np.uint64) for _ in range(MINHASH_BANDS)]
        self._sorted_rows: list[np.ndarray] = [np.zeros(0, dtype=np.int64) for _ in range(MINHASH_BANDS)]
        self._merged = 0  # строк, уже попавших в отсортированные массивы
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return self._size

    def add(self, item_id: int, signature: np.ndarray) -> None:
        self.add_many(np.array([item_id], dtype=np.int64), signature.reshape(1, MINHASH_PERM))

    def add_many(self, ids: np.ndarray, signatures: np.ndarray) -> None:
        with self._lock:
            need = self._size + len(ids)
            if need > len(self._ids):
                cap = max(need, len(self._ids) * 2, _GROW)
                self._sigs = np.resize(self._sigs, (cap, MINHASH_PERM))
                self._ids = np.resize(self._ids, cap)
            self._sigs[self._size:need] = signatures
            self._ids[self._size:need] = ids
            self._size = need
            if self._size - self._merged >= _MERGE_EVERY:
                self._merge()

    def _merge(self) -> None:
        """Влить буфер в отсортированные массивы: сортируется только новый кусок, вставка за O(N)."""
        start = self._merged
        keys = band_keys_batch(self._sigs[start:self._size])
        rows = np.arange(start, self._size, dtype=np.int64)
        for b in range(MINHASH_BANDS):
            order = np.argsort(keys[:, b], kind="stable")
            new_keys, new_rows = keys[order, b], rows[order]
            pos = np.searchsorted(self._sorted_keys[b], new_keys, side="right")
            self._sorted_keys[b] = np.insert(self._sorted_keys[b], pos, new_keys)
            self._sorted_rows[b] = np.insert(self._sorted_rows[b], pos, new_rows)
        self._merged = self._size

    def query(self, signature: np.ndarray, min_similarity: float = TEXT_MATCH_SIMILARITY, limit: int = 500) -> list[tuple[int, float]]:
        keys = band_keys(signature)
        with self._lock:
            rows: set[int] = set()
            for b in range(MINHASH_BANDS):
                sk = self._sorted_keys[b]
                lo, hi = np.searchsorted(sk, keys[b], "left"), np.searchsorted(sk, keys[b], "right")
                rows.update(self._sorted_rows[b][lo:hi].tolist())
            if self._merged < self._size:
                pending = self._sigs[self._merged:self._size]
                pkeys = band_keys_batch(pending)
                hit = np.nonzero((pkeys == keys[None, :]).any(axis=1))[0]
                rows.update((hit + self._merged).tolist())
            if not rows:
                return []
            idx = np.fromiter(rows, dtype=np.int64)
            sims = (self._sigs[idx] == signature[None, :]).mean(axis=1)
            ids = self._ids[idx]
        keep = np.nonzero(sims >= min_similarity)[0]
        order = keep[np.argsort(-sims[keep], kind="stable")][:limit]
        return [(int(ids[i]), float(sims[i])) for i in order]

