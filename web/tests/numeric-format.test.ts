import assert from "node:assert/strict";
import test from "node:test";
import { formatDate, money, num } from "../app/i18n";

test("counts and money use ASCII digits with stable decimal and grouping", () => {
  assert.equal(num(1234567), "1,234,567");
  assert.equal(money(1234.5), "1,234.50");
  assert.equal(money(-12.5), "-12.50");
  assert.equal(num(), "0");
  assert.equal(money(), "0.00");
});

test("Thai and English dates keep language/calendar conventions with ASCII digits", () => {
  for (const language of ["th", "en"] as const) {
    for (const value of ["2026-09-17", "2026-09-17T09:45:00"]) {
      const result = formatDate(value, language);
      assert.match(result, /[0-9]/);
      for (const digit of result.match(/\p{Decimal_Number}/gu) ?? []) {
        assert.match(digit, /^[0-9]$/);
      }
      assert.match(result, language === "th" ? /2569/ : /2026/);
    }
  }
  assert.equal(formatDate(null, "th"), "ยังไม่มีข้อมูล");
  assert.equal(formatDate(null, "en"), "No data yet");
});
