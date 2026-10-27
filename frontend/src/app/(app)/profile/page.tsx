"use client";
import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";
import ConsentCheckbox from "@/components/ConsentCheckbox";
import ItemCard from "@/components/ItemCard";
import { Item } from "@/components/ProvenanceBadge";
import { UserRound } from "lucide-react";
import Dropzone from "@/components/ui/Dropzone";
import EmptyState from "@/components/ui/EmptyState";
import Notice from "@/components/ui/Notice";
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
  if (error || !data) return <Notice kind="err">Could not load your profile. Please refresh.</Notice>;
  const empty = Object.keys(data.items).length === 0;

  return (
    <div className="grid max-w-4xl gap-6">
      <header className="grid gap-1">
        <h1>Master Career Profile</h1>
        <p className="text-sm text-muted">The single source of truth for resumes and messages. Nothing is added to a resume unless it is here.</p>
        <div className="mt-2" role="meter" aria-valuenow={data.completeness.score} aria-valuemin={0} aria-valuemax={100} aria-label="Profile completeness">
          <div className="h-2 w-full overflow-hidden rounded bg-surface-3"><div className="h-2 rounded bg-accent" style={{ width: `${data.completeness.score}%`, transition: "width .7s var(--ease)" }} /></div>
          <p className="mt-1 text-xs">{data.completeness.score}% complete{data.completeness.missing.length ? ` · missing: ${data.completeness.missing.join(", ")}` : ""}</p>
        </div>
      </header>

      <section aria-labelledby="add" className="card grid gap-4 p-4">
        <h2 id="add" className="eyebrow">Add information</h2>
        <label className="grid gap-1 text-sm">Resume (PDF or DOCX, up to 5 MB)
          <Dropzone hint="Drag it here or choose a file"><input type="file" accept=".pdf,.docx" disabled={busy} onChange={(e) => { const f = e.target.files?.[0]; if (f) act(() => upload<Task>("/resumes", f), "Resume parsed"); e.target.value = ""; }} /></Dropzone>
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
        {msg && <Notice>{msg}</Notice>}
        {lastResume && <p className="text-sm"><Link className="underline" href={`/profile/resume/${lastResume}`}>Compare extracted data with your original resume</Link></p>}
      </section>

      {data.questions.length > 0 && (
        <section aria-labelledby="qs" className="notice notice-warn !p-4">
          <h2 id="qs" className="eyebrow !text-warn">Needs your attention ({data.questions.length})</h2>
          <ul className="mt-2 list-disc pl-5 text-sm">{data.questions.map((q, i) => <li key={i}>{q.text}</li>)}</ul>
        </section>
      )}

      {empty && <EmptyState icon={UserRound} title="Your profile is empty" sub="Upload a resume above, or add details by hand once the profile has a section to edit." />}

      {ORDER.filter((s) => data.items[s]).map((s) => (
        <section key={s} aria-labelledby={`h-${s}`}>
          <h2 id={`h-${s}`} className="eyebrow mb-2">{LABEL[s]}</h2>
          <ul className="grid gap-2">{data.items[s].map((i) => <ItemCard key={i.id} item={i} onChange={() => mutate()} />)}</ul>
        </section>
      ))}
      <p className="text-sm"><Link className="underline" href="/profile/versions">Version history</Link></p>
    </div>
  );
}
