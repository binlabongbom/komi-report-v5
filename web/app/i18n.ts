export type Language = "th" | "en";

export function tr(language: Language, thai: string, english: string) {
  return language === "th" ? thai : english;
}

export function formatDate(value: string | null | undefined, language: Language) {
  if (!value) return tr(language, "ยังไม่มีข้อมูล", "No data yet");
  return new Intl.DateTimeFormat(language === "th" ? "th-TH" : "en-GB", value.includes("T")
    ? { dateStyle: "medium", timeStyle: "short" }
    : { dateStyle: "medium" }).format(new Date(value));
}
