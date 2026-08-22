import { scryptSync, timingSafeEqual } from "node:crypto";

const SCRYPT_N = 1 << 17;
const SCRYPT_R = 8;
const SCRYPT_P = 1;
const SCRYPT_MAXMEM = 256 * 1024 * 1024;
const DIGEST_LENGTH = 32;

export function webAccessConfigured(): boolean {
  return process.env.KOMI_WEB_ACCESS_CONFIGURED === "1";
}

export function verifyWebAccessCode(code: unknown): boolean {
  if (typeof code !== "string" || code.length < 1 || code.length > 128) return false;
  const encoded = process.env.KOMI_WEB_ACCESS_HASH ?? "";
  try {
    const delimiter = encoded.includes(":") ? ":" : "$";
    const [scheme, rawN, rawR, rawP, encodedSalt, encodedDigest] = encoded.split(delimiter);
    const n = Number(rawN);
    const r = Number(rawR);
    const p = Number(rawP);
    if (scheme !== "scrypt" || n !== SCRYPT_N || r !== SCRYPT_R || p !== SCRYPT_P) return false;
    const salt = Buffer.from(encodedSalt, "base64url");
    const expected = Buffer.from(encodedDigest, "base64url");
    if (salt.length !== 16 || expected.length !== DIGEST_LENGTH) return false;
    const actual = scryptSync(code, salt, expected.length, { N: n, r, p, maxmem: SCRYPT_MAXMEM });
    return timingSafeEqual(actual, expected);
  } catch {
    return false;
  }
}
