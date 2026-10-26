"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import useSWR from "swr";
import ConsentCheckbox from "@/components/ConsentCheckbox";
import PreferencesForm from "@/components/PreferencesForm";
import { api, settle, upload } from "@/lib/api";

const STEPS = [["resume", "Resume"], ["links", "GitHub & portfolio"], ["review", "Review profile"], ["preferences", "Career goals"], ["sources", "Contacts & Gmail"], ["discovery", "Find jobs"]] as const;
type Onb = { step: string; done: boolean; skipped: string[] };
type Prof = { completeness: { score: number }; questions: { text: string }[] };

export default function Onboarding() {
  const router = useRouter();
  const { data: onb, mutate } = useSWR<Onb>("/onboarding", (p: string) => api<Onb>(p));
  const prof = useSWR<Prof>("/profile", (p: string) => api<Prof>(p));
  const [step, setStep] = useState("resume");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);
  const [gh, setGh] = useState("");
  const [url, setUrl] = useState("");
  const [boardCompany, setBoardCompany] = useState("");
  const [boardUrl, setBoardUrl] = useState("");
  useEffect(() => { if (onb && STEPS.some(([k]) => k === onb.step)) setStep(onb.step); }, [onb]);
  const go = async (s: string, skipped?: string) => { setMsg(""); setStep(s); await api("/onboarding", { method: "PUT", body: { step: s, ...(skipped ? { skipped: [...(onb?.skipped ?? []), skipped] } : {}) } }); mutate(); };
  const next = (cur: string, skip = false) => { const i = STEPS.findIndex(([k]) => k === cur); return go(STEPS[Math.min(i + 1, STEPS.length - 1)][0], skip ? cur : undefined); };
  async function run(fn: () => Promise<unknown>, ok: string) { setBusy(true); setMsg(""); try { const r = (await settle((await fn()) as { task_id?: string })) as { result?: { error?: string; warning?: string } }; setMsg(r?.result?.error ?? r?.result?.warning ?? ok); prof.mutate(); } catch (e) { setMsg((e as Error).message); } finally { setBusy(false); } }
  const idx = STEPS.findIndex(([k]) => k === step);
  const skip = <button className="underline" onClick={() => next(step, true)}>Skip for now</button>;
  const nextBtn = <button className="rounded bg-black px-3 py-1.5 text-white" onClick={() => next(step)}>Continue</button>;

  return (
    <div className="mx-auto grid max-w-2xl gap-4 text-sm">
      <header><h1 className="text-xl font-semibold">Let&apos;s set you up</h1><p className="text-gray-600">Every step except having some profile information can be skipped, and you can come back later.</p>
        <ol className="mt-2 flex flex-wrap gap-2" aria-label="Setup steps">{STEPS.map(([k, l], i) => <li key={k}><button aria-current={step === k ? "step" : undefined} className={`rounded border px-2 py-1 text-xs ${step === k ? "bg-black text-white" : i < idx ? "bg-green-50" : ""}`} onClick={() => go(k)}>{i + 1}. {l}{onb?.skipped.includes(k) && " (skipped)"}</button></li>)}</ol></header>
      {msg && <p role="status" className="rounded bg-gray-50 p-2">{msg}</p>}

      {step === "resume" && <section aria-labelledby="s1" className="grid gap-3"><h2 id="s1" className="font-medium">Upload your resume</h2>
        <p>PDF or DOCX. We extract what we can and show you exactly what we found; nothing is added to your profile as confirmed until you review it. Image-only scans can&apos;t be read (no OCR); you&apos;d add details by hand.</p>
        <input type="file" aria-label="Resume file" accept=".pdf,.docx" disabled={busy} onChange={(e) => { const f = e.target.files?.[0]; if (f) run(() => upload("/resumes", f), "Resume read. Check it on the next steps."); e.target.value = ""; }} />
        <p>No resume? <Link className="underline" href="/profile">Add your details by hand</Link> and come back.</p><div className="flex gap-3">{nextBtn}{skip}</div></section>}

      {step === "links" && <section aria-labelledby="s2" className="grid gap-3"><h2 id="s2" className="font-medium">GitHub and portfolio (optional)</h2>
        <p>We only read public data, and only what you point us at. First allow it:</p>
        <ConsentCheckbox name="github" /><ConsentCheckbox name="portfolio" />
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); run(() => api("/profile/github", { body: { username: gh } }), "GitHub checked: repositories are suggestions for you to confirm."); }}>
          <input aria-label="GitHub username or URL" placeholder="GitHub username or URL" className="flex-1 rounded border px-2 py-1" value={gh} onChange={(e) => setGh(e.target.value)} /><button disabled={!gh || busy} className="rounded border px-3 py-1">Fetch</button></form>
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); run(() => api("/profile/portfolio", { body: { url } }), "Page read."); }}>
          <input aria-label="Portfolio URL" placeholder="https://your-portfolio.example" className="flex-1 rounded border px-2 py-1" value={url} onChange={(e) => setUrl(e.target.value)} /><button disabled={!url || busy} className="rounded border px-3 py-1">Fetch</button></form>
        <div className="flex gap-3">{nextBtn}{skip}</div></section>}

      {step === "review" && <section aria-labelledby="s3" className="grid gap-3"><h2 id="s3" className="font-medium">Review what we found</h2>
        <p>Profile completeness: <strong>{prof.data?.completeness.score ?? 0}%</strong>.</p>
        {prof.data && prof.data.questions.length > 0 && <ul className="list-disc pl-5">{prof.data.questions.slice(0, 5).map((q, i) => <li key={i}>{q.text}</li>)}</ul>}
        <p><Link className="underline" href="/profile">Open the profile editor</Link> to confirm, correct or add things. Confirmed facts are the only ones that can appear on a resume or in a message.</p><div className="flex gap-3">{nextBtn}{skip}</div></section>}

      {step === "preferences" && <section aria-labelledby="s4" className="grid gap-3"><h2 id="s4" className="font-medium">What are you looking for?</h2><PreferencesForm /><div className="flex gap-3">{nextBtn}{skip}</div></section>}

      {step === "sources" && <section aria-labelledby="s5" className="grid gap-3"><h2 id="s5" className="font-medium">Contacts and Gmail (optional)</h2>
        <ul className="list-disc pl-5"><li><Link className="underline" href="/imports">Import your LinkedIn connections CSV</Link> (from LinkedIn&apos;s official data export) and/or a list of HR/recruiter contacts you hold lawfully.</li>
          <li><Link className="underline" href="/outreach/settings">Set your name and sending mode</Link>. The default is manual: nothing is ever sent for you. Connecting Gmail is optional.</li></ul><div className="flex gap-3">{nextBtn}{skip}</div></section>}

      {step === "discovery" && <section aria-labelledby="s6" className="grid gap-3"><h2 id="s6" className="font-medium">Find jobs</h2>
        <p>Add the public job board of a company you care about (Greenhouse, Lever, Ashby, Workable or SmartRecruiters) and we&apos;ll list and verify its open roles.</p>
        <form className="grid gap-2" onSubmit={(e) => { e.preventDefault(); run(async () => { await api("/boards", { body: { company: boardCompany, board_url: boardUrl } }); return api("/jobs/discover", { body: {} }); }, "Board added and searched."); }}>
          <input required aria-label="Company name" placeholder="Company name" className="rounded border px-2 py-1" value={boardCompany} onChange={(e) => setBoardCompany(e.target.value)} />
          <input required aria-label="Job board URL" placeholder="https://boards.greenhouse.io/yourcompany" className="rounded border px-2 py-1" value={boardUrl} onChange={(e) => setBoardUrl(e.target.value)} />
          <button disabled={busy} className="w-fit rounded border px-3 py-1">Add and search</button></form>
        <div className="flex gap-3"><button className="rounded bg-black px-3 py-1.5 text-white" onClick={async () => { await api("/onboarding", { method: "PUT", body: { done: true } }); router.push("/dashboard"); }}>Finish setup</button></div></section>}
    </div>
  );
}
