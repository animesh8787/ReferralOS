"use client";
import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";
import { api } from "@/lib/api";

type Flag = { code: string; severity?: string; detail: string };
type Msg = { id: string; channel: string; kind: string; to_name: string | null; to_email: string | null; to_linkedin_url: string | null; company: string | null; job_title: string | null;
  job_status: string | null; match_score: number | null; contact_score: number | null; subject: string | null; preview: string; risk_flags: Flag[]; approval_state: string; send_state: string;
  pair_status: string; content_blocks: { code: string; detail: string }[]; can_approve: boolean; last_block: { code: string; detail: string }[]; stale: boolean; batch_id: string | null };
type Page = { total: number; items: Msg[] };
type Settings = { delivery_mode: string; global_pause: boolean; daily_limit: number; lawful_use_ack: string | null; gmail: { connected: boolean } };
type Audit = { total: number; items: { at: string; action: string; detail: Record<string, unknown> }[] };

const TABS = ["Review", "Manual-send queue", "Sending", "Activity"] as const;

export default function Outreach() {
  const [tab, setTab] = useState<(typeof TABS)[number]>("Review");
  const [sel, setSel] = useState<string[]>([]);
  const [msg, setMsg] = useState("");
  const [confirm, setConfirm] = useState<{ count: number; limit: number } | null>(null);
  const review = useSWR<Page>("/outreach/messages?approval_state=awaiting_approval&page_size=100", (p: string) => api<Page>(p));
  const queue = useSWR<Page>(tab === "Manual-send queue" ? "/outreach/messages?send_state=manual_pending&page_size=100" : null, (p: string) => api<Page>(p));
  const sending = useSWR<Page>(tab === "Sending" ? "/outreach/messages?approval_state=approved&page_size=100" : null, (p: string) => api<Page>(p));
  const cfg = useSWR<Settings>("/outreach/settings", (p: string) => api<Settings>(p));
  const audit = useSWR<Audit>(tab === "Activity" ? "/me/audit?page_size=60" : null, (p: string) => api<Audit>(p));
  const refresh = () => { review.mutate(); queue.mutate(); sending.mutate(); cfg.mutate(); };

  async function run(fn: () => Promise<unknown>, ok: string) {
    setMsg("");
    try { await fn(); setMsg(ok); refresh(); setSel([]); setConfirm(null); } catch (e) { setMsg((e as Error).message); }
  }
  async function approveSelected() {
    const ids = sel.length ? sel : (review.data?.items ?? []).filter((m) => m.can_approve).map((m) => m.id);
    if (ids.length > 1 && (!confirm || confirm.count !== ids.length)) { setConfirm({ count: 0, limit: 0 }); return; }
    run(() => api("/outreach/approve", { body: { message_ids: ids, scope: "selected", confirm_count: confirm?.count, confirm_daily_limit: confirm?.limit } }), `Approved ${ids.length} message(s).`);
  }
  const items = review.data?.items ?? [];
  const approvable = (sel.length ? items.filter((m) => sel.includes(m.id)) : items.filter((m) => m.can_approve)).length;
  const toggle = (id: string) => setSel(sel.includes(id) ? sel.filter((x) => x !== id) : [...sel, id]);

  return (
    <div className="mx-auto grid max-w-6xl gap-4">
      <header className="flex flex-wrap items-end justify-between gap-2">
        <div><h1 className="text-xl font-semibold">Outreach</h1>
          <p className="text-sm text-gray-600">Nothing is sent until you approve it. LinkedIn messages are never sent by this app: you copy them and send them yourself.</p></div>
        <div className="flex items-center gap-2 text-sm">
          <Link className="underline" href="/outreach/settings">Settings and Gmail</Link><Link className="underline" href="/suppression">Do-not-contact list</Link>
          <button className={`rounded border px-3 py-1 ${cfg.data?.global_pause ? "bg-red-100" : ""}`} onClick={() => run(() => api("/outreach/pause", { body: { paused: !cfg.data?.global_pause } }), cfg.data?.global_pause ? "Sending resumed." : "All sending paused.")}>
            {cfg.data?.global_pause ? "Resume all sending" : "Pause all sending"}</button>
        </div>
      </header>
      {cfg.data && !cfg.data.lawful_use_ack && <p role="alert" className="rounded bg-amber-100 p-2 text-sm">Before anything can be sent, read and acknowledge the lawful-use statement in <Link className="underline" href="/outreach/settings">Settings</Link>.</p>}
      {msg && <p role="status" className="text-sm">{msg}</p>}
      <div role="tablist" aria-label="Outreach sections" className="flex flex-wrap gap-2">{TABS.map((t) => <button key={t} role="tab" aria-selected={tab === t} className={`rounded border px-3 py-1 text-sm ${tab === t ? "bg-black text-white" : ""}`} onClick={() => setTab(t)}>{t}</button>)}</div>

      {tab === "Review" && (
        <section aria-labelledby="rv">
          <div className="mb-2 flex flex-wrap items-center gap-2"><h2 id="rv" className="font-medium">I prepared {review.data?.total ?? 0} messages for you to review</h2>
            <button className="rounded bg-black px-3 py-1 text-sm text-white" onClick={() => run(async () => { const r = await api<{ messages: string[]; skipped: { why: string }[] }>("/outreach/generate", { body: {} }); setMsg(`${r.messages.length} drafted, ${r.skipped.length} skipped.`); }, "Batch prepared.")}>Prepare a new batch</button>
            <button disabled={approvable === 0} className="rounded border px-3 py-1 text-sm disabled:opacity-40" onClick={approveSelected}>Approve {sel.length ? "selected" : "all ready"} ({approvable})</button></div>
          {confirm && (
            <form className="mb-2 grid gap-2 rounded border border-amber-300 bg-amber-50 p-3 text-sm" onSubmit={(e) => { e.preventDefault(); approveSelected(); }}>
              <p>To approve <strong>{approvable}</strong> messages, type the number of messages and your daily sending limit ({cfg.data?.daily_limit}) to confirm.</p>
              <label className="flex items-center gap-2">Messages <input required type="number" className="w-24 rounded border px-2 py-1" onChange={(e) => setConfirm({ ...confirm, count: Number(e.target.value) })} /></label>
              <label className="flex items-center gap-2">Daily limit <input required type="number" className="w-24 rounded border px-2 py-1" onChange={(e) => setConfirm({ ...confirm, limit: Number(e.target.value) })} /></label>
              <button className="w-fit rounded bg-black px-3 py-1 text-white">Confirm and approve</button></form>)}
          {items.length === 0 && <p className="text-sm text-gray-600">Nothing waiting. Prepare a batch from your best verified jobs, or add jobs and contacts first.</p>}
          {items.length > 0 && (
            <div className="overflow-auto"><table className="min-w-full border text-xs"><caption className="sr-only">Messages waiting for your approval</caption>
              <thead><tr className="bg-gray-50 text-left">{["", "To", "Channel", "Company · job", "Job status", "Match", "Contact", "Subject / preview", "Risk", ""].map((h, i) => <th key={i} className="border px-2 py-1">{h}</th>)}</tr></thead>
              <tbody>{items.map((m) => (
                <tr key={m.id} className={m.stale ? "bg-red-50" : ""}>
                  <td className="border px-2 py-1"><input type="checkbox" aria-label={`Select ${m.to_name}`} checked={sel.includes(m.id)} onChange={() => toggle(m.id)} /></td>
                  <td className="border px-2 py-1">{m.to_name ?? m.to_email}<br /><span className="text-gray-500">{m.to_email}</span></td>
                  <td className="border px-2 py-1">{m.channel === "linkedin" ? "LinkedIn (manual)" : "Email"}<br /><span className="text-gray-500">{m.kind.replace("_", " ")}</span></td>
                  <td className="border px-2 py-1">{m.company}<br /><span className="text-gray-500">{m.job_title ?? "no specific job"}</span></td>
                  <td className="border px-2 py-1">{m.job_status ?? "—"}{m.stale && <strong className="block text-red-700">stale</strong>}</td>
                  <td className="border px-2 py-1">{m.match_score?.toFixed(0) ?? "—"}</td><td className="border px-2 py-1">{m.contact_score?.toFixed(0) ?? "—"}</td>
                  <td className="max-w-xs border px-2 py-1"><strong>{m.subject}</strong><br />{m.preview}…</td>
                  <td className="border px-2 py-1">{[...m.content_blocks.map((b) => `⛔ ${b.code}`), ...m.risk_flags.map((f) => f.code)].join(", ") || "—"}</td>
                  <td className="border px-2 py-1 whitespace-nowrap"><Link className="underline" href={`/outreach/${m.id}`}>Open</Link>{" · "}
                    <button className="underline" onClick={() => run(() => api(`/outreach/messages/${m.id}/skip`, { body: {} }), "Skipped.")}>Skip</button></td>
                </tr>))}</tbody></table></div>)}
        </section>)}

      {tab === "Manual-send queue" && (
        <section aria-labelledby="mq"><h2 id="mq" className="mb-2 font-medium">Send these yourself, then mark them sent</h2>
          {queue.data?.items.length === 0 && <p className="text-sm text-gray-600">Nothing approved for manual sending.</p>}
          <ul className="grid gap-2">{queue.data?.items.map((m) => <li key={m.id} className="rounded border p-3 text-sm">
            <p className="font-medium">{m.to_name ?? m.to_email} · {m.company} · {m.channel === "linkedin" ? "LinkedIn" : "Email"}</p>
            <div className="mt-1 flex flex-wrap items-center gap-2">
              {m.to_linkedin_url && <a className="underline" href={m.to_linkedin_url} target="_blank" rel="noopener noreferrer">Open LinkedIn profile</a>}
              <Link className="underline" href={`/outreach/${m.id}`}>Open message</Link>
              <button className="rounded bg-black px-2 py-0.5 text-xs text-white" onClick={() => run(() => api(`/outreach/messages/${m.id}/mark-sent`, { body: {} }), "Marked as sent. We take your word for it.")}>I sent this</button></div></li>)}</ul></section>)}

      {tab === "Sending" && (
        <section aria-labelledby="sd" className="grid gap-2 text-sm"><h2 id="sd" className="font-medium">Sending</h2>
          <p>Delivery mode: <strong>{cfg.data?.delivery_mode.replaceAll("_", " ").toLowerCase()}</strong> · Gmail {cfg.data?.gmail.connected ? "connected" : "not connected"} · daily limit {cfg.data?.daily_limit}{cfg.data?.global_pause && <strong className="text-red-700"> · PAUSED</strong>}</p>
          <button className="w-fit rounded bg-black px-3 py-1.5 text-white" onClick={() => run(async () => { const r = await api<{ sent: number; dry_run: number; held: { codes: string[] }[]; blocked: { codes: string[] }[]; unconfirmed: number }>("/outreach/send", { body: {} });
            setMsg(`Sent ${r.sent}${r.dry_run ? `, dry-run ${r.dry_run}` : ""}; held ${r.held.length}${r.held[0] ? ` (${r.held[0].codes.join(", ")})` : ""}; blocked ${r.blocked.length}${r.blocked[0] ? ` (${r.blocked[0].codes.join(", ")})` : ""}; unconfirmed ${r.unconfirmed}.`); }, "Sender ran.")}>Send approved emails now</button>
          <ul className="grid gap-1">{sending.data?.items.map((m) => <li key={m.id} className="rounded border p-2">{m.to_email ?? m.to_name} · {m.send_state}{m.last_block?.[0] && <span className="text-amber-800"> · {m.last_block[0].code}: {m.last_block[0].detail}</span>}
            {m.send_state === "delivery_unconfirmed" && <strong className="text-red-700"> · delivery unconfirmed: it will never be re-sent automatically. <Link className="underline" href={`/outreach/${m.id}`}>Reconcile</Link></strong>}</li>)}</ul></section>)}

      {tab === "Activity" && (
        <section aria-labelledby="ac"><h2 id="ac" className="mb-2 font-medium">Your activity log</h2>
          <ul className="grid gap-1 text-xs">{audit.data?.items.map((a, i) => <li key={i} className="rounded border px-2 py-1">{new Date(a.at + "Z").toLocaleString()} · {a.action.replaceAll("_", " ")} {Object.keys(a.detail).length > 0 && <span className="text-gray-500">{JSON.stringify(a.detail)}</span>}</li>)}</ul></section>)}
      <p className="text-xs text-gray-600">Follow-ups are only ever drafted for your approval; <button className="underline" onClick={() => run(async () => { const r = await api<{ drafts_created: string[] }>("/outreach/followups/scan", { body: {} }); setMsg(`${r.drafts_created.length} follow-up draft(s) waiting in Review.`); }, "Follow-ups checked.")}>check for due follow-ups</button>.</p>
    </div>
  );
}
