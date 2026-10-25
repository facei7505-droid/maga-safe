// Страница-предупреждение: сюда declarativeNetRequest перенаправляет домены из чёрного списка.
// Исходный адрес приходит во фрагменте (#https://...) как есть, страница его только показывает.
(function () {
  "use strict";
  const target = location.hash.slice(1);
  let url = null;
  try {
    url = new URL(target);
  } catch (_) {
    url = null;
  }
  const okUrl = url && (url.protocol === "http:" || url.protocol === "https:");
  document.getElementById("domain").textContent = okUrl ? url.hostname : "неизвестный адрес";
  chrome.runtime.sendMessage({ type: "blocked" });

  document.getElementById("back").addEventListener("click", () => {
    if (history.length > 1) history.back();
    else window.close();
  });
  const proceed = document.getElementById("proceed");
  // В рамке на чужой странице «перейти» не показываем: иначе сайт заманит на клик и снимет блокировку
  if (!okUrl || window.top !== window) proceed.hidden = true;
  proceed.addEventListener("click", async () => {
    const reply = await chrome.runtime.sendMessage({ type: "allow", domain: url.hostname });
    if (reply && reply.ok) location.replace(url.href);
  });
})();
