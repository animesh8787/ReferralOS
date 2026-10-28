import { CheckCircle2 } from "lucide-react";
import Link from "next/link";
import ThemeToggle from "@/components/ui/ThemeToggle";

const STEPS = [
  ["Build your profile", "Upload your resume and import your connections. Every fact is traced to the line it came from."],
  ["Find jobs that are really open", "Postings are checked against the company's own job board, and the evidence is shown."],
  ["Tailor your resume honestly", "A claim check blocks any statement your profile can't support. You approve every version."],
  ["Ask the right people", "Contacts are ranked with reasons you can read. Nothing is sent until you approve it."],
];
const RULES = ["It never invents facts about you.", "Nothing is sent without your approval.", "It says “unknown” instead of guessing.", "You can export or delete your data at any time."];

export default function Landing() {
  return (
    <div className="min-h-screen">
      <header className="mx-auto flex max-w-5xl items-center justify-between gap-3 px-5 py-4">
        <Link href="/" className="brand !p-0">ReferralOS</Link>
        <div className="flex items-center gap-2"><ThemeToggle /><Link href="/login" className="btn">Sign in</Link><Link href="/signup" className="btn btn-primary">Get started</Link></div>
      </header>
      <main id="main">
        <section className="mx-auto max-w-5xl px-5 pb-12 pt-12 md:pt-20">
          <h1 className="max-w-3xl !text-4xl md:!text-5xl">Get referred for the jobs you want, honestly.</h1>
          <p className="mt-4 max-w-2xl text-lg text-muted">ReferralOS turns your resume and your network into a short list of real openings and the right people to ask. You review every draft before anything goes out.</p>
          <div className="mt-6 flex flex-wrap gap-3"><Link href="/signup" className="btn btn-primary">Create your account</Link><Link href="/login" className="btn">Sign in</Link></div>
        </section>

        <section className="mx-auto max-w-5xl px-5 py-8">
          <h2 className="mb-4 !text-2xl">How it works</h2>
          <ol className="grid gap-4 sm:grid-cols-2">
            {STEPS.map(([t, d], i) => (
              <li key={t} className="card flex gap-4 p-5">
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-accent-weak font-bold text-accent" aria-hidden="true">{i + 1}</span>
                <div><h3>{t}</h3><p className="text-muted">{d}</p></div>
              </li>
            ))}
          </ol>
        </section>

        <section className="mx-auto max-w-5xl px-5 py-8">
          <div className="card p-6">
            <h2 className="mb-3 !text-2xl">Built to be trusted</h2>
            <ul className="grid gap-2 sm:grid-cols-2">{RULES.map((r) => <li key={r} className="flex items-start gap-2"><CheckCircle2 size={20} strokeWidth={1.75} className="mt-0.5 shrink-0 text-ok" aria-hidden="true" />{r}</li>)}</ul>
          </div>
        </section>
      </main>
      <footer className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-2 border-t px-5 py-6 text-sm text-muted">
        <span>ReferralOS</span>
        <span><Link href="/login">Sign in</Link> · <Link href="/signup">Create account</Link></span>
      </footer>
    </div>
  );
}
