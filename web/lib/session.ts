const encoder = new TextEncoder();

export async function sessionToken(): Promise<string> {
  const credentialHash = process.env.KOMI_WEB_ACCESS_HASH ?? "";
  const authEpoch = process.env.KOMI_WEB_AUTH_EPOCH ?? "";
  const secret = process.env.KOMI_WEB_SESSION_SECRET ?? "";
  const digest = await crypto.subtle.digest(
    "SHA-256",
    encoder.encode(`${credentialHash}:${authEpoch}:${secret}`),
  );
  return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
}

export function webUser(): string {
  return process.env.KOMI_WEB_USER ?? "admin";
}
