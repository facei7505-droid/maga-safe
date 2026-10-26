// node --test extension/test/i18n.test.js
const test = require("node:test");
const assert = require("node:assert/strict");
const I = require("../lib/i18n.js");
const X = require("../lib/extract.js");

const placeholders = (s) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

test("every string has Russian and Kazakh text with the same placeholders", () => {
  for (const [key, entry] of Object.entries(I.STRINGS)) {
    assert.ok(typeof entry.ru === "string" && typeof entry.kk === "string", key);
    if (key !== "warnDomainBefore") assert.ok(entry.ru.trim() && entry.kk.trim(), `${key} is empty`);
    assert.deepEqual(placeholders(entry.kk), placeholders(entry.ru), key);
  }
});

test("every local cue and registry reason has both languages", () => {
  for (const id of [...Object.keys(X.CUE_INFO), "registry.requisite", "registry.black", "registry.domain", "registry.text_copy"]) {
    const r = I.REASONS[id];
    assert.ok(r && r.ru.length === 2 && r.kk.length === 2 && r.kk.every((s) => s.trim()), id);
  }
  assert.deepEqual(Object.keys(I.TRACK_TITLES).sort(), ["casino", "lottery", "pyramid"]);
});

test("auto language follows the browser, explicit choice wins", () => {
  assert.equal(I.pickLang("auto", "kk-KZ"), "kk");
  assert.equal(I.pickLang("auto", "ru-RU"), "ru");
  assert.equal(I.pickLang("auto", undefined), "ru");
  assert.equal(I.pickLang("ru", "kk-KZ"), "ru");
  assert.equal(I.pickLang("kk", "en-US"), "kk");
});

test("banner is rebuilt in Kazakh from reason ids, not from the server's Russian text", () => {
  const server = { score: 80, level: "high", level_label: "высокий", track: "lottery", title: "Признаки платного розыгрыша: ...",
    reasons: [{ id: "paid_entry", short: "платный вход", label: "Платное участие", weight: 30 },
      { id: "kaspi_transfer", short: "перевод на Kaspi", label: "Просят перевести", weight: 15 },
      { id: "registry.domain", short: "сайт", label: "домен", weight: 40 }], blacklisted_domains: ["evil.kz"] };
  const kk = I.localizeVerdict(server, "kk");
  assert.equal(kk.title, "Ақылы ұтыс ойынының белгілері: сайт қара тізімде, ақылы қатысу, Kaspi-ге аударым");
  assert.equal(kk.level_label, "жоғары");
  assert.match(kk.reasons[2].label, /evil\.kz$/);
  assert.equal(I.localizeVerdict(server, "ru").title, "Признаки платного розыгрыша: сайт в чёрном списке, платный вход, перевод на Kaspi");
  const unknown = I.localizeVerdict({ ...server, track: null, reasons: [{ id: "new.cue", short: "новое", label: "Новое", weight: 5 }] }, "kk");
  assert.equal(unknown.title, "Алаяқтық схеманың белгілері: новое");
});

test("copy warning is stronger for the black list, silent for cleared numbers, and localized", () => {
  assert.match(I.copyWarning([{ value: "+77473185264", found: true, list: "black" }]), /чёрном списке/);
  assert.match(I.copyWarning([{ value: "+77473185264", found: true, list: "black" }], "kk"), /қара тізімде.*Ақша аудармаңыз/);
  assert.match(I.copyWarning([{ value: "+77019998877", found: true, list: "grey" }]), /встречался в постах/);
  assert.equal(I.copyWarning([{ value: "+77015554433", found: false, list: null }], "kk"), null);
  assert.match(I.copyWarning([{ value: "a", found: true, list: "grey" }, { value: "b", found: true, list: "black" }]), /b в чёрном/);
});

test("context menu check is described in both languages", () => {
  const grey = { requisites: [{ value: "+77019998877", found: true, list: "grey", tracks: ["lottery", "casino"] }] };
  assert.equal(I.describeCheck(grey, "kk"), "+77019998877: схема белгілері бар посттарда кездескен (ақылы ұтыс ойыны, казино). Ақша аудармаңыз.");
  assert.match(I.describeCheck({ requisites: [] }, "ru"), /Не похоже/);
  assert.match(I.describeCheck({ requisites: [{ value: "x", found: false, tracks: [] }] }, "kk"), /табылмады/);
});
