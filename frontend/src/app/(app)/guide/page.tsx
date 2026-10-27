import Link from "next/link";

const ITEMS: [string, string, string, string][] = [
  ["Profile", "/profile", "Your single source of truth. Resume, GitHub and portfolio suggestions land here with where each fact came from and whether you confirmed it.", "Works offline. GitHub/portfolio need the internet and your consent."],
  ["Imports", "/imports", "Upload your LinkedIn connections export and/or an HR contact list. You map columns, see exactly which rows were rejected and why, and nothing is dropped silently.", "Works offline."],
  ["Prospects & Companies", "/prospects", "Ranks the people you know by who is worth approaching first, with a score, a separate confidence, and the reasons. It never claims anyone can refer you.", "Works offline."],
  ["Jobs", "/jobs", "Finds roles from company job boards you add and checks whether they still look open, keeping the evidence. A loading page is not proof; verified means the company's own board lists it.", "Needs the internet. Coverage depends on which companies use a supported board."],
  ["Opportunities", "/opportunities", "Matches each job against your profile: a requirement matrix (what supports each requirement), eligibility checks, and who to contact first.", "Works offline once jobs exist."],
  ["Resumes", "/resumes", "Builds a tailored resume from facts you've confirmed. Every statement is checked against your profile; nothing from a job description is added without evidence. You approve a version before it can be used.", "Works offline. AI rewording is optional."],
  ["Outreach", "/outreach", "Drafts referral requests (LinkedIn, sent by you) and emails, shows them in a review table, and sends nothing until you approve. Emails can go through your Gmail or be sent by you.", "Gmail needs a Google sign-in you set up. LinkedIn is always manual."],
  ["Tracking", "/tracking", "Follow every outreach from draft to outcome. Statuses like 'sent' and 'referral submitted' only change on real events or your own confirmation.", "Works offline."],
  ["Diagnostics", "/diagnostics", "See what the parsers read, which columns were unused, why rows were rejected and which integrations were actually verified.", "Works offline."],
];

export default function Guide() {
  return (
    <div className="grid max-w-3xl gap-4 text-sm">
      <h1>How ReferralOS works</h1>
      <p>Start from a real opening, find the few people who could help, tailor an honest resume, and reach out with your approval at every step. Where something can&apos;t be known, we say &ldquo;unknown&rdquo; rather than guess.</p>
      <ol className="grid gap-3">{ITEMS.map(([t, h, d, r]) => <li key={t} className="rounded border p-3"><h2 className="font-medium"><Link className="underline" href={h}>{t}</Link></h2><p>{d}</p><p className="text-xs text-muted">{r}</p></li>)}</ol>
      <section aria-labelledby="rules" className="rounded border border-warn bg-warn-weak p-3"><h2 id="rules" className="font-medium">Things this app will not do</h2>
        <ul className="list-disc pl-5"><li>Send any LinkedIn message for you, or ask for your LinkedIn or Gmail password.</li><li>Send anything you haven&apos;t approved, to someone on your do-not-contact list, or about a job that may be closed.</li>
          <li>Email the same person a second cold email, or send in bulk from purchased lists.</li><li>Call or text anyone. Phone numbers are for your reference only.</li><li>Invent skills, numbers, relationships or referral programmes.</li></ul></section>
      <section aria-labelledby="ext"><h2 id="ext" className="font-medium">What needs outside services</h2>
        <ul className="list-disc pl-5"><li><strong>Nothing</strong> for parsing, imports, scoring, matching, tailoring and drafting.</li><li><strong>Internet</strong> for GitHub, portfolio pages and job boards.</li><li><strong>A Google OAuth app</strong> (set up by whoever runs this server) to send through Gmail.</li><li><strong>Your own API key</strong> only if you opt in to AI rewording.</li></ul></section>
    </div>
  );
}
