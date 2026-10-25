// ПРУФ Sentinel, service worker: запросы к API ПРУФ, чёрный список доменов в declarativeNetRequest,
// пункт меню «Проверить в ПРУФ» и счётчики для popup. Токен хранится только здесь, в chrome.storage.
importScripts("lib/extract.js");

const DEFAULT_API = "http://127.0.0.1:8000";
const BLACKLIST_ALARM = "pruf-blacklist";
const BLACKLIST_PERIOD_MIN = 60;
const MAX_REGEX_RULES = 1000; // лимит Chrome на regex-правила
const ALLOW_RULE_BASE = 100000; // id сессионных правил «всё равно перейти»
const REQUEST_TIMEOUT_MS = 8000;

async function settings() {
  const s = await chrome.storage.local.get({ apiUrl: DEFAULT_API, token: "" });
  return { apiUrl: s.apiUrl.replace(/\/+$/, ""), token: s.token };
}

async function api(path, options = {}) {
  const { apiUrl, token } = await settings();
  const headers = { "Content-Type": "application/json" };
  if (token) headers.Authorization = "Bearer " + token;
  const resp = await fetch(apiUrl + path, { ...options, headers, signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS) });
  const body = await resp.json().catch(() => null);
  if (!resp.ok || !body || !body.success) throw new Error((body && body.error) || `HTTP ${resp.status}`);
  return body;
}

async function bump(field, by = 1) {
  const stats = (await chrome.storage.local.get({ stats: { checked: 0, threats: 0, blocked: 0 } })).stats;
  stats[field] = (stats[field] || 0) + by;
  await chrome.storage.local.set({ stats });
}

async function inspect(payload) {
  const body = await api("/api/v1/inspect", { method: "POST", body: JSON.stringify(payload) });
  await bump("checked");
  if (body.data.show_banner) await bump("threats");
  return body.data;
}

// ---------- чёрный список доменов ----------
function escapeRegex(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function blacklistRules(domains) {
  const warning = chrome.runtime.getURL("warning.html");
  return domains.slice(0, MAX_REGEX_RULES).map((domain, i) => ({
    id: i + 1,
    priority: 1,
    action: { type: "redirect", redirect: { regexSubstitution: warning + "#\\0" } },
    condition: { regexFilter: `^https?://([a-z0-9-]+\\.)*${escapeRegex(domain)}([/:?#].*)?$`, resourceTypes: ["main_frame"] },
  }));
}

async function refreshBlacklist() {
  try {
    const body = await api("/api/v1/blacklist/domains");
    const domains = body.data.filter((d) => /^[a-z0-9.-]+\.[a-z]{2,63}$/.test(d));
    const old = await chrome.declarativeNetRequest.getDynamicRules();
    await chrome.declarativeNetRequest.updateDynamicRules({
      removeRuleIds: old.map((r) => r.id),
      addRules: blacklistRules(domains),
    });
    await chrome.storage.local.set({ blacklist: { count: domains.length, updated: new Date().toISOString(), error: null } });
  } catch (err) {
    const prev = (await chrome.storage.local.get({ blacklist: {} })).blacklist;
    await chrome.storage.local.set({ blacklist: { ...prev, error: String(err.message || err) } });
  }
}

async function allowOnce(domain) {
  // «Всё равно перейти»: правило allow до закрытия браузера, только для этого домена
  if (typeof domain !== "string" || !/^[a-z0-9.-]+\.[a-z]{2,63}$/i.test(domain)) throw new Error("некорректный домен");
  const rules = await chrome.declarativeNetRequest.getSessionRules();
  const id = ALLOW_RULE_BASE + rules.length + 1;
  await chrome.declarativeNetRequest.updateSessionRules({
    addRules: [{ id, priority: 2, action: { type: "allow" }, condition: { requestDomains: [domain], resourceTypes: ["main_frame"] } }],
  });
}

// ---------- меню «Проверить в ПРУФ» ----------
function setupMenu() {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({ id: "pruf-check", title: "Проверить в ПРУФ", contexts: ["selection"] });
  });
}

function describe(result) {
  const found = result.requisites.filter((r) => r.found);
  if (!result.requisites.length) return "Не похоже на номер карты, телефон, IBAN или ссылку Kaspi.";
  if (!found.length) return `${result.requisites[0].value}: в реестре ПРУФ не найден. Это не гарантия честности.`;
  const tracks = found.flatMap((r) => r.tracks).join(", ");
  return `${found[0].value}: встречался в постах с признаками схем${tracks ? " (" + tracks + ")" : ""}. Не переводите деньги.`;
}

chrome.contextMenus.onClicked.addListener(async (info) => {
  if (info.menuItemId !== "pruf-check" || !info.selectionText) return;
  const selection = info.selectionText.slice(0, 200);
  const found = PrufExtract.extractRequisites(selection);
  let message;
  try {
    const body = await api("/api/v1/inspect", {
      method: "POST",
      body: JSON.stringify({ requisites: found.length ? found : [selection.slice(0, 64)], links: [], cues: [] }),
    });
    message = describe(body.data);
  } catch (err) {
    message = "Сервер ПРУФ недоступен: " + (err.message || err);
  }
  chrome.notifications.create({ type: "basic", iconUrl: "icons/icon128.png", title: "ПРУФ: проверка реквизита", message });
});

// ---------- сообщения от content.js, warning.html и popup ----------
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  const handlers = {
    inspect: () => inspect(msg.payload),
    allow: () => allowOnce(msg.domain),
    blocked: () => bump("blocked"),
    refresh: () => refreshBlacklist(),
  };
  const handler = handlers[msg && msg.type];
  if (!handler) return false;
  handler()
    .then((data) => sendResponse({ ok: true, data }))
    .catch((err) => sendResponse({ ok: false, error: String(err.message || err) }));
  return true; // ответ асинхронный
});

chrome.runtime.onInstalled.addListener(() => {
  setupMenu();
  chrome.alarms.create(BLACKLIST_ALARM, { periodInMinutes: BLACKLIST_PERIOD_MIN });
  refreshBlacklist();
});
chrome.runtime.onStartup.addListener(refreshBlacklist);
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === BLACKLIST_ALARM) refreshBlacklist();
});
