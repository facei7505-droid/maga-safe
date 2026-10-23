// ПРУФ: дашборд аналитика. Без сборки и внешних библиотек.
// Весь текст из постов выводится только через textContent (посты недоверенные).
import { graphView } from "./graph.js";
import {
  $, LEVEL, REQ_TYPE, SOURCE, STATUS, TRACK, api, badge, chips, day, el, lazyImg, releaseImages, showError, toast, token, when,
} from "./lib.js";
import { loadOverview } from "./overview.js";

const POSTS_PAGE = 12;
const state = { cases: [], current: null, view: "overview" };

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
    $("#cases-total").textContent = `Кейсов: ${meta.total}`;
    renderQueue();
  } catch (err) {
    showError(list, err);
  }
}

function caseMatches(c, q) {
  if (!q) return true;
  const hay = [c.key, ...c.channels, ...c.requisites, ...c.domains].join(" ").toLowerCase();
  return hay.includes(q);
}

function renderQueue() {
  const q = $("#f-search").value.trim().toLowerCase();
  const shown = state.cases.filter((c) => caseMatches(c, q));
  const list = $("#cases");
  if (!shown.length) {
    list.replaceChildren(el("p", { class: "muted" }, state.cases.length ? "Ничего не найдено." : "Кейсов нет. Загрузите посты через «Проверить» или scripts/seed_demo.py."));
    return;
  }
  list.replaceChildren(...shown.map(caseItem));
}

function caseItem(c) {
  const li = el("li", { "data-key": c.key, tabindex: 0, onclick: () => openCase(c.key), onkeydown: (e) => { if (e.key === "Enter") openCase(c.key); } },
    el("div", { class: "case-top" }, el("span", {}, badge(c.level, c.score), " ", el("b", {}, c.key), " ", el("span", { class: "status-pill " + c.status }, STATUS[c.status] || c.status)),
      el("span", { class: "prio", title: "Приоритет: риск, охват каналов, связь треков, повтор пруфа, скорость, реквизиты" }, `приоритет ${Math.round(c.priority)}`)),
    el("div", {}, chips(c.tracks)),
    c.priority_reasons && c.priority_reasons.length ? el("div", { class: "reasons" }, c.priority_reasons.map((r) => el("span", {}, r))) : null,
    el("div", { class: "meta" }, `${c.size} постов · ${c.channels.length} каналов · семейств пруфов: ${c.families}`),
    c.requisites.length ? el("div", { class: "meta" }, "Реквизиты: " + c.requisites.slice(0, 3).join(", ")) : null,
  );
  if (state.current === c.key) li.classList.add("active");
  return li;
}

function moveSelection(delta) {
  const items = [...document.querySelectorAll(".case-list li")];
  if (!items.length) return;
  const i = items.findIndex((li) => li.dataset.key === state.current);
  const next = items[Math.max(0, Math.min(items.length - 1, i + delta))];
  next.scrollIntoView({ block: "nearest" });
  openCase(next.dataset.key);
}

// ---------------- карточка кейса ----------------
async function openCase(key) {
  if (state.view !== "queue") switchView("queue");
  state.current = key;
  releaseImages();
  history.replaceState(null, "", "#case/" + encodeURIComponent(key));
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

function statusControls(c, d) {
  const statusSel = el("select", { "aria-label": "Статус кейса" }, ...Object.entries(STATUS).map(([v, label]) => {
    const o = el("option", { value: v }, label);
    if (v === d.status.status) o.selected = true;
    return o;
  }));
  const note = el("input", { placeholder: "Заметка аналитика", value: d.status.note || "", maxlength: 1000 });
  const save = el("button", { onclick: async () => {
    try {
      await api("/api/v1/cases/" + encodeURIComponent(c.key), {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: statusSel.value, note: note.value || null }),
      });
      loadCases();
      toast(`Кейс ${c.key}: ${STATUS[statusSel.value]}`, "ok");
    } catch (err) { toast(err.message, "bad"); }
  } }, "Сохранить статус");
  const exportBtn = el("button", { class: "primary", onclick: () => exportCase(c.key) }, "Пакет доказательств (ZIP)");
  const report = el("a", { class: "button", href: `/static/report.html#${encodeURIComponent(c.key)}`, target: "_blank" }, "Отчёт для печати");
  return el("div", { class: "actions" }, statusSel, note, save, exportBtn, report);
}

