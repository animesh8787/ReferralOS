import { ArrowRight, CheckCircle2, FileCheck2, Handshake, ListChecks, ShieldCheck, UserRound } from "lucide-react";
import Link from "next/link";
import RevealInit from "@/components/ui/Reveal";
import ThemeToggle from "@/components/ui/ThemeToggle";

const STEPS = [
  { icon: UserRound, t: "Build your profile", d: "Upload your resume and import your connections. Every fact is traced to the line it came from." },
  { icon: ListChecks, t: "Find jobs that are really open", d: "Postings are checked against the company's own board, with the evidence shown, not just a page that loads." },
  { icon: FileCheck2, t: "Tailor without inventing", d: "A claim check blocks any statement your profile can't support. You read and approve every version." },
  { icon: Handshake, t: "Ask the right people", d: "Contacts are ranked with reasons you can read. Drafts are honest, and nothing is sent until you approve it." },
];
const RULES = ["Never invents facts about you", "Nothing is sent without your approval", "Says “unknown” instead of guessing", "Your data stays yours: export or delete anytime"];
const PREVIEW = [["Backend Engineer", "Northwind Labs", "Verified open", "badge-ok"], ["Platform Engineer", "Fabrikam Systems", "Unconfirmed", "badge-warn"], ["Data Engineer", "Contoso Analytics", "Closed", "badge-danger"]];

export default function Landing() {
  return (
    <div className="min-h-screen">
      <RevealInit />
      <header className="mx-auto flex max-w-6xl items-center justify-between px-5 py-4">
        <Link href="/" className="brand !p-0">Referral<em>OS</em></Link>
        <div className="flex items-center gap-2"><ThemeToggle /><Link href="/login" className="btn">Sign in</Link><Link href="/signup" className="btn btn-primary">Get started</Link></div>
      </header>
      <main id="main">
        <section className="mx-auto grid max-w-6xl items-center gap-10 px-5 pb-16 pt-12 md:grid-cols-[1.1fr_.9fr] md:pt-20">
          <div className="reveal grid gap-5">
            <p className="eyebrow">Job-first referrals</p>
            <h1 className="!text-[clamp(2.2rem,5.4vw,3.8rem)] !font-light">Get referred, <em className="text-accent">honestly</em>.</h1>
            <p className="max-w-xl text-base text-muted">ReferralOS turns your resume and your network into a short, ranked list of real openings and the right people to ask, with drafts you review before anything goes out.</p>
            <div className="flex flex-wrap gap-3"><Link href="/signup" className="btn btn-primary">Create your account <ArrowRight size={14} aria-hidden="true" /></Link><Link href="/login" className="btn">Sign in</Link></div>
          </div>
          <div className="card glare reveal p-4" style={{ ["--d" as string]: ".12s", boxShadow: "var(--shadow-lg)" }} aria-label="Example opportunities (fictional)">
            <p className="field-label mb-3">Example: who to contact first (fictional data)</p>
            <ul className="grid gap-2">
              {PREVIEW.map(([role, co, st, cls]) => (
                <li key={role} className="flex items-center justify-between gap-3 rounded border bg-surface p-3">
                  <span className="grid"><span className="font-medium">{role}</span><span className="text-xs text-muted">{co}</span></span>
                  <span className={`badge ${cls}`}>{st}</span>
                </li>
              ))}
            </ul>
            <p className="mt-3 text-xs text-muted">Each status links to the evidence it is based on.</p>
          </div>
        </section>

        <section className="mx-auto max-w-6xl px-5 py-12">
          <p className="eyebrow reveal">How it works</p>
          <h2 className="reveal mb-6 font-display !text-3xl !font-light">Four steps, each one yours to approve</h2>
          <ol className="grid gap-px overflow-hidden rounded border bg-border-strong sm:grid-cols-2 lg:grid-cols-4">
            {STEPS.map((s, i) => (
              <li key={s.t} className="reveal glare relative grid content-start gap-2 bg-surface p-5" style={{ ["--d" as string]: `${i * 0.08}s` }}>
                <s.icon size={20} strokeWidth={1.6} className="text-accent" aria-hidden="true" />
                <h3 className="!text-lg">{s.t}</h3>
                <p className="text-muted">{s.d}</p>
              </li>
            ))}
          </ol>
        </section>

        <section className="mx-auto max-w-6xl px-5 py-12">
          <div className="card reveal grid gap-5 p-6 md:grid-cols-[.8fr_1.2fr]">
            <div className="grid content-start gap-2"><ShieldCheck size={22} strokeWidth={1.6} className="text-accent" aria-hidden="true" /><h2 className="font-display !text-2xl !font-light">Built to be trusted</h2><p className="text-muted">The rules are enforced by the code, not left to good intentions.</p></div>
            <ul className="grid gap-2 sm:grid-cols-2">{RULES.map((r) => <li key={r} className="flex items-start gap-2"><CheckCircle2 size={16} strokeWidth={1.6} className="mt-0.5 shrink-0 text-ok" aria-hidden="true" />{r}</li>)}</ul>
          </div>
        </section>
      </main>
      <footer className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-2 border-t px-5 py-6 text-xs text-muted">
        <span>ReferralOS · runs on your own machine or server</span>
        <span><Link href="/login">Sign in</Link> · <Link href="/signup">Create account</Link></span>
      </footer>
    </div>
  );
}
