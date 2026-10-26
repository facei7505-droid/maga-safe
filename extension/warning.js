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
  const domain = document.getElementById("domain");
  domain.textContent = okUrl ? url.hostname : PrufI18n.t("ru", "warnUnknown");
  chrome.storage.local.get({ lang: "auto" }).then((s) => {
    const lang = PrufI18n.pickLang(s.lang, navigator.language);
    PrufI18n.applyStatic(document, lang);
    if (!okUrl) domain.textContent = PrufI18n.t(lang, "warnUnknown");
  });
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
