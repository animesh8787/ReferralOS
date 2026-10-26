"use client";
import { useState } from "react";
import useSWR from "swr";
import ConsentCheckbox from "@/components/ConsentCheckbox";
import { api } from "@/lib/api";

type S = { sender_name: string; sender_email: string; delivery_mode: string; daily_limit: number; per_company_daily: number; intro_daily: number; pacing_seconds: number[]; max_followups: number;
  followup_spacing_business_days: number; tone: string; length: string; reply_tracking: boolean; lawful_use_ack: string | null; region_acks: Record<string, string>; hard_max_daily: number;
  hard_max_per_company: number; lawful_use_text: string; disclaimer: string; scopes_explained: Record<string, string>; gmail: { connected: boolean; account: string | null; mode: string; real_oauth_configured: boolean } };

export default function OutreachSettings() {
  const { data: s, mutate } = useSWR<S>("/outreach/settings", (p: string) => api<S>(p));
  const [f, setF] = useState<Partial<S>>({});
  const [msg, setMsg] = useState("");
  const [warn, setWarn] = useState<string[]>([]);
  const [email, setEmail] = useState("");
  if (!s) return <p role="status">Loading…</p>;
  const v = <K extends keyof S>(k: K) => (f[k] ?? s[k]) as S[K];
  const pace = (i: 0 | 1, x: number) => { const cur = [...v("pacing_seconds")]; cur[i] = x; setF({ ...f, pacing_seconds: cur }); };
  async function save() {
    setMsg("");
    try { const r = await api<{ warnings: string[] }>("/outreach/settings", { method: "PUT", body: { sender_name: v("sender_name"), sender_email: v("sender_email"), delivery_mode: v("delivery_mode"), daily_limit: Number(v("daily_limit")),
      per_company_daily: Number(v("per_company_daily")), intro_daily: Number(v("intro_daily")), max_followups: Number(v("max_followups")), followup_spacing_business_days: Number(v("followup_spacing_business_days")), pacing_seconds: v("pacing_seconds").map(Number), tone: v("tone"), length: v("length") } });
      setWarn(r.warnings); setF({}); setMsg("Saved."); mutate(); } catch (e) { setMsg((e as Error).message); }
  }
  const num = (k: keyof S, label: string, max?: number) => <label className="grid gap-1">{label}<input type="number" min={0} max={max} className="w-28 rounded border px-2 py-1" value={v(k) as number} onChange={(e) => setF({ ...f, [k]: Number(e.target.value) })} /></label>;

  return (
    <div className="mx-auto grid max-w-3xl gap-6 text-sm">
      <h1 className="text-xl font-semibold">Outreach settings</h1>
      <section aria-labelledby="id" className="grid gap-2"><h2 id="id" className="font-medium">Who the emails come from</h2>
        <p className="text-gray-600">Emails are sent from your own address, with your real name. Nothing can be sent without both.</p>
        <label className="grid gap-1">Your name<input className="rounded border px-2 py-1" value={v("sender_name")} onChange={(e) => setF({ ...f, sender_name: e.target.value })} /></label>
        <label className="grid gap-1">Your email address<input type="email" className="rounded border px-2 py-1" value={v("sender_email")} onChange={(e) => setF({ ...f, sender_email: e.target.value })} /></label></section>

      <section aria-labelledby="dm" className="grid gap-2"><h2 id="dm" className="font-medium">How emails are delivered</h2>
        {[["MANUAL_REVIEW", "Manual (default)", "The app prepares everything; you copy or open each email and send it yourself, then mark it sent."],
          ["AUTHORISED_INTEGRATION", "Send through my Gmail", "After you approve, the app sends from your connected Gmail account with pauses between emails, within your limits."],
          ["DRY_RUN", "Dry run", "Does everything except deliver. Use it to check a whole batch safely."]].map(([k, t, d]) => (
          <label key={k} className="flex items-start gap-2"><input type="radio" name="mode" checked={v("delivery_mode") === k} onChange={() => setF({ ...f, delivery_mode: k })} /><span><strong>{t}</strong><br /><span className="text-gray-600">{d}</span></span></label>))}</section>

      <section aria-labelledby="lm" className="grid gap-2"><h2 id="lm" className="font-medium">Limits</h2>
        <div className="flex flex-wrap gap-4">{num("daily_limit", `Emails per day (max ${s.hard_max_daily})`, s.hard_max_daily)}{num("per_company_daily", `Per company per day (max ${s.hard_max_per_company})`, s.hard_max_per_company)}{num("intro_daily", "Introductory emails per day")}
          {num("max_followups", "Follow-ups per person (max 3)", 3)}{num("followup_spacing_business_days", "Business days between follow-ups")}</div>
        <div className="flex flex-wrap items-end gap-3"><label className="grid gap-1">Pause between emails: at least (seconds)<input type="number" min={0} className="w-28 rounded border px-2 py-1" value={v("pacing_seconds")[0]} onChange={(e) => pace(0, Number(e.target.value))} /></label>
          <label className="grid gap-1">at most (seconds)<input type="number" min={0} className="w-28 rounded border px-2 py-1" value={v("pacing_seconds")[1]} onChange={(e) => pace(1, Number(e.target.value))} /></label>
          <span className="text-gray-600">Each gap is picked at random in this range, so a batch is spread out. It keeps you well inside provider limits.</span></div>
        <p className="text-gray-600">Defaults are deliberately low. Each person is only ever sent one first email. Raising limits makes spam filtering and annoyed recipients more likely.</p>
        <label className="flex gap-4"><span className="grid gap-1">Tone<select className="rounded border px-2 py-1" value={v("tone")} onChange={(e) => setF({ ...f, tone: e.target.value })}><option>conversational</option><option>formal</option></select></span>
          <span className="grid gap-1">Length<select className="rounded border px-2 py-1" value={v("length")} onChange={(e) => setF({ ...f, length: e.target.value })}><option>short</option><option>medium</option></select></span></label></section>
      <div><button className="rounded bg-black px-3 py-1.5 text-white" onClick={save}>Save settings</button>{warn.map((w, i) => <p key={i} role="status" className="mt-1 text-amber-800">{w}</p>)}{msg && <p role="status" className="mt-1">{msg}</p>}</div>

      <section aria-labelledby="ack" className="grid gap-2 rounded border p-3"><h2 id="ack" className="font-medium">Lawful use</h2>
        <p>{s.lawful_use_text}</p><p className="text-xs text-gray-600">{s.disclaimer} Countries such as the UK, EU members, Canada and Australia usually require prior consent for unsolicited commercial email; you will be asked to acknowledge each such region separately. Purchased or scraped lists cannot be used for automated sending.</p>
        {s.lawful_use_ack ? <p className="text-green-800">Acknowledged on {s.lawful_use_ack.slice(0, 10)}.</p> : <button className="w-fit rounded border px-3 py-1" onClick={async () => { await api("/outreach/acknowledge", { body: { kind: "lawful_use" } }); mutate(); }}>I understand and agree</button>}
        {Object.keys(s.region_acks).length > 0 && <p>Region acknowledgements: {Object.keys(s.region_acks).join(", ")}</p>}</section>

      <section aria-labelledby="gm" className="grid gap-2 rounded border p-3"><h2 id="gm" className="font-medium">Gmail connection</h2>
        <p>Official Google sign-in only. We never see or ask for your Gmail password.</p>
        <ul className="list-disc pl-5">{Object.entries(s.scopes_explained).map(([k, d]) => <li key={k}><strong>{k}</strong>: {d}</li>)}</ul>
        <ConsentCheckbox name="gmail" />
        <ConsentCheckbox name="reply_tracking" extra="(adds read access to threads this app started)" />
        {s.gmail.connected ? <p>Connected as <strong>{s.gmail.account}</strong>{s.gmail.mode === "mock" && " (simulated: offline mode)"} <button className="ml-2 underline" onClick={async () => { await api("/email/gmail", { method: "DELETE" }); mutate(); }}>Disconnect and revoke</button></p> :
          s.gmail.mode === "mock" ? <form className="flex gap-2" onSubmit={async (e) => { e.preventDefault(); try { await api("/email/gmail/mock-connect", { body: { email } }); mutate(); } catch (x) { setMsg((x as Error).message); } }}>
            <input required type="email" aria-label="Simulated Gmail address" placeholder="your.address@example.com" className="rounded border px-2 py-1" value={email} onChange={(e) => setEmail(e.target.value)} /><button className="rounded border px-3 py-1">Connect (simulated, offline)</button></form> :
          <button className="w-fit rounded border px-3 py-1" onClick={async () => { try { const r = await api<{ url: string }>("/email/gmail/authorize"); window.location.href = r.url; } catch (x) { setMsg((x as Error).message); } }}>Connect with Google</button>}
        <button className="w-fit rounded border px-3 py-1" onClick={async () => { try { const r = await api<{ ok: boolean; to: string; provider: string; detail: string }>("/email/test-send", { body: {} }); setMsg(r.ok ? `Test sent to ${r.to} (${r.provider}).` : `Test failed: ${r.detail}`); } catch (x) { setMsg((x as Error).message); } }}>Send one test email to myself</button></section>
    </div>
  );
}
