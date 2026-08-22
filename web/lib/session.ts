import { createHmac, timingSafeEqual } from "node:crypto";

export function sessionLifetimeSeconds(): number {
  const configured = Number(process.env.KOMI_WEB_SESSION_SECONDS ?? 12 * 60 * 60);
  return Number.isSafeInteger(configured) && configured >= 1 && configured <= 12 * 60 * 60
    ? configured
    : 12 * 60 * 60;
}

function signature(issuedAt: number, expiresAt: number): string {
  const credentialHash = process.env.KOMI_WEB_ACCESS_HASH ?? "";
  const authEpoch = process.env.KOMI_WEB_AUTH_EPOCH ?? "";
  const secret = process.env.KOMI_WEB_SESSION_SECRET ?? "";
  return createHmac("sha256", secret)
    .update(`v1:${issuedAt}:${expiresAt}:${authEpoch}:${credentialHash}`)
    .digest("base64url");
}

export function createSessionToken(nowSeconds = Math.floor(Date.now() / 1000)): string {
  const expiresAt = nowSeconds + sessionLifetimeSeconds();
  return `v1.${nowSeconds}.${expiresAt}.${signature(nowSeconds, expiresAt)}`;
}

export function verifySessionToken(token: string, nowSeconds = Math.floor(Date.now() / 1000)): boolean {
  const [version, rawIssuedAt, rawExpiresAt, actualSignature, extra] = token.split(".");
  if (version !== "v1" || extra !== undefined || !actualSignature) return false;
  const issuedAt = Number(rawIssuedAt);
  const expiresAt = Number(rawExpiresAt);
  if (!Number.isSafeInteger(issuedAt) || !Number.isSafeInteger(expiresAt)) return false;
  if (issuedAt > nowSeconds + 60 || expiresAt <= nowSeconds || expiresAt - issuedAt !== sessionLifetimeSeconds()) return false;
  const expected = Buffer.from(signature(issuedAt, expiresAt));
  const actual = Buffer.from(actualSignature);
  return expected.length === actual.length && timingSafeEqual(expected, actual);
}

export function webUser(): string {
  return process.env.KOMI_WEB_USER ?? "admin";
}
