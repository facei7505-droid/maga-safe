"""Манифест реальных наборов: хэши и состав без самих постов.

Реальные посты (eval/real_v*.jsonl) в git не кладём. Манифест коммитится вместо них: по нему видно, на скольких
постах, каких метках и языках сделан каждый замер, а владелец данных или проверяющий с доступом сверяет файлы
командой --verify (хэш совпал — замер сделан на тех же данных).

  python scripts/real_manifest.py            # записать eval/real_manifest.json
  python scripts/real_manifest.py --verify   # сверить файлы в eval/ с манифестом
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "eval" / "real_manifest.json"


def describe(path: Path) -> dict:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "posts": len(rows),
            "labels": dict(sorted(Counter(r["label"] for r in rows).items())),
            "langs": dict(sorted(Counter(r.get("lang", "?") for r in rows).items()))}


def build(eval_dir: Path) -> dict:
    return {p.stem: describe(p) for p in sorted(eval_dir.glob("real_v*.jsonl"))}


def verify(eval_dir: Path, manifest: dict) -> list[str]:
    problems = []
    for name, want in manifest.items():
        path = eval_dir / f"{name}.jsonl"
        if not path.exists():
            problems.append(f"{name}: файла нет")
        elif describe(path)["sha256"] != want["sha256"]:
            problems.append(f"{name}: хэш не совпадает — данные отличаются от тех, на которых сделан замер")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--eval-dir", type=Path, default=ROOT / "eval")
    ap.add_argument("--manifest", type=Path, default=MANIFEST)
    args = ap.parse_args()
    if args.verify:
        problems = verify(args.eval_dir, json.loads(args.manifest.read_text(encoding="utf-8")))
        print("\n".join(problems) or "все реальные наборы совпадают с манифестом")
        return 1 if problems else 0
    manifest = build(args.eval_dir)
    if not manifest:
        print(f"в {args.eval_dir} нет real_v*.jsonl: манифест пишется там, где лежат реальные посты")
        return 1
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(manifest)} наборов, {sum(m['posts'] for m in manifest.values())} постов → {args.manifest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
