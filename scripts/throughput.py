"""Пропускная способность ПРУФ на одном процессе: весь путь поста и задержка API для банка и расширения.

Что меряем:
  * приём: синтетические посты (текст, часть с картинкой) через Pruf.ingest — нормализация, детектор
    (правила + ML), реестр картинок и текстов, реквизиты, запись в SQLite. LLM-арбитр выключен: он
    зовётся только в спорной зоне, его цена считается отдельно. OCR по умолчанию выключен (--ocr включает);
  * сборка графа кейсов по всей базе;
  * задержка API в процессе (TestClient): POST /api/v1/bank/check и POST /api/v1/inspect.

Запуск: PRUF_DEV_MODE=1 python scripts/throughput.py --posts 2000 --requests 500
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import shutil
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("PRUF_DEV_MODE", "1")
os.environ.pop("WEB_CONCURRENCY", None)

from fastapi.testclient import TestClient  # noqa: E402

from pruf.api.app import create_app  # noqa: E402
from pruf.config import Settings  # noqa: E402
from pruf.graph.builder import CaseGraph  # noqa: E402
from pruf.pipeline import Pruf, Submission, Upload  # noqa: E402
from pruf.synth.generator import Generator  # noqa: E402

POSTS_PER_CAMPAIGN = 10
LEGIT_SHARE = 0.6  # в живом потоке легальных постов больше, чем схем
KZ_CHANNELS = 5_000  # оценка для слайда: каналы с аудиторией в Казахстане под наблюдением
POSTS_PER_CHANNEL_DAY = 20


def _rss_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def _pct(values: list[float]) -> dict[str, float]:
    arr = np.array(values) * 1000
    return {"p50_ms": round(float(np.percentile(arr, 50)), 2), "p95_ms": round(float(np.percentile(arr, 95)), 2),
            "p99_ms": round(float(np.percentile(arr, 99)), 2)}


def make_posts(n: int, tmp: Path) -> list:
    legit = int(n * LEGIT_SHARE)
    per_track = max(1, -(-(n - legit) // (3 * POSTS_PER_CAMPAIGN)))  # с запасом, лишнее отрезаем
    posts = Generator(seed=11, out_dir=tmp).dataset(campaigns_per_track=per_track, posts_per_campaign=POSTS_PER_CAMPAIGN,
                                                    legit=legit, image_rate=0.3)
    return sorted(posts, key=lambda p: p.posted_at)[:n]


def bench_ingest(pruf: Pruf, posts: list, tmp: Path) -> dict:
    times = []
    t0 = time.perf_counter()
    for p in posts:
        uploads = (Upload((tmp / p.image).read_bytes(), "image", "jpg"),) if p.image else ()
        start = time.perf_counter()
        pruf.ingest(Submission(text=p.text, uploads=uploads, source="bench", channel=p.channel, posted_at=p.posted_at,
                               external_id=p.id), allow_llm=False)
        times.append(time.perf_counter() - start)
    total = time.perf_counter() - t0
    return {"posts": len(posts), "with_image": sum(1 for p in posts if p.image), "seconds": round(total, 1),
            "posts_per_minute": round(len(posts) / total * 60), **_pct(times)}


def bench_graph(pruf: Pruf) -> dict:
    start = time.perf_counter()
    graph = CaseGraph(pruf.db)
    graph.ensure(pruf.version, force=True)
    return {"cases": len(graph.cases()), "seconds": round(time.perf_counter() - start, 2)}


def bench_api(settings: Settings, pruf: Pruf, requests: int, phones: list[str]) -> dict:
    out = {}
    with TestClient(create_app(settings, pruf=pruf)) as client:
        client.post("/api/v1/inspect", json={"requisites": phones[:1]})  # прогрев индексов расширения
        for name, path, body in (("bank_check", "/api/v1/bank/check", lambda ph: {"value": ph}),
                                 ("inspect", "/api/v1/inspect", lambda ph: {"requisites": [ph], "cues": ["giveaway", "kaspi_transfer"]})):
            times = []
            for i in range(requests):
                start = time.perf_counter()
                res = client.post(path, json=body(phones[i % len(phones)]))
                times.append(time.perf_counter() - start)
                if res.status_code != 200:
                    raise SystemExit(f"{path}: HTTP {res.status_code}")
            out[name] = {"requests": requests, **_pct(times)}
    return out


def kz_estimate(posts_per_minute: float) -> dict:
    per_day = KZ_CHANNELS * POSTS_PER_CHANNEL_DAY
    need = per_day / (24 * 60)
    return {"channels": KZ_CHANNELS, "posts_per_day": per_day, "needed_posts_per_minute": round(need),
            "headroom_x": round(posts_per_minute / need, 1)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--posts", type=int, default=2000)
    ap.add_argument("--requests", type=int, default=500)
    ap.add_argument("--ocr", action="store_true", help="с OCR картинок (медленнее, нужен tesseract)")
    ap.add_argument("--out", type=Path, default=Path("reports/throughput.json"))
    args = ap.parse_args()
    work = Path(tempfile.mkdtemp(prefix="pruf_bench_"))
    try:
        settings = Settings(data_dir=work / "data", anthropic_api_key="", resolve_links=False, rate_limit_per_minute=10**9)
        pruf = Pruf(settings, ocr_enabled=args.ocr)
        posts = make_posts(args.posts, work / "synth")
        ingest = bench_ingest(pruf, posts, work / "synth")
        print(json.dumps({"ingest": ingest}, ensure_ascii=False), flush=True)
        graph = bench_graph(pruf)
        print(json.dumps({"graph": graph}, ensure_ascii=False), flush=True)
        phones = sorted({r["display"] for r in pruf.db.all_post_requisites() if r["kind"] == "phone"}) or ["+77019998877"]
        api = bench_api(settings, pruf, args.requests, phones)
        print(json.dumps({"api": api}, ensure_ascii=False), flush=True)
        report = {"ingest": ingest, "graph": graph, "api": api, "ocr": args.ocr, "llm": "выключен (только спорная зона)",
                  "cpu": os.cpu_count(), "peak_rss_mb": round(_rss_mb()), "kazakhstan": kz_estimate(ingest["posts_per_minute"])}
    finally:
        shutil.rmtree(work, ignore_errors=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report["kazakhstan"], ensure_ascii=False))


if __name__ == "__main__":
    main()
