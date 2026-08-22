import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "KOMI Report V5",
  description: "Meter Control for Konica Minolta devices",
  icons: { icon: "/icon.png" },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="th"><body>{children}</body></html>;
}
