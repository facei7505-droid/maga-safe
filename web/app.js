// ПРУФ: дашборд аналитика. Без сборки и внешних библиотек.
// Весь текст из постов выводится только через textContent (посты недоверенные).
"use strict";

const TRACK = { lottery: "Розыгрыши", casino: "Казино", pyramid: "Пирамиды" };
const LEVEL = { high: "высокий", medium: "средний", low: "низкий" };
const STATUS = { new: "Новый", in_review: "В работе", confirmed: "Подтверждён", dismissed: "Отклонён" };
const COLORS = { post: "#1f5fbf", requisite: "#c62828", domain: "#8e24aa", channel: "#9aa0a6" };
const state = { cases: [], current: null, blobUrls: [] };

const $ = (sel) => document.querySelector(sel);

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "style") node.setAttribute("style", v);
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

function token() {
  // sessionStorage: токен живёт до закрытия вкладки и не остаётся в браузере надолго
  try { return sessionStorage.getItem("pruf_token") || ""; } catch { return ""; }
}

async function api(path, opts = {}) {
  const headers = Object.assign({}, opts.headers || {});
  const t = token();
  if (t) headers.Authorization = "Bearer " + t;
  const res = await fetch(path, Object.assign({}, opts, { headers }));
  if (opts.raw) {
    if (!res.ok) throw new Error("HTTP " + res.status);
    return res;
  }
  const body = await res.json().catch(() => ({ success: false, error: "HTTP " + res.status }));
  if (!body.success) throw new Error(body.error || "HTTP " + res.status);
  return body;
}

async function imageUrl(artifactId) {
  const res = await api(`/api/v1/artifacts/${artifactId}/file`, { raw: true });
  const url = URL.createObjectURL(await res.blob());
  state.blobUrls.push(url);
  return url;
}

function badge(level, score) {
  return el("span", { class: "badge " + level }, `${LEVEL[level] || level} · ${Math.round(score)}`);
}

function chips(tracks) {
  return (tracks || []).filter(Boolean).map((t) => el("span", { class: "chip " + t }, TRACK[t] || t));
}

function showError(target, err) {
  target.replaceChildren(el("p", { class: "err" }, "Ошибка: " + err.message));
}

// ---------------- статистика ----------------
async function loadStats() {
  try {
    const { data } = await api("/api/v1/stats");
    const lv = data.levels || {};
    $("#stats").replaceChildren(
      el("span", {}, "Постов: ", el("b", {}, data.posts)),
      el("span", {}, "Высокий: ", el("b", {}, lv.high || 0)),
      el("span", {}, "Средний: ", el("b", {}, lv.medium || 0)),
      el("span", {}, "Кейсов: ", el("b", {}, data.cases)),
      el("span", {}, "В реестре ПРУФ: ", el("b", {}, `${data.images_indexed} изобр. · ${data.texts_indexed} текстов`)),
    );
    const cap = data.capabilities || {};
    const off = [];
    if (!cap.ocr) off.push("OCR");
    if (!cap.ml) off.push("ML-модель");
    if (cap.llm && cap.llm.configured && cap.llm.failures) off.push(`LLM (ошибок: ${cap.llm.failures})`);
    const banner = $("#degraded");
    if (off.length) {
      banner.textContent = "Работает не всё: " + off.join(", ") + ". Анализ идёт по остальным признакам.";
      banner.classList.remove("hidden");
    } else banner.classList.add("hidden");
  } catch (err) {
    $("#stats").replaceChildren(el("span", { class: "err" }, err.message));
  }
}

// ---------------- очередь ----------------
async function loadCases() {
  const params = new URLSearchParams();
  for (const [id, key] of [["#f-level", "level"], ["#f-track", "track"], ["#f-status", "status"]]) {
    if ($(id).value) params.set(key, $(id).value);
  }
  params.set("limit", "200");
  const list = $("#cases");
  try {
    const { data, meta } = await api("/api/v1/cases?" + params);
    state.cases = data;
    list.replaceChildren(...data.map(caseItem));
    $("#cases-total").textContent = `Кейсов: ${meta.total}`;
    if (!data.length) list.replaceChildren(el("p", { class: "muted" }, "Кейсов нет. Загрузите посты через «Проверить» или scripts/seed_demo.py."));
  } catch (err) {
    showError(list, err);
  }
}

