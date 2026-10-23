"""Нагрузочный тест индексов реестра ПРУФ на ~1 млн элементов.

Что меряем:
  * ImageIndex (PDQ, 256 бит): загрузка, память, задержка запроса p50/p95/p99 при пороге PDQ_LOOSE,
    полнота поиска подсаженных почти-дубликатов (перевёрнуто 8–40 бит);
  * TextIndex (MinHash 64 × LSH 16 полос): загрузка, память, задержка запроса, полнота для копий
    со сходством ~0.6–0.9, стоимость дозаписи по одному элементу (слияние буфера каждые 4096).
Сигнатуры случайные: нагрузка на индекс та же, а генерация 1 млн настоящих текстов заняла бы часы.

Запуск: python scripts/loadtest.py --n 1000000 --queries 300
"""

from __future__ import annotations

import argparse
import json
import resource
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pruf.registry.hashing import MINHASH_PERM, PDQ_WORDS
from pruf.registry.index import ImageIndex, TextIndex
from pruf.registry.registry import PDQ_LOOSE

SEED = 20261023
TEXT_CHUNK = 100_000


def _rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def _pct(values: list[float]) -> dict[str, float]:
    arr = np.array(values) * 1000
    return {"p50_ms": round(float(np.percentile(arr, 50)), 2), "p95_ms": round(float(np.percentile(arr, 95)), 2),
            "p99_ms": round(float(np.percentile(arr, 99)), 2), "max_ms": round(float(arr.max()), 2)}


def _flip_bits(words: np.ndarray, bits: int, rng: np.random.Generator) -> np.ndarray:
    out = words.copy()
    for pos in rng.choice(PDQ_WORDS * 64, size=bits, replace=False):
        out[pos // 64] ^= np.uint64(1) << np.uint64(pos % 64)
    return out


def bench_images(n: int, queries: int, rng: np.random.Generator) -> dict:
    hashes = rng.integers(0, np.iinfo(np.uint64).max, size=(n, PDQ_WORDS), dtype=np.uint64, endpoint=True)
    index = ImageIndex()
    t0 = time.perf_counter()
    index.add_many(np.arange(n, dtype=np.int64), hashes)
    load_s = time.perf_counter() - t0
    targets = rng.choice(n, size=queries, replace=False)
    lat, found = [], 0
    for i, t in enumerate(targets):
        q = _flip_bits(hashes[t], int(8 + i % 33), rng)
        s = time.perf_counter()
        res = index.query(q, max_distance=PDQ_LOOSE)
        lat.append(time.perf_counter() - s)
        found += any(item_id == t for item_id, _ in res)
    s = time.perf_counter()
    for k in range(200):
        index.add(n + k, hashes[0])
    add_ms = (time.perf_counter() - s) / 200 * 1000
    return {"items": len(index), "load_s": round(load_s, 2), "index_mb": round(hashes.nbytes / 2**20, 1),
            "query": _pct(lat), "recall_near_dup": round(found / queries, 4), "add_one_ms": round(add_ms, 3),
            "threshold": PDQ_LOOSE}


def _perturb(sig: np.ndarray, similarity: float, rng: np.random.Generator) -> np.ndarray:
    out = sig.copy()
    change = rng.choice(MINHASH_PERM, size=int(round(MINHASH_PERM * (1 - similarity))), replace=False)
    out[change] = rng.integers(0, np.iinfo(np.uint64).max, size=len(change), dtype=np.uint64, endpoint=True)
    return out


def bench_texts(n: int, queries: int, rng: np.random.Generator) -> dict:
    index = TextIndex()
    keep_rows = rng.choice(n, size=queries, replace=False)
    kept: dict[int, np.ndarray] = {}
    t0 = time.perf_counter()
    for start in range(0, n, TEXT_CHUNK):
        stop = min(n, start + TEXT_CHUNK)
        sigs = rng.integers(0, np.iinfo(np.uint64).max, size=(stop - start, MINHASH_PERM), dtype=np.uint64, endpoint=True)
        for r in keep_rows[(keep_rows >= start) & (keep_rows < stop)]:
            kept[int(r)] = sigs[r - start].copy()
        index.add_many(np.arange(start, stop, dtype=np.int64), sigs)
    load_s = time.perf_counter() - t0
    by_sim: dict[str, list[int]] = {}
    lat = []
    for i, (row, sig) in enumerate(kept.items()):
        sim = (0.6, 0.7, 0.8, 0.9)[i % 4]
        q = _perturb(sig, sim, rng)
        s = time.perf_counter()
        res = index.query(q)
        lat.append(time.perf_counter() - s)
        by_sim.setdefault(str(sim), []).append(int(any(item_id == row for item_id, _ in res)))
    adds = []
    extra = rng.integers(0, np.iinfo(np.uint64).max, size=(5000, MINHASH_PERM), dtype=np.uint64, endpoint=True)
    for j in range(len(extra)):
        s = time.perf_counter()
        index.add(n + j, extra[j])
        adds.append(time.perf_counter() - s)
    mem = index._sigs.nbytes + sum(k.nbytes + r.nbytes for k, r in zip(index._sorted_keys, index._sorted_rows))
    return {"items": len(index), "load_s": round(load_s, 2), "index_mb": round(mem / 2**20, 1), "query": _pct(lat),
            "recall_by_similarity": {k: round(sum(v) / len(v), 3) for k, v in by_sim.items()},
            "add_one": _pct(adds)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=1_000_000)
    ap.add_argument("--queries", type=int, default=300)
    ap.add_argument("--out", type=Path, default=Path("reports/loadtest.json"))
    args = ap.parse_args()
    rng = np.random.default_rng(SEED)
    print(f"[load] изображения: {args.n} PDQ…", flush=True)
    images = bench_images(args.n, args.queries, rng)
    print(json.dumps(images, ensure_ascii=False), flush=True)
    print(f"[load] тексты: {args.n} MinHash…", flush=True)
    texts = bench_texts(args.n, args.queries, rng)
    print(json.dumps(texts, ensure_ascii=False), flush=True)
    report = {"n": args.n, "queries": args.queries, "cpu_threads": 1, "images": images, "texts": texts,
              "peak_rss_mb": round(_rss_mb(), 1)}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(f"[load] пиковая память процесса {report['peak_rss_mb']} МБ → {args.out}")


if __name__ == "__main__":
    main()
