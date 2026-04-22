import type { Metadata } from "next";
import { IBM_Plex_Sans, Space_Grotesk } from "next/font/google";

import { Navbar } from "@/components/navbar";

import "./globals.css";

const headingFont = Space_Grotesk({
  subsets: ["latin"],
  variable: "--font-heading",
});

const bodyFont = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-body",
});

export const metadata: Metadata = {
  title: "GTU AI Live QA",
  description:
    "Gebze Teknik Üniversitesi resmi belgeleriyle beslenen canlı soru-cevap demosu",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="tr">
      <body className={`${headingFont.variable} ${bodyFont.variable}`}>
        <Navbar />
        {children}
      </body>
    </html>
  );
}
