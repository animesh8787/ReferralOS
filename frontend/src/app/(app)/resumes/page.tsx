"use client";
import Link from "next/link";
import useSWR from "swr";
import { FileText } from "lucide-react";
import EmptyState from "@/components/ui/EmptyState";
import Notice from "@/components/ui/Notice";
import PageHeader from "@/components/ui/PageHeader";
import Skeleton from "@/components/ui/Skeleton";
import { api } from "@/lib/api";

type V = { id: string; job_id: string; job_title: string; version: number; status: string; score: number; needs_confirmation: number; render_ok: boolean; created_at: string };

export default function Resumes() {
  const { data, error, isLoading } = useSWR<V[]>("/tailoring", (p: string) => api<V[]>(p));
  return (
    <div className="grid max-w-3xl gap-4">
      <PageHeader title="Tailored resumes" sub="Each resume is built only from your confirmed profile. Start one from a job's page. Approved versions never change; edits make a new version." />
      {isLoading && <Skeleton rows={5} />}
      {error && <Notice kind="err">Could not load resumes.</Notice>}
      {data?.length === 0 && <EmptyState icon={FileText} title="No tailored resumes yet" sub="Open a job and choose “Tailor my resume”." />}
      <ul className="grid gap-2">{data?.map((v) => (
        <li key={v.id} className="card glare grid gap-1 p-3"><Link className="font-medium underline" href={`/resumes/${v.id}`}>{v.job_title} · version {v.version}</Link>
          <span className={`badge ml-2 ${v.status === "approved" ? "badge-ok" : "badge-muted"}`}>{v.status}</span>
          <p>Alignment estimate {v.score.toFixed(0)}/100{v.needs_confirmation > 0 && <span className="text-warn"> · {v.needs_confirmation} claim(s) need your confirmation</span>}{!v.render_ok && <span className="text-danger"> · render check failed</span>}</p></li>))}</ul>
    </div>
  );
}
