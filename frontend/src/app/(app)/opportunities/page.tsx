"use client";
import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";
import Pager from "@/components/Pager";
import StatusBadge from "@/components/StatusBadge";
import { api } from "@/lib/api";

type Elig = { key: string; status: string; reason: string; action?: string };
type Contact = { contact_id: string; name: string; position: string | null; score: number; employment: string; also_fits_jobs: string[]; linkedin_url: string | null; note: string };
type Opp = { job_id: string; title: string; company: string | null; location: string | null; status: string; match_score: number; priority_score: number; readiness_group: number;
  readiness_label: string; rank: number; score_only_rank: number; trade_off: string | null; prioritize_applying: string; why_pursue: string[]; eligibility: Elig[];
  referral_route: string; best_contacts: Contact[]; contact_first: Contact | null; message: { status: string }; resume: { status: string }; next_action: string; stale: boolean };

const EMP: Record<string, string> = { verified: "verified by you", likely_current: "likely current (inferred)", possibly_outdated: "possibly outdated", unknown: "employment unknown" };
const ELIG_STYLE: Record<string, string> = { SATISFIED: "text-green-800", UNCERTAIN: "text-amber-800", VIOLATED: "text-red-800" };
const ROUTE: Record<string, string> = { VERIFIED_REFERRAL_PROGRAM: "programme confirmed", REFERRAL_ROUTE_UNCONFIRMED: "route unconfirmed", NO_PUBLIC_EVIDENCE: "no public evidence", NOT_APPLICABLE: "n/a", UNKNOWN: "unknown" };

export default function Opportunities() {
  const [page, setPage] = useState(1);
  const [group, setGroup] = useState("");
  const [busy, setBusy] = useState(false);
  const { data, mutate, isLoading } = useSWR<{ total: number; items: Opp[] }>(`/opportunities?page=${page}&page_size=10${group ? `&group=${group}` : ""}`, (p: string) => api<{ total: number; items: Opp[] }>(p));

  return (
    <div className="mx-auto grid max-w-4xl gap-4">
      <header className="flex flex-wrap items-end justify-between gap-2">
        <div><h1 className="text-xl font-semibold">Opportunities</h1>
          <p className="text-sm text-gray-600">Ranked by usefulness to you, not company prestige. Verified, eligible openings always come first; an uncertain role with a high match is shown with the trade-off.</p></div>
        <button disabled={busy} className="rounded bg-black px-3 py-1.5 text-sm text-white disabled:opacity-50" onClick={async () => { setBusy(true); try { await api("/matching/run", { body: {} }); await mutate(); } finally { setBusy(false); } }}>Re-analyse my jobs</button>
      </header>
      <label className="text-sm">Show <select className="rounded border px-1 py-1" value={group} onChange={(e) => { setGroup(e.target.value); setPage(1); }}>
        <option value="">everything</option><option value="0">verified and eligible</option><option value="1">verified, eligibility to confirm</option><option value="2">not yet verified</option><option value="3">open but ineligible</option><option value="4">closed or likely closed</option></select></label>
      {isLoading && <p role="status">Loading…</p>}
      {data?.items.length === 0 && <p className="text-sm text-gray-600">No analysed jobs yet. Add job boards on the Jobs page, then press “Re-analyse my jobs”. Add your profile first so matches mean something.</p>}
      {data?.items.map((o) => (
        <article key={o.job_id} className="grid gap-2 rounded border p-4 text-sm" aria-labelledby={`t-${o.job_id}`}>
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div><h2 id={`t-${o.job_id}`} className="text-base font-semibold"><span className="text-gray-500">#{o.rank}</span> <Link className="underline" href={`/opportunities/${o.job_id}`}>{o.title}</Link></h2>
              <p>{o.company} · {o.location ?? "location not stated"}</p></div>
            <div className="text-right"><StatusBadge status={o.status} /><p className="mt-1">Priority {o.priority_score.toFixed(0)} · match {o.match_score.toFixed(0)}</p></div>
          </div>
          <p className="text-xs text-gray-600">{o.readiness_label}{o.stale && " · profile changed since this was analysed"}</p>
          {o.trade_off && <p className="rounded bg-amber-50 p-2">{o.trade_off} (By score alone it would be #{o.score_only_rank}.)</p>}
          <div><p className="font-medium">Why pursue</p><ul className="list-disc pl-5">{o.why_pursue.map((w, i) => <li key={i}>{w}</li>)}</ul></div>
          <div><p className="font-medium">Eligibility</p><ul className="pl-0">{o.eligibility.length === 0 ? <li className="text-gray-600">No hard constraints found in the posting.</li> :
            o.eligibility.map((e) => <li key={e.key} className={ELIG_STYLE[e.status]}><strong>{e.key.replaceAll("_", " ")}: {e.status.toLowerCase()}</strong> — {e.reason}{e.action && <> <em>({e.action})</em></>}</li>)}</ul></div>
          <p><span className="font-medium">Referral route:</span> {ROUTE[o.referral_route]}</p>
          <div><p className="font-medium">Who to contact first</p>
            {o.best_contacts.length === 0 ? <p className="text-gray-600">No suitable connections found at this company.</p> :
              <ol className="list-decimal pl-5">{o.best_contacts.map((c) => <li key={c.contact_id}>{c.name}, {c.position ?? "title unknown"} · score {c.score.toFixed(0)} · {EMP[c.employment]}
                {c.also_fits_jobs.length > 0 && <span className="text-gray-600"> · also fits {c.also_fits_jobs.length} other role(s); one message will cover them</span>}</li>)}</ol>}
            <p className="text-xs text-gray-600">Employment is inferred from connection data, not verified. Nobody here is assumed able to refer.</p></div>
          <p className="text-xs">Resume: {o.resume.status.replace("_", " ")} · Outreach: {o.message.status.replace("_", " ")}</p>
          <p className="rounded bg-gray-50 p-2"><strong>Next:</strong> {o.next_action}</p>
        </article>
      ))}
      {data && <Pager page={page} pageSize={10} total={data.total} onPage={setPage} />}
    </div>
  );
}