function caseFacts(c, d) {
  const images = d.posts.flatMap((p) => (p.artifacts || []).filter((a) => a.kind === "image"));
  const fact = (v, l) => el("div", { class: "fact" }, el("b", {}, v), el("span", {}, l));
  const days = c.first_seen && c.last_seen ? Math.max(1, Math.round((new Date(c.last_seen) - new Date(c.first_seen)) / 86400000)) : "?";
  return el("div", { class: "facts" },
    fact(c.size, "постов"), fact(c.channels.length, "каналов"), fact(c.requisites.length, "реквизитов"),
    fact(images.length, "скринов"), fact(c.families, "семейств пруфов"), fact(days, "дней активности"));
}

function renderCase(d) {
  const c = d.case;
  const postsCol = el("div", { class: "posts-col" });
  const posts = d.posts.map(renderPost);
  const showPosts = (n) => {
    postsCol.replaceChildren(...posts.slice(0, n));
    if (posts.length > n) postsCol.append(el("button", { class: "more", onclick: () => showPosts(n + POSTS_PAGE * 3) }, `Показать ещё (${posts.length - n})`));
  };
  showPosts(POSTS_PAGE);
  const jumpToPost = (id) => {
    const i = d.posts.findIndex((p) => p.id === id);
    if (i < 0) return;
    if (!posts[i].isConnected) showPosts(i + POSTS_PAGE);
    posts[i].scrollIntoView({ behavior: "smooth", block: "center" });
    posts[i].classList.remove("flash"); void posts[i].offsetWidth; posts[i].classList.add("flash");
  };

  $("#case").replaceChildren(
    el("div", { class: "case-head" },
      el("div", {},
        el("h2", {}, `Кейс ${c.key} `, badge(c.level, c.score)),
        el("div", {}, chips(c.tracks)),
        el("div", { class: "muted" }, `${day(c.first_seen) || "?"} — ${day(c.last_seen) || "?"}`),
      ),
      statusControls(c, d),
    ),
    caseFacts(c, d),
    el("div", { class: "kv" },
      el("div", {}, el("span", { class: "muted" }, "Реквизиты: "), c.requisites.join(", ") || "—"),
      el("div", {}, el("span", { class: "muted" }, "Каналы: "), c.channels.join(", ") || "—"),
      c.domains.length ? el("div", {}, el("span", { class: "muted" }, "Домены: "), c.domains.join(", ")) : null,
    ),
    el("p", { class: "note" }, "Система показывает признаки, а не вердикт. Решение по кейсу принимает аналитик."),
    el("div", { class: "grid2" },
      el("div", {},
        el("h3", {}, "Граф связей ", el("span", { class: "muted small" }, "наведите на узел, клик по посту — к посту")),
        graphView(d.graph, jumpToPost),
        el("h3", {}, "Пруфы по семействам ", el("span", { class: "muted small" }, "клик — таймлайн появлений")),
        proofFamilies(d)),
      el("div", {}, el("h3", {}, `Посты (${d.posts.length})`), postsCol),
    ),
  );
}

