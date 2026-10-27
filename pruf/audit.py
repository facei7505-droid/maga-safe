"""Проверка разметки человеком: слепая выборка для эксперта и согласие с ИИ-разметкой.

Наборы размечали два независимых ИИ-разметчика (каппа около 0,95). Жюри и партнёр спросят, согласен ли
с этой разметкой человек. Эксперт (юрист, аналитик банка, сотрудник АРРФР) получает офлайн-страницу с
постами без меток, отмечает трек или «не схема» и сохраняет ответы файлом. Здесь же считается каппа Коэна
эксперта против ИИ-разметки и выписываются расхождения.
"""

from __future__ import annotations

import hashlib
import html
import json
import random
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

LABELS = ("lottery", "casino", "pyramid", "legit")
LABEL_TITLES = {"lottery": "Платный / фальшивый розыгрыш", "casino": "Реклама казино или ставок",
                "pyramid": "Финансовая пирамида", "legit": "Не схема", "unsure": "Не уверен"}
UNSURE = "unsure"


@dataclass(frozen=True)
class Item:
    id: str
    text: str
    label: str
    lang: str
    source: str


def read_sets(paths: Iterable[Path]) -> list[Item]:
    items = []
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                items.append(Item(str(row["id"]), row["text"], row["label"], row.get("lang", "?"), path.stem))
    return items


