// Popup: счётчики, состояние чёрного списка и настройки подключения.
(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);

  async function render() {
    const s = await chrome.storage.local.get({ stats: {}, blacklist: {}, apiUrl: "http://127.0.0.1:8000", token: "" });
    $("checked").textContent = s.stats.checked || 0;
    $("threats").textContent = s.stats.threats || 0;
    $("blocked").textContent = s.stats.blocked || 0;
    const bl = s.blacklist;
    $("blacklist").textContent = bl.error
      ? "Чёрный список: ошибка обновления (" + bl.error + ")"
      : bl.updated
        ? `Чёрный список: ${bl.count} доменов, обновлён ${new Date(bl.updated).toLocaleString("ru-RU")}`
        : "Чёрный список: ещё не загружен";
    $("apiUrl").value = s.apiUrl;
    $("token").value = s.token;
  }

  $("save").addEventListener("click", async () => {
    const apiUrl = $("apiUrl").value.trim();
    if (!/^https?:\/\/[^\s/]+/.test(apiUrl)) {
      $("status").textContent = "Адрес должен начинаться с http:// или https://";
      return;
    }
    await chrome.storage.local.set({ apiUrl, token: $("token").value.trim() });
    $("status").textContent = "Сохранено, обновляю чёрный список…";
    await chrome.runtime.sendMessage({ type: "refresh" });
    $("status").textContent = "Готово";
    render();
  });
  $("refresh").addEventListener("click", async () => {
    await chrome.runtime.sendMessage({ type: "refresh" });
    render();
  });
  render();
})();
