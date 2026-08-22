"use client";

import { useMemo } from "react";
import type { HistoryGranularity, HistoryItem, SettingsData, SyncStatus } from "./dashboard-types";
import { formatDate, type Language, tr } from "./i18n";

export const slotColors = ["#0879db", "#e38b18", "#e45461"];
export const num = (value?: number) => new Intl.NumberFormat("th-TH", { maximumFractionDigits: 0 }).format(value ?? 0);
export const money = (value?: number) => new Intl.NumberFormat("th-TH", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value ?? 0);

export function StatusBadge({ status, language = "th" }: { status: string; language?: Language }) {
  const normalized = status.toLowerCase();
  if (normalized === "historical") return <span className="status review">{tr(language, "เครื่องเดิม", "Historical")}</span>;
  const online = normalized === "online";
  return <span className={`status ${online ? "online" : "stale"}`}>{online ? tr(language, "ออนไลน์", "Online") : tr(language, "ค่าล่าสุด", "Last known")}</span>;
}

export function Sparkline({ values, language = "th" }: { values: HistoryItem[]; language?: Language }) {
  const points = useMemo(() => {
    if (!values.length) return "";
    const max = Math.max(...values.map(item => item.usage), 1);
    return values.map((item, index) => `${(index / Math.max(values.length - 1, 1)) * 100},${92 - (item.usage / max) * 72}`).join(" ");
  }, [values]);
  return <div className="chart-stage">{!points ? <div className="empty">{tr(language, "ยังไม่มีประวัติเพียงพอสำหรับสร้างกราฟ", "Not enough history to draw this chart")}</div> : <svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label={tr(language, "กราฟแนวโน้มการใช้งาน", "Usage trend chart")}><defs><linearGradient id="usage-area" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#1687e8" stopOpacity=".22"/><stop offset="1" stopColor="#1687e8" stopOpacity="0"/></linearGradient></defs><polyline points={`0,96 ${points} 100,96`} fill="url(#usage-area)" stroke="none"/><polyline points={points} fill="none" stroke="#0879db" strokeWidth="1.4" vectorEffect="non-scaling-stroke"/></svg>}</div>;
}

const granularityLabels: Record<HistoryGranularity, { th: string; en: string }> = {
  daily: { th: "รายวัน", en: "Daily" },
  weekly: { th: "รายสัปดาห์", en: "Weekly" },
  monthly: { th: "รายเดือน", en: "Monthly" },
  quarterly: { th: "รายไตรมาส", en: "Quarterly" },
  yearly: { th: "รายปี", en: "Yearly" },
};

function GranularitySelect({ value, onChange, language }: { value: HistoryGranularity; onChange: (value: HistoryGranularity) => void; language: Language }) {
  return <label className="compact-select">{tr(language, "มุมมอง", "View")}<select value={value} onChange={event => onChange(event.target.value as HistoryGranularity)}>{Object.entries(granularityLabels).map(([key, label]) => <option value={key} key={key}>{tr(language, label.th, label.en)}</option>)}</select></label>;
}

export function UsageView({ history, granularity, onGranularity, language, loading }: { history: HistoryItem[]; granularity: HistoryGranularity; onGranularity: (value: HistoryGranularity) => void; language: Language; loading: boolean }) {
  return <section className="view-stack"><div className="section-intro"><div><h2>{tr(language, "ยอดใช้งานและค่าใช้จ่าย", "Usage and cost history")}</h2><p>{tr(language, "แสดงประวัติทั้งหมด ไม่ผูกกับช่วงวันที่ของ Overview", "Shows all history independently from the Overview date range")}</p></div><GranularitySelect value={granularity} onChange={onGranularity} language={language}/></div><article className="panel"><div className="table-wrap roomy"><table><thead><tr><th>{tr(language, "ช่วงเวลา", "Period")}</th><th>Color</th><th>B&W</th><th>Scan</th><th>{tr(language, "รวม", "Total")}</th><th>{tr(language, "ค่าใช้จ่ายสุทธิ", "Net cost")}</th><th>{tr(language, "คุณภาพข้อมูล", "Data quality")}</th></tr></thead><tbody>{loading ? <tr><td colSpan={7} className="empty-cell">{tr(language, "กำลังโหลดประวัติ…", "Loading history…")}</td></tr> : history.length ? [...history].reverse().map(item => { const mixedSlots = item.mixed_identity_slots ?? []; const needsReview = Boolean(item.held_days || item.incomplete_days || mixedSlots.length); const live = Boolean(item.provisional_days); const prefix = live ? "~" : ""; return <tr key={`${item.period_start}-${item.period_end}`}><td><strong>{formatDate(item.period_start, language)}</strong><small>{tr(language, "ถึง", "to")} {formatDate(item.period_end, language)}</small></td><td>{prefix}{num(item.color)}</td><td>{prefix}{num(item.bw)}</td><td>{prefix}{num(item.scan)}</td><td>{prefix}{num(item.usage)}</td><td>{live && !item.provisional_cost_available ? "—" : `${prefix}฿${money(item.net_cost)}`}</td><td>{needsReview ? <><span className="status review">{tr(language, "ตรวจสอบ", "Review")}</span>{mixedSlots.length > 0 && <small>{tr(language, "เปลี่ยนเครื่องใน Slot", "Printer changed in slot")} {mixedSlots.map(slot => slot + 1).join(", ")}</small>}</> : live ? <span className="status provisional">{tr(language, "ระหว่างวัน", "In progress")}</span> : <span className="status online">{tr(language, "ยืนยันแล้ว", "Confirmed")}</span>}</td></tr>; }) : <tr><td colSpan={7} className="empty-cell">{tr(language, "ยังไม่มีประวัติการใช้งาน", "No usage history yet")}</td></tr>}</tbody></table></div></article><p className="page-note">{tr(language, "เครื่องหมาย ~ คือข้อมูลวันนี้จาก Daily Cache ซึ่งยังไม่ปิด Billing Ledger", "The ~ symbol marks today’s Daily Cache data before the Billing Ledger is closed")}</p></section>;
}

function SettingsSummary({ settings, language }: { settings: SettingsData; language: Language }) {
  return <><div className="settings-grid"><article className="panel settings-card"><h3>{tr(language, "รอบบิลและการอ่านข้อมูล", "Billing and data collection")}</h3><dl><div><dt>{tr(language, "วันสิ้นสุดรอบบิล", "Billing end day")}</dt><dd>{settings.billing_day}</dd></div><div><dt>{tr(language, "ส่วนลดกระดาษเสีย", "Waste-paper discount")}</dt><dd>{settings.waste_pct}%</dd></div><div><dt>{tr(language, "เวลาทำงาน", "Working hours")}</dt><dd>{settings.work_start} – {settings.work_end}</dd></div><div><dt>SNMP</dt><dd>{tr(language, `ทุก ${settings.snmp_interval_minutes} นาที`, `Every ${settings.snmp_interval_minutes} minutes`)}</dd></div><div><dt>Web normal / peak</dt><dd>{settings.web_interval_minutes} / {settings.peak_web_interval_minutes} {tr(language, "นาที", "min")}</dd></div></dl></article>{settings.device_prices.map(device => <article className="panel settings-card price-card" key={device.slot} style={{"--slot": slotColors[device.slot]} as React.CSSProperties}><h3>{device.name}</h3><p>{tr(language, "บาทต่อหน้า · ราคาที่มีผลล่าสุด", "THB per page · latest effective price")}</p><div className="price-grid"><div><span>A4 Color</span><strong>฿{money(device.prices.a4_color)}</strong></div><div><span>A4 B&W</span><strong>฿{money(device.prices.a4_bw)}</strong></div><div><span>A3 Color</span><strong>฿{money(device.prices.a3_color)}</strong></div><div><span>A3 B&W</span><strong>฿{money(device.prices.a3_bw)}</strong></div></div></article>)}</div><div className="alert info">{tr(language, "หน้านี้เป็นแบบอ่านอย่างเดียว หากต้องการแก้ราคา รอบบิล หรือเวลาอ่านข้อมูล ให้เปิด KOMI Report Desktop", "This page is read-only. Open KOMI Report Desktop to change prices, billing, or collection schedules.")}</div></>;
}

function timelineText(value: string, language: Language) {
  if (language === "th") return value;
  const exact: Record<string, string> = {
    "Daily rollover": "Daily rollover",
    Normal: "Normal",
    Peak: "Peak",
    "รอบถัดไปตาม Timer": "At the next timer cycle",
    "ไม่บังคับอ่านเพิ่ม": "No forced additional read",
    "ตรวจ Cache ของวันก่อน": "Check the previous day's cache",
    "แพ็ก 1 Daily Record / เครื่อง แล้วลบ Cache เมื่อ commit สำเร็จ": "Commit one daily record per printer, then clear the cache",
    "เกิดเมื่อโปรแกรมทำงานและตรวจพบว่าเปลี่ยนวัน": "Runs when the app is active and detects a date change",
    "ทุก SNMP เก็บ heartbeat/toner · เมื่อ Web สำเร็จเก็บ Counter/User snapshot": "Each SNMP cycle stores heartbeat and toner; successful Web reads store counter and user snapshots",
    "พักใน Daily Cache": "Hold in Daily Cache",
    "Background ทำงานต่อเมื่อยุบไว้ใน System Tray": "Background collection continues while minimized to the System Tray",
    "ช่วงที่ผู้ใช้กำหนดเอง": "User-defined schedule window",
    "12:00 ทำงานตาม Normal schedule ต่อเนื่อง": "Normal schedule continues through 12:00",
  };
  if (exact[value]) return exact[value];
  const snmp = value.match(/^ทุก (\d+) นาที · Status \/ Total \/ Toner$/);
  if (snmp) return `Every ${snmp[1]} minutes · Status / Total / Toner`;
  const web = value.match(/^เมื่อ Total เพิ่ม · throttle (\d+) นาที$/);
  if (web) return `When Total increases · throttle ${web[1]} minutes`;
  return value;
}

function SyncDetails({ sync, language }: { sync: SyncStatus; language: Language }) {
  return <div className="support-content"><div className="sync-cards">{sync.devices.map(device => <article className="panel sync-card" key={device.slot} style={{"--slot": slotColors[device.slot]} as React.CSSProperties}><div><strong>{device.name}</strong><small>{device.host}</small></div><StatusBadge status={device.status} language={language}/><dl><div><dt>{tr(language, "ตรวจล่าสุด", "Last check")}</dt><dd>{formatDate(device.last_checked_at, language)}</dd></div><div><dt>{tr(language, "รอบถัดไป", "Next check")}</dt><dd>{formatDate(device.next_poll_at, language)}</dd></div><div><dt>{tr(language, "Web snapshot วันนี้", "Web snapshots today")}</dt><dd>{device.sample_count_today}</dd></div><div><dt>{tr(language, "SNMP heartbeat วันนี้", "SNMP heartbeats today")}</dt><dd>{device.heartbeat_count_today}</dd></div></dl></article>)}</div><article className="panel"><div className="panel-head"><div><h2>{tr(language, "ตารางการทำงาน 1 วัน", "Daily collection timeline")}</h2><p>{tr(language, "รายละเอียดสำหรับตรวจสอบเมื่อข้อมูลไม่อัปเดต", "Support detail for diagnosing stale data")}</p></div></div><div className="table-wrap timeline-wrap"><table><thead><tr><th>{tr(language, "เวลา", "Time")}</th><th>{tr(language, "โหมด", "Mode")}</th><th>SNMP</th><th>Web Connection</th><th>RAM / Daily Cache</th><th>Database</th></tr></thead><tbody>{sync.timeline.map((item, index) => <tr key={`${item.time_range}-${index}`}><td><strong>{item.time_range}</strong></td><td>{timelineText(item.mode, language)}</td><td>{timelineText(item.snmp, language)}</td><td>{timelineText(item.web, language)}</td><td>{timelineText(item.ram, language)}</td><td>{timelineText(item.database, language)}<small>{timelineText(item.note, language)}</small></td></tr>)}</tbody></table></div></article></div>;
}

export function SystemView({ settings, sync, failures, loading, onRetry, language }: { settings: SettingsData | null; sync: SyncStatus | null; failures: string[]; loading: boolean; onRetry: () => void; language: Language }) {
  return <section className="view-stack"><div className="section-intro"><div><h2>{tr(language, "ข้อมูลการตั้งค่าที่ใช้งานอยู่", "Current system configuration")}</h2><p>{tr(language, "ตรวจสอบข้อมูลได้จากหน้าเว็บ แต่การแก้ไขทำใน Desktop เท่านั้น", "Review settings here; changes are made in the Desktop app only")}</p></div><span className="source-badge">READ ONLY</span></div>{failures.length > 0 && <div className="alert error recovery" role="alert"><span>{tr(language, "ข้อมูลระบบบางส่วนโหลดไม่สำเร็จ ส่วนที่พร้อมยังแสดงตามปกติ", "Some system information could not be loaded. Available sections are still shown.")}</span><button onClick={onRetry}>{tr(language, "ลองใหม่", "Retry")}</button></div>}{loading && !settings && <div className="empty-state"><strong>{tr(language, "กำลังโหลดข้อมูลระบบ…", "Loading system information…")}</strong></div>}{settings && <SettingsSummary settings={settings} language={language}/>}<details className="support-details"><summary><div><strong>{tr(language, "ข้อมูลสำหรับเจ้าหน้าที่", "Support information")}</strong><small>{tr(language, "สถานะการอ่านข้อมูลและตารางทำงานอัตโนมัติ", "Collection status and automation timeline")}</small></div><span>{tr(language, "เปิดรายละเอียด", "Show details")}</span></summary>{sync ? <SyncDetails sync={sync} language={language}/> : <div className="empty-state compact"><strong>{tr(language, "ยังโหลดสถานะการอ่านข้อมูลไม่ได้", "Collection status is unavailable")}</strong><button className="secondary" onClick={onRetry}>{tr(language, "ลองใหม่", "Retry")}</button></div>}</details></section>;
}
