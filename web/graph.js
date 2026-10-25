// ПРУФ: граф связей кейса. Укладка Фрюхтермана–Рейнгольда с остыванием и вписыванием в рамку.
import { LEVEL, REQ_TYPE, el, svgEl, tip, untip } from "./lib.js";

const W = 720, H = 440, PAD = 28, ITERATIONS = 360;
const NODE_COLOR = { requisite: "var(--req)", domain: "var(--domain)", channel: "var(--chan)" };
const LEVEL_COLOR = { high: "var(--high)", medium: "var(--medium)", low: "var(--low)" };
const EDGE_WEIGHT = { reuses: 2.5, mentions: 1.4, links_to: 1.2, posted_in: 0.5 };

// 37 копий одного пруфа дают 666 рёбер «общий пруф»: оставляем остовное дерево,
// связность та же, а граф читается.
export function sparseReuse(edges) {
  const parent = new Map();
  const find = (x) => { while (parent.has(x) && parent.get(x) !== x) x = parent.get(x); return x; };
  return edges.filter((e) => {
    if (e.type !== "reuses") return true;
    const a = find(e.source), b = find(e.target);
    if (a === b) return false;
    parent.set(a, b); parent.set(b, b);
    return true;
  });
}

function layout(nodes, edges) {
  const n = nodes.length;
  const k = Math.sqrt((W * H) / Math.max(n, 1)) * 0.7;
  let temp = W / 6;
  // Детерминированный старт по спирали: одна и та же раскладка при каждом открытии
  nodes.forEach((p, i) => { const a = i * 2.399, r = 10 * Math.sqrt(i + 1); p.x = W / 2 + r * Math.cos(a); p.y = H / 2 + r * Math.sin(a); });
  for (let it = 0; it < ITERATIONS; it++) {
    for (const p of nodes) { p.dx = (W / 2 - p.x) * 0.03; p.dy = (H / 2 - p.y) * 0.03; }
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const a = nodes[i], b = nodes[j];
        const dx = a.x - b.x, dy = a.y - b.y, d = Math.max(Math.hypot(dx, dy), 0.5);
        const f = (k * k) / d / d;
        a.dx += dx * f; a.dy += dy * f; b.dx -= dx * f; b.dy -= dy * f;
      }
    }
    for (const e of edges) {
      const a = nodes[e.s], b = nodes[e.t];
      const dx = a.x - b.x, dy = a.y - b.y, d = Math.max(Math.hypot(dx, dy), 0.5);
      const f = (d / k) * (EDGE_WEIGHT[e.type] || 1);
      a.dx -= dx * f; a.dy -= dy * f; b.dx += dx * f; b.dy += dy * f;
    }
    for (const p of nodes) {
      const d = Math.max(Math.hypot(p.dx, p.dy), 0.01), step = Math.min(d, temp);
      p.x += (p.dx / d) * step; p.y += (p.dy / d) * step;
    }
    temp = Math.max(temp * 0.985, 0.5);
  }
  // Вписываем в рамку с сохранением пропорций, вместо обрезки по краям
  const xs = nodes.map((p) => p.x), ys = nodes.map((p) => p.y);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const s = Math.min((W - 2 * PAD) / Math.max(x1 - x0, 1), (H - 2 * PAD) / Math.max(y1 - y0, 1));
  const ox = (W - (x1 - x0) * s) / 2, oy = (H - (y1 - y0) * s) / 2;
  for (const p of nodes) { p.x = ox + (p.x - x0) * s; p.y = oy + (p.y - y0) * s; }
}

function describe(node, degree) {
  if (node.type === "post") {
    return [`Пост #${node.id.split(":")[1]}`, `${node.channel || "—"}`, `Риск: ${LEVEL[node.level] || node.level} · ${Math.round(node.score || 0)}`, `Связей: ${degree}`];
  }
  if (node.type === "requisite") return [REQ_TYPE[node.kind] || "Реквизит", node.label, `Постов: ${degree}`];
  if (node.type === "domain") return ["Домен", node.label, `Постов: ${degree}`];
  return ["Канал", node.label, `Постов в кейсе: ${degree}`];
}

