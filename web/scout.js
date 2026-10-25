// ПРУФ: вкладка «Разведка» — каналы, которые агент-разведчик нашёл сам (python -m pruf.scout).
import { $, api, badge, chips, el, showError, when } from "./lib.js";
import { networkPanel } from "./network.js";

const VIA = { seed: "семя", requisite: "общий реквизит", forward: "репост", domain: "общий домен", link: "ссылка t.me",
              mention: "@упоминание", search: "поиск по словам" };

export async function loadScout() {
  const root = $("#scout");
  root.replaceChildren(el("p", { class: "muted" }, "Загрузка…"));
  try {
    // Сети необязательны: если их расчёт упал, вкладка всё равно показывает каналы
    const nets = api("/api/v1/networks?limit=5").then((r) => r.data, () => []);
    const { data } = await api("/api/v1/scout");
    const parts = render(data);
    parts.splice(parts.length - 1, 0, networksSection(await nets));  // сети перед таблицей каналов
    root.replaceChildren(...parts.filter(Boolean));
  } catch (err) { showError(root, err); }
}

function render({ channels, edges }) {
  if (!channels.length) {
    return [el("div", { class: "panel empty" }, el("b", {}, "Разведчик ещё не запускался"),
      el("span", {}, "Демо без аккаунта Telegram: python -m pruf.scout --demo --no-keywords"))];
  }
  const risky = channels.filter((c) => c.status === "risky");
  const shared = sharedRequisites(edges, new Set(risky.map((c) => c.username)));
  return [
    el("div", { class: "kpis scout-kpis" },
      kpi(risky.length, "каналов с признаками схем"), kpi(channels.length - risky.length, "проверены и чистые"),
      kpi(edges.length, "связей между каналами"), kpi(shared.length, "общих реквизитов")),
    shared.length ? el("section", { class: "panel" }, el("h3", {}, "Общие реквизиты: одна сеть за разными каналами"),
      el("ul", { class: "scout-shared" }, shared.map(([value, names]) =>
        el("li", {}, el("span", { class: "mono" }, value), " — ", names.map((n) => "@" + n).join(", "))))) : null,
    el("div", { class: "panel table-panel" },
      el("div", { class: "table-scroll" }, el("table", { class: "table" },
        el("thead", {}, el("tr", {}, ["Канал", "Риск", "Трек", "Как нашли", "Откуда", "Постов со схемой", "Подписчики", "Проверен"]
          .map((h) => el("th", {}, h)))),
        el("tbody", {}, channels.map(row)))))];
}

// Сети по всей базе: и найденные разведчиком, и пришедшие из жалоб и бота
function networksSection(nets) {
  if (!nets.length) return null;
  return el("section", { class: "panel" },
    el("h3", {}, "Сети и ключевые реквизиты ", el("span", { class: "muted small" }, "каналы, связанные общими номерами, ссылками Kaspi и доменами")),
    el("div", { class: "nets-list" }, nets.map((n, i) => {
      const key = n.key_nodes[0];
      const box = el("details", i === 0 ? { open: "" } : {},
        el("summary", {}, el("b", {}, `Сеть ${n.key}: ${n.channels.length} каналов`), chips(n.tracks),
          key ? el("span", {}, "ключевой реквизит ", el("b", { class: "mono" }, key.label),
            el("span", { class: "muted" }, ` · отрежет от денег ${key.cut_off.length} из ${n.channels.length}`)) : null));
      box.append(networkPanel(n, { title: "Что если заблокировать" }) || el("p", { class: "muted" }, "Нет реквизитов для блокировки."));
      return box;
    })));
}

function kpi(value, label) {
  return el("div", { class: "kpi" }, el("div", { class: "kpi-v" }, value), el("div", { class: "kpi-l" }, label));
}

function row(c) {
  return el("tr", {},
    el("td", {}, el("span", { class: "mono" }, "@" + c.username), el("div", { class: "muted small" }, c.title || "")),
    el("td", {}, badge(c.level || "low", c.risk || 0)),
    el("td", {}, chips([c.track])),
    el("td", {}, VIA[c.found_via] || c.found_via || "—"),
    el("td", {}, c.found_from ? el("span", { class: "mono" }, "@" + c.found_from) : "—",
      c.found_detail ? el("div", { class: "muted small mono" }, c.found_detail) : null),
    el("td", {}, `${c.risky_posts ?? 0} из ${c.posts_checked ?? 0}`),
    el("td", {}, c.subscribers != null ? c.subscribers.toLocaleString("ru-RU") : "—"),
    el("td", {}, when(c.last_checked)));
}

function sharedRequisites(edges, risky) {
  const byValue = new Map();
  for (const e of edges) {
    if (e.via !== "requisite" && e.via !== "domain") continue;
    const set = byValue.get(e.detail) || new Set();
    [e.src, e.dst].filter((n) => risky.has(n)).forEach((n) => set.add(n));
    byValue.set(e.detail, set);
  }
  return [...byValue.entries()].filter(([, s]) => s.size > 1).map(([v, s]) => [v, [...s].sort()]).sort((a, b) => b[1].length - a[1].length);
}
