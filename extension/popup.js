// Popup: счётчики, состояние чёрного списка и настройки подключения.
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const { t, pickLang, applyStatic } = globalThis.PrufI18n;
  let lang = "ru";

  async function render() {
    const s = await chrome.storage.local.get({ stats: {}, blacklist: {}, apiUrl: "http://127.0.0.1:8000", token: "", lang: "auto" });
    lang = pickLang(s.lang, navigator.language);
    applyStatic(document, lang);
    $("lang").value = s.lang;
    $("checked").textContent = s.stats.checked || 0;
    $("threats").textContent = s.stats.threats || 0;
    $("blocked").textContent = s.stats.blocked || 0;
    $("copyWarnings").textContent = s.stats.copyWarnings || 0;
    $("reported").textContent = s.stats.reported || 0;
    const bl = s.blacklist;
    $("blacklist").textContent = bl.error
      ? t(lang, "blacklistError", { error: bl.error })
      : bl.updated
        ? t(lang, "blacklistOk", { count: bl.count, when: new Date(bl.updated).toLocaleString(lang === "kk" ? "kk-KZ" : "ru-RU") })
        : t(lang, "blacklistNone");
    $("apiUrl").value = s.apiUrl;
    $("token").value = s.token;
  }

  $("save").addEventListener("click", async () => {
    const apiUrl = $("apiUrl").value.trim();
    if (!/^https?:\/\/[^\s/]+/.test(apiUrl)) {
      $("status").textContent = t(lang, "badUrl");
      return;
    }
    await chrome.storage.local.set({ apiUrl, token: $("token").value.trim() });
    $("status").textContent = t(lang, "savedRefreshing");
    await chrome.runtime.sendMessage({ type: "refresh" });
    $("status").textContent = t(lang, "done");
    render();
  });
  $("lang").addEventListener("change", async () => {
    await chrome.storage.local.set({ lang: $("lang").value });
    render();
  });
  $("refresh").addEventListener("click", async () => {
    await chrome.runtime.sendMessage({ type: "refresh" });
    render();
  });
  render();
})();