// Одна карточка на семейство вместо десятков одинаковых превью
function proofFamilies(d) {
  const famOf = new Map();
  d.families.forEach((f, i) => f.forEach((pid) => famOf.set(pid, i)));
  const groups = new Map();
  for (const p of d.posts) {
    for (const art of p.artifacts || []) {
      if (art.kind !== "image") continue;
      const key = famOf.has(p.id) ? "f" + famOf.get(p.id) : "a" + art.id;
      if (!groups.has(key)) groups.set(key, { arts: [], channels: new Set(), first: p.posted_at, last: p.posted_at });
      const g = groups.get(key);
      g.arts.push(art);
      if (p.channel) g.channels.add(p.channel);
      if (p.posted_at && (!g.first || p.posted_at < g.first)) g.first = p.posted_at;
      if (p.posted_at && (!g.last || p.posted_at > g.last)) g.last = p.posted_at;
    }
  }
  if (!groups.size) return el("p", { class: "muted" }, "В кейсе нет скриншотов.");
  const sorted = [...groups.values()].sort((a, b) => b.arts.length - a.arts.length);
  return el("div", { class: "families" }, sorted.map((g) => {
    const art = g.arts[0];
    return el("button", { class: "family", onclick: () => openTimeline(art.id), title: "Открыть таймлайн" },
      el("div", { class: "stack" + (g.arts.length > 1 ? " many" : "") }, lazyImg(art.id, "пруф")),
      el("div", { class: "family-cap" },
        g.arts.length > 1 ? el("b", { class: "copies" }, `×${g.arts.length} копий`) : el("b", {}, "1 копия"),
        el("div", { class: "muted" }, `${g.channels.size} каналов · ${day(g.first)} — ${day(g.last)}`)));
  }));
}

// Признак ловит основу слова («розыгр»), а подсвечиваем слово целиком
const LETTER = /[\p{L}\p{N}]/u;
function wholeWords(text, s, e) {
  while (s > 0 && LETTER.test(text[s - 1])) s--;
  while (e < text.length && LETTER.test(text[e])) e++;
  return { s, e };
}

// Подсветка найденных признаков прямо в тексте: span указывает на исходный текст
function highlighted(text, evidence, source) {
  const spans = (evidence || [])
    .filter((e) => e.source === source && Array.isArray(e.span) && e.span[1] > e.span[0] && e.span[1] <= text.length)
    .map((e) => ({ ...wholeWords(text, e.span[0], e.span[1]), ev: e }))
    .sort((a, b) => a.s - b.s || b.e - a.e);
  const out = [];
  let pos = 0;
  for (const sp of spans) {
    if (sp.s < pos) continue;
    if (sp.s > pos) out.push(text.slice(pos, sp.s));
    const cls = sp.ev.stop ? "hl stop" : "hl";
    out.push(el("mark", { class: cls, title: `${sp.ev.label}${sp.ev.weight ? ` (${sp.ev.weight > 0 ? "+" : ""}${sp.ev.weight})` : ""}` }, text.slice(sp.s, sp.e)));
    pos = sp.e;
  }
  out.push(text.slice(pos));
  return el("div", { class: "text" }, out);
}

// Один признак может сработать в нескольких местах: показываем строку один раз со всеми цитатами
function groupEvidence(evidence) {
  const groups = new Map();
  for (const e of evidence || []) {
    const key = `${e.feature_id}|${e.source}`;
    if (!groups.has(key)) groups.set(key, { ...e, quotes: [] });
    if (e.quote && !groups.get(key).quotes.includes(e.quote)) groups.get(key).quotes.push(e.quote);
  }
  return [...groups.values()];
}

function evidenceLine(e) {
  const cls = e.stop ? "stop" : e.source === "registry" || e.source === "graph" ? "ctx" : e.weight > 0 ? "pos" : "";
  const w = e.weight ? ` (${e.weight > 0 ? "+" : ""}${e.weight})` : "";
  return el("div", { class: "ev " + cls },
    el("span", {}, e.label + w), el("span", { class: "src" }, SOURCE[e.source] || e.source),
    (e.quotes || (e.quote ? [e.quote] : [])).map((q) => el("q", {}, q)));
}

