// ПРУФ: отчёт по кейсу для печати и передачи (PDF через печать браузера).
import { $, LEVEL, REQ_TYPE, STATUS, TRACK, api, badge, day, el, lazyImg, showError, when } from "./lib.js";

const MAX_POSTS = 60;

async function main() {
  const key = decodeURIComponent(location.hash.slice(1));
  const root = $("#report");
  $("#print").addEventListener("click", () => window.print());
  if (!key) { root.replaceChildren(el("p", { class: "err" }, "Не указан кейс")); return; }
  try {
    const { data } = await api("/api/v1/cases/" + encodeURIComponent(key));
    const top = await topTimeline(data);
    render(root, data, top);
    document.title = `ПРУФ · кейс ${key}`;
  } catch (err) { showError(root, err); }
}

async function topTimeline(d) {
  const art = d.posts.flatMap((p) => p.artifacts || []).find((a) => a.kind === "image");
  if (!art) return null;
  try { return (await api(`/api/v1/artifacts/${art.id}/timeline`)).data; } catch { return null; }
}

function render(root, d, tl) {
  const c = d.case;
  const evidenceCounts = new Map();
  for (const p of d.posts) for (const e of (p.analysis && p.analysis.evidence) || []) {
    if (e.weight > 0 && !e.stop) evidenceCounts.set(e.label, (evidenceCounts.get(e.label) || 0) + 1);
  }
  const topEvidence = [...evidenceCounts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8);
  const edits = tl ? tl.items.flatMap((i) => ((i.diff && i.diff.changes) || []).filter((x) => x.kind === "amount" || x.kind === "date").map((x) => ({ ...x, post: i.post }))) : [];
  root.replaceChildren(
    el("header", { class: "r-head" },
      el("div", { class: "brand" }, el("span", { class: "logo" }, "П"), "ПРУФ"),
      el("div", {}, el("h1", {}, `Кейс ${c.key} `, badge(c.level, c.score)),
        el("div", { class: "muted" }, `Сформирован ${when(new Date().toISOString())} UTC · статус: ${STATUS[d.status.status] || d.status.status}`))),
    el("p", { class: "note" }, "Документ перечисляет признаки схем, найденные автоматически. Это не вердикт и не доказательство вины: решение принимает уполномоченный специалист после проверки."),
    el("h2", {}, "Сводка"),
    el("table", { class: "table kv-table" }, el("tbody", {},
      row("Треки", c.tracks.map((t) => TRACK[t] || t).join(", ")),
      row("Период", `${day(c.first_seen)} — ${day(c.last_seen)}`),
      row("Постов", c.size), row("Каналы", c.channels.join(", ") || "—"),
      row("Реквизиты", c.requisites.join(", ") || "—"), row("Домены", c.domains.join(", ") || "—"),
      row("Семейств пруфов", c.families),
      d.status.note ? row("Заметка аналитика", d.status.note) : null)),
    el("h2", {}, "Основные признаки"),
    el("ul", {}, topEvidence.map(([label, n]) => el("li", {}, `${label} — в ${n} постах`))),
    tl ? el("section", {},
      el("h2", {}, `Повторно использованный пруф: ${tl.appearances} появлений`),
      el("div", { class: "r-proof" }, el("div", { class: "shot" }, lazyImg(tl.items[0].artifact_id, "пруф")),
        el("div", {}, edits.length
          ? el("table", { class: "table compact" }, el("thead", {}, el("tr", {}, el("th", {}, "Дата"), el("th", {}, "Канал"), el("th", {}, "Было"), el("th", {}, "Стало"))),
            el("tbody", {}, edits.slice(0, 20).map((x) => el("tr", {}, el("td", {}, day(x.post.posted_at)), el("td", {}, x.post.channel || "—"), el("td", {}, x.before), el("td", { class: "diff" }, x.after)))))
          : el("p", { class: "muted" }, "Копии не отличаются по суммам и датам.")))) : null,
    el("h2", {}, `Посты (${d.posts.length}${d.posts.length > MAX_POSTS ? `, показаны первые ${MAX_POSTS}` : ""})`),
    el("table", { class: "table compact r-posts" },
      el("thead", {}, el("tr", {}, el("th", {}, "#"), el("th", {}, "Дата"), el("th", {}, "Канал"), el("th", {}, "Риск"), el("th", {}, "Признаки"))),
      el("tbody", {}, d.posts.slice(0, MAX_POSTS).map((p) => el("tr", {},
        el("td", {}, p.id), el("td", {}, when(p.posted_at)), el("td", {}, p.channel || "—"),
        el("td", {}, `${LEVEL[p.level] || p.level} · ${Math.round(p.score)}`),
        el("td", {}, ((p.analysis && p.analysis.evidence) || []).filter((e) => e.weight > 0 && !e.stop).slice(0, 4).map((e) => el("div", {}, e.label, e.quote ? el("q", {}, e.quote) : null))))))),
    el("h2", {}, "Реквизиты"),
    el("ul", {}, [...new Map(d.posts.flatMap((p) => p.requisites || []).map((r) => [r.key, r])).values()].map((r) => el("li", {}, `${REQ_TYPE[r.kind] || r.kind}: ${r.display}`))),
    el("footer", { class: "muted small" }, "ПРУФ · SafeNet KZ · номера карт в отчёте замаскированы (6+4)."),
  );
}

function row(k, v) { return el("tr", {}, el("th", {}, k), el("td", {}, v)); }

main();
