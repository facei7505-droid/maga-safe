// ПРУФ: вкладка «Обзор» — динамика, треки, каналы и ранние сигналы.
import { $, LEVEL, REQ_TYPE, STATUS, TRACK, api, chips, el, showError, svgEl, tip, untip, when } from "./lib.js";

const LEVELS = ["high", "medium", "low"];
const TRACK_COLOR = { lottery: "var(--t-lottery)", casino: "var(--t-casino)", pyramid: "var(--t-pyramid)" };

export async function loadOverview(openCase) {
  const root = $("#overview");
  root.replaceChildren(el("p", { class: "muted" }, "Загрузка…"));
  try {
    const [{ data: s }, { data: o }] = await Promise.all([api("/api/v1/stats"), api("/api/v1/overview")]);
    root.replaceChildren(
      kpis(s, o),
      surgesBlock(o.surges, openCase),
      el("div", { class: "ov-grid" },
        panel("Посты по дням и уровню риска", dailyChart(o.daily), levelLegend()),
        panel("Треки (посты со средним и высоким риском)", trackBars(o.tracks)),
        panel("Каналы с наибольшим числом постов с признаками", channelTable(o.channels)),
        panel("Кейсы по статусу", statusRow(o.case_statuses)),
      ),
    );
  } catch (err) { showError(root, err); }
}

function panel(title, ...body) {
  return el("section", { class: "panel" }, el("h3", {}, title), body);
}

function kpis(s, o) {
  const lv = s.levels || {};
  const risky = (lv.high || 0) + (lv.medium || 0);
  const tile = (value, label, hint, cls = "") => el("div", { class: "kpi " + cls }, el("div", { class: "kpi-v" }, value), el("div", { class: "kpi-l" }, label), hint ? el("div", { class: "kpi-h" }, hint) : null);
  return el("div", { class: "kpis" },
    tile(s.posts, "постов проверено"),
    tile(risky, "с признаками схем", s.posts ? `${Math.round((risky / s.posts) * 100)}% потока` : null, "hot"),
    tile(s.cases, "кейсов для аналитика", `${o.case_statuses.new || 0} новых`),
    tile(s.images_indexed + s.texts_indexed, "пруфов в реестре", `${s.images_indexed} скринов · ${s.texts_indexed} текстов`),
    tile(o.surges.length, "ранних сигналов", "реквизит в 3+ каналах за 72 ч", o.surges.length ? "warn" : ""),
  );
}

function surgesBlock(surges, openCase) {
  if (!surges.length) return el("p", { class: "muted" }, "Ранних сигналов нет: ни один реквизит не разошёлся по 3+ каналам за 72 часа.");
  return el("section", { class: "surges" },
    el("h3", {}, "⚡ Ранние сигналы: реквизит быстро расходится по каналам"),
    surges.map((sg) => el("div", { class: "surge" },
      el("div", { class: "surge-main" },
        el("span", { class: "req-type" }, REQ_TYPE[sg.type] || sg.type), " ", el("b", {}, sg.requisite),
        el("div", {}, `${sg.channels.length} каналов, ${sg.posts.length} постов за ${hoursBetween(sg.start, sg.end)} ч · ${when(sg.start)} → ${when(sg.end)}`),
        el("div", { class: "muted" }, sg.channels.join(", ")),
      ),
      el("div", { class: "surge-act" }, sg.cases.map((k) => el("button", { class: "primary", onclick: () => openCase(k) }, `Открыть кейс ${k}`))),
    )),
    el("p", { class: "muted small" }, "Так выглядит запуск новой волны: схему разгоняют по сетке каналов раньше, чем она наберёт жалобы. Это признак для проверки, не вердикт."),
  );
}

function hoursBetween(a, b) {
  return Math.max(1, Math.round((new Date(b) - new Date(a)) / 3600000));
}

function levelLegend() {
  return el("div", { class: "legend" }, LEVELS.map((l) => el("span", { class: "lg lvl " + l }, LEVEL[l])));
}

function dailyChart(daily) {
  const W = 720, H = 220, L = 34, B = 22, T = 8;
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "chart", role: "img", "aria-label": "Посты по дням" });
  if (!daily.length) return svg;
  const max = Math.max(1, ...daily.map((d) => d.high + d.medium + d.low));
  const step = Math.ceil(max / 4);
  const top = step * 4;
  const y = (v) => H - B - (v / top) * (H - B - T);
  for (let v = 0; v <= top; v += step) {
    svg.append(svgEl("line", { x1: L, x2: W, y1: y(v), y2: y(v), class: v ? "grid" : "axis" }),
      svgEl("text", { x: L - 6, y: y(v) + 4, "text-anchor": "end", class: "tick" }, v));
  }
  const bw = (W - L) / daily.length, barW = Math.max(2, bw - 2);
  daily.forEach((d, i) => {
    const x = L + i * bw + 1;
    const g = svgEl("g", { class: "bar" });
    let acc = 0;
    for (const lvl of LEVELS) {
      const v = d[lvl];
      if (!v) continue;
      const y1 = y(acc), y2 = y(acc + v);
      // 2px просвет между сегментами стопки
      g.append(svgEl("rect", { x, y: y2, width: barW, height: Math.max(1, y1 - y2 - (acc ? 2 : 0)), rx: 1.5, class: "seg " + lvl }));
      acc += v;
    }
    g.append(svgEl("rect", { x: L + i * bw, y: T, width: bw, height: H - B - T, class: "hit" }));
    g.addEventListener("mousemove", (evt) => tip(evt, [d.date, `высокий: ${d.high}`, `средний: ${d.medium}`, `низкий: ${d.low}`]));
    g.addEventListener("mouseleave", untip);
    svg.append(g);
    if (i % 7 === 0) svg.append(svgEl("text", { x: x + barW / 2, y: H - 6, "text-anchor": "middle", class: "tick" }, d.date.slice(5)));
  });
  return svg;
}

function trackBars(tracks) {
  const total = Object.values(tracks).reduce((a, b) => a + b, 0) || 1;
  const max = Math.max(1, ...Object.values(tracks));
  return el("div", { class: "hbars" }, Object.keys(TRACK).map((t) => {
    const v = tracks[t] || 0;
    return el("div", { class: "hbar" },
      el("div", { class: "hbar-l" }, TRACK[t]),
      el("div", { class: "hbar-track" }, el("div", { class: "hbar-fill", style: `width:${(v / max) * 100}%;background:${TRACK_COLOR[t]}` })),
      el("div", { class: "hbar-v" }, `${v} · ${Math.round((v / total) * 100)}%`));
  }));
}

function channelTable(channels) {
  if (!channels.length) return el("p", { class: "muted" }, "Нет каналов с признаками.");
  const max = Math.max(...channels.map((c) => c.risky));
  return el("table", { class: "table compact" },
    el("thead", {}, el("tr", {}, el("th", {}, "Канал"), el("th", {}, "С признаками"), el("th", {}, "Треки"))),
    el("tbody", {}, channels.map((c) => el("tr", {},
      el("td", {}, c.channel),
      el("td", {}, el("div", { class: "mini" }, el("div", { class: "mini-fill", style: `width:${(c.risky / max) * 100}%` }), el("span", {}, `${c.risky} из ${c.total}`))),
      el("td", {}, chips(c.tracks))))));
}

function statusRow(counts) {
  return el("div", { class: "status-row" }, Object.entries(STATUS).map(([k, label]) =>
    el("div", { class: "status-cell " + k }, el("div", { class: "kpi-v" }, counts[k] || 0), el("div", { class: "kpi-l" }, label))));
}
