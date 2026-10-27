"use client";
import Link from "next/link";
import useSWR from "swr";
import Skeleton from "@/components/ui/Skeleton";
import { api } from "@/lib/api";

type V = { id: string; job_id: string; job_title: string; version: number; status: string; score: number; needs_confirmation: number; render_ok: boolean; created_at: string };

export default function Resumes() {
  const { data, error, isLoading } = useSWR<V[]>("/tailoring", (p: string) => api<V[]>(p));
  return (
    <div className="grid max-w-3xl gap-3">
      <h1>Tailored resumes</h1>
      <p className="text-sm text-muted">Each resume is built only from your confirmed profile. Start one from a job&apos;s page. Approved versions never change; edits make a new version.</p>
      {isLoading && <Skeleton rows={5} />}
      {error && <p role="alert" className="text-danger">Could not load resumes.</p>}
      {data?.length === 0 && <p className="text-sm text-muted">None yet. Open a job and choose “Tailor my resume”.</p>}
      <ul className="grid gap-2">{data?.map((v) => (
        <li key={v.id} className="rounded border p-3 text-sm"><Link className="font-medium underline" href={`/resumes/${v.id}`}>{v.job_title} · version {v.version}</Link>
          <span className={`ml-2 rounded px-2 py-0.5 text-xs ${v.status === "approved" ? "bg-ok-weak" : "bg-surface-2"}`}>{v.status}</span>
          <p>Alignment estimate {v.score.toFixed(0)}/100{v.needs_confirmation > 0 && <span className="text-warn"> · {v.needs_confirmation} claim(s) need your confirmation</span>}{!v.render_ok && <span className="text-danger"> · render check failed</span>}</p></li>))}</ul>
    </div>
  );
}
