"use client";
import Link from "next/link";
import useSWR from "swr";
import { api } from "@/lib/api";

type V = { id: string; job_id: string; job_title: string; version: number; status: string; score: number; needs_confirmation: number; render_ok: boolean; created_at: string };

export default function Resumes() {
  const { data, error, isLoading } = useSWR<V[]>("/tailoring", (p: string) => api<V[]>(p));
  return (
    <div className="mx-auto grid max-w-3xl gap-3">
      <h1 className="text-xl font-semibold">Tailored resumes</h1>
      <p className="text-sm text-gray-600">Each resume is built only from your confirmed profile. Start one from a job&apos;s page. Approved versions never change; edits make a new version.</p>
      {isLoading && <p role="status">Loading…</p>}
      {error && <p role="alert" className="text-red-700">Could not load resumes.</p>}
      {data?.length === 0 && <p className="text-sm text-gray-600">None yet. Open a job and choose “Tailor my resume”.</p>}
      <ul className="grid gap-2">{data?.map((v) => (
        <li key={v.id} className="rounded border p-3 text-sm"><Link className="font-medium underline" href={`/resumes/${v.id}`}>{v.job_title} · version {v.version}</Link>
          <span className={`ml-2 rounded px-2 py-0.5 text-xs ${v.status === "approved" ? "bg-green-100" : "bg-gray-100"}`}>{v.status}</span>
          <p>Alignment estimate {v.score.toFixed(0)}/100{v.needs_confirmation > 0 && <span className="text-amber-800"> · {v.needs_confirmation} claim(s) need your confirmation</span>}{!v.render_ok && <span className="text-red-700"> · render check failed</span>}</p></li>))}</ul>
    </div>
  );
}
