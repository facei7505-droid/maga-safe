// ПРУФ: «что заблокировать» — ключевые реквизиты сети и проверка «что если» прямо в браузере.
// Сервер присылает рёбра канал — реквизит/домен; эффект блокировки считается здесь, без запросов.
import { REQ_TYPE, day, el, svgEl, tip, untip } from "./lib.js";

const ROW = 22, COL_W = 250, GAP = 220, TOP = 14;

const kindName = (kind) => (kind === "domain" ? "Домен" : REQ_TYPE[kind] || "Реквизит");

/** Кого отрезали от денег и на сколько частей распалась сеть, если заблокировать blocked. */
export function blockEffect(net, blocked) {
  const blockable = new Map(net.money.map((m) => [m.node, m.blockable !== false]));
  const routes = new Map(net.channels.map((c) => [c, []]));
  const adj = new Map();
  const link = (a, b) => { if (!adj.has(a)) adj.set(a, []); adj.get(a).push(b); };
  for (const [chan, node] of net.edges) {
    if (blockable.get(node)) routes.get(chan)?.push(node);
    if (blocked.has(node)) continue;
    link("c:" + chan, node); link(node, "c:" + chan);
  }
  const cut = net.channels.filter((c) => {
    const r = routes.get(c) || [];
    return r.length > 0 && r.every((n) => blocked.has(n));
  });
  const seen = new Set();
  let parts = 0;
  for (const c of net.channels) {
    const start = "c:" + c;
    if (seen.has(start)) continue;
    parts++;
    const stack = [start];
    seen.add(start);
    while (stack.length) {
      for (const nb of adj.get(stack.pop()) || []) if (!seen.has(nb)) { seen.add(nb); stack.push(nb); }
    }
  }
  return { cut, parts };
}

export function networkPanel(net, { title = "Что заблокировать: ключевые реквизиты" } = {}) {
  const keys = net.key_nodes || [];
  if (!keys.length) return null;
  const blocked = new Set();
  const effect = el("div", { class: "net-effect" });
  const picture = el("div", { class: "net-pic" });
  const rows = keys.map((k, i) => {
    const box = el("input", { type: "checkbox", "aria-label": `Заблокировать ${k.label}` });
    box.addEventListener("change", () => { box.checked ? blocked.add(k.node) : blocked.delete(k.node); redraw(); });
    return el("label", { class: "net-key" + (i === 0 ? " top" : "") }, box,
      el("div", {},
        el("div", {}, el("b", { class: "mono" }, k.label), " ", el("span", { class: "muted small" }, kindName(k.kind)),
          i === 0 ? el("span", { class: "net-tag" }, "ключевой") : null),
        el("div", { class: "muted small" },
          `деньги принимают ${k.channels.length} кан. · без него останутся без оплаты: ${k.cut_off.length}`)));
  });
  function redraw() {
    const { cut, parts } = blockEffect(net, blocked);
    effect.replaceChildren(...(blocked.size
      ? [el("b", {}, `Отрезаны от денег: ${cut.length} из ${net.channels.length} каналов`),
         el("span", {}, ` · сеть распадается на ${parts} ${parts === 1 ? "часть" : parts < 5 ? "части" : "частей"}`),
         cut.length ? el("div", { class: "muted small mono net-cut" }, cut.join(", ")) : null]
      : [el("span", { class: "muted" }, "Отметьте реквизит, чтобы увидеть, что будет после блокировки.")]).filter(Boolean));
    picture.replaceChildren(bipartite(net, blocked, new Set(cut)));
  }
  redraw();
  return el("section", { class: "panel net" },
    el("h3", {}, title, " ", el("span", { class: "muted small" }, "подсказка для банка и регулятора, решает аналитик")),
    rotation(net),
    el("div", { class: "net-grid" }, el("div", { class: "net-keys" }, rows, effect), picture));
}

// Сеть завела новые реквизиты позже старта: обычно это смена номера после блокировки
function rotation(net) {
  const fresh = net.fresh || [];
  if (!fresh.length) return null;
  return el("div", { class: "net-fresh", role: "note" },
    el("b", {}, "Ротация реквизитов: "), `сеть работает с ${day(net.since)}, часть каналов сменила реквизиты. Новые тоже нужно блокировать.`,
    el("ul", {}, fresh.map((f) => el("li", {},
      el("b", { class: "mono" }, f.label), ` ${kindName(f.kind)} · вместо ${f.replaces.join(", ")} · с ${day(f.first_seen)} · каналов: ${f.channels.length}`))));
}

// Две колонки: реквизиты и домены слева, каналы справа. Заблокированное красное, отрезанное серое.
function bipartite(net, blocked, cut) {
  const deg = new Map();
  for (const [, m] of net.edges) deg.set(m, (deg.get(m) || 0) + 1);
  const money = [...net.money].sort((a, b) => (deg.get(b.node) || 0) - (deg.get(a.node) || 0));
  const chans = [...net.channels];
  const rowsN = Math.max(money.length, chans.length);
  const step = rowsN > 30 ? 14 : ROW;
  const h = TOP * 2 + rowsN * step;
  const yM = new Map(money.map((m, i) => [m.node, TOP + (i + 0.5) * step * (rowsN / money.length)]));
  const yC = new Map(chans.map((c, i) => [c, TOP + (i + 0.5) * step * (rowsN / chans.length)]));
  const xM = COL_W - 10, xC = COL_W + GAP;
  const svg = svgEl("svg", { viewBox: `0 0 ${COL_W * 2 + GAP} ${h}`, class: "net-svg", role: "img", "aria-label": "Сеть каналов и реквизитов" });
  for (const [chan, node] of net.edges) {
    const off = blocked.has(node);
    svg.append(svgEl("line", { x1: xM, y1: yM.get(node), x2: xC, y2: yC.get(chan), class: "ne" + (off ? " off" : "") }));
  }
  for (const m of money) {
    const y = yM.get(m.node), off = blocked.has(m.node);
    const g = svgEl("g", { class: "nm" + (off ? " off" : "") + (m.blockable === false ? " link" : "") },
      svgEl("rect", { x: xM - 6, y: y - 6, width: 12, height: 12, rx: m.kind === "domain" ? 2 : 6 }),
      svgEl("text", { x: xM - 14, y: y + 4, "text-anchor": "end" }, String(m.label).slice(0, 30)));
    g.addEventListener("mousemove", (e) => tip(e, [kindName(m.kind), m.label, `каналов: ${deg.get(m.node) || 0}`]));
    g.addEventListener("mouseleave", untip);
    svg.append(g);
  }
  for (const c of chans) {
    const y = yC.get(c);
    svg.append(svgEl("g", { class: "nc" + (cut.has(c) ? " cut" : "") },
      svgEl("circle", { cx: xC, cy: y, r: 5 }), svgEl("text", { x: xC + 12, y: y + 4 }, c.slice(0, 28))));
  }
  return svg;
}
