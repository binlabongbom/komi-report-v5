import { randomBytes } from "node:crypto";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import assert from "node:assert/strict";

import { loginDecision, recordLoginFailure, recordLoginSuccess } from "../lib/login-guard";
import { createSessionToken, verifySessionToken } from "../lib/session";

function randomSecret(): string {
  return randomBytes(32).toString("hex");
}

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
