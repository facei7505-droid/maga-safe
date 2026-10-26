// ПРУФ: язык дашборда (ru / kk). Ключ перевода — сама русская строка, поэтому код вкладок не меняется:
// el() переводит строки-детей и подписи, статичная страница переводится один раз при загрузке.
// Строки с числами — шаблоны: {n} совпадает только с числом, {s} — с короткой подписью. Текст постов и цитаты
// под шаблоны не попадают, и в режиме ru ничего не трогается.
import { KK, KK_TEMPLATES } from "./i18n-kk.js";

const STORE_KEY = "pruf.lang";
export const LANGS = { ru: "Русский", kk: "Қазақша" };

function readLang() {
  try {
    const saved = localStorage.getItem(STORE_KEY);
    return saved in LANGS ? saved : "ru";
  } catch {
    return "ru";
  }
}

export const lang = readLang();
let featureLabels = {};

export function setLang(next) {
  try { localStorage.setItem(STORE_KEY, next); } catch { /* приватный режим: язык не запомнится */ }
  location.reload();
}

const NUM = "([0-9][0-9\\s.,]*)";
const SHORT = "([^\\n]{1,300}?)";
const compiled = KK_TEMPLATES.map(([ru, kk]) => {
  const body = ru.split(/(\{[ns]\})/).map((part) => {
    if (part === "{n}" || part === "{s}") return part === "{n}" ? NUM : SHORT;
    return part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }).join("");
  return { re: new RegExp(`^${body}$`), kk };
});

// Перевод строки интерфейса; в режиме ru и для незнакомых строк — как есть.
export function t(text) {
  if (lang !== "kk" || typeof text !== "string" || !text.trim()) return text;
  const lead = text.match(/^\s*/)[0], tail = text.match(/\s*$/)[0];
  const core = text.trim();
  if (core in KK) return lead + KK[core] + tail;
  if (core.length > 400) return text;
  for (const { re, kk } of compiled) {
    const m = core.match(re);
    if (m) return lead + kk.replace(/\{(\d)\}/g, (_, i) => t(m[Number(i) + 1])) + tail;
  }
  return text;
}

// Подпись признака: по коду признака, переводы из бота (pruf/bot/texts.py, LABELS_KK).
export function featureLabel(e) {
  if (lang !== "kk") return e.label;
  const id = String(e.feature_id || "");
  return featureLabels[id.startsWith("graph.requisite.") ? "graph.requisite" : id] || e.label;
}

const ATTRS = ["placeholder", "title", "aria-label"];

function translateTree(root) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const next = t(node.nodeValue);
    if (next !== node.nodeValue) node.nodeValue = next;
  }
  for (const elNode of root.querySelectorAll("[placeholder],[title],[aria-label]")) {
    for (const a of ATTRS) if (elNode.hasAttribute(a)) elNode.setAttribute(a, t(elNode.getAttribute(a)));
  }
}

// Один раз при загрузке: статичная разметка и подписи признаков с сервера.
export async function initI18n() {
  document.documentElement.lang = lang;
  if (lang !== "kk") return;
  translateTree(document.body);
  document.title = t(document.title);
  try {
    const res = await fetch("/api/v1/i18n/kk");
    if (res.ok) featureLabels = (await res.json()).data || {};
  } catch { /* без сети подписи признаков останутся по-русски */ }
}
