// Тексты расширения на русском и казахском. Свой словарь, а не _locales Chrome: язык переключается в попапе
// без переустановки и не зависит от языков браузера. «Авто» — казахский, если язык браузера kk.
// Общий файл для content.js, background.js, попапа, страницы-предупреждения и тестов Node.
// Глоссарий: розыгрыш — ұтыс ойыны, финансовая пирамида — қаржы пирамидасы, мошенники — алаяқтар,
// перевод — аударым, «Не переводите деньги» — «Ақша аудармаңыз», «Почему?» — «Неге?».
(function (root) {
  "use strict";

  const LANGS = ["ru", "kk"];
  const STRINGS = {
    why: { ru: "Почему?", kk: "Неге?" },
    hide: { ru: "Скрыть", kk: "Жасыру" },
    report: { ru: "Сообщить в ПРУФ", kk: "ПРУФ-қа хабарлау" },
    reportFailed: { ru: "Не отправлено, сервер недоступен", kk: "Жіберілмеді, сервер қолжетімсіз" },
    reportThanks: { ru: "Спасибо, жалоба отправлена", kk: "Рақмет, шағым жіберілді" },
    reportDuplicate: { ru: "Вы уже сообщали об этом посте", kk: "Бұл пост туралы бұрын хабарлағансыз" },
    bannerNote: {
      ru: "ПРУФ: риск {score} из 100 ({level}){local}. Это признаки, а не вердикт: не переводите деньги, пока не проверите организатора.",
      kk: "ПРУФ: тәуекел 100-ден {score} ({level}){local}. Бұл үкім емес, белгілер ғана: ұйымдастырушыны тексермейінше ақша аудармаңыз.",
    },
    localSuffix: { ru: ", оценка браузера без сервера", kk: ", серверсіз браузер бағасы" },
    levelHigh: { ru: "высокий", kk: "жоғары" },
    levelMedium: { ru: "средний", kk: "орташа" },
    levelLow: { ru: "низкий", kk: "төмен" },
    titleTrack: { ru: "Признаки {track}", kk: "{track} белгілері" },
    titleGeneric: { ru: "Признаки мошеннической схемы", kk: "Алаяқтық схеманың белгілері" },
    copyBlack: {
      ru: "⛔ ПРУФ: {value} в чёрном списке, схему подтвердил аналитик. Не переводите деньги.",
      kk: "⛔ ПРУФ: {value} қара тізімде, схеманы талдаушы растады. Ақша аудармаңыз.",
    },
    copyGrey: {
      ru: "⚠ ПРУФ: {value} уже встречался в постах с признаками схем. Не переводите деньги, пока не проверите получателя.",
      kk: "⚠ ПРУФ: {value} алаяқтық белгілері бар посттарда кездескен. Алушыны тексермейінше ақша аудармаңыз.",
    },
    menuCheck: { ru: "Проверить в ПРУФ", kk: "ПРУФ-та тексеру" },
    notifyTitle: { ru: "ПРУФ: проверка реквизита", kk: "ПРУФ: реквизитті тексеру" },
    siteBlack: { ru: "{value}: сайт в чёрном списке ПРУФ — казино или схема. Не вводите данные карты и не переводите деньги.",
                 kk: "{value}: сайт ПРУФ қара тізімінде — казино немесе схема. Карта деректерін енгізбеңіз, ақша аудармаңыз." },
    siteClean: { ru: "Сайт не в чёрном списке ПРУФ. Это не гарантия честности.", kk: "Сайт ПРУФ қара тізімінде жоқ. Бұл адалдықтың кепілі емес." },
    manualTitle: { ru: "Проверить перед переводом", kk: "Аудармас бұрын тексеру" },
    manualHint: { ru: "Номер карты или телефона, IBAN, ссылка Kaspi или сайт", kk: "Карта не телефон нөмірі, IBAN, Kaspi сілтемесі немесе сайт" },
    manualButton: { ru: "Проверить", kk: "Тексеру" },
    notRequisite: { ru: "Не похоже на номер карты, телефон, IBAN или ссылку Kaspi.", kk: "Карта нөміріне, телефонға, IBAN-ға немесе Kaspi сілтемесіне ұқсамайды." },
    notFound: { ru: "{value}: в реестре ПРУФ не найден. Это не гарантия честности.", kk: "{value}: ПРУФ тізілімінде табылмады. Бұл адалдықтың кепілі емес." },
    foundBlack: { ru: "{value}: в чёрном списке ПРУФ, схему подтвердил аналитик. Не переводите деньги.", kk: "{value}: ПРУФ қара тізімінде, схеманы талдаушы растады. Ақша аудармаңыз." },
    foundGrey: { ru: "{value}: встречался в постах с признаками схем{tracks}. Не переводите деньги.", kk: "{value}: схема белгілері бар посттарда кездескен{tracks}. Ақша аудармаңыз." },
    serverDown: { ru: "Сервер ПРУФ недоступен: {error}", kk: "ПРУФ сервері қолжетімсіз: {error}" },
    warnTitle: { ru: "ПРУФ: опасный сайт", kk: "ПРУФ: қауіпті сайт" },
    warnHeading: { ru: "Этот сайт в чёрном списке ПРУФ", kk: "Бұл сайт ПРУФ қара тізімінде" },
    warnDomainBefore: { ru: "Домен ", kk: "" },
    warnDomainAfter: {
      ru: " встречался в постах с признаками платных розыгрышей, казино или финансовых пирамид.",
      kk: " домені ақылы ұтыс ойындары, казино немесе қаржы пирамидалары белгілері бар посттарда кездескен.",
    },
    warnAdvice: {
      ru: "Не вводите данные карты и не переводите деньги. Если сомневаетесь, проверьте организатора по официальным источникам.",
      kk: "Карта деректерін енгізбеңіз және ақша аудармаңыз. Күмәндансаңыз, ұйымдастырушыны ресми дереккөздерден тексеріңіз.",
    },
    warnBack: { ru: "Вернуться назад", kk: "Артқа қайту" },
    warnProceed: { ru: "Всё равно перейти", kk: "Бәрібір өту" },
    warnUnknown: { ru: "неизвестный адрес", kk: "белгісіз мекенжай" },
    statChecked: { ru: "постов проверено", kk: "пост тексерілді" },
    statThreats: { ru: "угроз найдено", kk: "қауіп табылды" },
    statBlocked: { ru: "сайтов остановлено", kk: "сайт тоқтатылды" },
    statCopy: { ru: "стопов при копировании", kk: "көшіргенде ескерту" },
    statReported: { ru: "жалоб отправлено", kk: "шағым жіберілді" },
    blacklistError: { ru: "Чёрный список: ошибка обновления ({error})", kk: "Қара тізім: жаңарту қатесі ({error})" },
    blacklistOk: { ru: "Чёрный список: {count} доменов, обновлён {when}", kk: "Қара тізім: {count} домен, жаңартылды {when}" },
    blacklistNone: { ru: "Чёрный список: ещё не загружен", kk: "Қара тізім: әлі жүктелмеді" },
    blacklistOff: { ru: "Предупреждения на сайтах казино выключены", kk: "Казино сайттарындағы ескертулер өшірулі" },
    siteGuard: { ru: "Предупреждать на сайтах казино", kk: "Казино сайттарында ескерту" },
    siteGuardHint: {
      ru: "Нужен доступ ко всем сайтам: расширение откроет страницу-предупреждение вместо сайта из чёрного списка. Содержимое страниц не читается.",
      kk: "Барлық сайттарға рұқсат керек: кеңейтім қара тізімдегі сайттың орнына ескерту бетін ашады. Беттердің мазмұны оқылмайды.",
    },
    serverDenied: { ru: "Без доступа к адресу сервера расширение не сможет проверять посты", kk: "Сервер мекенжайына рұқсатсыз кеңейтім посттарды тексере алмайды" },
    language: { ru: "Язык", kk: "Тіл" },
    langAuto: { ru: "Авто (по браузеру)", kk: "Авто (браузер бойынша)" },
    connection: { ru: "Подключение к серверу ПРУФ", kk: "ПРУФ серверіне қосылу" },
    serverUrl: { ru: "Адрес сервера", kk: "Сервер мекенжайы" },
    token: { ru: "Токен расширения", kk: "Кеңейтудің токені" },
    save: { ru: "Сохранить", kk: "Сақтау" },
    refreshList: { ru: "Обновить список", kk: "Тізімді жаңарту" },
    badUrl: { ru: "Адрес должен начинаться с https:// (http:// — только localhost)", kk: "Мекенжай https:// деп басталуы керек (http:// — тек localhost)" },
    savedRefreshing: { ru: "Сохранено, обновляю чёрный список…", kk: "Сақталды, қара тізім жаңартылуда…" },
    done: { ru: "Готово", kk: "Дайын" },
  };

  // Причины по номеру признака: плашка берёт их отсюда, а не русский текст сервера. [короткое, пояснение]
  const REASONS = {
    paid_entry: { ru: ["платный вход", "Платное участие или вход: взнос в тенге"], kk: ["ақылы қатысу", "Қатысу немесе кіру ақылы: теңгемен жарна"] },
    delivery_fee: { ru: ["оплата доставки приза", "Просят оплатить «доставку» или «комиссию» за приз"], kk: ["жүлде жеткізуге төлем", "Жүлденің «жеткізу» немесе «комиссия» ақысын төлеуді сұрайды"] },
    giveaway: { ru: ["розыгрыш", "Розыгрыш или приз"], kk: ["ұтыс ойыны", "Ұтыс ойыны немесе жүлде"] },
    casino: { ru: ["реклама казино", "Реклама казино, слотов или ставок"], kk: ["казино жарнамасы", "Казино, слот немесе бәс тігу жарнамасы"] },
    big_win: { ru: ["«поднял x500»", "Хвастовство выигрышем: «поднял x500», «занос»"], kk: ["«x500 ұттым»", "Ұтыспен мақтану: «x500 ұттым», «занос»"] },
    promo_code: { ru: ["промокод на бонус", "Промокод или бонус на депозит"], kk: ["бонус промокоды", "Промокод немесе депозитке бонус"] },
    income_promise: { ru: ["обещание дохода", "Обещание дохода: % в день, «удвоим за неделю»"], kk: ["табыс уәдесі", "Табыс уәдесі: күніне %, «бір аптада екі есе»"] },
    referral: { ru: ["доход за приглашённых", "Доход за приглашённых друзей"], kk: ["шақырылғандар үшін табыс", "Шақырылған достар үшін табыс"] },
    guarantee: { ru: ["гарантия выплат", "«Гарантия выплат», «без риска»"], kk: ["төлем кепілдігі", "«Төлем кепілдігі», «тәуекелсіз»"] },
    kaspi_transfer: { ru: ["перевод на Kaspi", "Просят перевести деньги на Kaspi или карту"], kk: ["Kaspi-ге аударым", "Kaspi-ге немесе картаға ақша аударуды сұрайды"] },
    urgency: { ru: ["давление срочностью", "Давление срочностью: «осталось 5 мест», «только сегодня»"], kk: ["асықтыру", "Асықтыру: «5 орын қалды», «тек бүгін»"] },
    "registry.requisite": { ru: ["реквизит засвечен в схемах", "Этот номер или реквизит уже встречался в постах с признаками схем"], kk: ["реквизит схемаларда кездескен", "Бұл нөмір немесе реквизит схема белгілері бар посттарда бұрын кездескен"] },
    "registry.black": { ru: ["номер в чёрном списке", "Аналитик ПРУФ подтвердил схему с этим номером: не переводите деньги"], kk: ["нөмір қара тізімде", "ПРУФ талдаушысы осы нөмірмен схеманы растады: ақша аудармаңыз"] },
    "registry.domain": { ru: ["сайт в чёрном списке", "Ссылка ведёт на домен из чёрного списка ПРУФ"], kk: ["сайт қара тізімде", "Сілтеме ПРУФ қара тізіміндегі доменге апарады"] },
    "registry.text_copy": { ru: ["копия известной рассылки", "Текст дословно совпадает с постом, где ПРУФ нашёл признаки схемы"], kk: ["белгілі таратылымның көшірмесі", "Мәтін ПРУФ схема белгілерін тапқан постпен сөзбе-сөз сәйкес"] },
  };
  // Для заголовка: «Признаки платного розыгрыша» / «Ақылы ұтыс ойынының белгілері»
  const TRACK_TITLES = {
    lottery: { ru: "платного розыгрыша", kk: "Ақылы ұтыс ойынының" },
    casino: { ru: "скрытой рекламы казино", kk: "Жасырын казино жарнамасының" },
    pyramid: { ru: "финансовой пирамиды", kk: "Қаржы пирамидасының" },
  };
  const TRACK_NAMES = {
    lottery: { ru: "платный розыгрыш", kk: "ақылы ұтыс ойыны" },
    casino: { ru: "казино", kk: "казино" },
    pyramid: { ru: "пирамида", kk: "пирамида" },
  };
  const LEVEL_KEYS = { high: "levelHigh", medium: "levelMedium", low: "levelLow" };

  function pickLang(setting, browserLang) {
    if (LANGS.includes(setting)) return setting;
    return String(browserLang || "").toLowerCase().startsWith("kk") ? "kk" : "ru";
  }

  function t(lang, key, vars) {
    const entry = STRINGS[key];
    if (!entry) return key;
    const text = entry[lang] !== undefined ? entry[lang] : entry.ru;
    return text.replace(/\{(\w+)\}/g, (_, name) => (vars && vars[name] !== undefined ? String(vars[name]) : ""));
  }

  /** Ответ сервера (или локальная оценка) на выбранном языке: заголовок, причины, уровень. */
  function localizeVerdict(result, lang) {
    const reasons = result.reasons.map((r) => {
      const known = REASONS[r.id];
      const [short, label] = known ? known[lang] || known.ru : [r.short, r.label];
      const domains = r.id === "registry.domain" && result.blacklisted_domains && result.blacklisted_domains.length
        ? ": " + result.blacklisted_domains.join(", ") : "";
      return { ...r, short, label: label + domains };
    });
    const top = [...reasons].sort((a, b) => b.weight - a.weight).slice(0, 3).map((r) => r.short);
    const head = result.track && TRACK_TITLES[result.track]
      ? t(lang, "titleTrack", { track: TRACK_TITLES[result.track][lang] }) : t(lang, "titleGeneric");
    return { ...result, reasons, title: head + (top.length ? ": " + top.join(", ") : ""),
      level_label: t(lang, LEVEL_KEYS[result.level] || "levelLow") };
  }

  // Предупреждение при копировании номера. Чёрный список: аналитик подтвердил схему. Серый: номер замечен
  // в постах с признаками. Снятый номер сервер отдаёт как found: false, и предупреждения нет.
  function copyWarning(checked, lang = "ru") {
    const found = (checked || []).filter((r) => r && r.found);
    const black = found.find((r) => r.list === "black");
    if (black) return t(lang, "copyBlack", { value: black.value });
    if (found.length) return t(lang, "copyGrey", { value: found[0].value });
    return null;
  }

  /** Текст уведомления для пункта меню «Проверить в ПРУФ». */
  function describeCheck(result, lang = "ru") {
    const badSites = result.blacklisted_domains || [];
    if (badSites.length) return t(lang, "siteBlack", { value: badSites.join(", ") });
    const found = result.requisites.filter((r) => r.found);
    if (!result.requisites.length) return t(lang, "notRequisite");
    if (!found.length) return t(lang, "notFound", { value: result.requisites[0].value });
    const black = found.find((r) => r.list === "black");
    if (black) return t(lang, "foundBlack", { value: black.value });
    const names = [...new Set(found.flatMap((r) => r.tracks))].map((tr) => (TRACK_NAMES[tr] ? TRACK_NAMES[tr][lang] : tr));
    return t(lang, "foundGrey", { value: found[0].value, tracks: names.length ? " (" + names.join(", ") + ")" : "" });
  }

  /** Статичные страницы: элементы с data-i18n получают текст на выбранном языке. */
  function applyStatic(doc, lang) {
    doc.documentElement.lang = lang;
    doc.querySelectorAll("[data-i18n]").forEach((el) => { el.textContent = t(lang, el.getAttribute("data-i18n")); });
    doc.querySelectorAll("[data-i18n-placeholder]").forEach((el) => { el.placeholder = t(lang, el.getAttribute("data-i18n-placeholder")); });
  }

  const api = { LANGS, STRINGS, REASONS, TRACK_TITLES, pickLang, t, localizeVerdict, copyWarning, describeCheck, applyStatic };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.PrufI18n = api;
})(typeof globalThis !== "undefined" ? globalThis : self);
