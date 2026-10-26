"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import useSWR from "swr";
import CopyButton from "@/components/CopyButton";
import { api } from "@/lib/api";

type Block = { code: string; detail: string };
type M = { id: string; channel: string; kind: string; to_name: string | null; to_email: string | null; to_linkedin_url: string | null; company: string | null; job_title: string | null;
  job_status: string | null; subject: string | null; body: string; connect_note: string | null; subject_options: string[]; variants: Record<string, { subject?: string; body: string }>;
  risk_flags: { code: string; severity?: string; detail: string }[]; content_blocks: Block[]; warnings: Block[]; can_approve: boolean; approval_state: string; send_state: string; pair_status: string;
  last_block: Block[]; stale: boolean; stale_reason: string | null; mailto: string | null; mailto_too_long: boolean; attach_resume_id: string | null;
  ledger: { label: string; text: string; status: string; reasons: string[] }[]; region_guidance: { text: string; disclaimer: string; requires_extra_ack: boolean } | null };
type Ev = { id: string; type: string; label: string | null; confirmed: boolean | null; detail: Record<string, unknown>; at: string };

export default function MessagePage() {
  const { id } = useParams<{ id: string }>();
  const { data: m, mutate, error } = useSWR<M>(`/outreach/messages/${id}`, (p: string) => api<M>(p));
  const events = useSWR<Ev[]>(`/outreach/messages/${id}/events`, (p: string) => api<Ev[]>(p));
  const [subject, setSubject] = useState<string | null>(null);
  const [body, setBody] = useState<string | null>(null);
  const [reply, setReply] = useState("");
  const [msg, setMsg] = useState("");
  if (error) return <p role="alert" className="text-red-700">Message not found.</p>;
  if (!m) return <p role="status">Loading…</p>;
  const sent = ["sent", "manual_sent", "sending", "delivery_unconfirmed"].includes(m.send_state);
  const dirty = (subject !== null && subject !== m.subject) || (body !== null && body !== m.body);
  const act = async (fn: () => Promise<unknown>, ok: string) => { setMsg(""); try { await fn(); setMsg(ok); setSubject(null); setBody(null); mutate(); events.mutate(); } catch (e) { setMsg((e as Error).message); } };

  return (
    <div className="mx-auto grid max-w-4xl gap-4 text-sm">
      <header><h1 className="text-xl font-semibold">{m.kind.replace("_", " ")} to {m.to_name ?? m.to_email}</h1>
        <p>{m.company} · {m.job_title ?? "no specific job"} {m.job_status && `(${m.job_status})`} · {m.channel === "linkedin" ? "LinkedIn, sent by you" : "Email"}</p>
        <p className="text-gray-600">Approval: <strong>{m.approval_state.replace("_", " ")}</strong> · Delivery: <strong>{m.send_state.replace("_", " ")}</strong> · Pipeline: {m.pair_status}</p></header>
      {m.stale && <p role="alert" className="rounded bg-red-50 p-2 text-red-800">{m.stale_reason}</p>}
      {m.content_blocks.length > 0 && <section aria-label="Must fix before approval" className="rounded border border-red-300 bg-red-50 p-3"><h2 className="font-medium text-red-900">Fix before approving</h2><ul className="list-disc pl-5">{m.content_blocks.map((b, i) => <li key={i}><strong>{b.code.replaceAll("_", " ")}</strong>: {b.detail}</li>)}</ul></section>}
      {m.last_block?.length > 0 && <p className="rounded bg-amber-50 p-2">Last send attempt: {m.last_block.map((b) => `${b.code}: ${b.detail}`).join("; ")}</p>}
      {m.risk_flags.length > 0 && <section aria-label="Risk flags"><h2 className="font-medium">Things to know</h2><ul className="list-disc pl-5">{m.risk_flags.map((f, i) => <li key={i} className={f.severity === "high" ? "text-red-800" : ""}>{f.detail}</li>)}</ul></section>}
      {m.region_guidance?.requires_extra_ack && <p className="rounded bg-amber-50 p-2">{m.region_guidance.text} {m.region_guidance.disclaimer}</p>}

      {m.channel === "email" && (
        <section aria-labelledby="sj"><h2 id="sj" className="font-medium">Subject</h2>
          <input aria-label="Subject" disabled={sent} className="w-full rounded border px-2 py-1" value={subject ?? m.subject ?? ""} onChange={(e) => setSubject(e.target.value)} />
          <div className="mt-1 flex flex-wrap gap-2">{m.subject_options.map((o) => <button key={o} disabled={sent} className="rounded border px-2 py-0.5 text-xs" onClick={() => setSubject(o)}>{o}</button>)}</div></section>)}
      <section aria-labelledby="bd"><div className="flex items-center justify-between"><h2 id="bd" className="font-medium">Message</h2>
        <span className="flex gap-2">{Object.keys(m.variants).map((v) => <button key={v} disabled={sent} className="rounded border px-2 py-0.5 text-xs" onClick={() => act(() => api(`/outreach/messages/${id}`, { method: "PATCH", body: { variant: v } }), `Switched to version ${v}.`)}>Use version {v}</button>)}
          <CopyButton text={body ?? m.body} label="Copy message" />{m.connect_note && <CopyButton text={m.connect_note} label="Copy connection note" />}</span></div>
        <textarea aria-label="Message body" disabled={sent} rows={14} className="mt-1 w-full rounded border px-2 py-1 font-mono text-xs" value={body ?? m.body} onChange={(e) => setBody(e.target.value)} />
        {m.connect_note && <p className="mt-1 text-xs text-gray-600">Connection note ({m.connect_note.length}/300): {m.connect_note}</p>}
        {dirty && <button className="mt-1 rounded bg-black px-3 py-1 text-white" onClick={() => act(() => api(`/outreach/messages/${id}`, { method: "PATCH", body: { subject, body } }), "Saved. Any earlier approval was withdrawn: approve again to use this text.")}>Save changes</button>}
        {m.attach_resume_id && <p className="mt-1 text-xs">Your approved tailored resume (PDF) will be attached. <button className="underline" onClick={() => act(() => api(`/outreach/messages/${id}`, { method: "PATCH", body: { detach_resume: true } }), "Resume detached.")}>Don&apos;t attach</button></p>}</section>

      <section aria-labelledby="sup"><h2 id="sup" className="font-medium">What this message claims about you</h2>
        <ul className="list-disc pl-5">{m.ledger.map((c, i) => <li key={i}>{c.text} <em className={c.status === "validated" ? "text-green-800" : "text-red-800"}>({c.status.replace("_", " ")} against your profile)</em></li>)}{m.ledger.length === 0 && <li className="list-none text-gray-600">No factual claims about your background.</li>}</ul></section>

      <div className="flex flex-wrap items-center gap-2">
        {!sent && m.approval_state !== "approved" && <button disabled={!m.can_approve || dirty} className="rounded bg-black px-3 py-1.5 text-white disabled:opacity-40" onClick={() => act(() => api(`/outreach/messages/${id}/approve`, { body: {} }), "Approved.")}>Approve</button>}
        {!sent && <button className="rounded border px-3 py-1.5" onClick={() => act(() => api(`/outreach/messages/${id}/reject`, { body: {} }), "Rejected.")}>Reject</button>}
        {m.to_linkedin_url && <a className="underline" href={m.to_linkedin_url} target="_blank" rel="noopener noreferrer">Open LinkedIn profile</a>}
        {m.channel === "email" && m.mailto && !m.mailto_too_long && <a className="underline" href={m.mailto}>Open in my email app</a>}
        {m.channel === "email" && <a className="underline" href={`/api/outreach/messages/${id}/eml`}>Download .eml</a>}
        {m.approval_state === "approved" && !sent && m.send_state === "manual_pending" && <button className="rounded border px-3 py-1.5" onClick={() => act(() => api(`/outreach/messages/${id}/mark-sent`, { body: {} }), "Marked as sent.")}>I sent this myself</button>}
      </div>
      {m.mailto_too_long && <p className="text-xs text-gray-600">This message is too long for a mail link; use the .eml download or copy it.</p>}

      {m.send_state === "delivery_unconfirmed" && (
        <section aria-labelledby="uc" className="rounded border border-red-300 p-3"><h2 id="uc" className="font-medium">We could not confirm this was delivered</h2>
          <p>It will <strong>not</strong> be re-sent automatically. Check your Sent folder, or let us look.</p>
          <div className="mt-1 flex gap-2"><button className="rounded border px-2 py-1" onClick={async () => { const r = await api<{ note: string }>(`/outreach/messages/${id}/reconcile`, { body: {} }); setMsg(r.note); mutate(); }}>Look in Sent mail</button>
            <button className="rounded border px-2 py-1" onClick={() => act(() => api(`/outreach/messages/${id}/resolve`, { body: { outcome: "sent" } }), "Recorded as sent.")}>It was delivered</button>
            <button className="rounded border px-2 py-1" onClick={() => act(() => api(`/outreach/messages/${id}/resolve`, { body: { outcome: "not_sent" } }), "Moved back to review. Nothing was queued.")}>It was not delivered</button></div></section>)}

      {sent && (
        <section aria-labelledby="rp"><h2 id="rp" className="font-medium">Record a reply</h2>
          <textarea aria-label="Reply text" rows={3} className="w-full rounded border px-2 py-1" placeholder="Paste their reply or bounce notice" value={reply} onChange={(e) => setReply(e.target.value)} />
          <button disabled={!reply.trim()} className="mt-1 rounded border px-3 py-1 disabled:opacity-40" onClick={() => act(async () => { const r = await api<{ label: string; needs_confirmation: string | null }>(`/outreach/messages/${id}/reply`, { body: { body: reply, from_addr: m.to_email ?? "" } }); setReply(""); setMsg(`Recorded as: ${r.label.replace("_", " ")}. ${r.needs_confirmation ?? ""}`); }, "Reply recorded.")}>Record reply</button></section>)}

      <section aria-labelledby="ev"><h2 id="ev" className="font-medium">History</h2>
        <ul className="grid gap-1 text-xs">{events.data?.map((e) => <li key={e.id} className="rounded border px-2 py-1">{new Date(e.at + "Z").toLocaleString()} · <strong>{e.type.replaceAll("_", " ")}</strong>{e.label && ` (${e.label.replace("_", " ")})`}
          {e.type === "UNSUBSCRIBE_REQUESTED" && e.confirmed === null && <span> · <button className="underline" onClick={() => act(() => api(`/outreach/events/${e.id}/confirm`, { body: { confirmed: true } }), "Added to your do-not-contact list.")}>Yes, stop contacting them</button> · <button className="underline" onClick={() => act(() => api(`/outreach/events/${e.id}/confirm`, { body: { confirmed: false } }), "Dismissed.")}>No, this isn&apos;t an opt-out</button></span>}</li>)}</ul></section>
      {msg && <p role="status">{msg}</p>}
      <p><Link className="underline" href="/outreach">Back to outreach</Link></p>
    </div>
  );
}
