"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import useSWR from "swr";
import ConsentCheckbox from "@/components/ConsentCheckbox";
import PreferencesForm from "@/components/PreferencesForm";
import WeightsEditor from "@/components/WeightsEditor";
import { api } from "@/lib/api";

type Cfg = { weights: Record<string, number>; missing_policy: string };
type MCfg = { match_weights: Record<string, number>; contact_weights: Record<string, number>; opportunity_weights: Record<string, number>; contacts_per_job: number };
type LLM = { provider: string; monthly_budget_usd: number; key_set: boolean; spent_this_month_usd: number; consent: boolean; what_is_sent: string; estimate: string; status: string; model: string };
type Priv = { holds: Record<string, number>; raw_import_retention_days: number | null; consents: Record<string, boolean>; statements: string[] };
type Consents = Record<string, { granted: boolean; description: string }>;

export default function Settings() {
  const router = useRouter();
  const scoring = useSWR<Cfg>("/scoring/config", (p: string) => api<Cfg>(p));
  const matching = useSWR<MCfg>("/matching/config", (p: string) => api<MCfg>(p));
  const sources = useSWR<Record<string, boolean>>("/settings/sources", (p: string) => api<Record<string, boolean>>(p));
  const notes = useSWR<Record<string, boolean>>("/settings/notifications", (p: string) => api<Record<string, boolean>>(p));
  const llm = useSWR<LLM>("/settings/llm", (p: string) => api<LLM>(p));
  const priv = useSWR<Priv>("/privacy/summary", (p: string) => api<Priv>(p));
  const consents = useSWR<Consents>("/consents", (p: string) => api<Consents>(p));
  const [key, setKey] = useState("");
  const [budget, setBudget] = useState<string>("");
  const [days, setDays] = useState("");
  const [pw, setPw] = useState("");
  const [msg, setMsg] = useState("");
  const say = async (fn: () => Promise<unknown>, ok: string) => { setMsg(""); try { const r = await fn(); setMsg(typeof r === "string" ? r : ok); } catch (e) { setMsg((e as Error).message); } };
  const toggle = (data: Record<string, boolean> | undefined, path: string, mut: () => void) => Object.entries(data ?? {}).map(([k, v]) => (
    <label key={k} className="flex flex-wrap items-center gap-2"><input type="checkbox" checked={v} onChange={async (e) => { await api(path, { method: "PUT", body: { [k]: e.target.checked } }); mut(); }} />{k.replaceAll("_", " ")}</label>));

  return (
    <div className="mx-auto grid max-w-3xl gap-8 text-sm">
      <header><h1 className="text-xl font-semibold">Settings</h1>{msg && <p role="status" className="mt-1">{msg}</p>}</header>
      <section aria-labelledby="t"><h2 id="t" className="mb-2 text-base font-medium">Career targets</h2><PreferencesForm /></section>

      <section aria-labelledby="sc" className="grid gap-3"><h2 id="sc" className="text-base font-medium">Scoring</h2>
        <p className="text-gray-600">Weights are always rescaled to total 100 and every score shows its parts. Recalculate afterwards to apply them.</p>
        {scoring.data && <WeightsEditor title="Referral priority (who to approach)" weights={scoring.data.weights} onSave={async (w) => { await api("/scoring/config", { method: "PUT", body: { weights: w } }); scoring.mutate(); }} />}
        <label className="flex flex-wrap items-center gap-2">When data is missing <select className="rounded border px-2 py-1" value={scoring.data?.missing_policy ?? "neutral"} onChange={async (e) => { await api("/scoring/config", { method: "PUT", body: { missing_policy: e.target.value } }); scoring.mutate(); }}>
          <option value="neutral">count it as neutral and lower confidence</option><option value="exclude">leave it out and lower confidence</option></select></label>
        {matching.data && <>
          <WeightsEditor title="Job match" weights={matching.data.match_weights} onSave={async (w) => { await api("/matching/config", { method: "PUT", body: { match_weights: w } }); matching.mutate(); }} />
          <WeightsEditor title="Contact for a specific job" weights={matching.data.contact_weights} onSave={async (w) => { await api("/matching/config", { method: "PUT", body: { contact_weights: w } }); matching.mutate(); }} />
          <WeightsEditor title="Opportunity priority" weights={matching.data.opportunity_weights} onSave={async (w) => { await api("/matching/config", { method: "PUT", body: { opportunity_weights: w } }); matching.mutate(); }} />
          <label className="flex flex-wrap items-center gap-2">Contacts recommended per job (1 to 5) <input type="number" min={1} max={5} className="w-16 rounded border px-2 py-1" defaultValue={matching.data.contacts_per_job} onBlur={(e) => say(async () => { await api("/matching/config", { method: "PUT", body: { contacts_per_job: Number(e.target.value) } }); matching.mutate(); }, "Saved.")} /></label></>}</section>

      <section aria-labelledby="src" className="grid gap-1"><h2 id="src" className="text-base font-medium">Job sources</h2><p className="text-gray-600">Switch off a source and its boards are skipped (and reported as skipped).</p>{toggle(sources.data, "/settings/sources", sources.mutate)}</section>

      <section aria-labelledby="em" className="grid gap-1"><h2 id="em" className="text-base font-medium">Email and sending</h2><p>Sender name, delivery mode (manual by default), limits, Gmail connection and the lawful-use acknowledgement: <Link className="underline" href="/outreach/settings">Outreach settings</Link>.</p></section>

      <section aria-labelledby="ai" className="grid gap-2"><h2 id="ai" className="text-base font-medium">AI assistance (optional)</h2>
        <p className="text-gray-600">Everything works without it. If you turn it on, you use your own key, and it may only propose rewordings of single resume bullets, which are still checked against your profile. {llm.data?.what_is_sent}</p>
        <p className="text-xs text-amber-800">{llm.data?.status}</p>
        <ConsentCheckbox name="llm" onChange={() => llm.mutate()} />
        <label className="flex flex-wrap items-center gap-2">Provider <select className="rounded border px-2 py-1" value={llm.data?.provider ?? "none"} onChange={(e) => say(async () => { await api("/settings/llm", { method: "PUT", body: { provider: e.target.value } }); llm.mutate(); }, "Saved.")}><option value="none">None (deterministic)</option><option value="anthropic">Anthropic ({llm.data?.model})</option></select></label>
        <label className="flex flex-wrap items-center gap-2">API key <input type="password" autoComplete="off" className="w-full max-w-xs rounded border px-2 py-1" placeholder={llm.data?.key_set ? "A key is saved (hidden)" : "Paste your key"} value={key} onChange={(e) => setKey(e.target.value)} />
          <button className="rounded border px-2 py-1" onClick={() => say(async () => { await api("/settings/llm", { method: "PUT", body: { provider: llm.data?.provider ?? "none", api_key: key } }); setKey(""); llm.mutate(); }, "Key saved (encrypted).")}>Save key</button>
          {llm.data?.key_set && <button className="underline" onClick={() => say(async () => { await api("/settings/llm", { method: "PUT", body: { provider: "none", clear_key: true } }); llm.mutate(); }, "Key removed.")}>Remove</button>}</label>
        <label className="flex flex-wrap items-center gap-2">Monthly budget (USD) <input type="number" min={0} max={100} step={0.5} className="w-24 rounded border px-2 py-1" placeholder={String(llm.data?.monthly_budget_usd ?? 5)} value={budget} onChange={(e) => setBudget(e.target.value)} />
          <button className="rounded border px-2 py-1" onClick={() => say(async () => { await api("/settings/llm", { method: "PUT", body: { provider: llm.data?.provider ?? "none", monthly_budget_usd: Number(budget) } }); setBudget(""); llm.mutate(); }, "Budget saved.")}>Save</button>
          <span className="text-gray-600">Spent this month: ${llm.data?.spent_this_month_usd ?? 0}. Calls stop when the budget is reached. {llm.data?.estimate}</span></label></section>

      <section aria-labelledby="nt" className="grid gap-1"><h2 id="nt" className="text-base font-medium">Notifications (in the app)</h2>{toggle(notes.data, "/settings/notifications", notes.mutate)}<p className="text-xs text-gray-600">No emails are sent about your activity.</p></section>

      <section aria-labelledby="pv" className="grid gap-2"><h2 id="pv" className="text-base font-medium">Privacy and your data</h2>
        <p>What is held: {priv.data && Object.entries(priv.data.holds).map(([k, v]) => `${v} ${k.replaceAll("_", " ")}`).join(" · ")}. <Link className="underline" href="/privacy">Read the privacy summary</Link>.</p>
        <label className="flex flex-wrap items-center gap-2">Auto-delete raw import files after <input type="number" min={1} max={3650} className="w-20 rounded border px-2 py-1" placeholder={priv.data?.raw_import_retention_days ? String(priv.data.raw_import_retention_days) : "off"} value={days} onChange={(e) => setDays(e.target.value)} /> days
          <button className="rounded border px-2 py-1" onClick={() => say(async () => { await api("/privacy/retention", { method: "PUT", body: { raw_import_days: days ? Number(days) : null } }); priv.mutate(); }, days ? "Retention saved." : "Retention turned off.")}>Save</button>
          <button className="underline" onClick={() => say(async () => { const r = await api<{ purged_imports: number }>("/privacy/purge", { body: {} }); priv.mutate(); return `${r.purged_imports} import(s) purged.`; }, "")}>Purge now</button></label>
        {Object.keys(consents.data ?? {}).map((k) => <ConsentCheckbox key={k} name={k} onChange={() => priv.mutate()} />)}
        <p><a className="underline" href="/api/me/export">Download all my data (JSON)</a></p>
        <form className="grid gap-2 rounded border border-red-200 p-3" onSubmit={(e) => { e.preventDefault(); if (!window.confirm("Permanently delete your account and ALL your data, files and tokens? This cannot be undone.")) return;
          say(async () => { await api("/me/delete", { body: { password: pw } }); router.replace("/signup"); }, ""); }}>
          <h3 className="font-medium text-red-800">Delete my account and all data</h3><p className="text-xs">This removes your profile, imports, contacts, jobs analysis, resumes, drafts, messages, tokens and files.</p>
          <input type="password" required autoComplete="current-password" aria-label="Your password" placeholder="Confirm with your password" className="w-64 rounded border px-2 py-1" value={pw} onChange={(e) => setPw(e.target.value)} />
          <button className="w-fit rounded bg-red-700 px-3 py-1.5 text-white">Delete everything</button></form></section>
    </div>
  );
}
