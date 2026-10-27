"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import useSWR from "swr";
import Notice from "@/components/ui/Notice";
import Skeleton from "@/components/ui/Skeleton";
import { api } from "@/lib/api";

type Claim = { id: string; kind: string; text: string; status: string; reasons: string[] };
type Bullet = { claim_id: string; text: string };
type R = { id: string; job_id: string; version: number; parent_id: string | null; status: string; score: number; ok_to_approve: boolean;
  content: { experience: { claim_id: string; title: string; organization: string; start: string; end: string; bullets: Bullet[] }[];
    projects: { claim_id: string; name: string; bullets: Bullet[] }[]; skills: { group: string; items: { name: string }[] }[]; summary: { sentences: { text: string }[] } | null; section_order: string[] };
  ledger: Claim[]; validation: { claims_total: number; validated: number; needs_confirmation: { claim_id: string; text: string; reasons: string[] }[]; excluded: { claim_id: string; text: string; reasons: string[] }[];
    unresolved_contradictions: { item_id: string; section: string }[]; render_check: { ok: boolean; problems: string[] } };
  score_detail: { label: string; components: Record<string, { points: number; weight: number; known: boolean; explanation: string }>; improvements: { type: string; term: string | null; action: string; est_gain: number }[] };
  changes: { experience: { role: string; bullets_kept: number; bullets_in_master: number }[]; projects_left_out: string[]; unsupported_requirements: { term: string; status: string; why: string }[]; skills_listed_first: string[] };
  questions: { text: string }[]; files: string[] };
type V = { id: string; version: number; status: string; score: number };
const nice = (s: string) => s.replaceAll("_", " ").toLowerCase();