function renderPost(p) {
  const a = p.analysis || {};
  const grouped = groupEvidence(a.evidence);
  const ev = grouped.slice(0, 12).map(evidenceLine);
  const related = el("button", { class: "link", onclick: async () => {
    try {
      const { data, meta } = await api(`/api/v1/posts/${p.id}/related`);
      related.replaceWith(el("div", { class: "muted" }, `Связанные (${meta.total}): ` + data.map((r) => `#${r.id} ${r.channel || ""} [${LEVEL[r.level]}]`).join(", ")));
    } catch (err) { related.textContent = err.message; }
  } }, "Найти связанные");
  const thumbs = (p.artifacts || []).filter((x) => x.kind === "image").map((art) =>
    el("button", { class: "mini-thumb", onclick: () => openTimeline(art.id), title: "Таймлайн пруфа" }, lazyImg(art.id, "скрин")));
  return el("div", { class: "post", "data-post": p.id },
    el("div", {}, el("b", {}, `#${p.id}`), " ", badge(p.level, p.score), " ", el("span", { class: "muted" }, `${p.channel || "—"} · ${when(p.posted_at)}`)),
    a.summary ? el("div", { class: "summary" }, a.summary) : null,
    p.text ? highlighted(p.text, a.evidence, "text") : null,
    thumbs.length ? el("div", { class: "mini-thumbs" }, thumbs) : null,
    p.ocr_text ? el("details", {}, el("summary", {}, "Текст со скриншота (OCR)"), highlighted(p.ocr_text, a.evidence, "ocr")) : null,
    el("details", { class: "evidence" }, el("summary", {}, `Признаки (${grouped.length})`), ev),
    (a.degraded || []).map((x) => el("div", { class: "banner" }, x.reason)), related);
}

async function exportCase(key) {
  try {
    const res = await api(`/api/v1/cases/${encodeURIComponent(key)}/export`, { raw: true });
    const url = URL.createObjectURL(await res.blob());
    const a = el("a", { href: url, download: `pruf_${key}.zip` });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
    toast("Пакет доказательств скачан", "ok");
  } catch (err) { toast("Экспорт не удался: " + err.message, "bad"); }
}

// ---------------- таймлайн пруфа ----------------
function boxes(changes, which) {
  return (changes || []).filter((c) => (c.kind === "amount" || c.kind === "date") && c[which])
    .map((c) => {
      const [x0, y0, x1, y1] = c[which];
      return el("div", { class: "box", style: `left:${x0 * 100}%;top:${y0 * 100}%;width:${(x1 - x0) * 100}%;height:${(y1 - y0) * 100}%`, title: `${c.before} → ${c.after}` });
    });
}

const digitChanges = (item) => ((item.diff && item.diff.changes) || []).filter((c) => c.kind === "amount" || c.kind === "date");

async function openTimeline(artifactId) {
  const content = $("#modal-content");
  content.replaceChildren(el("p", {}, "Загрузка таймлайна…"));
  $("#modal").classList.remove("hidden");
  $("#modal-close").focus();
  try {
    const { data } = await api(`/api/v1/artifacts/${artifactId}/timeline`);
    const edited = data.items.filter((i) => digitChanges(i).length);
    const onlyEdited = el("input", { type: "checkbox" });
    const grid = el("div", { class: "timeline" });
    const draw = () => grid.replaceChildren(...data.items.filter((i) => !onlyEdited.checked || i.is_root || digitChanges(i).length).map(timelineItem));
    onlyEdited.addEventListener("change", draw);
    draw();
    const channels = new Set(data.items.map((i) => i.post.channel).filter(Boolean));
    content.replaceChildren(
      el("h2", {}, `Пруф встречается ${data.appearances} раз`),
      el("p", { class: "muted" }, `${channels.size} каналов · ${day(data.items[0] && data.items[0].post.posted_at)} — ${day(data.items.length && data.items[data.items.length - 1].post.posted_at)}. Копий с изменёнными суммами или датами: ${edited.length}. Красная рамка показывает отличающиеся цифры относительно выбранной копии.`),
      edited.length ? el("label", { class: "inline" }, onlyEdited, "только копии с правками") : null,
      grid,
    );
  } catch (err) { showError(content, err); }
}

