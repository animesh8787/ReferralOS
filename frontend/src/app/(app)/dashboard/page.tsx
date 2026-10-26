"use client";
import Link from "next/link";
import useSWR from "swr";
import { api } from "@/lib/api";

type D = { profile_completeness: { score: number; missing: string[] }; connections: number; hr_contacts: number; usable_coverage: { contacts_with_employer_and_title: number; percent: number | null };
  ranked_prospects: number; verified_jobs: number; matches: number; drafts_awaiting_approval: number; sent: number; replies: number; referrals_offered: number; applications: number;
  funnel: { stage: string; count: number; unit: string }[]; next_steps: { text: string; href: string }[]; note: string };

export default function Dashboard() {
  const { data: d, error, isLoading } = useSWR<D>("/dashboard", (p: string) => api<D>(p));
  const onb = useSWR<{ done: boolean }>("/onboarding", (p: string) => api<{ done: boolean }>(p));
  if (isLoading) return <p role="status">Loading…</p>;
  if (error || !d) return <p role="alert" className="text-red-700">Could not load the dashboard.</p>;
  const max = Math.max(1, ...d.funnel.map((f) => f.count));
  const stat = (label: string, v: number | string, href?: string) => <div className="rounded border p-3"><dt className="text-xs text-gray-600">{label}</dt><dd className="text-xl font-semibold">{href ? <Link className="underline" href={href}>{v}</Link> : v}</dd></div>;
  return (
    <div className="mx-auto grid max-w-5xl gap-6">
      <header><h1 className="text-xl font-semibold">Dashboard</h1>
        {onb.data && !onb.data.done && <p className="mt-1 rounded bg-amber-50 p-2 text-sm">Setup isn&apos;t finished. <Link className="underline" href="/onboarding">Continue the guided setup</Link></p>}</header>
      {d.next_steps.length > 0 && <section aria-labelledby="ns" className="rounded border p-4"><h2 id="ns" className="font-medium">Next steps</h2><ul className="mt-1 list-disc pl-5 text-sm">{d.next_steps.map((s) => <li key={s.text}><Link className="underline" href={s.href}>{s.text}</Link></li>)}</ul></section>}
      <dl className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {stat("Profile complete", `${d.profile_completeness.score}%`, "/profile")}{stat("Connections imported", d.connections, "/contacts")}
        {stat("With employer and title", d.usable_coverage.percent === null ? "—" : `${d.usable_coverage.percent}%`)}{stat("Ranked prospects", d.ranked_prospects, "/prospects")}
        {stat("Verified open jobs", d.verified_jobs, "/jobs")}{stat("Matched jobs", d.matches, "/opportunities")}
        {stat("Drafts to review", d.drafts_awaiting_approval, "/outreach")}{stat("Messages sent", d.sent, "/tracking")}
        {stat("Replies", d.replies, "/tracking")}{stat("Referrals offered", d.referrals_offered, "/tracking")}{stat("Applications", d.applications, "/tracking")}{stat("HR contacts", d.hr_contacts, "/contacts")}
      </dl>
      <section aria-labelledby="fn"><h2 id="fn" className="mb-2 font-medium">Pipeline</h2>
        <ol className="grid gap-1 text-sm">{d.funnel.map((f) => (
          <li key={f.stage} className="grid grid-cols-[10rem_1fr_3rem] items-center gap-2"><span>{f.stage}</span>
            <span className="h-4 rounded bg-gray-100" role="img" aria-label={`${f.count} ${f.unit}`}><span className="block h-4 rounded bg-green-600" style={{ width: `${(f.count / max) * 100}%` }} /></span>
            <span className="text-right tabular-nums">{f.count}</span></li>))}</ol>
        <p className="mt-1 text-xs text-gray-600">{d.note}</p></section>
    </div>
  );
}
