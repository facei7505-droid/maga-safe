// ПРУФ Sentinel: следит за лентой Telegram Web и Instagram, над подозрительным постом рисует плашку.
// Текст поста не покидает браузер: в background (и дальше на сервер) уходят только реквизиты,
// ссылки, хэш текста и номера признаков из lib/extract.js.
(function () {
  "use strict";

  const { buildPayload, worthChecking, localVerdict, extractRequisites } = globalThis.PrufExtract;
  // Telegram Web A (.text-content), Telegram Web K (.message), Instagram (article), WhatsApp Web (сообщение
  // с data-pre-plain-text; поле ввода его не имеет). Один селектор на площадку, чтобы вложенные элементы
  // одного поста не проверялись дважды.
  const POST_SELECTORS = [".text-content", ".bubble .message", "article", "div.copyable-text[data-pre-plain-text]"];
  const PLATFORM = { "web.telegram.org": "telegram", "www.instagram.com": "instagram", "web.whatsapp.com": "whatsapp" }[location.hostname] || "other";
  const TOAST_MS = 9000;
  const MIN_TEXT = 30;
  const MAX_TEXT = 4000;
  const DONE_ATTR = "data-pruf";
  const LEN_ATTR = "data-pruf-len";
  const RESCAN_STATES = new Set(["short", "clean"]); // пост дописался позже (подпись Instagram, «ещё», правка)
  const results = new Map(); // хэш текста → ответ сервера: одинаковые репосты не проверяем дважды
  const queue = [];
  let busy = false;

  function postElements(root) {
    const found = new Set();
    if (root.nodeType !== Node.ELEMENT_NODE) return found;
    for (const sel of POST_SELECTORS) {
      if (root.matches(sel)) found.add(root);
      root.querySelectorAll(sel).forEach((el) => found.add(el));
    }
    return found;
  }

  function schedule(el) {
    if (el.hasAttribute(DONE_ATTR) || el.closest(".pruf-host")) return;
    if (el.parentElement && el.parentElement.closest(`[${DONE_ATTR}]`)) return; // пост уже взят целиком
    el.setAttribute(DONE_ATTR, "queued");
    queue.push(el);
    if (!busy) drain();
  }

  async function drain() {
    busy = true;
    while (queue.length) {
      const el = queue.shift();
      try {
        await inspect(el);
      } catch (err) {
        el.setAttribute(DONE_ATTR, "error");
        console.warn("ПРУФ: не удалось проверить пост", err);
      }
    }
    busy = false;
  }

  async function inspect(el) {
    const text = (el.innerText || "").slice(0, MAX_TEXT);
    el.setAttribute(LEN_ATTR, String(text.length));
    if (text.trim().length < MIN_TEXT) {
      el.setAttribute(DONE_ATTR, "short");
      return;
    }
    const hrefs = Array.from(el.querySelectorAll("a[href]"), (a) => a.href);
    const payload = await buildPayload(text, hrefs);
    if (!worthChecking(payload)) {
      el.setAttribute(DONE_ATTR, "clean");
      return;
    }
    let result = results.get(payload.text_hash);
    if (!result) {
      const reply = await chrome.runtime.sendMessage({ type: "inspect", payload }).catch(() => null);
      if (reply && reply.ok) {
        result = reply.data;
        results.set(payload.text_hash, result);
      } else {
        // Сервер недоступен: оцениваем по локальным признакам, без реестра. В кэш не кладём, чтобы потом спросить сервер.
        result = localVerdict(payload.cues);
      }
    }
    el.setAttribute(DONE_ATTR, result.show_banner ? "risk" : "clean");
    if (result.show_banner) drawBanner(el, result, payload);
  }

  function reportButton(payload) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = "Сообщить в ПРУФ";
    btn.addEventListener("click", async () => {
      btn.disabled = true;
      const reply = await chrome.runtime.sendMessage({ type: "report", payload, platform: PLATFORM }).catch(() => null);
      btn.textContent = !reply || !reply.ok ? "Не отправлено, сервер недоступен"
        : reply.data.accepted ? "Спасибо, жалоба отправлена" : "Вы уже сообщали об этом посте";
    });
    return btn;
  }

  function drawBanner(el, result, payload) {
    const host = document.createElement("div");
    host.className = "pruf-host";
    const shadow = host.attachShadow({ mode: "open" });
    const style = document.createElement("style");
    style.textContent = `
      .b { font: 13px/1.4 system-ui, sans-serif; background: #fff4e5; color: #4a2b00; border: 1px solid #f0a020;
           border-radius: 8px; padding: 8px 10px; margin: 4px 0 6px; }
      .t { font-weight: 600; }
      button { font: inherit; background: none; border: 0; color: #9a4b00; text-decoration: underline; cursor: pointer; padding: 0; margin-left: 6px; }
      ul { margin: 6px 0 2px; padding-left: 18px; }
      .n { color: #7a5a2b; font-size: 12px; margin-top: 4px; }`;
    const box = document.createElement("div");
    box.className = "b";
    box.setAttribute("role", "alert");
    const title = document.createElement("span");
    title.className = "t";
    title.textContent = "⚠ " + result.title;
    const why = document.createElement("button");
    why.type = "button";
    why.textContent = "Почему?";
    const details = document.createElement("div");
    details.hidden = true;
    const list = document.createElement("ul");
    for (const r of result.reasons) {
      const li = document.createElement("li");
      li.textContent = r.label;
      list.appendChild(li);
    }
    const note = document.createElement("div");
    note.className = "n";
    note.textContent = `ПРУФ: риск ${result.score} из 100 (${result.level_label})${result.local ? ", оценка браузера без сервера" : ""}. ` +
      "Это признаки, а не вердикт: не переводите деньги, пока не проверите организатора.";
    details.append(list, note);
    if (!result.local) details.append(reportButton(payload));
    why.addEventListener("click", () => {
      details.hidden = !details.hidden;
      why.textContent = details.hidden ? "Почему?" : "Скрыть";
    });
    box.append(title, why, details);
    shadow.append(style, box);
    el.prepend(host);
  }

  function rescanIfGrown(target) {
    const node = target.nodeType === Node.ELEMENT_NODE ? target : target.parentElement;
    const post = node && node.closest(`[${DONE_ATTR}]`);
    if (!post || !RESCAN_STATES.has(post.getAttribute(DONE_ATTR))) return;
    if (String((post.innerText || "").slice(0, MAX_TEXT).length) === post.getAttribute(LEN_ATTR)) return;
    post.removeAttribute(DONE_ATTR);
    schedule(post);
  }

  // ---------- стоп на копировании номера ----------
  // Человек копирует номер Kaspi или карту, чтобы перевести деньги. Если номер засвечен в схемах, предупреждаем
  // тут же. На сервер уходит только сам реквизит из выделения.
  function toast(text) {
    const host = document.createElement("div");
    host.className = "pruf-host";
    host.style.cssText = "position:fixed;right:16px;bottom:16px;z-index:2147483647;max-width:360px";
    const shadow = host.attachShadow({ mode: "open" });
    const box = document.createElement("div");
    box.setAttribute("role", "alert");
    box.style.cssText = "font:14px/1.45 system-ui,sans-serif;background:#7a1d00;color:#fff;border-radius:10px;" +
      "padding:12px 14px;box-shadow:0 6px 24px rgba(0,0,0,.3)";
    box.textContent = text;
    shadow.append(box);
    document.body.append(host);
    setTimeout(() => host.remove(), TOAST_MS);
  }

  document.addEventListener("copy", async () => {
    const sel = document.getSelection();
    const anchor = sel && sel.anchorNode && (sel.anchorNode.nodeType === Node.ELEMENT_NODE ? sel.anchorNode : sel.anchorNode.parentElement);
    if (!anchor || anchor.closest("[contenteditable=true], [contenteditable=''], input, textarea")) return; // свой черновик не проверяем
    const selection = String(sel).slice(0, 300);
    const requisites = extractRequisites(selection);
    if (!requisites.length) return;
    const reply = await chrome.runtime.sendMessage({ type: "checkRequisites", requisites }).catch(() => null);
    const hit = reply && reply.ok && reply.data.requisites.find((r) => r.found);
    if (hit) toast(`⚠ ПРУФ: ${hit.value} уже встречался в постах с признаками схем. Не переводите деньги, пока не проверите получателя.`);
  });

  const observer = new MutationObserver((mutations) => {
    for (const m of mutations) {
      if (m.target.nodeType === Node.ELEMENT_NODE ? m.target.closest(".pruf-host") : false) continue;
      for (const node of m.addedNodes) {
        if (node.nodeType === Node.ELEMENT_NODE && !node.closest(".pruf-host")) postElements(node).forEach(schedule);
      }
      rescanIfGrown(m.target);
    }
  });
  observer.observe(document.body, { childList: true, subtree: true, characterData: true });
  postElements(document.body).forEach(schedule);
})();
