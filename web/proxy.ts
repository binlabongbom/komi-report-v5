import { NextRequest, NextResponse } from "next/server";
import { verifySessionToken } from "./lib/session";

export default async function proxy(request: NextRequest) {
  const path = request.nextUrl.pathname;
  if (path === "/login" || path.startsWith("/auth/session") || path.startsWith("/_next/") || path === "/favicon.ico") {
    return NextResponse.next();
  }
  const actual = request.cookies.get("komi_session")?.value ?? "";
  if (actual && verifySessionToken(actual)) return NextResponse.next();
  if (path.startsWith("/api/")) return NextResponse.json({ detail: "Authentication required" }, { status: 401 });
  const login = request.nextUrl.clone();
  login.pathname = "/login";
  login.search = "";
  return NextResponse.redirect(login);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image).*)"],
};
