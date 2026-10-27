// ПРУФ: демо-тур — сценарий показа из README по шагам, чтобы демо не зависело от того, куда нажать.
import { $, el } from "./lib.js";

const HERO_CASE = "C-211";
const HERO_PHONE = "+77473185264";

// ждём, пока элемент появится: вкладки грузят данные асинхронно
async function waitFor(selector, timeout = 8000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) {
    const found = $(selector);
    if (found) return found;
    await new Promise((r) => setTimeout(r, 120));
  }
  return null;
}

function steps({ switchView, openCase, closeModal }) {
  return [
    {
      title: "Ранний сигнал",
      text: "Один номер Kaspi за трое суток появился в пяти каналах — так выглядит запуск новой волны. ПРУФ видит это раньше первых жалоб.",
      run: async () => { closeModal(); switchView("overview"); (await waitFor(".surges"))?.scrollIntoView({ block: "center" }); },
    },
    {
      title: `Кейс ${HERO_CASE}: одна сеть, три схемы`,
      text: "Посты разных каналов связаны общими пруфами и реквизитами. Один и тот же скрин «выплаты» встречается больше 30 раз в разных каналах — это одна сеть.",
      run: async () => { closeModal(); await openCase(HERO_CASE); (await waitFor("#case .case-head"))?.scrollIntoView({ block: "start" }); },
    },
    {
      title: "Проверка поста и ход решения",
      text: "Вставляем пост: правила находят признаки с цитатами, модель и реестр добавляют контекст, Claude-арбитр — только в спорной зоне. Видно каждый шаг.",
      run: async () => {
        closeModal();
        switchView("check");
        (await waitFor("#examples button"))?.click();
        $("#check-form").requestSubmit();
        (await waitFor(".trace"))?.scrollIntoView({ block: "start" });
      },
    },
    {
      title: "Банк проверяет получателя",
      text: "Перед переводом банк проверяет номер: он в чёрном списке, схему подтвердил аналитик. Сам номер банку не раскрывается другим участникам — обмен по HMAC.",
      run: async () => {
        switchView("bank");
        $("#bank-value").value = HERO_PHONE;
        $("#bank-form").requestSubmit();
        (await waitFor(".verdict"))?.scrollIntoView({ block: "center" });
      },
    },
    {
      title: "Агент-разведчик за работой",
      text: "От одной жалобы агент сам идёт по репостам, упоминаниям и общим номерам и находит связанные каналы. Только читает, никому не пишет.",
      run: async () => {
        switchView("scout");
        const play = await waitFor(".journal button.primary");
        play?.scrollIntoView({ block: "start" });
        play?.click();
      },
    },
  ];
}

export function initTour(actions) {
  const list = steps(actions);
  let i = 0;
  const box = el("div", { class: "tour hidden", role: "dialog", "aria-label": "Демо-тур" });
  document.body.append(box);
  const show = async () => {
    const s = list[i];
    box.replaceChildren(
      el("div", { class: "tour-n muted small" }, `Шаг ${i + 1} из ${list.length}`),
      el("b", {}, s.title), el("p", {}, s.text),
      el("div", { class: "row tour-actions" },
        el("button", { type: "button", onclick: close }, "Закрыть"),
        i > 0 ? el("button", { type: "button", onclick: () => { i -= 1; show(); } }, "Назад") : null,
        el("button", { type: "button", class: "primary", onclick: () => { if (i < list.length - 1) { i += 1; show(); } else close(); } },
          i < list.length - 1 ? "Дальше" : "Готово")));
    box.classList.remove("hidden");
    await s.run();
  };
  function close() { box.classList.add("hidden"); }
  return () => { i = 0; show(); };
}
