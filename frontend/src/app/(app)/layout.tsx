"use client";
import { BarChart3, Briefcase, Building2, ClipboardList, FileText, HeartHandshake, LayoutDashboard, Menu, Search, Send, Settings, ShieldCheck, Sparkles, Stethoscope, Target, Upload, UserRound, Users, BookOpen, Ban } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import useSWR, { SWRConfig } from "swr";
import CommandPalette, { NavItem } from "@/components/ui/CommandPalette";
import Notice from "@/components/ui/Notice";
import Skeleton from "@/components/ui/Skeleton";
import ThemeToggle from "@/components/ui/ThemeToggle";
import { api, Me } from "@/lib/api";

type L = [string, string, typeof Menu];
const MAIN: [string, L[]][] = [
  ["Overview", [["/dashboard", "Dashboard", LayoutDashboard]]],
  ["Profile & data", [["/profile", "Profile", UserRound], ["/imports", "Imports", Upload], ["/contacts", "Contacts", Users], ["/prospects", "Prospects", Target], ["/companies", "Companies", Building2]]],
  ["Jobs", [["/jobs", "Jobs", Briefcase], ["/opportunities", "Opportunities", Sparkles], ["/resumes", "Resumes", FileText]]],
  ["Outreach", [["/outreach", "Outreach", Send], ["/tracking", "Tracking", ClipboardList]]],
];
const MORE: L[] = [["/suppression", "Do-not-contact", Ban], ["/settings", "Settings", Settings], ["/diagnostics", "Diagnostics", Stethoscope], ["/privacy", "Privacy", ShieldCheck], ["/guide", "Guide", BookOpen]];
const ITEMS: NavItem[] = [...MAIN.flatMap(([g, ls]) => ls.map(([href, label]) => ({ href, label, group: g }))), ...MORE.map(([href, label]) => ({ href, label, group: "Account & help" }))];

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const path = usePathname();
  const { data: me, error } = useSWR<Me>("/auth/me", (p: string) => api<Me>(p), { shouldRetryOnError: false });
  const [open, setOpen] = useState(false);
  const [palette, setPalette] = useState(false);
  const [narrow, setNarrow] = useState(false);
  const menuBtn = useRef<HTMLButtonElement>(null);
  useEffect(() => { if (error) router.replace("/login"); }, [error, router]);
  useEffect(() => { setOpen(false); }, [path]);
  useEffect(() => {
    const mq = matchMedia("(max-width: 900px)");
    const on = () => setNarrow(mq.matches);
    on(); mq.addEventListener("change", on);
    const key = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPalette((v) => !v); }
      else if (e.key === "Escape") setOpen(false);
    };
    addEventListener("keydown", key);
    return () => { mq.removeEventListener("change", on); removeEventListener("keydown", key); };
  }, []);
  // glare follows the pointer by writing CSS variables (no React re-render per mouse move)
  useEffect(() => {
    if (!matchMedia("(pointer: fine)").matches) return;
    const move = (e: PointerEvent) => {
      const el = (e.target as HTMLElement | null)?.closest<HTMLElement>(".glare");
      if (el) { const r = el.getBoundingClientRect(); el.style.setProperty("--gx", `${e.clientX - r.left}px`); el.style.setProperty("--gy", `${e.clientY - r.top}px`); }
    };
    addEventListener("pointermove", move, { passive: true });
    return () => removeEventListener("pointermove", move);
  }, []);

  const link = ([h, l, Icon]: L) => {
    const cur = path === h || path.startsWith(h + "/");
    return <li key={h}><Link href={h} aria-current={cur ? "page" : undefined} className="nav-link"><Icon size={16} strokeWidth={1.6} aria-hidden="true" />{l}</Link></li>;
  };
  const group = ITEMS.find((n) => path === n.href || path.startsWith(n.href + "/"))?.group ?? "ReferralOS";
  const hidden = narrow && !open;

  return (
    <SWRConfig value={{ keepPreviousData: true, revalidateOnFocus: false }}>
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-[300] focus:rounded focus:bg-surface focus:p-2">Skip to content</a>
      <div className="shell">
        <aside className="sidebar" data-open={open} {...(hidden ? { inert: true } : {})} aria-label="Sidebar">
          <Link href="/dashboard" className="brand">Referral<em>OS</em></Link>
          <nav aria-label="Main">
            {MAIN.map(([g, ls]) => <div key={g}><p className="nav-group">{g}</p><ul className="grid gap-px">{ls.map(link)}</ul></div>)}
          </nav>
          <nav aria-label="Account and help" className="mt-1">
            <p className="nav-group">Account &amp; help</p>
            <ul className="grid gap-px">{MORE.map(link)}</ul>
          </nav>
          <div className="mt-auto grid gap-2 border-t pt-3">
            <span className="truncate px-2 text-xs text-muted" title={me?.email}>{me?.email ?? "…"}</span>
            <div className="flex items-center justify-between gap-2 px-1">
              <button type="button" className="btn" onClick={async () => { await api("/auth/logout", { method: "POST", body: {} }); router.replace("/login"); }}>Sign out</button>
              <ThemeToggle />
            </div>
          </div>
        </aside>
        <div className="scrim" data-open={open} onClick={() => { setOpen(false); menuBtn.current?.focus(); }} aria-hidden="true" />
        <div className="min-w-0">
          <div className="topbar">
            <button ref={menuBtn} type="button" className="btn menu-btn" aria-label="Open menu" aria-expanded={open} onClick={() => setOpen(true)}><Menu size={16} strokeWidth={1.6} aria-hidden="true" /></button>
            <span className="eyebrow hidden sm:inline">{group}</span>
            <button type="button" className="btn ml-auto min-w-0 !justify-between gap-6 !normal-case !tracking-normal !font-normal text-muted" onClick={() => setPalette(true)}>
              <span className="flex items-center gap-2"><Search size={14} strokeWidth={1.6} aria-hidden="true" />Search or jump to…</span><kbd className="field-label hidden sm:inline">Ctrl K</kbd>
            </button>
          </div>
          {me && !me.email_verified && <div className="px-4 pt-4 md:px-6"><Notice kind="warn">Your email is not verified yet. Some features stay locked until it is.</Notice></div>}
          <main id="main" className="px-4 py-5 md:px-6">
            <div className="page">{me ? children : <Skeleton rows={6} />}</div>
          </main>
        </div>
      </div>
      <CommandPalette items={ITEMS} open={palette} onClose={() => setPalette(false)} />
    </SWRConfig>
  );
}
