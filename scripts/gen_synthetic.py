"""Сгенерировать синтетический датасет: data/synth/posts.jsonl + data/synth/images/."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pruf.synth.generator import Generator, write_jsonl  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=Path("data/synth"))
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--campaigns", type=int, default=9, help="кампаний на трек")
    ap.add_argument("--posts", type=int, default=18, help="постов на кампанию")
    ap.add_argument("--legit", type=int, default=700)
    ap.add_argument("--image-rate", type=float, default=0.35)
    args = ap.parse_args()
    gen = Generator(seed=args.seed, out_dir=args.out)
    posts = gen.dataset(args.campaigns, args.posts, args.legit, args.image_rate)
    write_jsonl(posts, args.out / "posts.jsonl")
    print(f"постов: {len(posts)}, с изображениями: {sum(1 for p in posts if p.image)}")
    print("метки:", dict(Counter(p.label for p in posts)))
    print("сплит:", dict(Counter((p.split, p.label) for p in posts)))
    print("языки:", dict(Counter(p.lang for p in posts)))


if __name__ == "__main__":
    main()