function nodeShape(p) {
  if (p.type === "requisite") {
    return svgEl("rect", { x: p.x - 7, y: p.y - 7, width: 14, height: 14, rx: 3, transform: `rotate(45 ${p.x} ${p.y})`, fill: NODE_COLOR.requisite });
  }
  if (p.type === "domain") return svgEl("rect", { x: p.x - 6, y: p.y - 6, width: 12, height: 12, rx: 2, fill: NODE_COLOR.domain });
  if (p.type === "channel") return svgEl("circle", { cx: p.x, cy: p.y, r: 4.5, fill: "var(--panel)", stroke: NODE_COLOR.channel, "stroke-width": 2 });
  return svgEl("circle", { cx: p.x, cy: p.y, r: 6.5, fill: LEVEL_COLOR[p.level] || "var(--muted)" });
}

/**
 * Рисует граф кейса. onPost(id) вызывается при клике по посту.
 * Каналы по умолчанию скрыты: это атрибут, а не улика, и они перегружают картинку.
 */
export function graphView(g, onPost) {
  const wrap = el("div", { class: "graph-wrap" });
  const toggle = el("input", { type: "checkbox" });
  const draw = () => wrap.replaceChildren(renderSvg(g, toggle.checked, onPost));
  toggle.addEventListener("change", draw);
  draw();
  return el("div", {},
    wrap,
    el("div", { class: "legend" },
      el("span", { class: "lg post" }, "пост (цвет = риск)"), el("span", { class: "lg req" }, "реквизит"),
      el("span", { class: "lg dom" }, "домен"), el("span", { class: "lg chan" }, "канал"),
      el("span", { class: "lg reuse" }, "общий пруф"),
      el("label", { class: "inline" }, toggle, "показать каналы")),
  );
}

function renderSvg(g, withChannels, onPost) {
  const keep = g.nodes.filter((n) => withChannels || n.type !== "channel");
  const nodes = keep.map((n) => ({ ...n }));
  const idx = new Map(nodes.map((n, i) => [n.id, i]));
  const edges = sparseReuse(g.edges.filter((e) => idx.has(e.source) && idx.has(e.target)))
    .map((e) => ({ ...e, s: idx.get(e.source), t: idx.get(e.target) }));
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, class: "graph", role: "img", "aria-label": "Граф связей кейса" });
  if (!nodes.length) return svg;
  layout(nodes, edges);

  const neighbors = nodes.map(() => new Set());
  const degree = new Array(nodes.length).fill(0);
  for (const e of g.edges) {
    const s = idx.get(e.source), t = idx.get(e.target);
    if (s === undefined || t === undefined) continue;
    neighbors[s].add(t); neighbors[t].add(s); degree[s]++; degree[t]++;
  }

  const edgeLayer = svgEl("g", { class: "edges" }), nodeLayer = svgEl("g", { class: "nodes" }), labelLayer = svgEl("g", { class: "labels" });
  const lines = edges.map((e) => {
    const a = nodes[e.s], b = nodes[e.t];
    const line = svgEl("line", { x1: a.x, y1: a.y, x2: b.x, y2: b.y, class: "e " + e.type });
    edgeLayer.append(line);
    return line;
  });
  const marks = nodes.map((p, i) => {
    const g2 = svgEl("g", { class: "n " + p.type, tabindex: p.type === "post" ? 0 : null }, nodeShape(p),
      svgEl("circle", { cx: p.x, cy: p.y, r: 14, class: "hit" }));
    g2.addEventListener("mousemove", (evt) => tip(evt, describe(p, degree[i])));
    g2.addEventListener("mouseenter", () => focus(i));
    g2.addEventListener("mouseleave", () => { untip(); focus(-1); });
    if (p.type === "post") {
      const open = () => onPost(Number(p.id.split(":")[1]));
      g2.addEventListener("click", open);
      g2.addEventListener("keydown", (evt) => { if (evt.key === "Enter") open(); });
    }
    nodeLayer.append(g2);
    if (p.type !== "post") {
      const right = p.x < W - 140;
      labelLayer.append(svgEl("text", { x: p.x + (right ? 11 : -11), y: p.y + 4, "text-anchor": right ? "start" : "end", class: "t " + p.type },
        String(p.label || "").slice(0, 24)));
    }
    return g2;
  });

  function focus(i) {
    svg.classList.toggle("focusing", i >= 0);
    marks.forEach((m, j) => m.classList.toggle("lit", i >= 0 && (j === i || neighbors[i].has(j))));
    lines.forEach((l, j) => l.classList.toggle("lit", i >= 0 && (edges[j].s === i || edges[j].t === i)));
  }

  svg.append(edgeLayer, nodeLayer, labelLayer);
  return svg;
}
