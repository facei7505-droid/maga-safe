// Локальное извлечение из текста поста: реквизиты, ссылки, номера признаков (cues) и SHA-256.
// На сервер уходит только это, сам текст поста остаётся в браузере.
// Общий файл для content.js, background.js и тестов Node (node --test extension/test).
(function (root) {
  "use strict";

  const PHONE_RE = /(?<![\d+])(?:\+7|8|7)[\s\-()]*7\d{2}[\s\-()]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}(?!\d)/g;
  const CARD_RE = /(?<!\d)(?:\d{4}[\s\-]?){3}\d{4}(?!\d)/g;
  const IBAN_RE = /\bKZ\d{2}(?:\s?[A-Z0-9]{4}){4}\b/gi;
  const KASPI_LINK_RE = /\b(?:https?:\/\/)?(?:pay\.)?kaspi\.(?:kz|me)\/(?:pay\/)?[\w\-/]+/gi;
  const URL_RE = /(?:https?:\/\/|www\.)[^\s<>"']+|(?<![a-z0-9.\-])(?:[a-z0-9\-]{1,63}\.){1,6}(?:kz|ru|com|me|io|net|org|bet|xyz|site|online|top|club|app|ly|su|cc|pro|win|casino)(?:\/[^\s<>"']*)?/gi;
  const MAX_REQUISITES = 10;
  const MAX_LINKS = 20;

  // Номера признаков совпадают с pruf/inspect.py (CUES); веса и подписи хранит сервер.
  const CUE_PATTERNS = {
    paid_entry: /(участи[еяю]|взнос|вход|қатысу|uchastie)[^.!?\n]{0,40}?\d[\d\s]*\s?(тг|тенге|теңге|₸|tg)|оплат\p{L}*\s+участи/u,
    delivery_fee: /(оплат\p{L}*|плат\p{L}*|төле\p{L}*|oplat\p{L}*)[^.!?\n]{0,30}?(доставк|комисси|жеткізу|dostavk)/u,
    giveaway: /розыгрыш|разыгрыва|ұтыс|giveaway|rozygrysh|(?<!\p{L})приз/u,
    casino: /казино|слот|авиатор|aviator|рулетк|kazino|casino|crash|букмекер|фриспин|ставк[аиу](?!\p{L})/u,
    big_win: /(поднял|вывел|занос|выиграл|podnyal)[^.!?\n]{0,30}?([xх]\s?\d{2,}|\d[\d\s]{2,}\s?(тг|тенге|₸))|(?<![\p{L}\d])[xх]\d{2,}(?!\d)/u,
    promo_code: /промокод|promo\s?code|promokod|бонус\s+(на\s+)?\d{2,3}\s?%|\d{2,3}\s?%\s+на\s+(депозит|пополнени)/u,
    income_promise: /\d+([.,]\d+)?\s?%\s?(в\s)?(день|сутки|неделю|месяц)|удвои\p{L}*|в два раза|пассивн\p{L}* доход|күніне\s*\d+\s*%|екі есе|\d+\s*%\s*v\s*den|passivn\p{L}*\s*dohod|udvoim/u,
    referral: /пригла\p{L}*\s+(\d+\s+)?(друз|друг)|за приглаш\p{L}*|реферал|шақыр|priglas\p{L}*/u,
    guarantee: /гарант\p{L}*\s+(выплат|доход|прибыл)|без риска|кепілді|garanti\p{L}*\s+vyplat/u,
    kaspi_transfer: /kaspi|каспи|на карту/u,
    urgency: /осталось\s+\d+\s+мест|только сегодня|успей|спешите|\d+\s+орын қалды|места ограничены/u,
  };

  // Копия CUES из pruf/inspect.py для оценки без сервера (tests/test_inspect.py сверяет их)
  const CUE_INFO = {
    paid_entry: ["common", "платный вход", "Платное участие или вход: взнос в тенге", 30],
    delivery_fee: ["lottery", "оплата доставки приза", "Просят оплатить «доставку» или «комиссию» за приз", 30],
    giveaway: ["lottery", "розыгрыш", "Розыгрыш или приз", 10],
    casino: ["casino", "реклама казино", "Реклама казино, слотов или ставок", 25],
    big_win: ["casino", "«поднял x500»", "Хвастовство выигрышем: «поднял x500», «занос»", 20],
    promo_code: ["casino", "промокод на бонус", "Промокод или бонус на депозит", 15],
    income_promise: ["pyramid", "обещание дохода", "Обещание дохода: % в день, «удвоим за неделю»", 35],
    referral: ["pyramid", "доход за приглашённых", "Доход за приглашённых друзей", 25],
    guarantee: ["pyramid", "гарантия выплат", "«Гарантия выплат», «без риска»", 15],
    kaspi_transfer: ["common", "перевод на Kaspi", "Просят перевести деньги на Kaspi или карту", 15],
    urgency: ["common", "давление срочностью", "Давление срочностью: «осталось 5 мест», «только сегодня»", 10],
  };
  const TRACK_TITLES = { lottery: "платного розыгрыша", casino: "скрытой рекламы казино", pyramid: "финансовой пирамиды" };
  const HIGH_THRESHOLD = 65; // pruf/models.py
  const MEDIUM_THRESHOLD = 35;

  /** Оценка по одним локальным признакам, когда сервер недоступен: без реестра, только текст. */
  function localVerdict(cues) {
    const reasons = [];
    const trackPoints = {};
    for (const id of new Set(cues)) {
      const info = CUE_INFO[id];
      if (!info) continue;
      const [track, short, label, weight] = info;
      reasons.push({ id, short, label, weight });
      if (track !== "common") trackPoints[track] = (trackPoints[track] || 0) + weight;
    }
    const score = Math.min(reasons.reduce((sum, r) => sum + r.weight, 0), 100);
    const tracks = Object.keys(trackPoints);
    const track = tracks.length ? tracks.reduce((a, b) => (trackPoints[b] > trackPoints[a] ? b : a)) : null;
    const top = [...reasons].sort((a, b) => b.weight - a.weight).slice(0, 3).map((r) => r.short);
    const head = track ? `Признаки ${TRACK_TITLES[track]}` : "Признаки мошеннической схемы";
    const level = score >= HIGH_THRESHOLD ? "high" : score >= MEDIUM_THRESHOLD ? "medium" : "low";
    return {
      score, level, level_label: { high: "высокий", medium: "средний", low: "низкий" }[level], track,
      show_banner: score >= HIGH_THRESHOLD, title: head + (top.length ? ": " + top.join(", ") : ""),
      reasons, requisites: [], blacklisted_domains: [], local: true,
    };
  }

  function luhnOk(digits) {
    let total = 0;
    for (let i = 0; i < digits.length; i++) {
      let d = Number(digits[digits.length - 1 - i]);
      if (i % 2 === 1) {
        d *= 2;
        if (d > 9) d -= 9;
      }
      total += d;
    }
    return total % 10 === 0;
  }

  function cleanDigits(text) {
    // Невидимые символы и не-ASCII цифры прячут номер от регулярок: «4400\u200b4301…», «+７…»
    return text
      .replace(/\p{Cf}/gu, "") // как clean_digits на сервере: все невидимые символы формата
      .replace(/\p{Nd}/gu, (ch) => {
        const cp = ch.codePointAt(0);
        if (cp < 128) return ch;
        // Блоки десятичных цифр Unicode идут подряд по 10: цифра = смещение от «нуля» блока
        for (let zero = cp; zero > cp - 10; zero--) {
          if (!/\p{Nd}/u.test(String.fromCodePoint(zero - 1))) return String(cp - zero);
        }
        return ch;
      });
  }

  function extractRequisites(text) {
    const src = cleanDigits(text || "");
    const out = [];
    const add = (v) => {
      if (!out.includes(v) && out.length < MAX_REQUISITES) out.push(v);
    };
    for (const m of src.matchAll(PHONE_RE)) add(m[0].replace(/[^\d+]/g, ""));
    for (const m of src.matchAll(CARD_RE)) {
      const digits = m[0].replace(/\D/g, "");
      if (luhnOk(digits)) add(digits);
    }
    for (const m of src.matchAll(IBAN_RE)) add(m[0].replace(/\s/g, "").toUpperCase());
    for (const m of src.matchAll(KASPI_LINK_RE)) add(m[0].replace(/^https?:\/\//i, "").toLowerCase().slice(0, 64));
    return out;
  }

  function extractLinks(text, hrefs) {
    const out = [];
    const add = (v) => {
      const url = String(v).replace(/[.,!?)»]+$/, "").slice(0, 2048);
      if (url && !out.includes(url) && out.length < MAX_LINKS) out.push(url);
    };
    for (const m of (text || "").matchAll(URL_RE)) add(m[0]);
    for (const h of hrefs || []) if (/^https?:\/\//i.test(h)) add(h);
    return out;
  }

  function foldForCues(text) {
    return (text || "").normalize("NFKC").toLowerCase().replace(/ё/g, "е");
  }

  function detectCues(text) {
    const folded = foldForCues(text);
    return Object.keys(CUE_PATTERNS).filter((id) => CUE_PATTERNS[id].test(folded));
  }

  // Реестр хранит текст с картами под маской 6+4 (redact_cards): хэшируем так же, иначе копия не совпадёт
  function redactCards(text) {
    return cleanDigits(text || "").replace(CARD_RE, (m) => {
      const digits = m.replace(/\D/g, "");
      return luhnOk(digits) ? `${digits.slice(0, 6)}******${digits.slice(-4)}` : m;
    });
  }

  // Тот же хэш считает сервер (pruf/inspect.py: text_hash от текста из реестра)
  function foldForHash(text) {
    return redactCards(text).normalize("NFKC").toLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();
  }

  async function textHash(text) {
    const data = new TextEncoder().encode(foldForHash(text));
    const digest = await root.crypto.subtle.digest("SHA-256", data);
    return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join("");
  }

  async function buildPayload(text, hrefs) {
    return {
      requisites: extractRequisites(text),
      links: extractLinks(text, hrefs),
      text_hash: await textHash(text),
      cues: detectCues(text),
    };
  }

  // Стоит ли спрашивать сервер: без реквизитов, ссылок и признаков пост не проверяем
  function worthChecking(payload) {
    return payload.requisites.length > 0 || payload.links.length > 0 || payload.cues.length > 0;
  }

  // Предупреждение при копировании номера. Чёрный список: аналитик подтвердил схему. Серый: номер замечен
  // в постах с признаками. Снятый номер сервер отдаёт как found: false, и предупреждения нет.
  function copyWarning(checked) {
    const found = (checked || []).filter((r) => r && r.found);
    const black = found.find((r) => r.list === "black");
    if (black) return `⛔ ПРУФ: ${black.value} в чёрном списке, схему подтвердил аналитик. Не переводите деньги.`;
    if (found.length) return `⚠ ПРУФ: ${found[0].value} уже встречался в постах с признаками схем. Не переводите деньги, пока не проверите получателя.`;
    return null;
  }

  const api = { extractRequisites, extractLinks, detectCues, foldForHash, textHash, buildPayload, worthChecking, luhnOk, cleanDigits,
    localVerdict, copyWarning, CUE_INFO };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.PrufExtract = api;
})(typeof globalThis !== "undefined" ? globalThis : self);
