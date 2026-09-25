import assert from "node:assert/strict";
import test from "node:test";
import type { UserItem } from "../app/dashboard-types";
import { buildUserRows } from "../lib/report-user-rows";

function item(overrides: Partial<UserItem> = {}): UserItem {
  return {
    device_slot: 0, device_identity: "serial:A", device_name_snapshot: "Printer A",
    device_serial_snapshot: "A", subject_type: "user", subject_id: "123",
    subject_name: "บอม", report_user_key: "user:name:บอม", usage: 100,
    latest_total: 400, needs_review: false, warnings: [], ...overrides,
  };
}

for (const count of [2, 3]) {
  test(`one named person across ${count} printer-local IDs keeps each printer's usage`, () => {
    const inputs = [item(), item({ device_slot: 1, device_identity: "serial:B", subject_id: "456", usage: 50 }),
      item({ device_slot: 2, device_identity: "serial:C", subject_id: "789", usage: 20 })].slice(0, count);
    const [row, ...others] = buildUserRows(inputs);
    assert.deepEqual(others, []);
    assert.equal(row.name, "บอม");
    assert.equal(row.usage, count === 2 ? 150 : 170);
    assert.deepEqual([...row.printers], [["serial:A", 100], ["serial:B", 50], ["serial:C", 20]].slice(0, count));
  });
}

test("different names sharing a local ID remain different people", () => {
  const rows = buildUserRows([item(), item({ device_slot: 1, device_identity: "serial:B",
    subject_name: "วิภา", report_user_key: "user:name:วิภา", usage: 50 })]);
  assert.deepEqual(rows.map(row => [row.name, row.usage]), [["บอม", 100], ["วิภา", 50]]);
});

test("numeric placeholders stay scoped to their source even with leading zeros", () => {
  const rows = buildUserRows([item({ subject_name: "123", report_user_key: "user:slot:0:device:serial:A:id:123" }),
    item({ device_slot: 1, device_identity: "serial:B", subject_id: "00123", subject_name: "123",
      report_user_key: "user:slot:1:device:serial:B:id:00123", usage: 50 })]);
  assert.equal(rows.length, 2);
  assert.equal(rows.reduce((sum, row) => sum + row.usage, 0), 150);
});

test("User and Account Track of the same name retain their separate types", () => {
  const rows = buildUserRows([item(), item({ subject_type: "account", report_user_key: "account:name:บอม" })]);
  assert.deepEqual(rows.map(row => row.type), ["user", "account"]);
});

test("older payloads cannot merge identical IDs across slots or replacement printers", () => {
  const rows = buildUserRows([item({ report_user_key: undefined }),
    item({ report_user_key: undefined, device_slot: 1 }),
    item({ report_user_key: undefined, device_identity: "serial:NEW" })]);
  assert.equal(rows.length, 3);
  assert.equal(new Set(rows.map(row => row.key)).size, 3);
});

test("canonical printer identity joins legacy records once and retains review/latest state", () => {
  const inputs = [item({ device_identity: "slot:0", report_device_identity: "serial:A", usage: 5 }),
    item({ report_device_identity: "serial:A", usage: 7, latest_total: 500, needs_review: true })];
  const before = structuredClone(inputs);
  const [row] = buildUserRows(inputs);
  assert.equal(row.usage, 12);
  assert.deepEqual([...row.printers], [["serial:A", 12]]);
  assert.equal(row.latest, 500);
  assert.equal(row.review, true);
  assert.deepEqual(inputs, before);
});

test("empty payload and unnamed older record render without an invented name", () => {
  assert.deepEqual(buildUserRows([]), []);
  const [row] = buildUserRows([item({ subject_name: " ", report_user_key: undefined })]);
  assert.equal(row.name, "123");
});
