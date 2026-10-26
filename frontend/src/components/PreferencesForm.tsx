"use client";
import { useEffect, useState } from "react";
import useSWR from "swr";
import { api } from "@/lib/api";

type Prefs = { target_roles: string[]; target_companies: string[]; excluded_companies: string[]; locations: string[]; work_arrangement: string[]; employment_type: string[]; graduation_date: string | null; work_authorization: string | null };
type Profile = { items: Record<string, { data: Partial<Prefs> }[]> };
const EMPTY: Prefs = { target_roles: [], target_companies: [], excluded_companies: [], locations: [], work_arrangement: [], employment_type: [], graduation_date: null, work_authorization: null };
const lines = (s: string) => s.split("\n").map((x) => x.trim()).filter(Boolean);

export default function PreferencesForm({ onSaved }: { onSaved?: () => void }) {
  const { data } = useSWR<Profile>("/profile", (p: string) => api<Profile>(p));
  const [p, setP] = useState<Prefs>(EMPTY);
  const [msg, setMsg] = useState("");
  useEffect(() => { const d = data?.items.preference?.[0]?.data; if (d) setP({ ...EMPTY, ...d }); }, [data]);
  const list = (k: "target_roles" | "target_companies" | "excluded_companies" | "locations", label: string, hint: string) => (
    <label className="grid gap-1">{label}<span className="text-xs text-gray-600">{hint}</span>
      <textarea rows={3} className="rounded border px-2 py-1" value={p[k].join("\n")} onChange={(e) => setP({ ...p, [k]: lines(e.target.value) })} /></label>);
  const check = (k: "work_arrangement" | "employment_type", opts: [string, string][]) => (
    <div className="flex flex-wrap gap-3">{opts.map(([v, l]) => <label key={v} className="flex items-center gap-1"><input type="checkbox" checked={p[k].includes(v)} onChange={(e) => setP({ ...p, [k]: e.target.checked ? [...p[k], v] : p[k].filter((x) => x !== v) })} />{l}</label>)}</div>);
  return (
    <form className="grid gap-3 text-sm" onSubmit={async (e) => { e.preventDefault(); setMsg(""); try { await api("/profile/preferences", { method: "PUT", body: p }); setMsg("Saved."); onSaved?.(); } catch (x) { setMsg((x as Error).message); } }}>
      {list("target_roles", "Roles you want", "One per line, e.g. Backend Engineer")}
      {list("target_companies", "Companies you most want", "Optional. One per line.")}
      {list("excluded_companies", "Companies to leave out", "Optional. They are never prioritised or contacted.")}
      {list("locations", "Preferred locations", "One per line, e.g. Remote, Austin")}
      <fieldset><legend className="mb-1">Work arrangement</legend>{check("work_arrangement", [["remote", "Remote"], ["hybrid", "Hybrid"], ["onsite", "On-site"]])}</fieldset>
      <fieldset><legend className="mb-1">Employment type</legend>{check("employment_type", [["internship", "Internship"], ["full_time", "Full-time"], ["part_time", "Part-time"], ["contract", "Contract"]])}</fieldset>
      <label className="grid gap-1">Graduation date (or expected)<input type="month" className="w-48 rounded border px-2 py-1" value={p.graduation_date ?? ""} onChange={(e) => setP({ ...p, graduation_date: e.target.value || null })} /></label>
      <label className="grid gap-1">Work authorisation (optional, private)<span className="text-xs text-gray-600">Used only to check postings that mention visas or citizenship. Leave blank if you prefer.</span>
        <input className="rounded border px-2 py-1" placeholder="e.g. US citizen, or needs sponsorship" value={p.work_authorization ?? ""} onChange={(e) => setP({ ...p, work_authorization: e.target.value || null })} /></label>
      <button className="w-fit rounded bg-black px-3 py-1.5 text-white">Save</button>{msg && <p role="status">{msg}</p>}
    </form>
  );
}
