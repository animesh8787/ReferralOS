"use client";
import { useState } from "react";
import useSWR from "swr";
import { api } from "@/lib/api";

type S = { total: number; items: { id: string; kind: string; value: string; reason: string; source: string }[] };

export default function Suppression() {
  const { data, mutate } = useSWR<S>("/suppression", (p: string) => api<S>(p));
  const [value, setValue] = useState("");
  const [kind, setKind] = useState("email");
  const [reason, setReason] = useState("do_not_contact");
  const [err, setErr] = useState("");

  return (
    <div className="grid max-w-3xl gap-4">
      <h1>Do-not-contact list</h1>
      <p className="text-sm text-muted">Addresses and domains here are never emailed. The list is kept when you re-import contacts. Replies that ask to stop are suggested here for you to confirm; hard bounces are added automatically.</p>
      <form className="flex flex-wrap items-end gap-2 text-sm" onSubmit={async (e) => { e.preventDefault(); setErr(""); try { await api("/suppression", { body: { value, kind, reason } }); setValue(""); mutate(); } catch (x) { setErr((x as Error).message); } }}>
        <label className="grid gap-1">Address or domain<input className="rounded border px-2 py-1" required value={value} onChange={(e) => setValue(e.target.value)} /></label>
        <label className="grid gap-1">Type<select className="rounded border px-2 py-1" value={kind} onChange={(e) => setKind(e.target.value)}><option>email</option><option>domain</option></select></label>
        <label className="grid gap-1">Reason<select className="rounded border px-2 py-1" value={reason} onChange={(e) => setReason(e.target.value)}>{["do_not_contact", "unsubscribed", "bounced", "complained", "blocklist"].map((r) => <option key={r}>{r}</option>)}</select></label>
        <button className="rounded bg-black px-3 py-1.5 text-white">Add</button>
      </form>
      {err && <p role="alert" className="text-sm text-danger">{err}</p>}
      {data?.items.length === 0 && <p className="text-sm text-muted">Nothing suppressed yet.</p>}
      <ul className="grid gap-1 text-sm">{data?.items.map((s) => (
        <li key={s.id} className="flex items-center justify-between rounded border px-3 py-1.5"><span>{s.value} <span className="text-muted">({s.kind}, {s.reason.replaceAll("_", " ")}, {s.source})</span></span>
          <button className="text-danger underline" onClick={async () => { await api(`/suppression/${s.id}`, { method: "DELETE" }); mutate(); }}>Remove</button></li>))}</ul>
    </div>
  );
}
