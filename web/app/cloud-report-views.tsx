"use client";

import { useMemo, useState, type KeyboardEvent } from "react";
import type { Device, DeviceUsage, HistoryItem, Overview, UserItem } from "./dashboard-types";
import { type Language, tr } from "./i18n";
import { money, num, Sparkline, StatusBadge } from "./report-views";

type UserRow = {
  key: string;
  name: string;
  type: string;
  usage: number;
  latest: number;
  review: boolean;
  printers: Map<string, number>;
};

function activateRow(event: KeyboardEvent, action: () => void) {
  if (event.key !== "Enter" && event.key !== " ") return;
  event.preventDefault();
  action();
}

function identityName(identity: string, overview: Overview | null) {
  const device = overview?.devices.find(item => item.device_identity === identity);
  return device?.name || identity.replace(/^(serial|host):/, "") || "—";
}

function userRows(users: UserItem[]) {
  const rows = new Map<string, UserRow>();
  for (const item of users) {
    const key = `${item.subject_type}:${item.subject_id}`;
    const row = rows.get(key) ?? {
      key,
      name: item.subject_name,
      type: item.subject_type,
      usage: 0,
      latest: 0,
      review: false,
      printers: new Map<string, number>(),
    };
    const identity = item.device_identity || `slot:${item.device_slot}`;
    row.usage += item.usage;
    row.latest = Math.max(row.latest, item.latest_total);
    row.review ||= item.needs_review;
    row.printers.set(identity, (row.printers.get(identity) ?? 0) + item.usage);
    rows.set(key, row);
  }
  return [...rows.values()].sort((a, b) => b.usage - a.usage);
}

function usageTotal(device: DeviceUsage) {
  return device.usage.total;
}

function CloudKpis({ items }: { items: { label: string; value: string; unit: string; tone: string; note?: string }[] }) {
  return <section className={`cloud-kpi-grid count-${items.length}`}>
    {items.map(item => <article className="cloud-kpi" key={item.label}>
      <i className={`cloud-kpi-mark ${item.tone}`}/>
      <span>{item.label}</span>
      <strong>{item.value}</strong>
      <small>{item.note || item.unit}</small>
    </article>)}
  </section>;
}

function BarList({ rows, empty }: { rows: { label: string; value: number; meta?: string }[]; empty: string }) {
  const max = Math.max(...rows.map(row => row.value), 1);
  if (!rows.length) return <div className="cloud-empty">{empty}</div>;
  return <div className="cloud-bars">{rows.map((row, index) => <div className="cloud-bar-row" key={`${row.label}-${index}`}>
    <div><strong>{row.label}</strong>{row.meta && <small>{row.meta}</small>}</div>
    <div className="cloud-bar-track"><i style={{ width: `${Math.max(2, (row.value / max) * 100)}%` }}/></div>
    <b>{num(row.value)}</b>
  </div>)}</div>;
}

function Panel({ title, subtitle, children, className = "" }: { title: string; subtitle?: string; children: React.ReactNode; className?: string }) {
  return <article className={`cloud-panel ${className}`}>
    <header><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div></header>
    {children}
  </article>;
}

function MixBars({ values }: { values: { label: string; value: number; tone: string }[] }) {
  const total = values.reduce((sum, item) => sum + item.value, 0);
  return <div className="cloud-mix">
    <div className="cloud-mix-track">{values.map(item => <i key={item.label} className={item.tone} style={{ width: `${total ? (item.value / total) * 100 : 0}%` }}/>)}</div>
    <div className="cloud-mix-legend">{values.map(item => <span key={item.label}><i className={item.tone}/>{item.label}<b>{num(item.value)}</b></span>)}</div>
  </div>;
}

function ReportStatus({ row, language }: { row: DeviceUsage; language: Language }) {
  if (row.usage.held_days || row.usage.incomplete_days) return <span className="status review">{tr(language, "ควรตรวจสอบ", "Review")}</span>;
  if (row.usage.provisional_days) return <span className="status provisional">{tr(language, "ระหว่างวัน", "In progress")}</span>;
  return <StatusBadge status={row.status} language={language}/>;
}

