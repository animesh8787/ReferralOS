"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import useSWR from "swr";
import Skeleton from "@/components/ui/Skeleton";
import { api } from "@/lib/api";

type Row = { requirement: string; type: string; term: string; importance: string; status: string; explanation: string };
type Comp = { points: number; weight: number; known: boolean; explanation: string };
type M = { computed: boolean; title: string; company: string; match_score: number; matrix: Row[]; match_components: Record<string, Comp>; priority_components: Record<string, Comp>;
  match_extra: { aligned_skills: string[]; missing_qualifications: string[]; to_verify: string[] }; analysis: { description_ok: boolean; note?: string; disqualifier_flags: string[] } };

const COLOR: Record<string, string> = { STRONG_EVIDENCE: "bg-ok-weak", PARTIAL_EVIDENCE: "bg-warn-weak", NEEDS_VERIFICATION: "bg-accent-weak", CONFLICTING_EVIDENCE: "bg-danger-weak", NO_EVIDENCE: "bg-surface-2" };
const nice = (s: string) => s.replaceAll("_", " ").toLowerCase();

export default function OpportunityDetail() {
  const { id } = useParams<{ id: string }>();
  const { data, error } = useSWR<M>(`/opportunities/${id}`, (p: string) => api<M>(p));
  if (error) return <p role="alert" className="text-danger">Not found.</p>;
  if (!data) return <Skeleton rows={5} />;
  if (!data.computed) return <p>This job has not been analysed yet. Use “Re-analyse my jobs” on the <Link className="underline" href="/opportunities">Opportunities</Link> page.</p>;
  const Breakdown = ({ title, c }: { title: string; c: Record<string, Comp> }) => (
    <section aria-label={title}><h2 className="font-medium">{title}</h2>
      <ul className="mt-1 grid gap-1 text-sm">{Object.entries(c).map(([k, v]) => <li key={k}><strong>{nice(k)}</strong>: {v.points.toFixed(1)} of {v.weight.toFixed(0)}{!v.known && <em> (unknown, handled by your missing-data policy)</em>}<br /><span className="text-muted">{v.explanation}</span></li>)}</ul></section>);
  return (
    <div className="grid max-w-4xl gap-5">
      <h1>{data.title} · {data.company}</h1>
      <p className="text-sm">Job Match Score <strong>{data.match_score.toFixed(0)}/100</strong>. This is an internal alignment estimate from your profile, not an ATS score and no guarantee of passing screening.</p>
      {data.analysis.disqualifier_flags.length > 0 && <p className="rounded bg-warn-weak p-2 text-sm">Worth checking in the posting: {data.analysis.disqualifier_flags.join("; ")}.</p>}
      <section aria-labelledby="mx"><h2 id="mx" className="font-medium">Requirement matrix</h2>
        {!data.analysis.description_ok && <p className="text-sm text-muted">{data.analysis.note}</p>}
        {data.matrix.length > 0 && <table className="mt-1 min-w-full border text-xs"><thead><tr className="bg-surface-2 text-left"><th className="border px-2 py-1">Requirement</th><th className="border px-2 py-1">Need</th><th className="border px-2 py-1">Your evidence</th><th className="border px-2 py-1">Why</th></tr></thead>
          <tbody>{data.matrix.map((r, i) => <tr key={i}><td className="border px-2 py-1">{r.term} <span className="text-muted">({nice(r.type)})</span></td><td className="border px-2 py-1">{r.importance}</td>
            <td className="border px-2 py-1"><span className={`rounded px-1 ${COLOR[r.status]}`}>{nice(r.status)}</span></td><td className="border px-2 py-1">{r.explanation}</td></tr>)}</tbody></table>}
        <p className="mt-1 text-xs text-muted">“No evidence” means nothing in your profile shows it, not that you lack the skill. Nothing from a job description is ever added to your resume without evidence.</p></section>
      <Breakdown title="Match score breakdown" c={data.match_components} />
      <Breakdown title="Priority score breakdown" c={data.priority_components} />
      {data.match_extra.to_verify.length > 0 && <p className="text-sm">To count these, confirm where you used them: {data.match_extra.to_verify.join(", ")}. <Link className="underline" href="/profile">Open profile</Link></p>}
    </div>
  );
}
