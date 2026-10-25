// ПРУФ: общие помощники дашборда. Весь текст из постов выводится только через textContent.

export const TRACK = { lottery: "Розыгрыши", casino: "Казино", pyramid: "Пирамиды" };
export const LEVEL = { high: "высокий", medium: "средний", low: "низкий" };
export const STATUS = { new: "Новый", in_review: "В работе", confirmed: "Подтверждён", dismissed: "Отклонён" };
export const REQ_TYPE = { phone: "Телефон", card: "Карта", iban: "IBAN", kaspi_link: "Ссылка Kaspi", promo: "Промокод" };
export const SOURCE = { text: "текст", ocr: "скрин", voice: "голос", link: "ссылка", registry: "реестр", graph: "граф", ml: "ML", llm: "LLM" };
export const NS = "http://www.w3.org/2000/svg";

export const $ = (sel, root = document) => root.querySelector(sel);

export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  setAttrs(node, attrs);
  appendAll(node, children);
  return node;
}

export function svgEl(tag, attrs = {}, ...children) {
  const node = document.createElementNS(NS, tag);
  setAttrs(node, attrs);
  appendAll(node, children);
  return node;
}

function setAttrs(node, attrs) {
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") node.setAttribute("class", v);
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
}

function appendAll(node, children) {
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}

export function token() {
  // sessionStorage: токен живёт до закрытия вкладки и не остаётся в браузере надолго
  try { return sessionStorage.getItem("pruf_token") || ""; } catch { return ""; }
}

export async function api(path, opts = {}) {
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

// Картинки грузим с токеном и держим как blob-URL; освобождаем при смене кейса
const blobUrls = [];
export async function imageUrl(artifactId) {
  const res = await api(`/api/v1/artifacts/${artifactId}/file`, { raw: true });
  const url = URL.createObjectURL(await res.blob());
  blobUrls.push(url);
  return url;
}
export function releaseImages() {
  for (const url of blobUrls.splice(0)) URL.revokeObjectURL(url);
}
export function lazyImg(artifactId, alt) {
  const img = el("img", { alt, loading: "lazy" });
  imageUrl(artifactId).then((u) => { img.src = u; }).catch(() => img.classList.add("broken"));
  return img;
}

export function badge(level, score) {
  return el("span", { class: "badge " + level }, `${LEVEL[level] || level} · ${Math.round(score)}`);
}

export function chips(tracks) {
  return (tracks || []).filter(Boolean).map((t) => el("span", { class: "chip " + t }, TRACK[t] || t));
}

export function showError(target, err) {
  target.replaceChildren(el("p", { class: "err" }, "Ошибка: " + err.message));
}

export const day = (iso) => (iso || "").slice(0, 10);
export const when = (iso) => (iso || "").slice(0, 16).replace("T", " ");

// Один всплывающий тултип на страницу: графики и граф показывают в нём подробности
let tipNode = null;
export function tip(evt, lines) {
  if (!tipNode) { tipNode = el("div", { class: "tip", role: "tooltip" }); document.body.append(tipNode); }
  tipNode.replaceChildren(...lines.map((l, i) => el(i ? "div" : "b", {}, l)));
  tipNode.classList.add("on");
  const pad = 14, r = tipNode.getBoundingClientRect();
  const x = Math.min(evt.clientX + pad, window.innerWidth - r.width - 8);
  const y = evt.clientY + pad + r.height > window.innerHeight ? evt.clientY - r.height - pad : evt.clientY + pad;
  tipNode.style.left = x + "px";
  tipNode.style.top = y + "px";
}
export function untip() { if (tipNode) tipNode.classList.remove("on"); }

export function toast(text, kind = "") {
  const t = el("div", { class: "toast " + kind }, text);
  document.body.append(t);
  setTimeout(() => t.classList.add("out"), 2200);
  setTimeout(() => t.remove(), 2700);
}
