// node --test extension/test
const test = require("node:test");
const assert = require("node:assert/strict");
const X = require("../lib/extract.js");

const PYRAMID = "Пассивный доход 5% в день! Пригласи друзей и получай бонус с каждого, вход от 5000 тг, каспи +7 747 318 52 64";
const LOTTERY = "🎁 РОЗЫГРЫШ iPhone 15 Pro! Участие всего 2000 тг, переводите на Kaspi 8 701 999 88 77. Итоги в пятницу, осталось 5 мест!";
const CASINO = "Вчера поднял x500 на слотах 🔥 промокод WIN777, пополнение через каспи, зеркало joy-slots-kz.top";
const LEGIT = "Розыгрыш среди подписчиков! Участие бесплатное, ничего платить не нужно. Итоги 1 ноября в прямом эфире";

test("extracts Kazakh phones in any spelling and normalizes them", () => {
  assert.deepEqual(X.extractRequisites("каспи +7 747 318 52 64 или 8(701)9998877"), ["+77473185264", "87019998877"]);
});

test("keeps only cards with a valid Luhn checksum", () => {
  assert.deepEqual(X.extractRequisites("карта 4400 4301 2345 6781"), []);
  assert.deepEqual(X.extractRequisites("карта 4111 1111 1111 1111"), ["4111111111111111"]);
});

test("finds cards hidden with zero-width and fullwidth digits", () => {
  assert.deepEqual(X.extractRequisites("4111​1111 1111 １１１１"), ["4111111111111111"]);
});

test("extracts IBAN and Kaspi pay links", () => {
  const got = X.extractRequisites("IBAN KZ86 125K ZT50 0410 0100 и https://kaspi.kz/pay/bonus-akciya-30");
  assert.deepEqual(got, ["KZ86125KZT5004100100", "kaspi.kz/pay/bonus-akciya-30"]);
});

test("collects links from text and anchor hrefs without duplicates", () => {
  const links = X.extractLinks("зеркало joy-slots-kz.top!", ["https://joy-slots-kz.top", "javascript:alert(1)", "https://t.me/x"]);
  assert.deepEqual(links, ["joy-slots-kz.top", "https://joy-slots-kz.top", "https://t.me/x"]);
});

test("detects pyramid cues", () => {
  assert.deepEqual(X.detectCues(PYRAMID).sort(), ["income_promise", "kaspi_transfer", "paid_entry", "referral"].sort());
});

test("detects paid lottery with urgency", () => {
  const cues = X.detectCues(LOTTERY);
  for (const id of ["paid_entry", "giveaway", "kaspi_transfer", "urgency"]) assert.ok(cues.includes(id), id);
});

test("detects casino ads", () => {
  const cues = X.detectCues(CASINO);
  for (const id of ["casino", "big_win", "promo_code", "kaspi_transfer"]) assert.ok(cues.includes(id), id);
});

test("free giveaway raises only the weak giveaway cue", () => {
  assert.deepEqual(X.detectCues(LEGIT), ["giveaway"]);
});

test("detects Kazakh and translit pyramid wording", () => {
  assert.ok(X.detectCues("Күніне 3% табыс! Достарыңды шақыр").includes("income_promise"));
  assert.ok(X.detectCues("Passivnyi dohod 7% v den! Priglasi druzei").includes("referral"));
});

test("text hash ignores case, punctuation and spacing", async () => {
  const a = await X.textHash("Пассивный доход 5% в день!!!");
  const b = await X.textHash("  пассивный   ДОХОД 5 в день ");
  assert.equal(a, b);
  assert.match(a, /^[0-9a-f]{64}$/);
});

test("payload holds no post text", async () => {
  const payload = await X.buildPayload(PYRAMID, []);
  assert.deepEqual(Object.keys(payload).sort(), ["cues", "links", "requisites", "text_hash"]);
  assert.ok(!JSON.stringify(payload).includes("Пассивный"));
  assert.ok(X.worthChecking(payload));
});

test("plain chat message is not sent to the server", async () => {
  assert.equal(X.worthChecking(await X.buildPayload("Привет, как дела? Встречаемся вечером у фонтана", [])), false);
});

