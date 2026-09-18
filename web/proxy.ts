import { NextRequest, NextResponse } from "next/server";
import { isPasswordlessReportRequest, passwordlessReportsEnabled } from "./lib/report-access";
import { verifySessionToken } from "./lib/session";

export default async function proxy(request: NextRequest) {
  const path = request.nextUrl.pathname;
  if (path === "/login" && passwordlessReportsEnabled() &&
      (request.method === "GET" || request.method === "HEAD") &&
      request.nextUrl.searchParams.get("admin") !== "1") {
    const reports = request.nextUrl.clone();
    reports.pathname = "/";
    reports.search = "";
    return NextResponse.redirect(reports);
  }
  if (
    path === "/login" ||
    path.startsWith("/auth/session") ||
    path.startsWith("/_next/") ||
    path === "/favicon.ico" ||
    path === "/icon.png" ||
    path === "/icon.svg" ||
    path === "/api/v1/peer/discovery" ||
    path === "/api/v1/peer/claim" ||
    path === "/api/v1/peer/setup-snapshot"
  ) {
    return NextResponse.next();
  }
  const actual = request.cookies.get("komi_session")?.value ?? "";
  if (actual && verifySessionToken(actual)) return NextResponse.next();
  if (
    passwordlessReportsEnabled() &&
    isPasswordlessReportRequest(request.method, path)
  ) {
    return NextResponse.next();
  }
  if (path.startsWith("/api/")) return NextResponse.json({ detail: "Authentication required" }, { status: 401 });
  const login = request.nextUrl.clone();
  login.pathname = "/login";
  login.search = "";
  return NextResponse.redirect(login);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image).*)"],
};