function caseItem(c) {
  const li = el("li", { "data-key": c.key, onclick: () => openCase(c.key) },
    el("div", {}, badge(c.level, c.score), " ", el("b", {}, c.key), " ", el("span", { class: "muted" }, STATUS[c.status] || c.status)),
    el("div", {}, chips(c.tracks)),
    el("div", { class: "meta" }, `${c.size} постов · ${c.channels.length} каналов · семейств пруфов: ${c.families}`),
    c.requisites.length ? el("div", { class: "meta" }, "Реквизиты: " + c.requisites.slice(0, 3).join(", ")) : null,
  );
  if (state.current === c.key) li.classList.add("active");
  return li;
}

// ---------------- карточка кейса ----------------
function releaseImages() {
  for (const url of state.blobUrls) URL.revokeObjectURL(url);
  state.blobUrls = [];
}

async function openCase(key) {
  state.current = key;
  releaseImages();
  document.querySelectorAll(".case-list li").forEach((li) => li.classList.toggle("active", li.dataset.key === key));
  const card = $("#case");
  card.replaceChildren(el("p", { class: "muted" }, "Загрузка…"));
  try {
    const { data } = await api("/api/v1/cases/" + encodeURIComponent(key));
    renderCase(data);
  } catch (err) {
    showError(card, err);
  }
}

function renderCase(d) {
  const c = d.case;
  const card = $("#case");
  const statusSel = el("select", {}, ...Object.entries(STATUS).map(([v, label]) => {
    const o = el("option", { value: v }, label);
    if (v === d.status.status) o.selected = true;
    return o;
  }));
  const note = el("input", { placeholder: "Заметка аналитика", value: d.status.note || "" });
  const save = el("button", { onclick: async () => {
    try {
      await api("/api/v1/cases/" + encodeURIComponent(c.key), {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: statusSel.value, note: note.value || null }),
      });
      loadCases();
      save.textContent = "Сохранено";
    } catch (err) { save.textContent = err.message; }
  } }, "Сохранить статус");
  const exportBtn = el("button", { class: "primary", onclick: () => exportCase(c.key) }, "Пакет доказательств (ZIP)");

  const proofs = el("div", { class: "thumbs" });
  const posts = d.posts.map((p) => renderPost(p, proofs));

  card.replaceChildren(
    el("div", { class: "case-head" },
      el("div", {},
        el("h2", {}, `Кейс ${c.key} `, badge(c.level, c.score)),
        el("div", {}, chips(c.tracks)),
        el("div", { class: "muted" }, `${c.size} постов · ${c.first_seen ? c.first_seen.slice(0, 10) : "?"} — ${c.last_seen ? c.last_seen.slice(0, 10) : "?"}`),
        el("div", { class: "muted" }, "Каналы: " + (c.channels.join(", ") || "—")),
        el("div", { class: "muted" }, "Реквизиты: " + (c.requisites.join(", ") || "—")),
        c.domains.length ? el("div", { class: "muted" }, "Домены: " + c.domains.join(", ")) : null,
      ),
      el("div", { class: "actions" }, statusSel, note, save, exportBtn),
    ),
    el("p", { class: "muted" }, "Система показывает признаки, а не вердикт. Решение по кейсу принимает аналитик."),
    el("div", { class: "grid2" },
      el("div", {}, el("h3", {}, "Граф связей"), graphSvg(d.graph),
        el("div", { class: "legend" }, "● пост  ● реквизит  ● домен  ● канал · линии: общий пруф, реквизит, ссылка"),
        el("h3", {}, "Пруфы (нажмите — таймлайн появлений)"), proofs,
        d.families.length ? el("p", { class: "muted" }, `Семейства по общим пруфам: ${d.families.map((f) => "#" + f.join(", #")).join(" | ")}`) : null),
      el("div", {}, el("h3", {}, `Посты (${d.posts.length})`), el("div", { class: "posts-col" }, posts)),
    ),
  );
}