export function CloudOverview({ overview, history, users, loading, language }: { overview: Overview | null; history: HistoryItem[]; users: UserItem[]; loading: boolean; language: Language }) {
  const rows = useMemo(() => userRows(users), [users]);
  const totals = overview?.totals;
  const unavailable = "—";
  return <div className="cloud-view">
    <CloudKpis items={[
      { label: tr(language, "พิมพ์สี", "Color print"), value: loading ? unavailable : totals?.print_available ? num(totals.print_color) : unavailable, unit: tr(language, "หน้า", "pages"), tone: "blue" },
      { label: tr(language, "พิมพ์ขาวดำ", "B&W print"), value: loading ? unavailable : totals?.print_available ? num(totals.print_bw) : unavailable, unit: tr(language, "หน้า", "pages"), tone: "slate" },
      { label: tr(language, "ยอดใช้งานรวม", "Total usage"), value: loading ? unavailable : num(totals?.usage), unit: tr(language, "หน้า", "pages"), tone: "navy" },
      { label: tr(language, "สำเนาสี", "Color copy"), value: loading ? unavailable : totals?.copy_available ? num(totals.copy_color) : unavailable, unit: tr(language, "หน้า", "pages"), tone: "orange" },
      { label: tr(language, "สำเนาขาวดำ", "B&W copy"), value: loading ? unavailable : totals?.copy_available ? num(totals.copy_bw) : unavailable, unit: tr(language, "หน้า", "pages"), tone: "slate" },
      { label: tr(language, "ค่าใช้จ่ายรวม", "Total cost"), value: loading ? unavailable : money(totals?.net_cost), unit: tr(language, "บาท", "THB"), tone: "green" },
    ]}/>
    <section className="cloud-two-col">
      <Panel title={tr(language, "แนวโน้ม Print / Copy", "Print / Copy timeline")} subtitle={tr(language, "ยอดรวมทุกเครื่องในช่วงวันที่เลือก", "All printers in the selected date range")}><Sparkline values={history} language={language}/><div className="cloud-chart-foot">{tr(language, "Device Meter จาก Web Connection", "Device Meter from Web Connection")}</div></Panel>
      <Panel title={tr(language, "สัดส่วน Color, B&W และ Scan", "Color, B&W and Scan mix")} subtitle={tr(language, "ไม่บวก Scan เข้ากับยอดพิมพ์", "Scan is not added to print usage")}><MixBars values={[
        { label: "Color", value: totals?.color ?? 0, tone: "orange" },
        { label: "B&W", value: totals?.bw ?? 0, tone: "slate" },
        { label: "Scan", value: totals?.scan ?? 0, tone: "cyan" },
      ]}/></Panel>
      <Panel title={tr(language, "ผู้ใช้งานสูงสุด", "Top users")} subtitle="User Authentication / Account Track"><BarList rows={rows.slice(0, 8).map(row => ({ label: row.name, value: row.usage, meta: row.type === "user" ? "User" : "Account Track" }))} empty={tr(language, "ยังไม่มีข้อมูล User / Account ในช่วงนี้", "No user or account data in this range")}/></Panel>
      <Panel title={tr(language, "เครื่องพิมพ์ที่ใช้งานสูงสุด", "Top printers")} subtitle={tr(language, "เรียงตามยอดพิมพ์และถ่ายเอกสาร", "Sorted by print and copy usage")}><BarList rows={(overview?.devices ?? []).slice().sort((a, b) => usageTotal(b) - usageTotal(a)).slice(0, 8).map(device => ({ label: device.name, value: usageTotal(device), meta: device.serial || device.host }))} empty={tr(language, "ยังไม่มีข้อมูลเครื่องพิมพ์ในช่วงนี้", "No printer data in this range")}/></Panel>
    </section>
  </div>;
}

