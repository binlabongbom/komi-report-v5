import { NextRequest, NextResponse } from "next/server";
import { verifyWebAccessCode, webAccessConfigured } from "../../../lib/access-credential";
import { sessionToken, webUser } from "../../../lib/session";

export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => ({}));
  if (!webAccessConfigured() || body.user !== webUser() || !verifyWebAccessCode(body.code)) {
    return NextResponse.json({ ok: false, message: "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง" }, { status: 401 });
  }
  const response = NextResponse.json({ ok: true });
  response.cookies.set("komi_session", await sessionToken(), {
    httpOnly: true,
    sameSite: "strict",
    secure: request.nextUrl.protocol === "https:",
    path: "/",
    maxAge: 60 * 60 * 12,
  });
  return response;
}

export async function DELETE() {
  const response = NextResponse.json({ ok: true });
  response.cookies.set("komi_session", "", { httpOnly: true, path: "/", maxAge: 0 });
  return response;
}