function timelineItem(item) {
  const changes = digitChanges(item);
  return el("div", { class: "tl-item" + (item.is_root ? " root" : "") + (changes.length ? " edited" : "") },
    el("div", { class: "shot" }, lazyImg(item.artifact_id, "копия пруфа"), boxes(changes, "box_after")),
    el("div", {}, el("b", {}, day(item.post.posted_at)), " ", badge(item.post.level, item.post.score)),
    el("div", { class: "muted" }, `${item.post.channel || "—"} · пост #${item.post.id}`),
    item.is_root ? el("div", { class: "muted" }, "выбранная копия") : null,
    changes.map((c) => el("div", { class: "diff" }, `${c.before} → ${c.after}`)),
  );
}

function closeModal() {
  $("#modal").classList.add("hidden");
}

// ---------------- проверка ----------------
const EXAMPLES = {
  "Розыгрыш": "Поздравляем! Вы выиграли iPhone 15 в нашем розыгрыше 🎁 Для получения приза оплатите доставку 5000 тг на Kaspi +7 747 318 52 64 и пришлите чек в лс",
  "Казино (kk)": "Кеше 2000 салып 180 000 ұтып алдым 😱 Сілтеме профильде, промокод BONUS777 — депозитке +200% фриспин",
  "Пирамида (translit)": "Vlozhi 10 000 tg i poluchi 30 000 cherez nedelyu! Priglasi 3 druzei i dohod udvoitsya. Perevod na kaspi.kz/pay/invest1507",
  "Легальный": "Розыгрыш без взноса: подпишитесь на канал и отметьте друга. Итоги 1 ноября в прямом эфире, официальные правила по ссылке на сайте магазина.",
};

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
    renderCheck(data, text);
    loadStats(); loadCases();
  } catch (err) { showError(out, err); }
}

function gauge(score, level) {
  return el("div", { class: "gauge " + level, style: `--p:${Math.max(0, Math.min(100, score))}` },
    el("div", { class: "gauge-v" }, Math.round(score)), el("div", { class: "gauge-l" }, LEVEL[level] || level));
}

function renderCheck(data, text) {
  const a = data.analysis;
  const tracks = a.tracks.map((t) => el("div", { class: "track-score" }, el("span", {}, `${TRACK[t.track]}: ${t.score}`), t.capped_reason ? el("span", { class: "muted" }, ` (${t.capped_reason})`) : null,
    el("div", { class: "score-bar" }, el("div", { class: t.level, style: `width:${t.score}%` }))));
  const proofs = (data.proofs || []).map((p) => el("div", { class: "post" },
    el("b", {}, `Пруф: найдено появлений в реестре: ${p.match_count}`),
    p.match_count ? el("button", { onclick: () => openTimeline(p.artifact_id) }, "Открыть таймлайн") : null,
    p.matches.flatMap((m) => m.changes.filter((c) => c.kind === "amount" || c.kind === "date")).slice(0, 5).map((c) => el("div", { class: "diff" }, `${c.before} → ${c.after}`))));
  $("#check-result").replaceChildren(
    el("div", { class: "check-head" }, gauge(a.score, a.level),
      el("div", {}, el("h2", {}, "Риск ", badge(a.level, a.score), a.track ? el("span", {}, " ", chips([a.track])) : null), el("p", {}, a.summary))),
    (a.degraded || []).map((d) => el("div", { class: "banner" }, d.reason)),
    text ? el("div", {}, el("h3", {}, "Где найдены признаки"), highlighted(text, a.evidence, "text")) : null,
    el("div", { class: "grid2" }, el("div", {}, el("h3", {}, "Признаки"), groupEvidence(a.evidence).map(evidenceLine)),
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
    state.bank = data;
    renderBank();
  } catch (err) {
    tbody.replaceChildren(el("tr", {}, el("td", { colspan: 7, class: "err" }, err.message + " (нужен токен банка или режим разработки)")));
  }
}

function renderBank() {
  const q = $("#bank-search").value.trim().toLowerCase();
  const rows = (state.bank || []).filter((r) => !q || r.value.toLowerCase().includes(q) || r.cases.join(" ").toLowerCase().includes(q));
  $("#bank-rows").replaceChildren(...rows.map((r) => el("tr", {},
    el("td", {}, el("span", { class: "req-type" }, REQ_TYPE[r.type] || r.type)), el("td", { class: "mono" }, r.value), el("td", {}, Math.round(r.max_score)), el("td", {}, r.posts),
    el("td", {}, chips(r.tracks)), el("td", {}, r.cases.map((k) => el("button", { class: "link", onclick: () => openCase(k) }, k))), el("td", {}, day(r.last_seen)))));
}

async function bankCheck(ev) {
  ev.preventDefault();
  const out = $("#bank-check-result");
  const value = $("#bank-value").value.trim();
  if (!value) return;
  try {
    const { data } = await api("/api/v1/bank/check", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ value }) });
    out.replaceChildren(data.found
      ? el("div", { class: "verdict hit" }, el("b", {}, `⚠ ${REQ_TYPE[data.type] || data.type} ${data.value} встречается в ${data.posts} постах с признаками схем`),
        el("div", {}, chips(data.tracks), ` · макс. балл ${Math.round(data.max_score)} · впервые ${day(data.first_seen)}`), el("div", { class: "muted" }, data.note))
      : el("div", { class: "verdict clean" }, el("b", {}, `✓ ${REQ_TYPE[data.type] || data.type} не встречался в постах с признаками схем`), el("div", { class: "muted" }, "Отсутствие в реестре не гарантирует безопасность.")));
  } catch (err) { showError(out, err); }
}

