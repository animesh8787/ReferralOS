"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import useSWR from "swr";
import { api, Me } from "@/lib/api";

const MAIN: [string, string][] = [["/dashboard", "Dashboard"], ["/profile", "Profile"], ["/imports", "Imports"], ["/contacts", "Contacts"], ["/prospects", "Prospects"], ["/companies", "Companies"],
  ["/jobs", "Jobs"], ["/opportunities", "Opportunities"], ["/resumes", "Resumes"], ["/outreach", "Outreach"], ["/tracking", "Tracking"]];
const MORE: [string, string][] = [["/suppression", "Do-not-contact"], ["/settings", "Settings"], ["/diagnostics", "Diagnostics"], ["/privacy", "Privacy"], ["/guide", "Guide"]];

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const path = usePathname();
  const { data: me, error } = useSWR<Me>("/auth/me", (p: string) => api<Me>(p), { shouldRetryOnError: false });
  useEffect(() => { if (error) router.replace("/login"); }, [error, router]);
  if (!me) return <p className="p-8" role="status">Loading…</p>;
  const link = ([h, l]: [string, string]) => {
    const cur = path === h || path.startsWith(h + "/");
    return <li key={h}><Link href={h} aria-current={cur ? "page" : undefined} className={`rounded px-2 py-1 ${cur ? "bg-gray-900 text-white" : "hover:bg-gray-100"}`}>{l}</Link></li>;
  };
  return (
    <div className="min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:rounded focus:bg-white focus:p-2">Skip to content</a>
      <header className="border-b px-4 py-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Link href="/dashboard" className="font-semibold">ReferralOS</Link>
          <div className="flex items-center gap-3 text-sm"><span className="text-gray-600">{me.email}</span>
            <button className="underline" onClick={async () => { await api("/auth/logout", { method: "POST", body: {} }); router.replace("/login"); }}>Sign out</button></div>
        </div>
        <nav aria-label="Main" className="mt-1"><ul className="flex flex-wrap gap-1 text-sm">{MAIN.map(link)}</ul></nav>
        <nav aria-label="Account and help" className="mt-1"><ul className="flex flex-wrap gap-1 text-xs text-gray-700">{MORE.map(link)}</ul></nav>
      </header>
      {!me.email_verified && <p role="alert" className="bg-amber-100 px-6 py-2 text-sm">Your email is not verified yet. Some features stay locked until it is.</p>}
      <main id="main" className="p-4 md:p-6">{children}</main>
    </div>
  );
}
