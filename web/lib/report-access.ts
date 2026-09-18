const READ_ONLY_REPORT_API_PATHS = new Set([
  "/api/health",
  "/api/v1/health",
  "/api/devices",
  "/api/v1/devices",
  "/api/reports/periods",
  "/api/v1/reports/periods",
  "/api/reports/overview",
  "/api/v1/reports/overview",
  "/api/reports/history",
  "/api/v1/reports/history",
  "/api/reports/users",
  "/api/v1/reports/users",
]);

export function passwordlessReportsEnabled(): boolean {
  const configured = Boolean(process.env.KOMI_WEB_ACCESS_CODE) ||
    (Boolean(process.env.KOMI_WEB_ACCESS_HASH) && process.env.KOMI_WEB_ACCESS_CONFIGURED !== "0");
  if (!configured) return true;
  return process.env.KOMI_WEB_REPORT_PASSWORDLESS === "1";
}

export function isPasswordlessReportRequest(method: string, path: string): boolean {
  if (method !== "GET" && method !== "HEAD") return false;
  if (path === "/") return true;
  return READ_ONLY_REPORT_API_PATHS.has(path);
}
