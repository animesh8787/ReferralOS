"use client";
import { useState } from "react";
import useSWR from "swr";
import Pager from "@/components/Pager";
import { api } from "@/lib/api";

type P = { id: string; status: string; channel: string; job_title: string | null; who: string | null; match_score: number | null; contact_score: number | null; follow_up_at: string | null; note: string | null;
  last_message: { id: string; kind: string; send_state: string; subject: string | null } | null };
type R = { total: number; counts: Record<string, number>; items: P[] };
const ORDER = ["CONTACT_IDENTIFIED", "DRAFT_READY", "AWAITING_APPROVAL", "APPROVED", "QUEUED", "SENT", "DELIVERY_UNCONFIRMED", "REPLIED", "REFERRAL_OFFERED", "REFERRAL_SUBMITTED", "APPLICATION_SUBMITTED", "REJECTED", "CLOSED", "DO_NOT_CONTACT"];
const MANUAL = ["REPLIED", "REFERRAL_OFFERED", "REFERRAL_SUBMITTED", "APPLICATION_SUBMITTED", "REJECTED", "CLOSED", "DO_NOT_CONTACT"];

export default function Tracking() {
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [msg, setMsg] = useState("");
  const { data, mutate } = useSWR<R>(`/tracking/pairs?page=${page}&page_size=25${status ? `&status=${status}` : ""}`, (p: string) => api<R>(p));
  async function set(id: string, st: string) {
    let evidence: string | undefined;
    if (st === "REFERRAL_SUBMITTED") { evidence = window.prompt("What is your evidence that a referral was submitted? (who, when, any reference)") ?? undefined; if (!evidence) return; }
    try { await api(`/tracking/pairs/${id}`, { method: "PATCH", body: { status: st, evidence } }); setMsg("Updated."); mutate(); } catch (e) { setMsg((e as Error).message); }
  }
  return (
    <div className="mx-auto grid max-w-6xl gap-4">
      <header><h1 className="text-xl font-semibold">Tracking</h1><p className="text-sm text-gray-600">Every outreach from draft to outcome. “Sent” only appears after a real send or after you confirm you sent it. “Referral submitted” needs your evidence.</p></header>
      {msg && <p role="status" className="text-sm">{msg}</p>}
      <div className="flex flex-wrap gap-2" role="group" aria-label="Pipeline stages">
        <button className={`rounded border px-2 py-1 text-xs ${status === "" ? "bg-black text-white" : ""}`} onClick={() => { setStatus(""); setPage(1); }}>All</button>
        {ORDER.filter((s) => data?.counts[s]).map((s) => <button key={s} className={`rounded border px-2 py-1 text-xs ${status === s ? "bg-black text-white" : ""}`} onClick={() => { setStatus(s); setPage(1); }}>{s.replaceAll("_", " ").toLowerCase()} ({data?.counts[s]})</button>)}</div>
      {data?.items.length === 0 && <p className="text-sm text-gray-600">Nothing here yet.</p>}
      {data && data.items.length > 0 && <>
        <div className="overflow-auto"><table className="min-w-full border text-sm"><caption className="sr-only">Outreach pipeline</caption>
          <thead><tr className="bg-gray-50 text-left">{["Who", "Job", "Channel", "Status", "Last message", "Follow-up due", "Update"].map((h) => <th key={h} className="border px-2 py-1">{h}</th>)}</tr></thead>
          <tbody>{data.items.map((p) => <tr key={p.id}><td className="border px-2 py-1">{p.who}</td><td className="border px-2 py-1">{p.job_title ?? "—"}</td><td className="border px-2 py-1">{p.channel}</td>
            <td className="border px-2 py-1">{p.status.replaceAll("_", " ").toLowerCase()}</td><td className="border px-2 py-1">{p.last_message ? `${p.last_message.kind.replace("_", " ")}: ${p.last_message.send_state.replace("_", " ")}` : "—"}</td>
            <td className="border px-2 py-1">{p.follow_up_at ? new Date(p.follow_up_at + "Z").toLocaleDateString() : "—"}</td>
            <td className="border px-2 py-1"><select aria-label={`Update status for ${p.who}`} className="rounded border px-1 py-0.5 text-xs" value="" onChange={(e) => e.target.value && set(p.id, e.target.value)}><option value="">Set…</option>{MANUAL.map((m) => <option key={m} value={m}>{m.replaceAll("_", " ").toLowerCase()}</option>)}</select></td></tr>)}</tbody></table></div>
        <Pager page={page} pageSize={25} total={data.total} onPage={setPage} /></>}
      <p className="text-sm"><a className="underline" href="/api/exports/outreach-queue.csv">Export outreach queue (CSV)</a></p>
    </div>
  );
}