function evidenceLine(e) {
  const cls = e.stop ? "stop" : e.source === "registry" || e.source === "graph" ? "ctx" : e.weight > 0 ? "pos" : "";
  const w = e.weight ? ` (${e.weight > 0 ? "+" : ""}${e.weight})` : "";
  return el("div", { class: "ev " + cls },
    el("span", {}, e.label + w), el("span", { class: "src" }, e.source),
    e.quote ? el("q", {}, e.quote) : null);
}

function renderPost(p, proofs) {
  const a = p.analysis || {};
  const ev = (a.evidence || []).slice(0, 12).map(evidenceLine);
  for (const art of p.artifacts || []) {
    if (art.kind !== "image") continue;
    const img = el("img", { alt: "пруф" });
    imageUrl(art.id).then((u) => { img.src = u; }).catch(() => {});
    proofs.append(el("div", { class: "thumb", onclick: () => openTimeline(art.id) }, img, el("div", { class: "cap" }, `#${p.id} · ${p.channel || ""}`)));
  }
  const related = el("button", { onclick: async () => {
    try {
      const { data, meta } = await api(`/api/v1/posts/${p.id}/related`);
      related.replaceWith(el("div", { class: "muted" }, `Связанные (${meta.total}): ` + data.map((r) => `#${r.id} ${r.channel || ""} [${LEVEL[r.level]}]`).join(", ")));
    } catch (err) { related.textContent = err.message; }
  } }, "Найти связанные");
  return el("div", { class: "post" },
    el("div", {}, el("b", {}, `#${p.id}`), " ", badge(p.level, p.score), " ", el("span", { class: "muted" }, `${p.channel || "—"} · ${(p.posted_at || "").slice(0, 16).replace("T", " ")}`)),
    a.summary ? el("div", {}, a.summary) : null,
    p.text ? el("div", { class: "text" }, p.text) : null,
    p.ocr_text ? el("details", {}, el("summary", {}, "Текст со скриншота (OCR)"), el("div", { class: "text" }, p.ocr_text)) : null,
    ev, (a.degraded || []).map((d) => el("div", { class: "banner" }, d.reason)), related);
}

async function exportCase(key) {
  try {
    const res = await api(`/api/v1/cases/${encodeURIComponent(key)}/export`, { raw: true });
    const url = URL.createObjectURL(await res.blob());
    const a = el("a", { href: url, download: `pruf_${key}.zip` });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  } catch (err) { alert("Экспорт не удался: " + err.message); }
}

// ---------------- граф (простая силовая укладка) ----------------
// 37 копий одного пруфа дают 666 рёбер «общий пруф»: рисуем только остовное дерево,
// связность та же, а граф читается.
function sparseReuse(edges) {
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

function graphSvg(g) {
  const W = 640, H = 360, NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("class", "graph");
  const nodes = g.nodes.map((n, i) => ({ ...n, x: W / 2 + 150 * Math.cos(i), y: H / 2 + 120 * Math.sin(i), vx: 0, vy: 0 }));
  const idx = new Map(nodes.map((n, i) => [n.id, i]));
  const edges = sparseReuse(g.edges.filter((e) => idx.has(e.source) && idx.has(e.target)))
    .map((e) => ({ ...e, s: idx.get(e.source), t: idx.get(e.target) }));
  for (let it = 0; it < 300; it++) {
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i], b = nodes[j];
        let dx = a.x - b.x, dy = a.y - b.y; const d2 = dx * dx + dy * dy + 0.01;
        const f = 900 / d2; dx *= f; dy *= f;
        a.vx += dx; a.vy += dy; b.vx -= dx; b.vy -= dy;
      }
    }
    for (const e of edges) {
      const a = nodes[e.s], b = nodes[e.t];
      const dx = b.x - a.x, dy = b.y - a.y; const d = Math.sqrt(dx * dx + dy * dy) + 0.01;
      const f = (d - 60) * 0.02;
      a.vx += dx / d * f; a.vy += dy / d * f; b.vx -= dx / d * f; b.vy -= dy / d * f;
    }
    for (const n of nodes) {
      n.vx += (W / 2 - n.x) * 0.002; n.vy += (H / 2 - n.y) * 0.002;
      n.x = Math.max(12, Math.min(W - 12, n.x + n.vx * 0.5)); n.y = Math.max(12, Math.min(H - 12, n.y + n.vy * 0.5));
      n.vx *= 0.6; n.vy *= 0.6;
    }
  }
  for (const e of edges) {
    const line = document.createElementNS(NS, "line");
    const a = nodes[e.s], b = nodes[e.t];
    line.setAttribute("x1", a.x); line.setAttribute("y1", a.y); line.setAttribute("x2", b.x); line.setAttribute("y2", b.y);
    line.setAttribute("stroke", e.type === "reuses" ? "#ff1744" : e.type === "mentions" ? "#c62828" : "#9aa0a6");
    line.setAttribute("stroke-width", e.type === "reuses" ? 2 : 1);
    if (e.type === "posted_in") line.setAttribute("stroke-dasharray", "3 3");
    svg.append(line);
  }
  for (const n of nodes) {
    const c = document.createElementNS(NS, "circle");
    c.setAttribute("cx", n.x); c.setAttribute("cy", n.y);
    c.setAttribute("r", n.type === "post" ? 7 : 6);
    const levelColor = n.level === "high" ? "#c62828" : n.level === "medium" ? "#e08a00" : "#2e7d32";
    c.setAttribute("fill", n.type === "post" ? levelColor : COLORS[n.type] || "#999");
    if (n.type === "requisite") c.setAttribute("stroke", "#000");
    const title = document.createElementNS(NS, "title");
    title.textContent = n.label || n.channel || n.id;
    c.append(title);
    svg.append(c);
    if (n.type !== "post") {
      const t = document.createElementNS(NS, "text");
      t.setAttribute("x", n.x + 8); t.setAttribute("y", n.y + 3);
      t.textContent = String(n.label || "").slice(0, 22);
      svg.append(t);
    }
  }
  return svg;
}

