"use client";
import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";
import Pager from "@/components/Pager";
import StatusBadge from "@/components/StatusBadge";
import { api } from "@/lib/api";

type Job = { id: string; title: string; company: string | null; location: string | null; work_arrangement: string; employment_type: string; status: string;
  needs_reverify: boolean; contacts_at_company: number; outreach_eligible: boolean; origin: string };
type Board = { id: string; company: string | null; ats: string; token: string; confirmed: boolean; last_status: string | null; jobs_found: number };
type Run = { summary: { boards: number; reachable: number; jobs_seen: number; new_jobs: number; contact_companies: number; contact_companies_without_reachable_board: number };
  coverage: { company: string | null; ats: string; reachable: boolean; jobs: number; error: string | null }[] };
type Cand = { ats: string; token: string; basis: string; sample: string[] };

const ATS = ["greenhouse", "lever", "ashby", "workable", "smartrecruiters"];

export default function JobsPage() {
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [hasContacts, setHasContacts] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [cands, setCands] = useState<Cand[]>([]);
  const [bf, setBf] = useState({ company: "", ats: "greenhouse", token: "", board_url: "" });
  const [mf, setMf] = useState({ url: "", title: "", company: "", location: "", description: "" });
  const qs = `/jobs?page=${page}&page_size=50&q=${encodeURIComponent(q)}${status ? `&status=${status}` : ""}${hasContacts ? `&has_contacts=${hasContacts}` : ""}`;
  const jobs = useSWR<{ total: number; items: Job[] }>(qs, (p: string) => api<{ total: number; items: Job[] }>(p));
  const boards = useSWR<Board[]>("/boards", (p: string) => api<Board[]>(p));
  const runs = useSWR<Run[]>("/jobs/discovery-runs", (p: string) => api<Run[]>(p));

  async function run(label: string, fn: () => Promise<unknown>) {
    setBusy(true); setMsg("");
    try { await fn(); setMsg(label); } catch (e) { setMsg((e as Error).message); } finally { setBusy(false); jobs.mutate(); boards.mutate(); runs.mutate(); }
  }
  const last = runs.data?.[0];

  return (
    <div className="mx-auto grid max-w-6xl gap-6">
      <header className="flex flex-wrap items-end justify-between gap-2">
        <div><h1 className="text-xl font-semibold">Jobs</h1>
          <p className="text-sm text-gray-600">Only roles listed as open by the company&apos;s own job board count as verified. Everything else is shown with the reason it is uncertain.</p></div>
        <div className="flex gap-2 text-sm">
          <button disabled={busy} className="rounded bg-black px-3 py-1.5 text-white disabled:opacity-50" onClick={() => run("Discovery finished.", () => api("/jobs/discover", { body: {} }))}>Find jobs on my boards</button>
          <button disabled={busy} className="rounded border px-3 py-1.5 disabled:opacity-50" onClick={() => run("Stale jobs re-checked.", () => api("/jobs/verify-stale", { body: {} }))}>Re-check stale jobs</button>
        </div>
      </header>
      {msg && <p role="status" className="text-sm">{msg}</p>}

      {last && (
        <section aria-labelledby="cov" className="rounded border p-3 text-sm">
          <h2 id="cov" className="font-medium">Coverage of the last run</h2>
          <p>{last.summary.reachable} of {last.summary.boards} boards reachable · {last.summary.jobs_seen} jobs seen · {last.summary.new_jobs} new.
            {last.summary.contact_companies_without_reachable_board > 0 && <> {last.summary.contact_companies_without_reachable_board} of the {last.summary.contact_companies} companies you know people at have <strong>no reachable job board</strong>, so their jobs are not covered.</>}</p>
          <ul className="mt-1 list-disc pl-5">{last.coverage.filter((c) => !c.reachable).map((c, i) => <li key={i}>{c.company} ({c.ats}): {c.error}</li>)}</ul>
        </section>
      )}

      <details className="rounded border p-3 text-sm">
        <summary className="cursor-pointer font-medium">Job boards ({boards.data?.length ?? 0})</summary>
        <ul className="my-2 grid gap-1">{boards.data?.map((b) => (
          <li key={b.id} className="flex justify-between rounded border px-2 py-1"><span>{b.company} · {b.ats}/{b.token} · {b.last_status ?? "not run yet"}{b.last_status === "ok" && ` (${b.jobs_found} jobs)`}</span>
            <button className="text-red-700 underline" onClick={() => run("Board removed.", () => api(`/boards/${b.id}`, { method: "DELETE" }))}>Remove</button></li>))}</ul>
        <form className="grid gap-2 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); run("Board added.", () => api("/boards", { body: { company: bf.company, ...(bf.board_url ? { board_url: bf.board_url } : { ats: bf.ats, token: bf.token }) } })); }}>
          <label className="grid gap-1">Company<input required className="rounded border px-2 py-1" value={bf.company} onChange={(e) => setBf({ ...bf, company: e.target.value })} /></label>
          <label className="grid gap-1">Board URL (or fill ATS + token)<input className="rounded border px-2 py-1" placeholder="https://boards.greenhouse.io/yourcompany" value={bf.board_url} onChange={(e) => setBf({ ...bf, board_url: e.target.value })} /></label>
          <label className="grid gap-1">ATS<select className="rounded border px-2 py-1" value={bf.ats} onChange={(e) => setBf({ ...bf, ats: e.target.value })}>{ATS.map((a) => <option key={a}>{a}</option>)}</select></label>
          <label className="grid gap-1">Board token<input className="rounded border px-2 py-1" value={bf.token} onChange={(e) => setBf({ ...bf, token: e.target.value })} /></label>
          <div className="flex gap-2 sm:col-span-2"><button className="rounded bg-black px-3 py-1 text-white">Add board</button>
            <button type="button" className="rounded border px-3 py-1" onClick={async () => { const r = await api<{ candidates: Cand[] }>("/boards/suggest", { body: { company: bf.company, careers_url: bf.board_url || undefined } }); setCands(r.candidates); setMsg(r.candidates.length ? "" : "No public board found with that name."); }}>Look for a board</button></div>
        </form>
        {cands.map((c) => (
          <p key={c.ats + c.token} className="mt-2 rounded bg-amber-50 p-2">{c.ats}/{c.token}: {c.basis}. {c.sample.length > 0 && <>Sample roles: {c.sample.join("; ")}. </>}
            <button className="underline" onClick={() => { setBf({ ...bf, ats: c.ats, token: c.token, board_url: "" }); setCands([]); }}>This is the right company, use it</button></p>))}
      </details>

      <details className="rounded border p-3 text-sm">
        <summary className="cursor-pointer font-medium">Add a job by link or by pasting it</summary>
        <form className="mt-2 grid gap-2" onSubmit={(e) => { e.preventDefault(); run("Job added.", () => api("/jobs/manual", { body: Object.fromEntries(Object.entries(mf).filter(([, v]) => v)) })); }}>
          <label className="grid gap-1">Job page URL (we read its structured job data)<input className="rounded border px-2 py-1" value={mf.url} onChange={(e) => setMf({ ...mf, url: e.target.value })} /></label>
          <div className="grid gap-2 sm:grid-cols-3">
            <label className="grid gap-1">Title<input className="rounded border px-2 py-1" value={mf.title} onChange={(e) => setMf({ ...mf, title: e.target.value })} /></label>
            <label className="grid gap-1">Company<input className="rounded border px-2 py-1" value={mf.company} onChange={(e) => setMf({ ...mf, company: e.target.value })} /></label>
            <label className="grid gap-1">Location<input className="rounded border px-2 py-1" value={mf.location} onChange={(e) => setMf({ ...mf, location: e.target.value })} /></label></div>
          <label className="grid gap-1">Description (paste the full text)<textarea rows={4} className="rounded border px-2 py-1" value={mf.description} onChange={(e) => setMf({ ...mf, description: e.target.value })} /></label>
          <p className="text-xs text-gray-600">A pasted job stays private to you and is marked Unknown: pasted text cannot show that a role is still open.</p>
          <button className="w-fit rounded bg-black px-3 py-1 text-white">Add job</button>
        </form>
      </details>

      <div className="flex flex-wrap gap-2 text-sm">
        <input aria-label="Search jobs" className="rounded border px-2 py-1" placeholder="Search title, location, description" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
        <label>Status <select className="rounded border px-1 py-1" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}><option value="">all</option>{["ACTIVE_VERIFIED", "ACTIVE_UNCONFIRMED", "POSSIBLY_CLOSED", "CLOSED", "UNKNOWN"].map((s) => <option key={s}>{s}</option>)}</select></label>
        <label>People I know there <select className="rounded border px-1 py-1" value={hasContacts} onChange={(e) => { setHasContacts(e.target.value); setPage(1); }}><option value="">any</option><option value="true">yes</option><option value="false">no</option></select></label>
      </div>
      {jobs.isLoading && <p role="status">Loading…</p>}
      {jobs.data?.items.length === 0 && <p className="text-sm text-gray-600">No jobs yet. Add a job board above and press “Find jobs”, or add a job by link.</p>}
      {jobs.data && jobs.data.items.length > 0 && (
        <>
          <div className="overflow-auto"><table className="min-w-full border text-sm"><caption className="sr-only">Jobs</caption>
            <thead><tr className="bg-gray-50 text-left">{["Title", "Company", "Location", "Type", "Status", "Contacts"].map((h) => <th key={h} className="border px-2 py-1">{h}</th>)}</tr></thead>
            <tbody>{jobs.data.items.map((j) => (
              <tr key={j.id}><td className="border px-2 py-1"><Link className="underline" href={`/jobs/${j.id}`}>{j.title}</Link></td><td className="border px-2 py-1">{j.company}</td>
                <td className="border px-2 py-1">{j.location ?? "—"} <span className="text-gray-600">({j.work_arrangement})</span></td><td className="border px-2 py-1">{j.employment_type.replace("_", " ")}</td>
                <td className="border px-2 py-1"><StatusBadge status={j.status} />{j.needs_reverify && <span className="ml-1 text-xs text-amber-800">re-check</span>}</td><td className="border px-2 py-1">{j.contacts_at_company}</td></tr>))}</tbody></table></div>
          <Pager page={page} pageSize={50} total={jobs.data.total} onPage={setPage} />
        </>
      )}
    </div>
  );
}
