"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  Device,
  HistoryGranularity,
  HistoryItem,
  Overview,
  Period,
  SettingsData,
  SyncStatus,
  UserItem,
} from "./dashboard-types";
import { CloudOverview, CloudPrinters, CloudUsers } from "./cloud-report-views";
import { formatDate, type Language, tr } from "./i18n";
import { SystemView, UsageView } from "./report-views";

type ViewId = "overview" | "users" | "printers" | "usage" | "system";
type DateRange = { start: string; end: string };
type PageResponse<T> = { items: T[]; next_offset: number | null };
type Health = { status: string; device_count: number; online_count: number };
type AccessMode = { authenticated: boolean; reportPasswordless: boolean };

const EMPTY_RANGE: DateRange = { start: "", end: "" };
const menu: { id: ViewId; icon: ViewId; th: string; en: string; group: "reports" | "system" }[] = [
  { id: "overview", icon: "overview", th: "ภาพรวม", en: "Overview", group: "reports" },
  { id: "users", icon: "users", th: "ผู้ใช้งาน", en: "Users", group: "reports" },
  { id: "printers", icon: "printers", th: "เครื่องพิมพ์", en: "Printers", group: "reports" },
  { id: "usage", icon: "usage", th: "ประวัติการใช้งาน", en: "Usage", group: "reports" },
  { id: "system", icon: "system", th: "ข้อมูลระบบ", en: "System information", group: "system" },
];
const reportViews = new Set<ViewId>(["overview", "users", "printers"]);

function NavIcon({ icon }: { icon: ViewId }) {
  const paths: Record<ViewId, React.ReactNode> = {
    overview: <><path d="M4 13h6V4H4zM14 20h6V9h-6zM4 20h6v-3H4zM14 5h6"/></>,
    users: <><circle cx="9" cy="8" r="3"/><path d="M3.5 19c.5-4 2.3-6 5.5-6s5 2 5.5 6M16 7.5a2.5 2.5 0 0 1 0 5M16 14c2.7.3 4.1 2 4.5 5"/></>,
    printers: <><path d="M7 8V3h10v5M6 18H4V9h16v9h-2M7 14h10v7H7z"/><path d="M16 11h1"/></>,
    usage: <><path d="M4 19V9M10 19V5M16 19v-7M22 19H2"/></>,
    system: <><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-1.6v-.2h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1z"/></>,
  };
  return <svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{paths[icon]}</svg>;
}

async function json<T>(url: string): Promise<T> {
  const response = await fetch(url, { cache: "no-store" });
  if (response.status === 401) {
    window.location.href = "/login";
    throw new Error("Authentication required");
  }
  if (!response.ok) throw new Error(url);
  return response.json();
}

function reportUrl(path: string, range: DateRange | null, extra: Record<string, string> = {}) {
  const params = new URLSearchParams(extra);
  if (range?.start) params.set("period_start", range.start);
  if (range?.end) params.set("period_end", range.end);
  const query = params.toString();
  return query ? `${path}?${query}` : path;
}

async function allPages<T>(path: string, range: DateRange | null, extra: Record<string, string> = {}) {
  const items: T[] = [];
  let offset = 0;
  for (;;) {
    const page = await json<PageResponse<T>>(reportUrl(path, range, { ...extra, limit: "100", offset: String(offset) }));
    items.push(...page.items);
    if (page.next_offset == null) return items;
    offset = page.next_offset;
  }
}

