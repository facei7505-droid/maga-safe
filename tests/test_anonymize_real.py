"""Обезличивание реальных постов: телефоны, карты, IBAN и каналы заменены, связи между постами сохранены."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import anonymize_real  # noqa: E402
from anonymize_real import Anonymizer, luhn_complete  # noqa: E402


def luhn_ok(number: str) -> bool:
    digits = [int(c) for c in number]
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
    return total % 10 == 0


def test_phone_is_replaced_consistently_with_same_format():
    anon = Anonymizer()
    first = anon.text("Пиши +7 747 318 52 64 или 8(747)318-52-64")
    assert "318" not in first
    phones = re.findall(r"\+7 700 \d{3} \d{2} \d{2}", first)
    assert len(phones) == 2 and phones[0] == phones[1]  # один и тот же номер в двух записях


def test_card_is_replaced_with_luhn_valid_fake():
    out = Anonymizer().text("Перевод на 4400 4301 2345 6789")
    card = re.search(r"\d{4} \d{4} \d{4} \d{4}", out).group(0)
    assert card != "4400 4301 2345 6789" and card.startswith("4400 43") and luhn_ok(card.replace(" ", ""))
    assert luhn_ok(luhn_complete("440043123456789"))


def test_iban_and_channels_aliased_but_bots_kept():
    anon = Anonymizer()
    out = anon.text("IBAN KZ86125KZT5004100100 • зеркало t.me/s/Real_Casino_KZ и @real_casino_kz, бот @win_pay_bot")
    assert "KZ86125" not in out and re.search(r"KZ00\d{16}", out)
    assert "t.me/channel_01" in out and "@channel_01" in out  # один канал — один псевдоним
    assert "@win_pay_bot" in out


def test_cli_joins_labels_with_raw_and_hides_channel(tmp_path, monkeypatch):
    labels = tmp_path / "labels.jsonl"
    raw = tmp_path / "raw.jsonl"
    out = tmp_path / "real.jsonl"
    labels.write_text(json.dumps({"id": "r1", "label": "casino", "lang": "ru"}) + "\n", encoding="utf-8")
    raw.write_text(json.dumps({"id": "r1", "channel": "secret_casino", "text": "Звони +7 701 111 22 33"}) + "\n",
                   encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["anonymize_real", "--labels", str(labels), "--raw", str(raw), "--out", str(out)])
    assert anonymize_real.main() == 0
    row = json.loads(out.read_text(encoding="utf-8"))
    assert row == {"id": "r1", "label": "casino", "lang": "ru", "channel": "channel_01", "text": row["text"]}
    assert "111 22 33" not in row["text"] and "secret" not in out.read_text(encoding="utf-8")
