import { randomBytes } from "node:crypto";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import assert from "node:assert/strict";

import { loginDecision, recordLoginFailure, recordLoginSuccess } from "../lib/login-guard";
import { createSessionToken, verifySessionToken } from "../lib/session";
import {
  isPasswordlessReportRequest,
  passwordlessReportsEnabled,
} from "../lib/report-access";

function randomSecret(): string {
  return randomBytes(32).toString("hex");
}

test("fresh and previously unconfigured installs open reports by default", () => {
  const keys = ["KOMI_WEB_ACCESS_HASH", "KOMI_WEB_ACCESS_CODE", "KOMI_WEB_ACCESS_CONFIGURED", "KOMI_WEB_REPORT_PASSWORDLESS"];
  const saved = keys.map(key => process.env[key]);
  try {
    keys.forEach(key => delete process.env[key]);
    assert.equal(passwordlessReportsEnabled(), true);
    process.env.KOMI_WEB_ACCESS_HASH = "unknown-generated-hash";
    process.env.KOMI_WEB_ACCESS_CONFIGURED = "0";
    process.env.KOMI_WEB_REPORT_PASSWORDLESS = "0";
    assert.equal(passwordlessReportsEnabled(), true);
    process.env.KOMI_WEB_ACCESS_CONFIGURED = "1";
    assert.equal(passwordlessReportsEnabled(), false);
  } finally {
    keys.forEach((key, index) => {
      if (saved[index] === undefined) delete process.env[key];
      else process.env[key] = saved[index];
    });
  }
});

test("login guard persists only a keyed subject and temporary lockout", () => {
  const root = mkdtempSync(join(tmpdir(), "komi-auth-test-"));
  try {
    process.env.KOMI_WEB_AUTH_STATE_FILE = join(root, "auth-state.json");
    process.env.KOMI_WEB_SESSION_SECRET = randomSecret();
    const remote = "192.0.2.30";
    const user = "admin";
    const now = 1_800_000_000_000;

    for (let index = 0; index < 4; index += 1) {
      assert.equal(recordLoginFailure(remote, user, now + index).allowed, true);
    }
    const locked = recordLoginFailure(remote, user, now + 4);

    assert.equal(locked.allowed, false);
    assert.equal(loginDecision(remote, user, now + 5).allowed, false);
    const stored = readFileSync(process.env.KOMI_WEB_AUTH_STATE_FILE, "utf8");
    assert.equal(stored.includes(remote), false);
    assert.equal(stored.includes(user), false);
    recordLoginSuccess(remote, user);
    assert.equal(loginDecision(remote, user, now + 5).allowed, true);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("session expires, survives restart state, and is revoked by auth epoch rotation", () => {
  process.env.KOMI_WEB_SESSION_SECRET = randomSecret();
  process.env.KOMI_WEB_ACCESS_HASH = randomSecret();
  process.env.KOMI_WEB_AUTH_EPOCH = randomSecret();
  process.env.KOMI_WEB_SESSION_SECONDS = "30";
  const issuedAt = 2_000_000_000;
  const token = createSessionToken(issuedAt);

  assert.equal(verifySessionToken(token, issuedAt + 1), true);
  assert.equal(verifySessionToken(token, issuedAt + 30), false);
  assert.equal(verifySessionToken(token, issuedAt + 1), true, "same persisted env survives process restart");

  process.env.KOMI_WEB_AUTH_EPOCH = randomSecret();
  assert.equal(verifySessionToken(token, issuedAt + 1), false);
});

test("passwordless mode grants only exact read-only report routes", () => {
  process.env.KOMI_WEB_REPORT_PASSWORDLESS = "1";
  assert.equal(passwordlessReportsEnabled(), true);
  for (const path of [
    "/",
    "/api/health",
    "/api/devices",
    "/api/reports/periods",
    "/api/reports/overview",
    "/api/reports/history",
    "/api/reports/users",
  ]) {
    assert.equal(isPasswordlessReportRequest("GET", path), true, path);
  }
  for (const path of [
    "/api/settings",
    "/api/sync/status",
    "/api/docs",
    "/api/openapi.json",
    "/login",
  ]) {
    assert.equal(isPasswordlessReportRequest("GET", path), false, path);
  }
  assert.equal(isPasswordlessReportRequest("POST", "/api/reports/overview"), false);
  assert.equal(isPasswordlessReportRequest("DELETE", "/api/devices"), false);
  delete process.env.KOMI_WEB_REPORT_PASSWORDLESS;
});

test("peer setup routes remain capability-gated outside Web login", () => {
  const proxySource = readFileSync(join(process.cwd(), "proxy.ts"), "utf8");
  assert.equal(proxySource.includes('path === "/api/v1/peer/discovery"'), true);
  assert.equal(proxySource.includes('path === "/api/v1/peer/claim"'), true);
  assert.equal(proxySource.includes('path === "/api/v1/peer/setup-snapshot"'), true);
  assert.equal(proxySource.includes('path === "/api/v2/peer/settings-history"'), true);
  assert.equal(proxySource.includes("X-KOMI-Peer-Sync-Token"), false);
});

test("paged peer history reaches capability validation without opening other peer paths", async () => {
  const { NextRequest } = await import("next/server");
  const { default: proxy } = await import("../proxy");
  const allowed = await proxy(new NextRequest("https://komi.local/api/v2/peer/settings-history/page?offset=0"));
  assert.equal(allowed.headers.get("x-middleware-next"), "1");
  const denied = await proxy(new NextRequest("https://komi.local/api/v2/peer/settings-history/unknown"));
  assert.equal(denied.status, 401);
});

test("passwordless proxy redirects stale login to reports while retaining explicit admin login", async () => {
  const { NextRequest } = await import("next/server");
  const { default: proxy } = await import("../proxy");
  process.env.KOMI_WEB_REPORT_PASSWORDLESS = "1";
  try {
    const redirected = await proxy(new NextRequest("https://komi.local/login"));
    assert.equal(redirected.headers.get("location"), "https://komi.local/");
    const admin = await proxy(new NextRequest("https://komi.local/login?admin=1"));
    assert.equal(admin.headers.get("location"), null);
    const reports = await proxy(new NextRequest("https://komi.local/"));
    assert.equal(reports.headers.get("location"), null);
    for (const icon of ["/icon.png", "/icon.svg"]) {
      assert.equal((await proxy(new NextRequest(`https://komi.local${icon}`))).headers.get("location"), null);
    }
    const protectedApi = await proxy(new NextRequest("https://komi.local/api/settings"));
    assert.equal(protectedApi.status, 401);
    const write = await proxy(new NextRequest("https://komi.local/api/devices", { method: "POST" }));
    assert.equal(write.status, 401);
    process.env.KOMI_WEB_REPORT_PASSWORDLESS = "0";
    const locked = await proxy(new NextRequest("https://komi.local/"));
    assert.equal(locked.headers.get("location"), "https://komi.local/login");
  } finally {
    delete process.env.KOMI_WEB_REPORT_PASSWORDLESS;
  }
});