export default function Home() {
  const [language, setLanguage] = useState<Language>("th");
  const [active, setActive] = useState<ViewId>("overview");
  const [periods, setPeriods] = useState<Period[]>([]);
  const [range, setRange] = useState<DateRange>(EMPTY_RANGE);
  const [draftRange, setDraftRange] = useState<DateRange>(EMPTY_RANGE);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [devices, setDevices] = useState<Device[]>([]);
  const [users, setUsers] = useState<UserItem[]>([]);
  const [usageHistory, setUsageHistory] = useState<HistoryItem[]>([]);
  const [usageGranularity, setUsageGranularity] = useState<HistoryGranularity>("monthly");
  const [sync, setSync] = useState<SyncStatus | null>(null);
  const [settings, setSettings] = useState<SettingsData | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [loading, setLoading] = useState(true);
  const [usageLoading, setUsageLoading] = useState(false);
  const [systemLoading, setSystemLoading] = useState(false);
  const [reportFailures, setReportFailures] = useState<string[]>([]);
  const [usageError, setUsageError] = useState(false);
  const [systemFailures, setSystemFailures] = useState<string[]>([]);
  const [periodError, setPeriodError] = useState("");
  const [accessMode, setAccessMode] = useState<AccessMode | null>(null);
  const reportRequest = useRef(0);
  const usageRequest = useRef(0);

  useEffect(() => {
    const saved = window.localStorage.getItem("komi-web-language");
    if (saved === "en") setLanguage("en");
  }, []);

  const changeLanguage = useCallback((next: Language) => {
    setLanguage(next);
    window.localStorage.setItem("komi-web-language", next);
  }, []);

  const loadHealth = useCallback(async () => {
    try {
      setHealth(await json<Health>("/api/health"));
    } catch (error) {
      if (error instanceof Error && error.message !== "Authentication required") setHealth(null);
    }
  }, []);

  const loadReports = useCallback(async (selected: DateRange | null) => {
    const request = ++reportRequest.current;
    setLoading(true);
    setReportFailures([]);
    const results = await Promise.allSettled([
      json<Overview>(reportUrl("/api/reports/overview", selected)),
      allPages<HistoryItem>("/api/reports/history", selected, { granularity: "daily" }),
      json<{ items: Device[] }>("/api/devices"),
      allPages<UserItem>("/api/reports/users", selected),
    ]);
    if (request !== reportRequest.current) return;
    const failures: string[] = [];
    const [overviewResult, historyResult, deviceResult, userResult] = results;
    if (overviewResult.status === "fulfilled") setOverview(overviewResult.value); else { setOverview(null); failures.push("overview"); }
    if (historyResult.status === "fulfilled") setHistory(historyResult.value); else { setHistory([]); failures.push("history"); }
    if (deviceResult.status === "fulfilled") setDevices(deviceResult.value.items); else { setDevices([]); failures.push("devices"); }
    if (userResult.status === "fulfilled") setUsers(userResult.value); else { setUsers([]); failures.push("users"); }
    setReportFailures(failures);
    setLoading(false);
  }, []);

  const loadUsage = useCallback(async (granularity: HistoryGranularity) => {
    const request = ++usageRequest.current;
    setUsageLoading(true);
    setUsageError(false);
    try {
      const items = await allPages<HistoryItem>("/api/reports/history", null, { granularity });
      if (request === usageRequest.current) setUsageHistory(items);
    } catch (error) {
      if (request === usageRequest.current && error instanceof Error && error.message !== "Authentication required") {
        setUsageHistory([]);
        setUsageError(true);
      }
    } finally {
      if (request === usageRequest.current) setUsageLoading(false);
    }
  }, []);

  const loadSystem = useCallback(async () => {
    setSystemLoading(true);
    setSystemFailures([]);
    const [settingsResult, syncResult] = await Promise.allSettled([
      json<SettingsData>("/api/settings"),
      json<SyncStatus>("/api/sync/status"),
    ]);
    const failures: string[] = [];
    if (settingsResult.status === "fulfilled") setSettings(settingsResult.value); else { setSettings(null); failures.push("settings"); }
    if (syncResult.status === "fulfilled") setSync(syncResult.value); else { setSync(null); failures.push("sync"); }
    setSystemFailures(failures);
    setSystemLoading(false);
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function initialize() {
      let mode: AccessMode = { authenticated: false, reportPasswordless: false };
      try {
        mode = await json<AccessMode>("/auth/session");
      } catch {
        // The proxy remains the authority.  A failed mode check does not open
        // any additional route and ordinary report requests still fail closed.
      }
      if (cancelled) return;
      setAccessMode(mode);
      void loadHealth();
      if (mode.authenticated) void loadSystem();
      let selected: DateRange | null = null;
      try {
        const periodData = await json<{ items: Period[] }>("/api/reports/periods");
        if (cancelled) return;
        setPeriods(periodData.items);
        if (periodData.items.length) {
          selected = { start: periodData.items[0].start, end: periodData.items[0].end };
          setRange(selected);
          setDraftRange(selected);
        }
      } catch (error) {
        if (error instanceof Error && error.message !== "Authentication required") setPeriodError("periods");
      }
      if (!cancelled) await loadReports(selected);
    }
    void initialize();
    return () => { cancelled = true; };
  }, [loadHealth, loadReports, loadSystem]);

  const minimumDate = periods.at(-1)?.start ?? "";
  const maximumDate = periods[0]?.end ?? "";
  const visibleMenu = accessMode?.authenticated
    ? menu
    : menu.filter(item => item.group === "reports");
  const activeItem = visibleMenu.find(item => item.id === active) ?? visibleMenu[0];
  const isPeriodReport = reportViews.has(active);
  const failureNames = useMemo(() => reportFailures.map(item => ({
    overview: tr(language, "ภาพรวม", "overview"),
    history: tr(language, "กราฟ", "charts"),
    devices: tr(language, "เครื่องพิมพ์", "printers"),
    users: tr(language, "ผู้ใช้งาน", "users"),
  })[item]).filter(Boolean), [language, reportFailures]);

  function applyRange() {
    if (!draftRange.start || !draftRange.end || draftRange.start > draftRange.end) {
      setPeriodError("invalid");
      return;
    }
    setPeriodError("");
    setRange(draftRange);
    void loadReports(draftRange);
  }

  function selectView(view: ViewId) {
    setActive(view);
    if (view === "usage" && !usageHistory.length && !usageLoading) void loadUsage(usageGranularity);
    if (view === "system" && !settings && !systemLoading) void loadSystem();
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  }

  function changeGranularity(next: HistoryGranularity) {
    setUsageGranularity(next);
    void loadUsage(next);
  }

  function refreshCurrent() {
    void loadHealth();
    if (isPeriodReport) void loadReports(range.start ? range : null);
    else if (active === "usage") void loadUsage(usageGranularity);
    else void loadSystem();
  }

  async function logout() {
    await fetch("/auth/session", { method: "DELETE" });
    window.location.href = "/login";
  }

  let view = <CloudOverview overview={overview} history={history} users={users} loading={loading} language={language}/>;
  if (active === "users") view = <CloudUsers users={users} overview={overview} language={language}/>;
  if (active === "printers") view = <CloudPrinters key={`${range.start}|${range.end}`} overview={overview} history={history} devices={devices} language={language}/>;
  if (active === "usage") view = usageError
    ? <div className="empty-state"><strong>{tr(language, "โหลดประวัติการใช้งานไม่สำเร็จ", "Usage history could not be loaded")}</strong><button className="primary" onClick={() => void loadUsage(usageGranularity)}>{tr(language, "ลองใหม่", "Retry")}</button></div>
    : <UsageView history={usageHistory} granularity={usageGranularity} onGranularity={changeGranularity} language={language} loading={usageLoading}/>;
  if (active === "system") view = <SystemView settings={settings} sync={sync} failures={systemFailures} loading={systemLoading} onRetry={() => void loadSystem()} language={language}/>;

  return <main className="app-shell" lang={language}>
    <aside className="sidebar">
      <div className="brand"><span className="brand-mark"><i/><i/><i/><i/></span><div><strong>KOMI REPORT</strong><small>Meter Control V5</small></div></div>
      <nav aria-label={tr(language, "เมนูหลัก", "Main navigation")}>{visibleMenu.map((item, index) => <div key={item.id}>{(index === 0 || visibleMenu[index - 1].group !== item.group) && <small className="nav-group">{item.group === "reports" ? tr(language, "รายงาน", "Reports") : tr(language, "ระบบ", "System")}</small>}<button className={active === item.id ? "active" : ""} onClick={() => selectView(item.id)} title={tr(language, item.th, item.en)} aria-current={active === item.id ? "page" : undefined}><NavIcon icon={item.icon}/><span>{tr(language, item.th, item.en)}</span></button></div>)}</nav>
      <div className="sidebar-foot">{accessMode?.authenticated && <button onClick={() => void logout()}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10 4H4v16h6M14 8l4 4-4 4M8 12h10"/></svg><span>{tr(language, "ออกจากระบบ", "Sign out")}</span></button>}<small>{accessMode?.reportPasswordless && !accessMode.authenticated ? tr(language, "รายงาน LAN · อ่านอย่างเดียว", "LAN reports · Read only") : "Web Edition · Read only"}</small></div>
    </aside>
    <section className="workspace">
      <header className="topbar"><div><p>{activeItem.group === "reports" ? tr(language, "รายงาน", "Reports") : tr(language, "ระบบ", "System")}</p><h1>{tr(language, activeItem.th, activeItem.en)}</h1></div><div className="topbar-actions"><div className="language-switch" role="group" aria-label={tr(language, "เลือกภาษา", "Choose language")}><button className={language === "th" ? "active" : ""} onClick={() => changeLanguage("th")} aria-pressed={language === "th"}>ไทย</button><button className={language === "en" ? "active" : ""} onClick={() => changeLanguage("en")} aria-pressed={language === "en"}>EN</button></div><div className={`server-pill ${health ? "" : "offline"}`}><span/>{health ? tr(language, `พร้อมใช้งาน · ${health.online_count}/${health.device_count} เครื่อง`, `Online · ${health.online_count}/${health.device_count} printers`) : tr(language, "ไม่สามารถติดต่อ Server", "Server unavailable")}</div></div></header>
      <div className="content">
        {failureNames.length > 0 && <div className="alert error recovery" role="alert"><span>{tr(language, `โหลด ${failureNames.join(", ")} ไม่สำเร็จ ส่วนอื่นยังใช้งานได้`, `Could not load ${failureNames.join(", ")}. Other sections remain available.`)}</span><button onClick={() => void loadReports(range.start ? range : null)}>{tr(language, "ลองใหม่", "Retry")}</button></div>}
        {isPeriodReport && <section className="toolbar cloud-toolbar" aria-label={tr(language, "กำหนดช่วงรายงาน", "Report date range")}>
          <label>{tr(language, "วันที่เริ่มต้น", "From")}<input type="date" value={draftRange.start} min={minimumDate} max={maximumDate} onChange={event => setDraftRange(current => ({ ...current, start: event.target.value }))}/></label>
          <label>{tr(language, "วันที่สิ้นสุด", "To")}<input type="date" value={draftRange.end} min={minimumDate} max={maximumDate} onChange={event => setDraftRange(current => ({ ...current, end: event.target.value }))}/></label>
          <button className="primary apply-range" onClick={applyRange} disabled={loading}>{loading ? tr(language, "กำลังโหลด…", "Loading…") : tr(language, "แสดงรายงาน", "Apply")}</button>
          <div className="sync-meta"><span>{tr(language, "ข้อมูลล่าสุด", "Last data update")}</span><strong>{formatDate(overview?.last_sync_at, language)}</strong></div>
          <button className="secondary refresh-button" onClick={refreshCurrent} disabled={loading}>{tr(language, "รีเฟรช", "Refresh")}</button>
          {periodError && <p className="range-error" role="alert">{periodError === "invalid" ? tr(language, "กรุณาตรวจสอบวันที่เริ่มต้นและวันที่สิ้นสุด", "Check the start and end dates") : tr(language, "โหลดรายการรอบบิลไม่สำเร็จ แต่ยังลองเลือกวันที่ได้", "Billing periods could not be loaded; you can still choose dates")}</p>}
        </section>}
        {!isPeriodReport && <div className="page-actions"><button className="secondary" onClick={refreshCurrent} disabled={active === "usage" ? usageLoading : systemLoading}>{tr(language, "รีเฟรชข้อมูล", "Refresh")}</button></div>}
        {view}
      </div>
    </section>
  </main>;
}
