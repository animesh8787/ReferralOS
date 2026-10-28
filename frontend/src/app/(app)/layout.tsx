"use client";
import { sendEmailVerification } from "firebase/auth";
import { Ban, BookOpen, Briefcase, Building2, ClipboardList, FileText, LayoutDashboard, Menu, Send, Settings, ShieldCheck, Sparkles, Stethoscope, Target, Upload, UserRound, Users } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import useSWR, { SWRConfig } from "swr";
import Notice from "@/components/ui/Notice";
import Skeleton from "@/components/ui/Skeleton";
import ThemeToggle from "@/components/ui/ThemeToggle";
import { api, Me } from "@/lib/api";
import { fbAuth, firebaseEnabled } from "@/lib/firebase";

type L = [string, string, typeof Menu];
const MAIN: [string, L[]][] = [
  ["Overview", [["/dashboard", "Dashboard", LayoutDashboard]]],
  ["Profile and data", [["/profile", "Profile", UserRound], ["/imports", "Imports", Upload], ["/contacts", "Contacts", Users], ["/prospects", "Prospects", Target], ["/companies", "Companies", Building2]]],
  ["Jobs", [["/jobs", "Jobs", Briefcase], ["/opportunities", "Opportunities", Sparkles], ["/resumes", "Resumes", FileText]]],
  ["Outreach", [["/outreach", "Outreach", Send], ["/tracking", "Tracking", ClipboardList]]],
];
const MORE: L[] = [["/suppression", "Do-not-contact", Ban], ["/settings", "Settings", Settings], ["/diagnostics", "Diagnostics", Stethoscope], ["/privacy", "Privacy", ShieldCheck], ["/guide", "Guide", BookOpen]];

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const path = usePathname();
  const { data: me, error } = useSWR<Me>("/auth/me", (p: string) => api<Me>(p), { shouldRetryOnError: false });
  const [open, setOpen] = useState(false);
  const [narrow, setNarrow] = useState(false);
  const [resent, setResent] = useState("");
  const menuBtn = useRef<HTMLButtonElement>(null);
  useEffect(() => { if (error) router.replace("/login"); }, [error, router]);
  useEffect(() => { setOpen(false); }, [path]);
  useEffect(() => {
    const mq = matchMedia("(max-width: 900px)");
    const on = () => setNarrow(mq.matches);
    on(); mq.addEventListener("change", on);
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    addEventListener("keydown", key);
    return () => { mq.removeEventListener("change", on); removeEventListener("keydown", key); };
  }, []);

  const link = ([h, l, Icon]: L) => {
    const cur = path === h || path.startsWith(h + "/");
    return <li key={h}><Link href={h} aria-current={cur ? "page" : undefined} className="nav-link"><Icon size={18} strokeWidth={1.75} aria-hidden="true" />{l}</Link></li>;
  };
  const hidden = narrow && !open;  // the closed phone drawer must not be reachable by keyboard or screen reader

  async function resend() {
    try {
      if (firebaseEnabled) {
        const u = fbAuth().currentUser;
        if (!u) throw new Error("Please sign out and sign in again, then resend.");
        await sendEmailVerification(u);
      } else await api("/auth/resend-verification", { body: {} });
      setResent("Verification email sent, check your inbox.");
    } catch (e) { setResent((e as Error).message); }
  }

  return (
    <SWRConfig value={{ keepPreviousData: true, revalidateOnFocus: false }}>
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-[300] focus:rounded focus:bg-surface focus:p-2">Skip to content</a>
      <div className="shell">
        <aside className="sidebar" data-open={open} {...(hidden ? { inert: true } : {})} aria-label="Sidebar">
          <Link href="/dashboard" className="brand">ReferralOS</Link>
          <nav aria-label="Main">
            {MAIN.map(([g, ls]) => <div key={g}><p className="nav-group">{g}</p><ul className="grid gap-px">{ls.map(link)}</ul></div>)}
          </nav>
          <nav aria-label="Account and help" className="mt-1">
            <p className="nav-group">Account and help</p>
            <ul className="grid gap-px">{MORE.map(link)}</ul>
          </nav>
          <div className="mt-auto grid gap-2 border-t pt-3">
            <span className="truncate px-2 text-sm text-muted" title={me?.email}>{me?.email ?? "…"}</span>
            <div className="flex items-center justify-between gap-2 px-1">
              <button type="button" className="btn" onClick={async () => { await api("/auth/logout", { method: "POST", body: {} }); if (firebaseEnabled) await fbAuth().signOut(); router.replace("/login"); }}>Sign out</button>
              <ThemeToggle />
            </div>
          </div>
        </aside>
        <div className="scrim" data-open={open} onClick={() => { setOpen(false); menuBtn.current?.focus(); }} aria-hidden="true" />
        <div className="min-w-0">
          <div className="topbar">
            <button ref={menuBtn} type="button" className="btn" aria-label="Open menu" aria-expanded={open} onClick={() => setOpen(true)}><Menu size={20} strokeWidth={1.75} aria-hidden="true" /></button>
            <span className="text-lg font-bold">ReferralOS</span>
          </div>
          {me && !me.email_verified && (
            <div className="px-4 pt-4 md:px-6">
              <Notice kind="warn">Your email is not verified yet. Some features stay locked until it is. {resent || <button type="button" className="underline" onClick={resend}>Resend verification email</button>}</Notice>
            </div>
          )}
          <main id="main" className="px-4 py-6 md:px-8">
            <div className="page">{me ? children : <Skeleton rows={6} />}</div>
          </main>
        </div>
      </div>
    </SWRConfig>
  );
}
