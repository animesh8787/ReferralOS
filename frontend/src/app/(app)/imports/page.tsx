"use client";
import { useState } from "react";
import useSWR from "swr";
import Pager from "@/components/Pager";
import { api } from "@/lib/api";

type Preview = { import_id: string; encoding: string; delimiter: string; header_row: number; headers: string[]; mapping: Record<string, string | null>;
  unmapped: string[]; preview: string[][]; total_rows: number; warnings: string[]; provenance_options: Record<string, string> | null };
type Batch = { id: string; kind: string; filename: string; status: string; provenance: string | null; report: Record<string, unknown> };
type Rows = { total: number; rows: { row: number; status: string; reasons: { code: string; note: string }[]; raw: Record<string, string> }[] };

async function uploadCsv(kind: string, file: File): Promise<Preview> {
  const fd = new FormData();
  fd.append("kind", kind);
  fd.append("file", file);
  const m = document.cookie.match(/(?:^|; )csrf=([^;]+)/);
  const res = await fetch("/api/imports", { method: "POST", credentials: "same-origin", headers: { "X-CSRF-Token": m ? decodeURIComponent(m[1]) : "" }, body: fd });
  const d = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof d.detail === "string" ? d.detail : "Upload failed");
  return d;
}

export default function ImportsPage() {
  const list = useSWR<Batch[]>("/imports", (p: string) => api<Batch[]>(p), { refreshInterval: (d) => (d?.some((b) => b.status === "running" || b.status === "uploaded") ? 2000 : 0) });
  const [kind, setKind] = useState<"linkedin" | "hr">("linkedin");
  const [prev, setPrev] = useState<Preview | null>(null);
  const [mapping, setMapping] = useState<Record<string, string | null>>({});
  const [prov, setProv] = useState("");
  const [region, setRegion] = useState("US");
  const [err, setErr] = useState("");
  const [note, setNote] = useState("");
  const [rowsFor, setRowsFor] = useState<string | null>(null);
  const [filter, setFilter] = useState("invalid");
  const [page, setPage] = useState(1);
  const rows = useSWR<Rows>(rowsFor ? `/imports/${rowsFor}/rows?status=${filter}&page=${page}&page_size=25` : null, (p: string) => api<Rows>(p));

  async function onFile(f: File) {
    setErr(""); setNote("");
    try { const p = await uploadCsv(kind, f); setPrev(p); setMapping(p.mapping); } catch (e) { setErr((e as Error).message); }
  }
  async function start() {
    if (!prev) return;
    setErr("");
    try {
      const r = await api<{ warning: string | null }>(`/imports/${prev.import_id}/start`, { body: { mapping, provenance: prov || undefined, region } });
      setNote(r.warning ?? "Import started. This page updates as it runs.");
      setPrev(null);
      list.mutate();
    } catch (e) { setErr((e as Error).message); }
  }

  return (
    <div className="mx-auto grid max-w-5xl gap-6">
      <header>
        <h1 className="text-xl font-semibold">Imports & data quality</h1>
        <p className="text-sm text-gray-600">Contacts you import are other people&apos;s data. Use them lawfully and honour opt-outs. Nothing is discarded silently: every row is kept with its status and reason.</p>
      </header>

      <section aria-labelledby="up" className="grid gap-3 rounded border p-4">
        <h2 id="up" className="font-medium">New import</h2>
        <fieldset className="flex gap-4 text-sm"><legend className="sr-only">File type</legend>
          <label><input type="radio" checked={kind === "linkedin"} onChange={() => { setKind("linkedin"); setPrev(null); }} /> LinkedIn connections export</label>
          <label><input type="radio" checked={kind === "hr"} onChange={() => { setKind("hr"); setPrev(null); }} /> HR / recruiter contacts</label>
        </fieldset>
        <label className="grid gap-1 text-sm">CSV file (up to 25 MB)<input type="file" accept=".csv,text/csv" onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])} /></label>
        {err && <p role="alert" className="text-sm text-red-700">{err}</p>}
        {note && <p role="status" className="text-sm">{note}</p>}

        {prev && (
          <div className="grid gap-3 text-sm">
            <p>Detected: {prev.encoding}, delimiter “{prev.delimiter === "\t" ? "tab" : prev.delimiter}”, header on line {prev.header_row + 1}, {prev.total_rows.toLocaleString()} rows.</p>
            {prev.warnings.map((w, i) => <p key={i} className="text-amber-800">{w}</p>)}
            <div className="grid gap-2 sm:grid-cols-2">
              {Object.keys(prev.mapping).map((f) => (
                <label key={f} className="grid gap-1">{f.replaceAll("_", " ")}
                  <select className="rounded border px-2 py-1" value={mapping[f] ?? ""} onChange={(e) => setMapping({ ...mapping, [f]: e.target.value || null })}>
                    <option value="">— not mapped —</option>
                    {prev.headers.filter(Boolean).map((h) => <option key={h}>{h}</option>)}
                  </select></label>
              ))}
            </div>
            {prev.unmapped.length > 0 && <p className="text-gray-600">Unused columns: {prev.unmapped.join(", ")}</p>}
            <div className="overflow-auto"><table className="min-w-full border text-xs"><caption className="sr-only">Preview of the first rows</caption>
              <thead><tr>{prev.headers.map((h, i) => <th key={i} className="border bg-gray-50 px-2 py-1 text-left">{h}</th>)}</tr></thead>
              <tbody>{prev.preview.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j} className="border px-2 py-1">{c}</td>)}</tr>)}</tbody></table></div>
            {kind === "hr" && prev.provenance_options && (
              <>
                <label className="grid gap-1">Where did this list come from? (required)
                  <select required className="rounded border px-2 py-1" value={prov} onChange={(e) => setProv(e.target.value)}>
                    <option value="">Choose…</option>
                    {Object.entries(prev.provenance_options).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select></label>
                {prov === "purchased" && <p role="alert" className="rounded bg-amber-100 p-2">Purchased or scraped lists often lack consent. Bulk sending is blocked for these contacts; you can only send one-off manual drafts. This is guidance, not legal advice.</p>}
                <label className="grid gap-1">Phone region (for numbers without a country code)<input className="w-20 rounded border px-2 py-1" maxLength={2} value={region} onChange={(e) => setRegion(e.target.value.toUpperCase())} /></label>
                <p className="text-xs text-gray-600">Phone numbers are stored for your manual reference only. This app never calls or texts anyone; local telemarketing rules still apply.</p>
              </>
            )}
            <button className="w-fit rounded bg-black px-3 py-1.5 text-white disabled:opacity-50" disabled={kind === "hr" && !prov} onClick={start}>Start import</button>
          </div>
        )}
      </section>

      <section aria-labelledby="hist">
        <h2 id="hist" className="mb-2 font-medium">Import history</h2>
        {list.data?.length === 0 && <p className="text-sm text-gray-600">No imports yet.</p>}
        <ul className="grid gap-2">
          {list.data?.map((b) => {
            const r = b.report as Record<string, number & Record<string, number>>;
            return (
              <li key={b.id} className="rounded border p-3 text-sm">
                <p className="font-medium">{b.filename} <span className="font-normal text-gray-600">({b.kind}{b.provenance ? `, ${b.provenance.replaceAll("_", " ")}` : ""})</span> · {b.status}</p>
                {r.read !== undefined && <p>Read {r.read} · valid {r.valid} · duplicates {r.duplicate} · invalid {r.invalid}{r.suppressed ? ` · suppressed ${r.suppressed}` : ""}{r.reviews ? ` · ${r.reviews} company matches to review` : ""}</p>}
                <button className="mt-1 underline" onClick={() => { setRowsFor(b.id); setPage(1); }}>Inspect rows</button>
              </li>
            );
          })}
        </ul>
      </section>

      {rowsFor && (
        <section aria-labelledby="rows" className="grid gap-2">
          <h2 id="rows" className="font-medium">Rows</h2>
          <label className="text-sm">Show <select className="rounded border px-2 py-1" value={filter} onChange={(e) => { setFilter(e.target.value); setPage(1); }}>
            {["invalid", "duplicate", "valid"].map((s) => <option key={s}>{s}</option>)}</select></label>
          {rows.data && (
            <>
              <table className="min-w-full border text-xs"><thead><tr className="bg-gray-50"><th className="border px-2 py-1 text-left">Line</th><th className="border px-2 py-1 text-left">Why</th><th className="border px-2 py-1 text-left">Original values</th></tr></thead>
                <tbody>{rows.data.rows.map((r) => <tr key={r.row}><td className="border px-2 py-1">{r.row}</td><td className="border px-2 py-1">{r.reasons.map((x) => x.note).join("; ") || "—"}</td><td className="border px-2 py-1">{Object.values(r.raw).join(" | ")}</td></tr>)}</tbody></table>
              <Pager page={page} pageSize={25} total={rows.data.total} onPage={setPage} />
            </>
          )}
        </section>
      )}
    </div>
  );
}
