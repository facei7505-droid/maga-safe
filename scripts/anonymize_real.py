"""Обезличивание реальных постов перед публикацией в репозитории.

Настоящие телефоны и карты заменяются вымышленными того же формата (карты проходят проверку Луна),
одинаково по всему набору, чтобы связи между постами сохранились. Имена каналов и @упоминания
заменяются на @channel_NN. Соответствие не сохраняется.

Запуск: python scripts/anonymize_real.py --labels labels.jsonl --raw key.jsonl --out eval/real_v1.jsonl
labels.jsonl: id, label, lang; raw.jsonl: id, text, channel.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

PHONE_RE = re.compile(r"(?:\+7|(?<!\d)8)[\s\-()]*7\d{2}[\s\-()]*[\d*]{3}[\s\-]*[\d*]{2}[\s\-]*[\d*]{2}(?!\d)")
CARD_RE = re.compile(r"(?<!\d)\d{4}[\s\-]?\d{4}[\s\-]?\d{4}[\s\-]?\d{4}(?!\d)")
IBAN_RE = re.compile(r"\bKZ\d{2}[A-Z0-9]{13,16}\b", re.IGNORECASE)
CHANNEL_RE = re.compile(r"(?:https?://)?(?:t\.me|telegram\.me)/(?:s/)?([A-Za-z][A-Za-z0-9_]{3,31})|@([A-Za-z][A-Za-z0-9_]{3,31})")


def _digits(seed: str, n: int) -> str:
    h = hashlib.sha256(seed.encode()).hexdigest()
    return "".join(str(int(c, 16) % 10) for c in h)[:n]


def luhn_complete(prefix: str) -> str:
    total = 0
    for i, ch in enumerate(reversed(prefix)):
        d = int(ch)
        if i % 2 == 0:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
    return prefix + str((10 - total % 10) % 10)


class Anonymizer:
    def __init__(self) -> None:
        self.channels: dict[str, str] = {}

    def channel(self, name: str) -> str:
        key = name.lower()
        if key not in self.channels:
            self.channels[key] = f"channel_{len(self.channels) + 1:02d}"
        return self.channels[key]

    def text(self, text: str) -> str:
        text = PHONE_RE.sub(lambda m: self._phone(m.group(0)), text)
        text = CARD_RE.sub(lambda m: self._card(m.group(0)), text)
        text = IBAN_RE.sub(lambda m: "KZ00" + _digits(m.group(0), 16), text)
        return CHANNEL_RE.sub(self._channel_ref, text)

    def _phone(self, raw: str) -> str:
        d = _digits("phone" + re.sub(r"\D", "", raw)[-10:], 7)  # +7 и 8 впереди — один номер
        return f"+7 700 {d[:3]} {d[3:5]} {d[5:]}"

    def _card(self, raw: str) -> str:
        body = luhn_complete("440043" + _digits("card" + re.sub(r"\D", "", raw), 9))
        return " ".join(body[i:i + 4] for i in range(0, 16, 4))

    def _channel_ref(self, m: re.Match[str]) -> str:
        name = m.group(1) or m.group(2)
        if name.lower().endswith("bot"):
            return m.group(0) if m.group(2) else f"t.me/{name}"
        alias = self.channel(name)
        return f"t.me/{alias}" if m.group(1) else f"@{alias}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--labels", type=Path, required=True)
    ap.add_argument("--raw", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    raw = {r["id"]: r for r in map(json.loads, args.raw.read_text(encoding="utf-8").splitlines()) if r}
    anon = Anonymizer()
    rows = []
    for line in args.labels.read_text(encoding="utf-8").splitlines():
        lab = json.loads(line)
        src = raw[lab["id"]]
        rows.append({"id": lab["id"], "label": lab["label"], "lang": lab["lang"], "channel": anon.channel(src["channel"]),
                     "text": anon.text(src["text"])})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(f"{len(rows)} постов, {len(anon.channels)} каналов → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
