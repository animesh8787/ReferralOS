"use client";
import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";
import ConsentCheckbox from "@/components/ConsentCheckbox";
import ItemCard from "@/components/ItemCard";
import { Item } from "@/components/ProvenanceBadge";
import Skeleton from "@/components/ui/Skeleton";
import { api, settle, upload } from "@/lib/api";

type Profile = {
  items: Record<string, Item[]>;
  completeness: { score: number; missing: string[] };
  questions: { item_id: string | null; type: string; text: string }[];
};
type Consents = Record<string, { granted: boolean; description: string }>;
type Task = { status: string; resume_id?: string; result?: { error?: string; warning?: string; added?: number } };

const ORDER = ["personal", "summary", "education", "experience", "project", "skill", "certification", "award", "publication", "preference"];
const LABEL: Record<string, string> = { personal: "Contact", summary: "Summary", education: "Education", experience: "Experience", project: "Projects", skill: "Skills", certification: "Certifications", award: "Awards", publication: "Publications", preference: "Preferences" };

export default function ProfilePage() {
  const { data, mutate, error, isLoading } = useSWR<Profile>("/profile", (p: string) => api<Profile>(p));
  const consents = useSWR<Consents>("/consents", (p: string) => api<Consents>(p));
  const [msg, setMsg] = useState("");
  const [gh, setGh] = useState("");
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [lastResume, setLastResume] = useState("");

  async function act(fn: () => Promise<Task>, okText: string) {
    setBusy(true);
    setMsg("");
    try {
      const r = await settle(await fn());
      if (r.resume_id) setLastResume(r.resume_id);
      setMsg(r.result?.error ?? r.result?.warning ?? `${okText}${r.result?.added !== undefined ? ` (${r.result.added} items added)` : ""}`);
      await mutate();
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (isLoading) return <Skeleton rows={5} />;
  if (error || !data) return <p role="alert" className="text-danger">Could not load your profile. Please refresh.</p>;
  const empty = Object.keys(data.items).length === 0;

  return (
    <div className="grid max-w-4xl gap-6">
      <header>
        <h1>Master Career Profile</h1>
        <p className="text-sm text-muted">The single source of truth for resumes and messages. Nothing is added to a resume unless it is here.</p>
        <div className="mt-2" role="meter" aria-valuenow={data.completeness.score} aria-valuemin={0} aria-valuemax={100} aria-label="Profile completeness">
          <div className="h-2 w-full rounded bg-surface-3"><div className="h-2 rounded bg-ok" style={{ width: `${data.completeness.score}%` }} /></div>
          <p className="mt-1 text-xs">{data.completeness.score}% complete{data.completeness.missing.length ? ` · missing: ${data.completeness.missing.join(", ")}` : ""}</p>
        </div>
      </header>

      <section aria-labelledby="add" className="grid gap-4 rounded border p-4">
        <h2 id="add" className="font-medium">Add information</h2>
        <label className="grid gap-1 text-sm">Resume (PDF or DOCX, up to 5 MB)
          <input type="file" accept=".pdf,.docx" disabled={busy} onChange={(e) => { const f = e.target.files?.[0]; if (f) act(() => upload<Task>("/resumes", f), "Resume parsed"); e.target.value = ""; }} />
        </label>
        {(["github", "portfolio"] as const).map((k) => (
          <div key={k} className="grid gap-2 text-sm">
            <ConsentCheckbox name={k} extra="Only public data is read; you choose what to keep." />
            {consents.data?.[k]?.granted && (
              <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); act(() => api<Task>(`/profile/${k}`, { body: k === "github" ? { username: gh } : { url } }), k === "github" ? "GitHub checked" : "Page read"); }}>
                <input className="flex-1 rounded border px-2 py-1" required aria-label={k === "github" ? "GitHub username or URL" : "Portfolio URL"} placeholder={k === "github" ? "GitHub username or profile URL" : "https://your-portfolio.example"} value={k === "github" ? gh : url} onChange={(e) => (k === "github" ? setGh(e.target.value) : setUrl(e.target.value))} />
                <button disabled={busy} className="rounded bg-black px-3 py-1 text-white disabled:opacity-50">Fetch</button>
              </form>
            )}
          </div>
        ))}
        {msg && <p role="status" className="text-sm">{msg}</p>}
        {lastResume && <p className="text-sm"><Link className="underline" href={`/profile/resume/${lastResume}`}>Compare extracted data with your original resume</Link></p>}
      </section>

      {data.questions.length > 0 && (
        <section aria-labelledby="qs" className="rounded border border-warn bg-warn-weak p-4">
          <h2 id="qs" className="font-medium">Needs your attention ({data.questions.length})</h2>
          <ul className="mt-2 list-disc pl-5 text-sm">{data.questions.map((q, i) => <li key={i}>{q.text}</li>)}</ul>
        </section>
      )}

      {empty && <p className="text-sm text-muted">Your profile is empty. Upload a resume above, or add details by hand once the profile has a section to edit.</p>}

      {ORDER.filter((s) => data.items[s]).map((s) => (
        <section key={s} aria-labelledby={`h-${s}`}>
          <h2 id={`h-${s}`} className="mb-2 font-medium">{LABEL[s]}</h2>
          <ul className="grid gap-2">{data.items[s].map((i) => <ItemCard key={i.id} item={i} onChange={() => mutate()} />)}</ul>
        </section>
      ))}
      <p className="text-sm"><Link className="underline" href="/profile/versions">Version history</Link></p>
    </div>
  );
}
