"""Проверка разметки человеком (pruf/audit.py).

1) Выборка и страница для эксперта (метки ИИ не показываются):
   python scripts/human_audit.py sample --n 120 --out audit/round1
   → audit/round1.html (отправить эксперту) и audit/round1.key.json (оставить у себя)
2) Эксперт присылает pruf-audit-answers.json. Согласие с ИИ-разметкой:
   python scripts/human_audit.py score --key audit/round1.key.json --answers pruf-audit-answers.json --report docs/audit.md
По умолчанию берутся все наборы eval/*.jsonl, в том числе реальные посты, если они есть.
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pruf.audit import agreement, answer_key, labeling_page, read_sets, report_markdown, stratified_sample
from pruf.config import ROOT


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample")
    s.add_argument("--n", type=int, default=120)
    s.add_argument("--sets", type=Path, nargs="*", default=sorted((ROOT / "eval").glob("*.jsonl")))
    s.add_argument("--out", type=Path, default=Path("audit/round1"))
    s.add_argument("--seed", type=int, default=2026)
    c = sub.add_parser("score")
    c.add_argument("--key", type=Path, required=True)
    c.add_argument("--answers", type=Path, required=True)
    c.add_argument("--report", type=Path)
    args = ap.parse_args()

    if args.cmd == "sample":
        sample = stratified_sample(read_sets(args.sets), args.n, args.seed)
        salt = secrets.token_hex(8)  # без соли номер поста можно сопоставить с открытыми наборами
        args.out.parent.mkdir(parents=True, exist_ok=True)
        page, key = args.out.with_suffix(".html"), args.out.with_suffix(".key.json")
        page.write_text(labeling_page(sample, salt), encoding="utf-8")
        key.write_text(json.dumps(answer_key(sample, salt), ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{len(sample)} постов → {page} (эксперту), ключ с метками ИИ → {key} (не отправлять)")
        return 0

    answers = json.loads(args.answers.read_text(encoding="utf-8"))
    key = json.loads(args.key.read_text(encoding="utf-8"))
    result = agreement(answers["answers"], key)
    report = report_markdown(result, answers.get("expert") or "эксперт")
    if args.report:
        args.report.write_text(report, encoding="utf-8")
        print(f"отчёт → {args.report}")
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
