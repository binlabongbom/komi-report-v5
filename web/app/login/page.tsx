"use client";

import { FormEvent, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Language, tr } from "../i18n";

export default function LoginPage() {
  const router = useRouter();
  const [user, setUser] = useState("admin");
  const [code, setCode] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [language, setLanguage] = useState<Language>("th");

  useEffect(() => {
    const stored = window.localStorage.getItem("komi-web-language");
    if (stored === "th" || stored === "en") setLanguage(stored);
  }, []);

  function changeLanguage(next: Language) {
    setLanguage(next);
    setMessage("");
    window.localStorage.setItem("komi-web-language", next);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setMessage("");
    try {
      const response = await fetch("/auth/session", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ user, code }),
      });
      if (!response.ok) {
        await response.json().catch(() => ({}));
        setMessage(tr(language, "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง", "Incorrect username or password"));
        return;
      }
      router.replace("/");
      router.refresh();
    } catch {
      setMessage(tr(language,
        "เชื่อมต่อ KOMI Report Server ไม่สำเร็จ กรุณาลองอีกครั้ง",
        "Cannot connect to KOMI Report Server. Please try again.",
      ));
    } finally {
      setLoading(false);
    }
  }

  return <main className="login-page">
    <section className="login-card">
      <div className="login-language language-switch" role="group" aria-label={tr(language, "เลือกภาษา", "Select language")}>
        <button type="button" className={language === "th" ? "active" : ""} aria-pressed={language === "th"} onClick={() => changeLanguage("th")}>ไทย</button>
        <button type="button" className={language === "en" ? "active" : ""} aria-pressed={language === "en"} onClick={() => changeLanguage("en")}>EN</button>
      </div>
      <div className="login-brand"><span className="brand-mark"><i/><i/><i/><i/></span><div><strong>KOMI REPORT</strong><small>Meter Control V5</small></div></div>
      <h1>{tr(language, "เข้าสู่ระบบรายงาน", "Sign in to reports")}</h1>
      <p>{tr(language, "สำหรับผู้ใช้งานภายในเครือข่ายเดียวกัน", "For users on the same network")}</p>
      <form onSubmit={submit}>
        <label>{tr(language, "ชื่อผู้ใช้", "Username")}<input value={user} onChange={event => setUser(event.target.value)} autoComplete="username"/></label>
        <label>{tr(language, "รหัสผ่าน", "Password")}<input type="password" value={code} maxLength={128} onChange={event => setCode(event.target.value)} autoComplete="current-password" autoFocus/></label>
        {message && <div className="login-error" role="alert" aria-live="assertive">{message}</div>}
        <button className="primary" disabled={loading || !code}>{loading
          ? tr(language, "กำลังตรวจสอบ…", "Signing in…")
          : tr(language, "เข้าสู่ระบบ", "Sign in")}</button>
      </form>
      <small className="login-note">{tr(language,
        "หากยังไม่ได้รับรหัสผ่าน ให้ติดต่อผู้ดูแล KOMI Report",
        "Contact the KOMI Report administrator if you do not have access.",
      )}</small>
    </section>
  </main>;
}