// ---------------- таймлайн пруфа ----------------
function boxes(changes, which) {
  return (changes || []).filter((c) => (c.kind === "amount" || c.kind === "date") && c[which])
    .map((c) => {
      const [x0, y0, x1, y1] = c[which];
      return el("div", { class: "box", style: `left:${x0 * 100}%;top:${y0 * 100}%;width:${(x1 - x0) * 100}%;height:${(y1 - y0) * 100}%`, title: `${c.before} → ${c.after}` });
    });
}

async function openTimeline(artifactId) {
  const content = $("#modal-content");
  content.replaceChildren(el("p", {}, "Загрузка таймлайна…"));
  $("#modal").classList.remove("hidden");
  try {
    const { data } = await api(`/api/v1/artifacts/${artifactId}/timeline`);
    const edited = data.items.filter((i) => i.diff && (i.diff.changes || []).some((c) => c.kind === "amount" || c.kind === "date"));
    const items = data.items.map((item) => {
      const img = el("img", { alt: "копия пруфа" });
      imageUrl(item.artifact_id).then((u) => { img.src = u; }).catch(() => {});
      const changes = item.diff ? item.diff.changes : [];
      const digitChanges = (changes || []).filter((c) => c.kind === "amount" || c.kind === "date");
      const isEdited = digitChanges.length > 0;
      return el("div", { class: "tl-item" + (item.is_root ? " root" : "") + (isEdited ? " edited" : "") },
        el("div", { class: "shot" }, img, boxes(changes, "box_after")),
        el("div", {}, el("b", {}, (item.post.posted_at || "").slice(0, 10)), " ", badge(item.post.level, item.post.score)),
        el("div", { class: "muted" }, `${item.post.channel || "—"} · пост #${item.post.id}`),
        item.is_root ? el("div", { class: "muted" }, "выбранная копия") : null,
        digitChanges.map((c) => el("div", { class: "diff" }, `${c.before} → ${c.after}`)),
      );
    });
    content.replaceChildren(
      el("h2", {}, `Пруф встречается ${data.appearances} раз`),
      el("p", { class: "muted" }, `Копий с изменёнными суммами или датами: ${edited.length}. Красная рамка показывает отличающиеся цифры относительно выбранной копии.`),
      el("div", { class: "timeline" }, items),
    );
  } catch (err) { showError(content, err); }
}

