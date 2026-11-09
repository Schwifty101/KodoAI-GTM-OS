import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = { title: "GTM OS", description: "KodoAI med spa outreach, local operator tool" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <nav>
          <span className="brand">GTM OS</span>
          <Link href="/leads">Leads</Link>
          <Link href="/review">Review</Link>
          <Link href="/outreach">Outreach</Link>
        </nav>
        <main>{children}</main>
      </body>
    </html>
  );
}
