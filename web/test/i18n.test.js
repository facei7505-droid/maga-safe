// Казахский дашборд: строки интерфейса и шаблоны с числами переводятся, текст постов и незнакомое — нет.
import assert from "node:assert/strict";
import { test } from "node:test";

globalThis.localStorage = { getItem: () => "kk", setItem() {} };
const { t, lang } = await import("../i18n.js");
const { KK, KK_TEMPLATES } = await import("../i18n-kk.js");

test("язык берётся из сохранённой настройки", () => {
  assert.equal(lang, "kk");
});

test("точные строки и пробелы вокруг них", () => {
  assert.equal(t("Обзор"), "Шолу");
  assert.equal(t(" Риск "), " Тәуекел ");
});

test("шаблоны с числами и вложенный перевод", () => {
  assert.equal(t("Кейсов: 12"), "Кейстер: 12");
  assert.equal(t("Из 100 схем находит 83"), "100 схеманың ішінен 83 табады");
  assert.equal(t("высокий риск, балл 88"), "жоғары тәуекел, балл 88");
  assert.equal(t("Кейс C-211: Подтверждён · в чёрный список: 3"), "C-211 кейсі: Расталды · қара тізімге: 3");
  assert.equal(t("шаг 4 из 39"), "қадам 4 / 39");
});

test("{n} принимает только числа: текст поста не подменяется", () => {
  assert.equal(t("много постов · мало каналов · семейств пруфов: два"), "много постов · мало каналов · семейств пруфов: два");
  assert.equal(t("Розыгрыш iPhone! Участие 500 тг"), "Розыгрыш iPhone! Участие 500 тг");
});

test("у каждого шаблона перевод использует только свои слоты", () => {
  for (const [ru, kk] of KK_TEMPLATES) {
    const slots = (ru.match(/\{[ns]\}/g) || []).length;
    const used = [...kk.matchAll(/\{(\d)\}/g)].map((m) => Number(m[1]));
    assert.ok(used.every((i) => i < slots), `${ru} → ${kk}`);
  }
  assert.ok(Object.values(KK).every((v) => typeof v === "string" && v.trim()));
});
