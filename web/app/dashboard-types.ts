export type Period = { start: string; end: string };

export type Device = {
  slot: number;
  name: string;
  host: string;
  model: string;
  serial: string;
  status: string;
  last_checked_at: string | null;
  last_success_at: string | null;
  last_total: number | null;
  status_detail: string;
};

export type Usage = {
  total: number;
  color: number;
  bw: number;
  scan: number;
  gross_cost: number;
  net_cost: number;
  incomplete_days: number;
  held_days: number;
  confirmed_total: number;
  confirmed_gross_cost: number;
  confirmed_net_cost: number;
  provisional_total: number;
  provisional_print_color: number;
  provisional_print_bw: number;
  provisional_copy_color: number;
  provisional_copy_bw: number;
  provisional_scan: number;
  provisional_gross_cost: number;
  provisional_net_cost: number;
  provisional_days: number;
  provisional_cost_available: boolean;
};

export type DeviceUsage = Device & {
  device_identity: string;
  is_current_identity: boolean;
  usage: Usage & {
    device_slot: number;
    period_start: string;
    period_end: string;
    device_identity: string;
    device_name_snapshot: string;
    device_serial_snapshot: string;
  };
};

export type Overview = {
  period: Period | null;
  last_sync_at: string | null;
  waste_pct: number;
  empty: boolean;
  totals: {
    usage: number;
    color: number;
    bw: number;
    scan: number;
    print_color: number;
    print_bw: number;
    copy_color: number;
    copy_bw: number;
    print_available: boolean;
    copy_available: boolean;
    gross_cost: number;
    net_cost: number;
    incomplete_days: number;
    held_days: number;
    confirmed_usage: number;
    confirmed_net_cost: number;
    provisional_usage: number;
    provisional_net_cost: number;
    provisional_days: number;
    provisional_cost_available: boolean;
  };
  devices: DeviceUsage[];
  top_users: {
    name: string;
    type: string;
    usage: number;
    needs_review: boolean;
    device_identities: string[];
  }[];
  data_quality: {
    status: string;
    incomplete_days: number;
    held_days: number;
    subject_warnings: number;
    mixed_identity_slots: number[];
    historical_identity_slots: number[];
    provisional_days: number;
  };
};

export type HistoryGranularity = "daily" | "weekly" | "monthly" | "quarterly" | "yearly";

export type HistoryItem = {
  period_start: string;
  period_end: string;
  usage: number;
  color: number;
  bw: number;
  scan: number;
  net_cost: number;
  incomplete_days: number;
  held_days: number;
  device_identities: string[];
  mixed_identity_slots: number[];
  provisional_usage: number;
  provisional_net_cost: number;
  provisional_days: number;
  provisional_cost_available: boolean;
};

export type UserItem = {
  device_slot: number;
  device_identity: string;
  device_name_snapshot: string;
  device_serial_snapshot: string;
  subject_type: string;
  subject_id: string;
  subject_name: string;
  usage: number;
  latest_total: number;
  needs_review: boolean;
  warnings: string[];
};

export type SyncStatus = {
  server_time: string;
  snmp_interval_minutes: number;
  devices: (Device & {
    next_poll_at: string | null;
    sample_count_today: number;
    heartbeat_count_today: number;
    last_cache_status: string;
  })[];
  timeline: {
    time_range: string;
    mode: string;
    snmp: string;
    web: string;
    ram: string;
    database: string;
    note: string;
  }[];
};

export type SettingsData = {
  mode: "read_only";
  billing_day: number;
  waste_pct: number;
  work_start: string;
  work_end: string;
  snmp_interval_minutes: number;
  web_interval_minutes: number;
  peak_web_interval_minutes: number;
  device_prices: {
    slot: number;
    name: string;
    prices: { a3_color: number; a3_bw: number; a4_color: number; a4_bw: number };
  }[];
};
