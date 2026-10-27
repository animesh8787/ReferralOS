"use client";
import Link from "next/link";
import useSWR from "swr";
import Notice from "@/components/ui/Notice";
import PageHeader from "@/components/ui/PageHeader";
import Skeleton from "@/components/ui/Skeleton";
import { api } from "@/lib/api";

type D = { profile_completeness: { score: number; missing: string[] }; connections: number; hr_contacts: number; usable_coverage: { contacts_with_employer_and_title: number; percent: number | null };
  ranked_prospects: number; verified_jobs: number; matches: number; drafts_awaiting_approval: number; sent: number; replies: number; referrals_offered: number; applications: number;
  funnel: { stage: string; count: number; unit: string }[]; next_steps: { text: string; href: string }[]; note: string };

export default function Dashboard() {
  const { data: d, error, isLoading } = useSWR<D>("/dashboard", (p: string) => api<D>(p));
  const onb = useSWR<{ done: boolean }>("/onboarding", (p: string) => api<{ done: boolean }>(p));
  if (isLoading) return <Skeleton rows={8} />;
  if (error || !d) return <Notice kind="err">Could not load the dashboard.</Notice>;
  const max = Math.max(1, ...d.funnel.map((f) => f.count));
  const stat = (label: string, v: number | string, href?: string) => <div className="grid content-between gap-1"><dt className="text-muted">{label}</dt><dd className="text-3xl">{href ? <Link className="no-underline hover:underline" href={href}>{v}</Link> : v}</dd></div>;
  return (
    <div className="grid gap-6">
      <div className="grid gap-3"><PageHeader title="Dashboard" />
        {onb.data && !onb.data.done && <Notice kind="warn">Setup isn&apos;t finished. <Link className="underline" href="/onboarding">Continue the guided setup</Link></Notice>}</div>
      {d.next_steps.length > 0 && <section aria-labelledby="ns" className="card p-4"><h2 id="ns" className="eyebrow">Next steps</h2><ul className="mt-1 list-disc pl-5 text-sm">{d.next_steps.map((s) => <li key={s.text}><Link className="underline" href={s.href}>{s.text}</Link></li>)}</ul></section>}
      <dl className="stat-strip grid-cols-2 md:grid-cols-4">
        {stat("Profile complete", `${d.profile_completeness.score}%`, "/profile")}{stat("Connections imported", d.connections, "/contacts")}
        {stat("With employer and title", d.usable_coverage.percent === null ? "—" : `${d.usable_coverage.percent}%`)}{stat("Ranked prospects", d.ranked_prospects, "/prospects")}
        {stat("Verified open jobs", d.verified_jobs, "/jobs")}{stat("Matched jobs", d.matches, "/opportunities")}
        {stat("Drafts to review", d.drafts_awaiting_approval, "/outreach")}{stat("Messages sent", d.sent, "/tracking")}
        {stat("Replies", d.replies, "/tracking")}{stat("Referrals offered", d.referrals_offered, "/tracking")}{stat("Applications", d.applications, "/tracking")}{stat("HR contacts", d.hr_contacts, "/contacts")}
      </dl>
      <section aria-labelledby="fn"><h2 id="fn" className="eyebrow mb-2">Pipeline</h2>
        <ol className="grid gap-1 text-sm">{d.funnel.map((f) => (
          <li key={f.stage} className="grid grid-cols-[10rem_1fr_3rem] items-center gap-2"><span>{f.stage}</span>
            <span className="h-4 rounded bg-surface-2" role="img" aria-label={`${f.count} ${f.unit}`}><span className="block h-4 rounded bg-accent" style={{ width: `${(f.count / max) * 100}%`, transition: "width .7s var(--ease)" }} /></span>
            <span className="text-right tabular-nums">{f.count}</span></li>))}</ol>
        <p className="mt-1 text-xs text-muted">{d.note}</p></section>
    </div>
  );
}
