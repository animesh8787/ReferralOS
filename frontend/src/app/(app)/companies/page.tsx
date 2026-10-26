"use client";
import { useState } from "react";
import useSWR from "swr";
import Pager from "@/components/Pager";
import { api } from "@/lib/api";

type Co = { total: number; items: { id: string; name: string; connections: number; hr_contacts: number }[] };
type Person = { contact_id: string; name: string; position: string | null; score: number; confidence: number };
type Intel = { company: { name: string }; connections: number; by_role: Record<string, number>; best_first_outreach: Person[]; top_contacts: Person[]; recruiters: Person[];
  hr_contacts: { id: string; name: string | null; title: string | null; email: string | null; flags: string[]; suppressed: boolean }[]; verified_open_roles: { known: boolean; note: string } };

function People({ title, rows }: { title: string; rows: Person[] }) {
  if (!rows.length) return null;
  return (<div><h3 className="font-medium">{title}</h3><ul className="list-disc pl-5">{rows.map((p) => <li key={p.contact_id}>{p.name}, {p.position ?? "title unknown"} · score {p.score.toFixed(0)} · confidence {p.confidence.toFixed(0)}</li>)}</ul></div>);
}

export default function Companies() {
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [sel, setSel] = useState<string | null>(null);
  const list = useSWR<Co>(`/companies?q=${encodeURIComponent(q)}&page=${page}&page_size=30`, (p: string) => api<Co>(p));
  const intel = useSWR<Intel>(sel ? `/companies/${sel}/intelligence` : null, (p: string) => api<Intel>(p));
  return (
    <div className="mx-auto grid max-w-5xl gap-4 md:grid-cols-2">
      <section aria-labelledby="c"><h1 id="c" className="mb-2 text-xl font-semibold">Companies</h1>
        <input aria-label="Search companies" className="mb-2 w-full rounded border px-2 py-1 text-sm" placeholder="Search" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
        {list.data?.items.length === 0 && <p className="text-sm text-gray-600">No companies yet. Import contacts first.</p>}
        <ul className="grid gap-1 text-sm">{list.data?.items.map((c) => (
          <li key={c.id}><button aria-pressed={sel === c.id} className={`w-full rounded border px-3 py-1.5 text-left ${sel === c.id ? "bg-gray-100" : ""}`} onClick={() => setSel(c.id)}>
            {c.name} <span className="text-gray-600">· {c.connections} connections{c.hr_contacts ? ` · ${c.hr_contacts} HR contacts` : ""}</span></button></li>))}</ul>
        {list.data && <div className="mt-2"><Pager page={page} pageSize={30} total={list.data.total} onPage={setPage} /></div>}
      </section>
      <section aria-live="polite" className="text-sm">
        {intel.data && (
          <div className="grid gap-3"><h2 className="text-lg font-semibold">{intel.data.company.name}</h2>
            <p>{intel.data.connections} connections: {Object.entries(intel.data.by_role).map(([k, v]) => `${v} ${k.replaceAll("_", " ")}`).join(", ") || "none scored yet"}</p>
            <People title="Best first outreach" rows={intel.data.best_first_outreach} /><People title="Top contacts" rows={intel.data.top_contacts} /><People title="Recruiters" rows={intel.data.recruiters} />
            {intel.data.hr_contacts.length > 0 && <div><h3 className="font-medium">HR contacts from your CSV</h3><ul className="list-disc pl-5">{intel.data.hr_contacts.map((h) => <li key={h.id}>{h.name ?? h.email} {h.title && `· ${h.title}`} {h.suppressed && <strong>(do not contact)</strong>} {h.flags.length > 0 && <em>({h.flags.join(", ")})</em>}</li>)}</ul></div>}
            <p className="text-gray-600">Open roles: {intel.data.verified_open_roles.known ? "see Jobs" : intel.data.verified_open_roles.note}</p></div>)}
        {!sel && <p className="text-gray-600">Choose a company to see who you know there.</p>}
      </section>
    </div>
  );
}
