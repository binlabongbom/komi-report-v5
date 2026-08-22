import { createHmac } from "node:crypto";
import { mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

const WINDOW_MS = 10 * 60 * 1000;
const LOCK_MS = 15 * 60 * 1000;
const MAX_FAILURES = 5;

type FailureRecord = { failures: number[]; lockedUntil: number };
type State = { version: 1; records: Record<string, FailureRecord> };

export type LoginDecision = { allowed: boolean; retryAfterSeconds: number };

function statePath(): string {
  return process.env.KOMI_WEB_AUTH_STATE_FILE ?? "";
}

function emptyState(): State {
  return { version: 1, records: {} };
}

function readState(): State {
  const path = statePath();
  if (!path) return emptyState();
  try {
    const parsed = JSON.parse(readFileSync(path, "utf8")) as Partial<State>;
    if (parsed.version !== 1 || typeof parsed.records !== "object" || !parsed.records) return emptyState();
    return { version: 1, records: parsed.records };
  } catch {
    return emptyState();
  }
}

function writeState(state: State): void {
  const path = statePath();
  if (!path) return;
  mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
  const temporary = `${path}.tmp`;
  writeFileSync(temporary, `${JSON.stringify(state)}\n`, { encoding: "utf8", mode: 0o600 });
  renameSync(temporary, path);
}

function subjectKey(remoteAddress: string, user: string): string {
  const secret = process.env.KOMI_WEB_SESSION_SECRET ?? "";
  return createHmac("sha256", secret)
    .update(remoteAddress)
    .update("\0")
    .update(user.trim().toLowerCase())
    .digest("hex");
}

function activeFailures(record: FailureRecord | undefined, now: number): FailureRecord {
  return {
    failures: (record?.failures ?? []).filter(value => value > now - WINDOW_MS),
    lockedUntil: record?.lockedUntil ?? 0,
  };
}

export function loginDecision(remoteAddress: string, user: string, now = Date.now()): LoginDecision {
  const record = activeFailures(readState().records[subjectKey(remoteAddress, user)], now);
  if (record.lockedUntil <= now) return { allowed: true, retryAfterSeconds: 0 };
  return { allowed: false, retryAfterSeconds: Math.max(1, Math.ceil((record.lockedUntil - now) / 1000)) };
}

export function recordLoginFailure(remoteAddress: string, user: string, now = Date.now()): LoginDecision {
  const state = readState();
  const key = subjectKey(remoteAddress, user);
  const record = activeFailures(state.records[key], now);
  if (record.lockedUntil > now) {
    return { allowed: false, retryAfterSeconds: Math.max(1, Math.ceil((record.lockedUntil - now) / 1000)) };
  }
  record.failures.push(now);
  if (record.failures.length >= MAX_FAILURES) record.lockedUntil = now + LOCK_MS;
  state.records[key] = record;
  writeState(state);
  return loginDecision(remoteAddress, user, now);
}

export function recordLoginSuccess(remoteAddress: string, user: string): void {
  const state = readState();
  delete state.records[subjectKey(remoteAddress, user)];
  writeState(state);
}
