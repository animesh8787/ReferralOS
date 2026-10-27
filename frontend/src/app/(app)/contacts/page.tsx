"use client";
import { useState } from "react";
import useSWR from "swr";
import Pager from "@/components/Pager";
import Skeleton from "@/components/ui/Skeleton";
import { api } from "@/lib/api";

type Page<T> = { total: number; items: T[] };
type C = { id: string; name: string; company: string | null; position: string | null; linkedin_url: string | null; email: string | null; role_category: string | null; seniority: string | null };
type E = { id: string; name: string | null; title: string | null; company: string | null; email: string | null; email_raw: string | null; email_valid: boolean; email_flags: string[];
  phone: string | null; suppressed: boolean; bulk_send_blocked: boolean; provenance: string };

export default function ContactsPage() {
  const [tab, setTab] = useState<"li" | "hr">("li");
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const path = tab === "li" ? "contacts" : "email-contacts";
  const { data, error, isLoading } = useSWR<Page<C & E>>(`/${path}?q=${encodeURIComponent(q)}&page=${page}&page_size=50`, (p: string) => api<Page<C & E>>(p));

  return (
    <div className="grid gap-4">
      <h1>Contacts</h1>
      <div role="tablist" aria-label="Contact type" className="flex gap-2">
        {([["li", "LinkedIn connections"], ["hr", "HR / recruiter emails"]] as const).map(([k, l]) => (
          <button key={k} role="tab" aria-selected={tab === k} className={`rounded border px-3 py-1 text-sm ${tab === k ? "bg-black" : ""}`} onClick={() => { setTab(k); setPage(1); }}>{l}</button>
        ))}
      </div>
      <input aria-label="Search contacts" className="max-w-sm rounded border px-3 py-1.5 text-sm" placeholder="Search name, company or title" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} />
      {isLoading && <Skeleton rows={5} />}
      {error && <p role="alert" className="text-danger">Could not load contacts.</p>}
      {data && data.items.length === 0 && <p className="text-sm text-muted">{q ? "No matches." : "Nothing here yet. Import a CSV on the Imports page."}</p>}
      {data && data.items.length > 0 && (
        <>
          <div className="overflow-auto"><table className="min-w-full border text-sm">
            <caption className="sr-only">{tab === "li" ? "LinkedIn connections" : "HR contacts"}</caption>
            <thead><tr className="bg-surface-2 text-left"><th className="border px-2 py-1">Name</th><th className="border px-2 py-1">Company</th><th className="border px-2 py-1">{tab === "li" ? "Position" : "Title"}</th>
              <th className="border px-2 py-1">{tab === "li" ? "Profile" : "Email / phone"}</th>{tab === "hr" && <th className="border px-2 py-1">Flags</th>}</tr></thead>
            <tbody>{data.items.map((c) => (
              <tr key={c.id}>
                <td className="border px-2 py-1">{c.name ?? "—"}</td><td className="border px-2 py-1">{c.company ?? "—"}</td><td className="border px-2 py-1">{(tab === "li" ? c.position : c.title) ?? "—"}</td>
                <td className="border px-2 py-1">{tab === "li" ? (c.linkedin_url ? <a className="underline" href={c.linkedin_url} target="_blank" rel="noopener noreferrer">LinkedIn</a> : "—") : (<>{c.email ?? c.email_raw ?? "—"}{c.phone && <> · <a className="underline" href={`tel:${c.phone}`}>{c.phone}</a></>}</>)}</td>
                {tab === "hr" && <td className="border px-2 py-1 text-xs">{[!c.email_valid && "invalid email", ...c.email_flags, c.suppressed && "SUPPRESSED", c.bulk_send_blocked && "bulk blocked"].filter(Boolean).join(", ") || "—"}</td>}
              </tr>))}</tbody></table></div>
          <Pager page={page} pageSize={50} total={data.total} onPage={setPage} />
          {tab === "hr" && <p className="text-xs text-muted">Phone links are for manual use only. Calling or messaging by phone is subject to local telemarketing rules.</p>}
        </>
      )}
    </div>
  );
}