export function CloudUsers({ users, overview, language }: { users: UserItem[]; overview: Overview | null; language: Language }) {
  const rows = useMemo(() => userRows(users), [users]);
  const [selected, setSelected] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const normalizedQuery = query.trim().toLocaleLowerCase(language === "th" ? "th-TH" : "en-US");
  const filteredRows = useMemo(() => normalizedQuery
    ? rows.filter(row => row.name.toLocaleLowerCase(language === "th" ? "th-TH" : "en-US").includes(normalizedQuery))
    : rows, [language, normalizedQuery, rows]);
  const active = filteredRows.find(row => row.key === selected) ?? null;
  const total = rows.reduce((sum, row) => sum + row.usage, 0);
  const noMatch = tr(language, `ไม่พบผู้ใช้หรือ Account Track ที่ตรงกับ “${query.trim()}”`, `No user or Account Track matches “${query.trim()}”`);
  const printerTotals = new Map<string, number>();
  for (const row of active ? [active] : filteredRows) for (const [identity, value] of row.printers) printerTotals.set(identity, (printerTotals.get(identity) ?? 0) + value);
  const clearSearch = () => {
    setQuery("");
    setSelected(null);
  };
  return <div className="cloud-view">
    <CloudKpis items={[
      { label: tr(language, "ผู้ใช้ที่มีข้อมูล", "Users with data"), value: num(rows.length), unit: tr(language, "คน", "users"), tone: "navy" },
      { label: tr(language, "ยอดใช้งานรวม", "Total usage"), value: num(total), unit: tr(language, "หน้า", "pages"), tone: "blue" },
      { label: tr(language, "เฉลี่ยต่อผู้ใช้", "Average per user"), value: num(rows.length ? total / rows.length : 0), unit: tr(language, "หน้า", "pages"), tone: "orange" },
      { label: tr(language, "ผู้ใช้สูงสุด", "Highest usage"), value: num(rows[0]?.usage), unit: tr(language, "หน้า", "pages"), tone: "green" },
    ]}/>
    <section className="cloud-user-search" role="search" aria-label={tr(language, "ค้นหาผู้ใช้งาน", "Search users")}>
      <div className="cloud-user-search-copy">
        <label htmlFor="cloud-user-search-input">{tr(language, "ค้นหาชื่อผู้ใช้งาน", "Search user name")}</label>
        <small>{tr(language, "ค้นหาได้ทั้ง User และ Account Track ในช่วงวันที่เลือก", "Search users and Account Track in the selected date range")}</small>
      </div>
      <div className="cloud-user-search-control">
        <svg aria-hidden="true" viewBox="0 0 24 24"><circle cx="11" cy="11" r="6.5"/><path d="m16 16 4 4"/></svg>
        <input
          id="cloud-user-search-input"
          type="search"
          value={query}
          placeholder={tr(language, "เช่น ฝ่ายขาย หรือ somchai", "e.g. Sales or somchai")}
          autoComplete="off"
          enterKeyHint="search"
          onChange={event => { setQuery(event.target.value); setSelected(null); }}
          onKeyDown={event => { if (event.key === "Escape") clearSearch(); }}
        />
      </div>
      <span className="cloud-user-search-result" role="status" aria-live="polite">
        {normalizedQuery
          ? tr(language, `พบ ${num(filteredRows.length)} จาก ${num(rows.length)} รายการ`, `${num(filteredRows.length)} of ${num(rows.length)} results`)
          : tr(language, `ทั้งหมด ${num(rows.length)} รายการ`, `${num(rows.length)} total`)}
      </span>
      <button type="button" onClick={clearSearch} disabled={!normalizedQuery}>{tr(language, "ล้างคำค้น", "Clear search")}</button>
    </section>
    <div className="cloud-filter-line"><span>{active
      ? tr(language, `กำลังแสดงการกระจายของ ${active.name}`, `Showing printer distribution for ${active.name}`)
      : normalizedQuery
        ? tr(language, `กำลังแสดง ${num(filteredRows.length)} รายการที่ตรงคำค้น · เลือกแถวเพื่อดูรายคน`, `Showing ${num(filteredRows.length)} matching results · select a row for one user`)
        : tr(language, "เลือกผู้ใช้จากตารางเพื่อดูการกระจายตามเครื่อง", "Select a user to see printer distribution")}</span><button onClick={() => setSelected(null)} disabled={!active}>{tr(language, "ล้างการเลือก", "Clear selection")}</button></div>
    <section className="cloud-two-col">
      <Panel title={normalizedQuery ? tr(language, "ผู้ใช้งานที่ตรงคำค้น", "Matching users") : tr(language, "ผู้ใช้งานสูงสุด", "Top users")} subtitle={tr(language, "เรียงตามยอดใช้งานในช่วงที่เลือก", "Sorted by usage in the selected range")}><BarList rows={filteredRows.slice(0, 8).map(row => ({ label: row.name, value: row.usage }))} empty={normalizedQuery ? noMatch : tr(language, "ยังไม่มีข้อมูลผู้ใช้", "No user data")}/></Panel>
      <Panel title={tr(language, "เครื่องที่ใช้งาน", "Printers used")} subtitle={tr(language, "การกระจายยอดตามเครื่อง", "Usage distribution by printer")}><BarList rows={[...printerTotals].map(([identity, value]) => ({ label: identityName(identity, overview), value }))} empty={normalizedQuery && !filteredRows.length ? noMatch : tr(language, "ยังไม่มีข้อมูลการกระจาย", "No distribution data")}/></Panel>
    </section>
    <Panel title={tr(language, "ผู้ใช้และ Account Track", "Users and Account Track")} subtitle={tr(language, "ข้อมูล RAM ใช้วิเคราะห์การกระจาย ไม่ใช้คำนวณค่าใช้จ่าย", "RAM data is for usage distribution only and is not used for billing")} className="cloud-table-panel">
      <div className="table-wrap"><table className="cloud-table"><thead><tr><th>User / Account</th><th>{tr(language, "ประเภท", "Type")}</th><th>{tr(language, "ยอดช่วงนี้", "Range usage")}</th><th>{tr(language, "Total Counter ล่าสุด", "Latest total counter")}</th><th>{tr(language, "เครื่องที่ใช้", "Printers")}</th><th>{tr(language, "สถานะ", "Status")}</th></tr></thead><tbody>{filteredRows.length ? filteredRows.map(row => {
        const toggle = () => setSelected(current => current === row.key ? null : row.key);
        return <tr key={row.key} className={selected === row.key ? "selected" : ""} role="button" tabIndex={0} aria-pressed={selected === row.key} onClick={toggle} onKeyDown={event => activateRow(event, toggle)}><td><strong>{row.name}</strong></td><td>{row.type === "user" ? "User" : "Account Track"}</td><td>{num(row.usage)}</td><td>{num(row.latest)}</td><td>{[...row.printers].map(([identity]) => identityName(identity, overview)).join(", ")}</td><td><span className={`status ${row.review ? "review" : "online"}`}>{row.review ? tr(language, "ควรตรวจสอบ", "Review") : tr(language, "พร้อมใช้", "Ready")}</span></td></tr>;
      }) : <tr><td colSpan={6} className="empty-cell">{normalizedQuery ? noMatch : tr(language, "ยังไม่มีข้อมูล User / Account ในช่วงนี้", "No user or account data in this range")}</td></tr>}</tbody></table></div>
    </Panel>
  </div>;
}

