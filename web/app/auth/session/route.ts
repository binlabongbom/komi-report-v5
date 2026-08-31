import { NextRequest, NextResponse } from "next/server";
import { verifyWebAccessCode, webAccessConfigured } from "../../../lib/access-credential";
import { loginDecision, recordLoginFailure, recordLoginSuccess } from "../../../lib/login-guard";
import {
  createSessionToken,
  sessionLifetimeSeconds,
  verifySessionToken,
  webUser,
} from "../../../lib/session";
import { passwordlessReportsEnabled } from "../../../lib/report-access";

export async function GET(request: NextRequest) {
  const actual = request.cookies.get("komi_session")?.value ?? "";
  return NextResponse.json({
    authenticated: Boolean(actual && verifySessionToken(actual)),
    reportPasswordless: passwordlessReportsEnabled(),
  });
}

export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => ({}));
  const user = typeof body.user === "string" ? body.user : "";
  const remoteAddress = request.headers.get("x-komi-remote-address") ?? "unknown";
  const decision = loginDecision(remoteAddress, user);
  if (!decision.allowed) {
    return NextResponse.json(
      { ok: false, message: "ลองเข้าสู่ระบบหลายครั้งเกินไป กรุณารอชั่วคราว" },
      { status: 429, headers: { "Retry-After": String(decision.retryAfterSeconds) } },
    );
  }
  if (!webAccessConfigured() || body.user !== webUser() || !verifyWebAccessCode(body.code)) {
    const failed = recordLoginFailure(remoteAddress, user);
    const headers = failed.allowed ? undefined : { "Retry-After": String(failed.retryAfterSeconds) };
    return NextResponse.json(
      { ok: false, message: "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง" },
      { status: failed.allowed ? 401 : 429, headers },
    );
  }
  recordLoginSuccess(remoteAddress, user);
  const response = NextResponse.json({ ok: true });
  response.cookies.set("komi_session", createSessionToken(), {
    httpOnly: true,
    sameSite: "strict",
    secure: true,
    path: "/",
    maxAge: sessionLifetimeSeconds(),
  });
  return response;
}

export async function DELETE() {
  const response = NextResponse.json({ ok: true });
  response.cookies.set("komi_session", "", {
    httpOnly: true,
    sameSite: "strict",
    secure: true,
    path: "/",
    maxAge: 0,
  });
  return response;
}
