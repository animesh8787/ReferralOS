import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({ variable: "--font-inter", subsets: ["latin"], display: "swap" });

export const metadata: Metadata = {
  title: "ReferralOS",
  description: "Job-first referral, resume tailoring and outreach",
};

// Runs before first paint so the saved (or OS) theme never flashes. Port of Nexus OS theme-boot.js.
const THEME_BOOT = `try{var t=localStorage.getItem("referralos-theme");if(t!=="light"&&t!=="dark")t=null;
if(!t&&matchMedia("(prefers-color-scheme: dark)").matches)t="dark";if(t)document.documentElement.dataset.theme=t}catch(e){}`;

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{ __html: THEME_BOOT }} /></head>
      <body className={`${inter.variable} antialiased`}>
        {children}
      </body>
    </html>
  );
}