export default function Workspace() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { data: r, error, mutate } = useSWR<R>(`/tailoring/${id}`, (p: string) => api<R>(p));
  const versions = useSWR<V[]>(r ? `/tailoring?job_id=${r.job_id}` : null, (p: string) => api<V[]>(p));
  const [edit, setEdit] = useState<{ id: string; text: string } | null>(null);
  const [msg, setMsg] = useState("");
  if (error) return <Notice kind="err">Resume not found.</Notice>;
  if (!r) return <Skeleton rows={5} />;
  const status = new Map(r.ledger.map((c) => [c.id, c]));

  async function act(label: string, fn: () => Promise<{ id?: string }>) {
    setMsg("");
    try { const res = await fn(); setMsg(label); if (res.id && res.id !== id) router.push(`/resumes/${res.id}`); else { mutate(); versions.mutate(); } } catch (e) { setMsg((e as Error).message); }
  }
  const BulletRow = ({ b }: { b: Bullet }) => {
    const c = status.get(b.claim_id);
    return (
      <li className="card px-3 py-2">
        {edit?.id === b.claim_id ? (
          <form className="grid gap-1" onSubmit={(e) => { e.preventDefault(); act("Saved as a new version.", () => api(`/tailoring/${id}`, { method: "PATCH", body: { bullet_edits: [{ claim_id: b.claim_id, text: edit.text }] } })); }}>
            <textarea aria-label="Edit bullet" className="rounded border px-2 py-1" rows={2} value={edit.text} onChange={(e) => setEdit({ id: edit.id, text: e.target.value })} />
            <span className="flex gap-2"><button className="rounded bg-black px-2 py-0.5 text-white">Save as new version</button><button type="button" className="underline" onClick={() => setEdit(null)}>Cancel</button></span>
          </form>
        ) : (<>
          {b.text}
          <span className="ml-2 whitespace-nowrap text-xs">
            <button className="underline" onClick={() => setEdit({ id: b.claim_id, text: b.text })}>Edit</button>{" · "}
            <button className="text-danger underline" onClick={() => act("Removed in a new version.", () => api(`/tailoring/${id}`, { method: "PATCH", body: { exclude_claims: [b.claim_id] } }))}>Remove</button>
          </span>
          {c?.status === "needs_confirmation" && <p className="text-xs text-warn">Needs your confirmation: {c.reasons.join(" ")}{" "}
            <button className="underline" onClick={() => act("Added to your profile as a confirmed fact; new version created.", () => api(`/tailoring/${id}/confirm-claim`, { body: { claim_id: b.claim_id } }))}>This is true: add to my profile</button></p>}
        </>)}
      </li>
    );
  };

  return (
    <div className="grid gap-4">
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div><h1>Resume workspace · version {r.version} <span className={`badge align-middle ${r.status === "approved" ? "badge-ok" : "badge-muted"}`}>{r.status}</span></h1>
          <p className="text-sm"><Link className="underline" href={`/jobs/${r.job_id}`}>View the job</Link> · Alignment estimate <strong>{r.score.toFixed(0)}/100</strong></p>
          <p className="text-xs text-muted">{r.score_detail.label}</p></div>
        <div className="flex flex-wrap gap-2 text-sm">
          <button disabled={r.status === "approved" || !r.ok_to_approve} className="rounded bg-black px-3 py-1.5 text-white disabled:opacity-40" onClick={() => act("Approved. This version is now locked.", () => api(`/tailoring/${id}/approve`, { body: {} }))}>Approve this version</button>
          <button className="rounded border px-3 py-1.5" onClick={() => act("Regenerated as a new version.", () => api(`/tailoring/${id}/regenerate`, { body: {} }))}>Regenerate</button>
        </div>
      </header>
      {msg && !msg.startsWith("---") && <Notice>{msg}</Notice>}
      {r.status === "approved" && <Notice kind="ok">Approved versions never change. Any edit or regeneration creates a new version.</Notice>}
      {!r.validation.render_check.ok && <Notice kind="err">File check failed: {r.validation.render_check.problems.join("; ")}</Notice>}

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="grid content-start gap-4 text-sm">
          <section aria-labelledby="val" className="card p-4"><h2 id="val" className="eyebrow mb-2">Claim check</h2>
            <p>{r.validation.validated} of {r.validation.claims_total} statements are supported by your profile.</p>
            {r.validation.needs_confirmation.length > 0 && <p className="text-warn">{r.validation.needs_confirmation.length} need your confirmation before approval.</p>}
            {r.validation.unresolved_contradictions.length > 0 && <p className="text-danger">{r.validation.unresolved_contradictions.length} profile entries with unresolved conflicts were left out. <Link className="underline" href="/profile">Resolve them</Link></p>}
            {r.validation.excluded.length > 0 && <details><summary className="cursor-pointer">Left out ({r.validation.excluded.length})</summary><ul className="list-disc pl-5">{r.validation.excluded.map((c) => <li key={c.claim_id}>{c.text}: {c.reasons.join(" ")}</li>)}</ul></details>}</section>

          <section aria-labelledby="cov" className="card p-4"><h2 id="cov" className="eyebrow mb-2">Requirements your background does not support yet</h2>
            {r.changes.unsupported_requirements.length === 0 ? <p>None.</p> : <ul className="list-disc pl-5">{r.changes.unsupported_requirements.map((u, i) => <li key={i}><strong>{u.term}</strong> ({nice(u.status)}): {u.why}</li>)}</ul>}
            <p className="text-xs text-muted">These are never added to the resume automatically.</p></section>

          <section aria-labelledby="sc" className="card p-4"><h2 id="sc" className="eyebrow mb-2">Why this score</h2>
            <ul className="grid gap-1">{Object.entries(r.score_detail.components).map(([k, v]) => <li key={k}><strong>{nice(k)}</strong>: {v.points.toFixed(1)} of {v.weight.toFixed(0)}{!v.known && <em> (unknown)</em>}<br /><span className="text-muted">{v.explanation}</span></li>)}</ul>
            {r.score_detail.improvements.length > 0 && <><h3 className="mt-2 font-medium">What could raise it (only if true)</h3><ul className="list-disc pl-5">{r.score_detail.improvements.map((t, i) => <li key={i}>{t.action}{t.est_gain > 0 && <span className="text-muted"> (up to about +{t.est_gain})</span>}</li>)}</ul></>}</section>

          {r.questions.length > 0 && <section aria-labelledby="q" className="card p-4"><h2 id="q" className="eyebrow mb-2">Questions for you</h2><ul className="list-disc pl-5">{r.questions.map((q, i) => <li key={i}>{q.text}</li>)}</ul></section>}

          <section aria-labelledby="chg" className="card p-4"><h2 id="chg" className="eyebrow mb-2">Changes from your master resume</h2>
            <ul className="list-disc pl-5"><li>Skills listed first: {r.changes.skills_listed_first.slice(0, 6).join(", ") || "none"}</li>
              {r.changes.experience.map((e, i) => <li key={i}>{e.role}: kept {e.bullets_kept} of {e.bullets_in_master} bullets (wording unchanged)</li>)}
              {r.changes.projects_left_out.length > 0 && <li>Left out as less relevant: {r.changes.projects_left_out.join(", ")}</li>}</ul>
            <p className="text-xs text-muted">Your master profile was not changed.</p></section>

          <section aria-labelledby="dl" className="card p-4"><h2 id="dl" className="eyebrow mb-2">Downloads</h2>
            <ul className="flex flex-wrap gap-3">{r.files.map((f) => <li key={f}><a className="underline" href={`/api/tailoring/${id}/files/${f}`}>{f}</a></li>)}<li><a className="underline" href={`/api/tailoring/${id}/bundle.zip`}>all (zip)</a></li></ul></section>

          <section aria-labelledby="ver" className="card p-4"><h2 id="ver" className="eyebrow mb-2">Versions</h2>
            <ul className="grid gap-1">{versions.data?.map((v) => <li key={v.id}>{v.id === id ? <strong>v{v.version} (viewing)</strong> : <Link className="underline" href={`/resumes/${v.id}`}>v{v.version}</Link>} · {v.status} · {v.score.toFixed(0)}/100
              {v.id !== id && <> · <button className="underline" onClick={async () => { const c = await api<{ text_diff: string }>(`/tailoring/${id}/compare/${v.id}`); setMsg(c.text_diff || "No text differences."); }}>compare</button></>}</li>)}</ul>
            {msg.startsWith("---") && <pre className="mt-1 max-h-60 overflow-auto rounded bg-surface-2 p-2 text-xs">{msg}</pre>}</section>
        </div>

        <div className="grid content-start gap-4">
          <section aria-labelledby="pv" className="card p-4"><h2 id="pv" className="eyebrow mb-2">Live preview</h2>
            <iframe title="PDF preview" className="h-[640px] w-full rounded border" src={`/api/tailoring/${id}/files/resume.pdf?inline=true#toolbar=0`} /></section>
          <section aria-labelledby="ed" className="text-sm"><h2 id="ed" className="font-medium">Edit text</h2>
            {r.content.summary && <p className="mb-2 rounded border p-2"><strong>Summary:</strong> {r.content.summary.sentences.map((s) => s.text).join(" ")}</p>}
            {r.content.experience.map((e) => <div key={e.claim_id} className="mb-2"><p className="font-medium">{e.title}, {e.organization}</p><ul className="grid gap-1">{e.bullets.map((b) => <BulletRow key={b.claim_id} b={b} />)}</ul></div>)}
            {r.content.projects.map((p) => <div key={p.claim_id} className="mb-2"><p className="font-medium">{p.name}</p><ul className="grid gap-1">{p.bullets.map((b) => <BulletRow key={b.claim_id} b={b} />)}</ul></div>)}
            <p className="text-xs text-muted">Wording that adds a technology or number not in your profile is flagged and must be confirmed before it can be approved.</p></section>
        </div>
      </div>
    </div>
  );
}