export function CloudPrinters({ overview, history, devices, language }: { overview: Overview | null; history: HistoryItem[]; devices: Device[]; language: Language }) {
  const rows = (overview?.devices ?? []).slice().sort((a, b) => usageTotal(b) - usageTotal(a));
  const [selected, setSelected] = useState<string | null>(null);
  const active = rows.find(row => row.device_identity === selected) ?? null;
  const liveDevice = active ? devices.find(device => device.slot === active.slot) : null;
  const color = rows.reduce((sum, row) => sum + row.usage.color, 0);
  const bw = rows.reduce((sum, row) => sum + row.usage.bw, 0);
  return <div className="cloud-view">
    <CloudKpis items={[
      { label: tr(language, "เครื่องที่มีการใช้งาน", "Printers used"), value: num(rows.filter(row => usageTotal(row) > 0).length), unit: tr(language, "เครื่อง", "printers"), tone: "navy" },
      { label: tr(language, "พิมพ์ / ถ่ายเอกสาร", "Print / copy"), value: num(overview?.totals.usage), unit: tr(language, "หน้า", "pages"), tone: "blue" },
      { label: "Color", value: num(overview?.totals.color), unit: tr(language, "หน้า", "pages"), tone: "orange" },
      { label: "B&W", value: num(overview?.totals.bw), unit: tr(language, "หน้า", "pages"), tone: "slate" },
      { label: tr(language, "ค่าใช้จ่ายสุทธิ", "Net cost"), value: money(overview?.totals.net_cost), unit: tr(language, "บาท", "THB"), tone: "green" },
    ]}/>
    <div className="cloud-filter-line"><span>{active ? tr(language, `กำลังแสดงรายละเอียดของ ${active.name} · กราฟยังเปรียบเทียบทุกเครื่อง`, `Showing ${active.name} details · charts still compare all printers`) : tr(language, "เลือกเครื่องจากตารางเพื่อดู Meter detail · กราฟแสดงทุกเครื่องพร้อมกัน", "Select a printer for meter details · charts compare all printers")}</span><button onClick={() => setSelected(null)} disabled={!active}>{tr(language, "ล้างการเลือก", "Clear selection")}</button></div>
    <section className="cloud-printer-charts">
      <Panel title={tr(language, "แนวโน้มการใช้งาน", "Usage timeline")} subtitle={tr(language, "ทุกเครื่องพิมพ์ในช่วงวันที่เลือก", "All printers in the selected date range")}><Sparkline values={history} language={language}/><div className="cloud-chart-foot">{tr(language, "การเลือกแถวไม่เปลี่ยนกราฟ", "Row selection does not change the chart")}</div></Panel>
      <Panel title="Color vs B&W" subtitle={tr(language, "ทุกเครื่องพร้อมกัน · ไม่รวม Scan", "All printers · Scan excluded")}><MixBars values={[{ label: "Color", value: color, tone: "orange" }, { label: "B&W", value: bw, tone: "slate" }]}/></Panel>
    </section>
    <section className="cloud-printer-bottom">
      <Panel title={tr(language, "เครื่องพิมพ์", "Printers")} subtitle={tr(language, "เลือกแถวเพื่อเปลี่ยน Meter detail เท่านั้น", "Select a row to change meter details only")} className="cloud-table-panel"><div className="table-wrap"><table className="cloud-table"><thead><tr><th>{tr(language, "เครื่องพิมพ์", "Printer")}</th><th>{tr(language, "สถานะข้อมูล", "Data status")}</th><th>Color</th><th>B&W</th><th>Scan</th><th>{tr(language, "รวม", "Total")}</th><th>{tr(language, "ค่าใช้จ่าย", "Cost")}</th></tr></thead><tbody>{rows.length ? rows.map(row => {
        const toggle = () => setSelected(current => current === row.device_identity ? null : row.device_identity);
        return <tr key={row.device_identity} className={selected === row.device_identity ? "selected" : ""} role="button" tabIndex={0} aria-pressed={selected === row.device_identity} onClick={toggle} onKeyDown={event => activateRow(event, toggle)}><td><strong>{row.name}</strong><small>{row.serial || row.host}</small></td><td><ReportStatus row={row} language={language}/></td><td>{num(row.usage.color)}</td><td>{num(row.usage.bw)}</td><td>{num(row.usage.scan)}</td><td>{num(usageTotal(row))}</td><td>฿{money(row.usage.net_cost)}</td></tr>;
      }) : <tr><td colSpan={7} className="empty-cell">{tr(language, "ยังไม่มีข้อมูลเครื่องพิมพ์ในช่วงนี้", "No printer data in this range")}</td></tr>}</tbody></table></div></Panel>
      <Panel title="Meter detail" subtitle={tr(language, "ค่าล่าสุดสำหรับเครื่องที่เลือก", "Latest values for the selected printer")}><dl className="cloud-meter-detail"><div><dt>{tr(language, "เครื่องพิมพ์", "Printer")}</dt><dd>{active?.name ?? tr(language, "เลือกเครื่องจากตาราง", "Select a printer")}</dd></div><div><dt>IP address</dt><dd>{active?.host ?? "—"}</dd></div><div><dt>Serial</dt><dd>{active?.serial ?? "—"}</dd></div><div><dt>{tr(language, "Total Meter ล่าสุด", "Latest total meter")}</dt><dd>{liveDevice?.last_total == null ? "—" : num(liveDevice.last_total)}</dd></div><div><dt>{tr(language, "ยอดในช่วงนี้", "Usage in range")}</dt><dd>{active ? `${num(usageTotal(active))} ${tr(language, "หน้า", "pages")}` : "—"}</dd></div></dl></Panel>
    </section>
  </div>;
}
