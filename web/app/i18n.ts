export type Language = "th" | "en";

const integerFormatter = new Intl.NumberFormat("th-TH", {
  numberingSystem: "latn", maximumFractionDigits: 0,
});
const moneyFormatter = new Intl.NumberFormat("th-TH", {
  numberingSystem: "latn", minimumFractionDigits: 2, maximumFractionDigits: 2,
});

export const num = (value?: number) => integerFormatter.format(value ?? 0);
export const money = (value?: number) => moneyFormatter.format(value ?? 0);

export function tr(language: Language, thai: string, english: string) {
  return language === "th" ? thai : english;
}

export function formatDate(value: string | null | undefined, language: Language) {
  if (!value) return tr(language, "ยังไม่มีข้อมูล", "No data yet");
  return new Intl.DateTimeFormat(language === "th" ? "th-TH" : "en-GB", value.includes("T")
    ? { dateStyle: "medium", timeStyle: "short", numberingSystem: "latn" }
    : { dateStyle: "medium", numberingSystem: "latn" }).format(new Date(value));
}
