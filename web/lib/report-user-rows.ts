import type { UserItem } from "../app/dashboard-types";

export type UserRow = {
  key: string;
  name: string;
  type: string;
  usage: number;
  latest: number;
  review: boolean;
  printers: Map<string, number>;
};

export function buildUserRows(users: readonly UserItem[]): UserRow[] {
  const rows = new Map<string, UserRow>();
  for (const item of users) {
    const identity = item.report_device_identity || item.device_identity ||
      (item.device_serial_snapshot ? `serial:${item.device_serial_snapshot}` : `slot:${item.device_slot}`);
    // The API uses the same name resolver as Desktop/Excel, before pagination.
    // Older payloads without its key remain scoped to the original account;
    // a matching local ID alone must never combine different printers' users.
    const key = item.report_user_key || JSON.stringify([
      "source", item.subject_type, item.device_slot, identity, item.subject_id,
    ]);
    const row = rows.get(key) ?? {
      key,
      name: item.subject_name.trim() || item.subject_id,
      type: item.subject_type,
      usage: 0,
      latest: 0,
      review: false,
      printers: new Map<string, number>(),
    };
    row.usage += item.usage;
    row.latest = Math.max(row.latest, item.latest_total);
    row.review ||= item.needs_review;
    row.printers.set(identity, (row.printers.get(identity) ?? 0) + item.usage);
    rows.set(key, row);
  }
  return [...rows.values()].sort((a, b) => b.usage - a.usage);
}
