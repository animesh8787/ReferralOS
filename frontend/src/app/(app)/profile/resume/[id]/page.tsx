"use client";
import { useParams } from "next/navigation";
import useSWR from "swr";
import ProvenanceBadges, { Item } from "@/components/ProvenanceBadge";
import { api } from "@/lib/api";

type Detail = { filename: string; status: string; raw_text: string | null; parse_info: { warnings?: string[]; error?: string; rejected?: unknown[] };
  items: (Item & { span: { start: number; end: number } | null })[] };

export default function ResumeReview() {
  const { id } = useParams<{ id: string }>();
  const { data, error } = useSWR<Detail>(`/resumes/${id}`, (p: string) => api<Detail>(p));
  if (error) return <p role="alert" className="text-red-700">Resume not found.</p>;
  if (!data) return <p role="status">Loading…</p>;
  const text = data.raw_text ?? "";
  return (
    <div className="grid gap-4">
      <h1 className="text-xl font-semibold">Extracted vs original: {data.filename}</h1>
      {data.parse_info.warnings?.map((w, i) => <p key={i} role="alert" className="rounded bg-amber-100 p-2 text-sm">{w}</p>)}
      {data.parse_info.error && <p role="alert" className="text-red-700">{data.parse_info.error}</p>}
      <div className="grid gap-4 md:grid-cols-2">
        <section aria-labelledby="orig"><h2 id="orig" className="mb-1 font-medium">Original text</h2>
          <pre className="max-h-[70vh] overflow-auto whitespace-pre-wrap rounded border bg-gray-50 p-3 text-xs">{text || "No text extracted."}</pre></section>
        <section aria-labelledby="ext"><h2 id="ext" className="mb-1 font-medium">What we extracted</h2>
          <ul className="grid max-h-[70vh] gap-2 overflow-auto">
            {data.items.map((i) => (
              <li key={i.id} className="rounded border p-2 text-sm">
                <p className="font-medium">{i.section}</p>
                <ProvenanceBadges item={i} />
                {i.span && text && <p className="mt-1 whitespace-pre-wrap text-xs text-gray-600">“{text.slice(i.span.start, i.span.end).trim().slice(0, 200)}”</p>}
              </li>
            ))}
          </ul></section>
      </div>
    </div>
  );
}