// ---------------- навигация ----------------
function switchView(name) {
  state.view = name;
  document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("hidden", v.id !== "view-" + name));
  if (name === "bank") loadBank();
  if (name === "overview") loadOverview(openCase);
  if (name !== "queue") history.replaceState(null, "", "#" + name);
}

function onKey(e) {
  if (e.key === "Escape") { closeModal(); return; }
  if (e.target.closest("input, textarea, select") || !$("#modal").classList.contains("hidden")) return;
  if (state.view === "queue" && (e.key === "j" || e.key === "ArrowDown")) { e.preventDefault(); moveSelection(1); }
  if (state.view === "queue" && (e.key === "k" || e.key === "ArrowUp")) { e.preventDefault(); moveSelection(-1); }
  if (e.key === "/") { e.preventDefault(); switchView("queue"); $("#f-search").focus(); }
}

function init() {
  $("#token").value = token();
  $("#token").addEventListener("change", (e) => {
    try { sessionStorage.setItem("pruf_token", e.target.value.trim()); } catch { /* приватный режим */ }
    loadStats(); loadCases();
    if (state.view === "overview") loadOverview(openCase);
  });
  document.querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => switchView(b.dataset.view)));
  ["#f-level", "#f-track", "#f-status"].forEach((id) => $(id).addEventListener("change", loadCases));
  $("#f-search").addEventListener("input", renderQueue);
  $("#bank-search").addEventListener("input", renderBank);
  $("#bank-form").addEventListener("submit", bankCheck);
  $("#check-form").addEventListener("submit", submitCheck);
  $("#examples").replaceChildren(...Object.entries(EXAMPLES).map(([label, text]) =>
    el("button", { type: "button", class: "chip-btn", onclick: () => { $("#check-text").value = text; $("#check-store").checked = false; } }, label)));
  $("#modal-close").addEventListener("click", closeModal);
  $("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") closeModal(); });
  document.addEventListener("keydown", onKey);
  loadStats();
  loadCases();
  const hash = decodeURIComponent(location.hash.slice(1));
  if (hash.startsWith("case/")) openCase(hash.slice(5));
  else switchView(["queue", "check", "bank"].includes(hash) ? hash : "overview");
}

init();
