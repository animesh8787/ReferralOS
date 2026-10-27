"use client";
import useSWR from "swr";
import Skeleton from "@/components/ui/Skeleton";
import { api } from "@/lib/api";

type D = { resumes: { id: string; filename: string; status: string; parser: string | null; pages: number | null; columns_detected: number | null; image_only: boolean; warnings: string[]; error: string | null;
  items_extracted: number; items_rejected_untraceable: number; mean_confidence: number | null; flagged_items: number; sections_found: string[] }[];
  imports: { id: string; kind: string; filename: string; status: string; encoding: string; delimiter: string; header_line: number; mapped: Record<string, string>; unmapped_fields: string[]; unmapped_columns: string[]; rows: Record<string, number>; rejected_reasons: Record<string, number> }[];
  jobs: { sources_seen: Record<string, number>; boards: { ats: string; token: string; status: string | null; jobs: number }[] };
  integrations: { name: string; state: string; mode: string; verified_against: string }[] };

export default function Diagnostics() {
  const { data: d, error } = useSWR<D>("/diagnostics", (p: string) => api<D>(p));
  if (error) return <p role="alert" className="text-danger">Could not load diagnostics.</p>;
  if (!d) return <Skeleton rows={5} />;
  return (
    <div className="grid gap-6 text-sm">
      <header><h1>Diagnostics</h1><p className="text-muted">What the system actually read and did, so you can check it against your real files.</p></header>
      <section aria-labelledby="r"><h2 id="r" className="mb-1 font-medium">Resume parsing</h2>{d.resumes.length === 0 && <p>No resumes uploaded.</p>}
        {d.resumes.map((r) => <div key={r.id} className="mb-2 rounded border p-2"><p className="font-medium">{r.filename} · {r.status}</p>
          <p>Parser {r.parser ?? "n/a"} · {r.pages ?? "?"} page(s) · {r.columns_detected === 2 ? "two columns detected" : "single column"} · {r.items_extracted} items extracted · mean confidence {r.mean_confidence ?? "n/a"} · {r.flagged_items} flagged · {r.items_rejected_untraceable} dropped (not traceable to the text)</p>
          <p>Sections found: {r.sections_found.join(", ") || "none"}</p>{r.warnings.map((w, i) => <p key={i} className="text-warn">{w}</p>)}{r.error && <p className="text-danger">{r.error}</p>}</div>)}</section>
      <section aria-labelledby="i"><h2 id="i" className="mb-1 font-medium">Imports</h2>{d.imports.length === 0 && <p>No imports yet.</p>}
        {d.imports.map((i) => <div key={i.id} className="mb-2 rounded border p-2"><p className="font-medium">{i.filename} ({i.kind}) · {i.status}</p>
          <p>{i.encoding}, delimiter “{i.delimiter === "\t" ? "tab" : i.delimiter}”, header on line {i.header_line}. Rows: {Object.entries(i.rows).map(([k, v]) => `${v} ${k}`).join(", ") || "none"}.</p>
          <p>Mapped: {Object.entries(i.mapped).map(([k, v]) => `${k} ← “${v}”`).join("; ") || "nothing"}</p>
          <p>Fields with no column: {i.unmapped_fields.join(", ") || "none"} · Columns not used: {i.unmapped_columns.join(", ") || "none"}</p>
          {Object.keys(i.rejected_reasons).length > 0 && <p>Why rows were flagged: {Object.entries(i.rejected_reasons).map(([k, v]) => `${k.replaceAll("_", " ")} (${v})`).join(", ")}</p>}</div>)}</section>
      <section aria-labelledby="j"><h2 id="j" className="mb-1 font-medium">Jobs by source</h2>
        <p>{Object.entries(d.jobs.sources_seen).map(([k, v]) => `${k}: ${v}`).join(" · ") || "No jobs found yet."}</p>
        <ul className="list-disc pl-5">{d.jobs.boards.map((b, i) => <li key={i}>{b.ats}/{b.token}: {b.status ?? "not run"}{b.status === "ok" && ` (${b.jobs} jobs)`}</li>)}</ul></section>
      <section aria-labelledby="h"><h2 id="h" className="mb-1 font-medium">Integration health</h2>
        <div className="overflow-auto"><table className="min-w-full border text-xs"><thead><tr className="bg-surface-2 text-left"><th className="border px-2 py-1">Integration</th><th className="border px-2 py-1">State</th><th className="border px-2 py-1">Mode</th><th className="border px-2 py-1">Actually verified against</th></tr></thead>
          <tbody>{d.integrations.map((i) => <tr key={i.name}><td className="border px-2 py-1">{i.name}</td><td className="border px-2 py-1">{i.state}</td><td className="border px-2 py-1">{i.mode}</td><td className="border px-2 py-1">{i.verified_against}</td></tr>)}</tbody></table></div></section>
    </div>
  );
}