def stratified_sample(items: Sequence[Item], n: int, seed: int = 2026) -> list[Item]:
    """Поровну по меткам и пропорционально языкам внутри метки; порядок перемешан, чтобы метки не угадывались."""
    rng = random.Random(seed)
    by_label: dict[str, list[Item]] = defaultdict(list)
    for item in items:
        by_label[item.label].append(item)
    per_label = max(1, n // max(1, len(by_label)))
    picked: list[Item] = []
    for label in sorted(by_label):
        pool = sorted(by_label[label], key=lambda i: i.id)
        rng.shuffle(pool)
        picked.extend(pool[:per_label])
    rng.shuffle(picked)
    return picked[:n]


def blind_id(item: Item, salt: str) -> str:
    """Номер поста для эксперта: по нему нельзя понять набор и метку."""
    return hashlib.sha256(f"{salt}|{item.source}|{item.id}".encode()).hexdigest()[:10]


def answer_key(sample: Sequence[Item], salt: str) -> dict[str, dict[str, str]]:
    return {blind_id(i, salt): {"label": i.label, "lang": i.lang, "source": i.source, "id": i.id} for i in sample}


def labeling_page(sample: Sequence[Item], salt: str, title: str = "ПРУФ: проверка разметки") -> str:
    """Самодостаточная HTML-страница: без сети и сервера, ответы сохраняются файлом JSON из браузера."""
    options = list(LABEL_TITLES.items())
    cards = []
    for n, item in enumerate(sample, 1):
        bid = blind_id(item, salt)
        radios = "".join(
            f'<label><input type="radio" name="{bid}" value="{value}"> {html.escape(text)}</label>' for value, text in options)
        cards.append(f'<section class="post" data-id="{bid}"><div class="n">{n} / {len(sample)}</div>'
                     f'<p>{html.escape(item.text)}</p><div class="opts">{radios}</div>'
                     f'<input class="note" placeholder="Комментарий (необязательно)" data-note="{bid}"></section>')
    return _PAGE.format(title=html.escape(title), total=len(sample), cards="\n".join(cards))


@dataclass(frozen=True)
class Agreement:
    n: int
    unsure: int
    kappa_scam: float  # схема или нет
    kappa_track: float  # четыре класса
    agree_scam: float
    confusion: dict[str, dict[str, int]]
    disagreements: list[dict[str, str]]


def cohen_kappa(a: Sequence[str], b: Sequence[str]) -> float:
    n = len(a)
    if n == 0:
        return 0.0
    observed = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    expected = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    return 1.0 if expected == 1 else (observed - expected) / (1 - expected)


def agreement(answers: Mapping[str, Mapping[str, str]], key: Mapping[str, Mapping[str, str]]) -> Agreement:
    """answers: {blind_id: {"label": ..., "note": ...}} из страницы; key: answer_key()."""
    rows = [(bid, a["label"], key[bid]) for bid, a in answers.items() if bid in key and a.get("label")]
    unsure = sum(1 for _, label, _ in rows if label == UNSURE)
    rows = [r for r in rows if r[1] != UNSURE]
    human = [label for _, label, _ in rows]
    ai = [k["label"] for _, _, k in rows]
    scam_h = ["scam" if x != "legit" else "legit" for x in human]
    scam_a = ["scam" if x != "legit" else "legit" for x in ai]
    confusion = {t: {h: 0 for h in LABELS} for t in LABELS}
    for h, t in zip(human, ai):
        confusion[t][h] += 1
    disagreements = [{"id": k["id"], "source": k["source"], "ai": k["label"], "human": label,
                      "note": answers[bid].get("note", "")} for bid, label, k in rows if label != k["label"]]
    return Agreement(n=len(rows), unsure=unsure, kappa_scam=round(cohen_kappa(scam_h, scam_a), 3),
                     kappa_track=round(cohen_kappa(human, ai), 3),
                     agree_scam=round(sum(x == y for x, y in zip(scam_h, scam_a)) / len(rows), 3) if rows else 0.0,
                     confusion=confusion, disagreements=disagreements)


def report_markdown(result: Agreement, expert: str) -> str:
    lines = [f"# Проверка разметки человеком: {expert}", "",
             f"Постов с ответом: {result.n}, «не уверен»: {result.unsure}.", "",
             "| Мера | Значение |", "|---|---|",
             f"| Каппа Коэна «схема / не схема» | {result.kappa_scam:.3f} |",
             f"| Каппа Коэна по четырём классам | {result.kappa_track:.3f} |",
             f"| Совпадение «схема / не схема» | {result.agree_scam:.1%} |", "",
             "Строки — ИИ-разметка, столбцы — эксперт.", "",
             "| ИИ \\ эксперт | " + " | ".join(LABELS) + " |", "|---|" + "---|" * len(LABELS)]
    for t in LABELS:
        lines.append(f"| {t} | " + " | ".join(str(result.confusion[t][h]) for h in LABELS) + " |")
    if result.disagreements:
        lines += ["", "## Расхождения", "", "| Набор | id | ИИ | Эксперт | Комментарий |", "|---|---|---|---|---|"]
        lines += [f"| {d['source']} | {d['id']} | {d['ai']} | {d['human']} | {d['note'].replace('|', '/')} |"
                  for d in result.disagreements]
    return "\n".join(lines) + "\n"


_PAGE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
:root {{ --bg: #f7f7f5; --card: #fff; --ink: #1d1d1b; --muted: #6b6b66; --line: #e3e3de; --accent: #2457d6; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg: #161615; --card: #20201f; --ink: #ececea; --muted: #a2a29c; --line: #34342f; --accent: #7aa2ff; }} }}
body {{ margin: 0; background: var(--bg); color: var(--ink); font: 16px/1.5 system-ui, sans-serif; }}
main {{ max-width: 760px; margin: 0 auto; padding: 24px 16px 96px; }}
.post {{ background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 16px; margin: 0 0 14px; }}
.post p {{ white-space: pre-wrap; margin: 6px 0 12px; }}
.n {{ color: var(--muted); font-size: 13px; }}
.opts {{ display: flex; flex-wrap: wrap; gap: 6px 16px; }}
.note {{ width: 100%; box-sizing: border-box; margin-top: 10px; padding: 6px 8px; border: 1px solid var(--line); border-radius: 8px; background: transparent; color: inherit; }}
footer {{ position: fixed; inset: auto 0 0 0; background: var(--card); border-top: 1px solid var(--line); padding: 10px 16px; display: flex; gap: 12px; align-items: center; justify-content: center; flex-wrap: wrap; }}
button {{ background: var(--accent); color: #fff; border: 0; border-radius: 8px; padding: 8px 16px; font: inherit; cursor: pointer; }}
</style></head><body><main>
<h1>{title}</h1>
<p>Отметьте для каждого поста, что это. Решайте по тексту, как если бы пост попал к вам на проверку; «не уверен» — нормальный ответ.
Ответы сохраняются в этом браузере; в конце нажмите «Сохранить ответы» и отправьте файл. Никуда ничего не отправляется само.</p>
{cards}
</main>
<footer><span id="done">0 / {total}</span><input id="who" placeholder="Ваше имя и роль" style="padding:6px 8px"><button id="save">Сохранить ответы</button></footer>
<script>
const KEY = "pruf-audit-" + document.title;
let state = {{}};
try {{ state = JSON.parse(localStorage.getItem(KEY) || "{{}}"); }} catch (e) {{ state = {{}}; }}
function persist() {{ try {{ localStorage.setItem(KEY, JSON.stringify(state)); }} catch (e) {{}} count(); }}
function count() {{ document.getElementById("done").textContent = Object.values(state).filter(a => a.label).length + " / {total}"; }}
document.querySelectorAll(".post").forEach(card => {{
  const id = card.dataset.id, saved = state[id] || {{}};
  card.querySelectorAll("input[type=radio]").forEach(r => {{
    r.checked = saved.label === r.value;
    r.addEventListener("change", () => {{ state[id] = {{ ...(state[id] || {{}}), label: r.value }}; persist(); }});
  }});
  const note = card.querySelector(".note");
  note.value = saved.note || "";
  note.addEventListener("input", () => {{ state[id] = {{ ...(state[id] || {{}}), note: note.value }}; persist(); }});
}});
count();
document.getElementById("save").addEventListener("click", () => {{
  const body = JSON.stringify({{ expert: document.getElementById("who").value, answers: state }}, null, 1);
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([body], {{ type: "application/json" }}));
  a.download = "pruf-audit-answers.json"; a.click();
}});
</script></body></html>
"""
