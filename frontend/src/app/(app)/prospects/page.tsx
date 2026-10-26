"use client";
import { useState } from "react";
import useSWR from "swr";
import Pager from "@/components/Pager";
import { api } from "@/lib/api";

type Comp = { points: number; weight: number; known: boolean; value?: number | null; explanation?: string };
type P = { contact_id: string; rank: number; tier: number | null; score: number; confidence: number; excluded: boolean; name: string; company: string | null;
  position: string | null; role_category: string | null; seniority: string | null; linkedin_url: string | null; employment_status: string; components: Record<string, Comp> };
type List = { total: number; unscored_contacts: number; items: P[] };
type Detail = P & { confidence_parts: { parts: Record<string, number>; note: string }; scoring_version: string };
type Cfg = { weights: Record<string, number>; missing_policy: string; tiers: number[]; components: string[] };

const nice = (s: string) => s.replaceAll("_", " ");

export default function Prospects() {
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [tier, setTier] = useState("");
  const [role, setRole] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [msg, setMsg] = useState("");
  const qs = `/prospects?page=${page}&page_size=50&q=${encodeURIComponent(q)}${tier ? `&tier=${tier}` : ""}${role ? `&role_category=${role}` : ""}`;
  const list = useSWR<List>(qs, (p: string) => api<List>(p));
  const detail = useSWR<Detail>(open ? `/prospects/${open}` : null, (p: string) => api<Detail>(p));
  const cfg = useSWR<Cfg>("/scoring/config", (p: string) => api<Cfg>(p));
  const [w, setW] = useState<Record<string, number> | null>(null);
  const weights = w ?? cfg.data?.weights ?? {};

  async function saveCfg(body: object) {
    setMsg("");
    try {
      await api("/scoring/config", { method: "PUT", body });
      await api("/scoring/recompute", { body: {} });
      setW(null); cfg.mutate(); list.mutate();
      setMsg("Settings saved and prospects recalculated.");
    } catch (e) { setMsg((e as Error).message); }
  }

  return (
    <div className="mx-auto grid max-w-6xl gap-4">
      <header className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h1 className="text-xl font-semibold">Ranked prospects</h1>
          <p className="text-sm text-gray-600">Score = outreach priority from facts we hold. Confidence = how well-supported that score is. Neither predicts whether anyone will refer you; employer and role are inferred from your export, not verified.</p>
        </div>
        <div className="flex gap-2 text-sm">
          <a className="rounded border px-2 py-1 underline" href="/api/exports/prospects.csv">CSV</a>
          <a className="rounded border px-2 py-1 underline" href="/api/exports/prospects.xlsx">Excel</a>
          <button className="rounded border px-2 py-1" onClick={async () => { await api("/scoring/recompute", { body: {} }); list.mutate(); }}>Recalculate</button>
        </div>
      </header>

      <div className="flex flex-wrap gap-2 text-sm">
        <input aria-label="Search prospects" className="rounded border px-2 py-1" placeholder="Search name, company, title" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
        <label>Tier <select className="rounded border px-1 py-1" value={tier} onChange={(e) => { setTier(e.target.value); setPage(1); }}><option value="">all</option>{[1, 2, 3].map((t) => <option key={t}>{t}</option>)}</select></label>
        <label>Role <select className="rounded border px-1 py-1" value={role} onChange={(e) => { setRole(e.target.value); setPage(1); }}><option value="">all</option>{["engineer", "eng_manager", "recruiter", "leadership", "product", "other", "unknown"].map((t) => <option key={t} value={t}>{nice(t)}</option>)}</select></label>
      </div>

      {list.data && list.data.unscored_contacts > 0 && <p role="status" className="rounded bg-amber-100 p-2 text-sm">{list.data.unscored_contacts} contacts are not scored yet. Press Recalculate.</p>}
      {list.isLoading && <p role="status">Loading…</p>}
      {list.data && list.data.items.length === 0 && <p className="text-sm text-gray-600">No prospects yet. Import your LinkedIn connections first.</p>}
      {list.data && list.data.items.length > 0 && (
        <>
          <div className="overflow-auto"><table className="min-w-full border text-sm"><caption className="sr-only">Prospects ranked by priority score</caption>
            <thead><tr className="bg-gray-50 text-left">{["#", "Tier", "Score", "Confidence", "Name", "Company", "Position", ""].map((h) => <th key={h} className="border px-2 py-1">{h}</th>)}</tr></thead>
            <tbody>{list.data.items.map((p) => (
              <tr key={p.contact_id} className={p.excluded ? "opacity-50" : ""}>
                <td className="border px-2 py-1">{p.rank}</td><td className="border px-2 py-1">{p.tier ?? "—"}</td><td className="border px-2 py-1 font-medium">{p.score.toFixed(1)}</td>
                <td className="border px-2 py-1">{p.confidence.toFixed(0)}</td><td className="border px-2 py-1">{p.name}</td>
                <td className="border px-2 py-1">{p.company ?? "—"}{p.excluded && " (excluded)"}</td><td className="border px-2 py-1">{p.position ?? "—"}</td>
                <td className="border px-2 py-1"><button className="underline" aria-expanded={open === p.contact_id} onClick={() => setOpen(open === p.contact_id ? null : p.contact_id)}>Why?</button></td>
              </tr>))}</tbody></table></div>
          <Pager page={page} pageSize={50} total={list.data.total} onPage={setPage} />
        </>
      )}

      {open && detail.data && (
        <section aria-label="Score breakdown" className="rounded border p-4 text-sm">
          <h2 className="font-medium">{detail.data.name}: {detail.data.score.toFixed(1)} / 100 · confidence {detail.data.confidence.toFixed(0)}</h2>
          <ul className="mt-2 grid gap-2">{Object.entries(detail.data.components).map(([k, c]) => (
            <li key={k}><span className="font-medium">{nice(k)}</span>: {c.points.toFixed(1)} of {c.weight.toFixed(0)} {!c.known && <em>(unknown, handled by your missing-data policy)</em>}<br /><span className="text-gray-600">{c.explanation}</span></li>))}</ul>
          <p className="mt-2 text-gray-600">Confidence parts: {Object.entries(detail.data.confidence_parts.parts).map(([k, v]) => `${nice(k)} ${Math.round(v * 100)}%`).join(" · ")}. {detail.data.confidence_parts.note}</p>
          {detail.data.linkedin_url && <p className="mt-1"><a className="underline" href={detail.data.linkedin_url} target="_blank" rel="noopener noreferrer">Open LinkedIn profile</a></p>}
        </section>
      )}

      <details className="rounded border p-4 text-sm">
        <summary className="cursor-pointer font-medium">Scoring settings</summary>
        {cfg.data && (
          <form className="mt-3 grid gap-2" onSubmit={(e) => { e.preventDefault(); saveCfg({ weights, missing_policy: cfg.data!.missing_policy }); }}>
            <p className="text-gray-600">Weights are rescaled to total 100 when saved.</p>
            {cfg.data.components.map((k) => (
              <label key={k} className="flex items-center gap-2"><span className="w-44">{nice(k)}</span>
                <input type="number" min={0} className="w-20 rounded border px-2 py-1" value={weights[k] ?? 0} onChange={(e) => setW({ ...weights, [k]: Number(e.target.value) })} /></label>))}
            <label className="flex items-center gap-2"><span className="w-44">When data is unknown</span>
              <select className="rounded border px-2 py-1" value={cfg.data.missing_policy} onChange={(e) => saveCfg({ missing_policy: e.target.value })}>
                <option value="neutral">count as neutral (and lower confidence)</option><option value="exclude">leave it out (and lower confidence)</option></select></label>
            <button className="w-fit rounded bg-black px-3 py-1 text-white">Save weights and recalculate</button>
          </form>)}
        {msg && <p role="status" className="mt-2">{msg}</p>}
      </details>
    </div>
  );
}
