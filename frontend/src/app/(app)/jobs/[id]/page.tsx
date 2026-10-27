"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import useSWR from "swr";
import StatusBadge from "@/components/StatusBadge";
import Skeleton from "@/components/ui/Skeleton";
import { api } from "@/lib/api";

type Detail = { id: string; title: string; company: string | null; company_id: string; location: string | null; status: string; status_reasons: string[]; last_verified: string | null;
  needs_reverify: boolean; description: string | null; apply_url: string | null; contacts_at_company: number; outreach_note: string | null;
  sources: { type: string; board: string; source_url: string | null; last_seen: string }[];
  verification_evidence: { checked_at: string; source: string; kind: string; detail: Record<string, unknown> }[];
  referral_route: { status: string; source: string; evidence_url: string | null; evidence_excerpt: string | null } };

const ROUTE: Record<string, string> = {
  VERIFIED_REFERRAL_PROGRAM: "Programme confirmed on an official page", REFERRAL_ROUTE_UNCONFIRMED: "Route unconfirmed (you told us there may be one)",
  NO_PUBLIC_EVIDENCE: "No public evidence of a programme", NOT_APPLICABLE: "Not applicable", UNKNOWN: "Unknown",
};

export default function JobDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { data, error, mutate } = useSWR<Detail>(`/jobs/${id}`, (p: string) => api<Detail>(p));
  const [url, setUrl] = useState("");
  const [msg, setMsg] = useState("");
  if (error) return <p role="alert" className="text-danger">Job not found.</p>;
  if (!data) return <Skeleton rows={5} />;
  return (
    <div className="grid max-w-4xl gap-5">
      <header><h1>{data.title}</h1><p>{data.company} · {data.location ?? "location not stated"}</p>
        <p className="mt-1 flex items-center gap-2"><StatusBadge status={data.status} />{data.needs_reverify && <span className="text-sm text-warn">Evidence is older than 3 days; re-verify before using.</span>}</p>
        <div className="mt-2 flex gap-2">
          <button className="rounded border px-3 py-1 text-sm" onClick={async () => { await api(`/jobs/${id}/verify`, { body: {} }); mutate(); }}>Verify again</button>
          <button disabled={data.status === "CLOSED"} className="rounded bg-black px-3 py-1 text-sm text-white disabled:opacity-40" onClick={async () => { try { const r = await api<{ id: string }>("/tailoring", { body: { job_id: id } }); router.push(`/resumes/${r.id}`); } catch (e) { setMsg((e as Error).message); } }}>Tailor my resume</button>
          <Link className="rounded border px-3 py-1 text-sm" href={`/opportunities/${id}`}>See match analysis</Link>
        </div></header>

      <section aria-labelledby="why"><h2 id="why" className="font-medium">Why this status</h2>
        <ul className="list-disc pl-5 text-sm">{data.status_reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
        {data.outreach_note && <p className="mt-1 rounded bg-warn-weak p-2 text-sm">{data.outreach_note}</p>}</section>

      <section aria-labelledby="ev"><h2 id="ev" className="font-medium">Verification evidence</h2>
        <table className="min-w-full border text-xs"><thead><tr className="bg-surface-2 text-left"><th className="border px-2 py-1">When (UTC)</th><th className="border px-2 py-1">Source</th><th className="border px-2 py-1">What was seen</th><th className="border px-2 py-1">Detail</th></tr></thead>
          <tbody>{data.verification_evidence.map((e, i) => <tr key={i}><td className="border px-2 py-1">{e.checked_at}</td><td className="border px-2 py-1">{e.source}</td><td className="border px-2 py-1">{e.kind.replaceAll("_", " ")}</td><td className="border px-2 py-1">{JSON.stringify(e.detail)}</td></tr>)}</tbody></table></section>

      <section aria-labelledby="route"><h2 id="route" className="font-medium">Referral route</h2>
        <p className="text-sm">{ROUTE[data.referral_route.status]}{data.referral_route.evidence_url && <> · <a className="underline" href={data.referral_route.evidence_url} target="_blank" rel="noopener noreferrer">evidence</a></>}</p>
        {data.referral_route.evidence_excerpt && <blockquote className="mt-1 border-l-2 pl-2 text-xs text-muted">…{data.referral_route.evidence_excerpt}…</blockquote>}
        <p className="mt-1 text-xs text-muted">Messages will not claim a referral programme unless it is confirmed on an official page.</p>
        <form className="mt-2 flex gap-2 text-sm" onSubmit={async (e) => { e.preventDefault(); try { await api(`/companies/${data.company_id}/referral-route/check`, { body: { urls: [url] } }); setMsg("Checked."); mutate(); } catch (x) { setMsg((x as Error).message); } }}>
          <input required aria-label="Official careers or referral page URL" className="flex-1 rounded border px-2 py-1" placeholder="Official careers or referral page URL" value={url} onChange={(e) => setUrl(e.target.value)} /><button className="rounded border px-3 py-1">Check page</button></form>
        {msg && <p role="status" className="text-sm">{msg}</p>}</section>

      <section aria-labelledby="src"><h2 id="src" className="font-medium">Sources</h2>
        <ul className="list-disc pl-5 text-sm">{data.sources.map((s, i) => <li key={i}>{s.type}{s.board && ` (${s.board})`}{s.source_url && <> · <a className="underline" href={s.source_url} target="_blank" rel="noopener noreferrer">listing</a></>}</li>)}</ul>
        {data.apply_url && <p className="mt-1 text-sm"><a className="underline" href={data.apply_url} target="_blank" rel="noopener noreferrer">Official application link</a></p>}
        <p className="mt-1 text-sm">You know {data.contacts_at_company} people at this company.</p></section>

      <section aria-labelledby="jd"><h2 id="jd" className="font-medium">Description</h2>
        <p className="whitespace-pre-wrap text-sm">{data.description ?? "No description available. Paste it from the posting if you need analysis."}</p></section>
    </div>
  );
}