// ---------------- проверка ----------------
async function submitCheck(ev) {
  ev.preventDefault();
  const out = $("#check-result");
  out.replaceChildren(el("p", { class: "muted" }, "Анализ…"));
  const text = $("#check-text").value.trim();
  const files = $("#check-files").files;
  const store = $("#check-store").checked;
  try {
    let data;
    if (files.length || store) {
      const fd = new FormData();
      if (text) fd.append("text", text);
      if ($("#check-channel").value) fd.append("channel", $("#check-channel").value);
      fd.append("store", store ? "1" : "0");
      for (const f of files) fd.append("files", f);
      ({ data } = await api("/api/v1/analyze", { method: "POST", body: fd }));
    } else {
      ({ data } = await api("/api/v1/analyze/text", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text, store: false }) }));
      data = { analysis: data, proofs: [] };
    }
    renderCheck(data);
    loadStats(); loadCases();
  } catch (err) { showError(out, err); }
}

function renderCheck(data) {
  const a = data.analysis;
  const tracks = a.tracks.map((t) => el("div", {}, `${TRACK[t.track]}: ${t.score}`, t.capped_reason ? el("span", { class: "muted" }, ` (${t.capped_reason})`) : null,
    el("div", { class: "score-bar" }, el("div", { style: `width:${t.score}%;background:${t.level === "high" ? "var(--high)" : t.level === "medium" ? "var(--medium)" : "var(--low)"}` }))));
  const proofs = (data.proofs || []).map((p) => el("div", { class: "post" },
    el("b", {}, `Пруф: найдено появлений в реестре: ${p.match_count}`),
    p.match_count ? el("button", { onclick: () => openTimeline(p.artifact_id) }, "Открыть таймлайн") : null,
    p.matches.flatMap((m) => m.changes.filter((c) => c.kind === "amount" || c.kind === "date")).slice(0, 5).map((c) => el("div", { class: "diff" }, `${c.before} → ${c.after}`))));
  $("#check-result").replaceChildren(
    el("h2", {}, "Риск ", badge(a.level, a.score), a.track ? el("span", {}, " ", chips([a.track])) : null),
    el("p", {}, a.summary),
    (a.degraded || []).map((d) => el("div", { class: "banner" }, d.reason)),
    el("div", { class: "grid2" }, el("div", {}, el("h3", {}, "Признаки"), a.evidence.map(evidenceLine)),
      el("div", {}, el("h3", {}, "Баллы по трекам"), tracks, proofs,
        a.requisites.length ? el("p", {}, "Реквизиты: " + a.requisites.map((r) => r.display).join(", ")) : null,
        data.post_id ? el("p", { class: "muted" }, `Сохранено как пост #${data.post_id}`) : null)),
  );
}

// ---------------- реквизиты ----------------
async function loadBank() {
  const tbody = $("#bank-rows");
  try {
    const { data } = await api("/api/v1/bank/requisites?limit=200");
    tbody.replaceChildren(...data.map((r) => el("tr", {},
      el("td", {}, r.type), el("td", {}, r.value), el("td", {}, Math.round(r.max_score)), el("td", {}, r.posts),
      el("td", {}, chips(r.tracks)), el("td", {}, r.cases.join(", ")), el("td", {}, (r.last_seen || "").slice(0, 10)))));
  } catch (err) {
    tbody.replaceChildren(el("tr", {}, el("td", { colspan: 7, class: "err" }, err.message + " (нужен токен банка или режим разработки)")));
  }
}

// ---------------- навигация ----------------
function switchView(name) {
  document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("hidden", v.id !== "view-" + name));
  if (name === "bank") loadBank();
}

function init() {
  $("#token").value = token();
  $("#token").addEventListener("change", (e) => {
    try { sessionStorage.setItem("pruf_token", e.target.value.trim()); } catch { /* приватный режим */ }
    loadStats(); loadCases();
  });
  document.querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => switchView(b.dataset.view)));
  ["#f-level", "#f-track", "#f-status"].forEach((id) => $(id).addEventListener("change", loadCases));
  $("#check-form").addEventListener("submit", submitCheck);
  $("#modal-close").addEventListener("click", () => $("#modal").classList.add("hidden"));
  $("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") $("#modal").classList.add("hidden"); });
  loadStats();
  loadCases();
}

init();
