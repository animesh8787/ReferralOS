"use client";
import Link from "next/link";
import useSWR from "swr";
import { api } from "@/lib/api";

type Priv = { holds: Record<string, number>; raw_import_retention_days: number | null; consents: Record<string, boolean>; statements: string[] };

export default function Privacy() {
  const { data, error } = useSWR<Priv>("/privacy/summary", (p: string) => api<Priv>(p));
  if (error) return <p role="alert" className="text-red-700">Could not load.</p>;
  if (!data) return <p role="status">Loading…</p>;
  return (
    <div className="mx-auto grid max-w-3xl gap-4 text-sm">
      <h1 className="text-xl font-semibold">Privacy summary</h1>
      <ul className="list-disc pl-5">{data.statements.map((s) => <li key={s}>{s}</li>)}</ul>
      <section aria-labelledby="h"><h2 id="h" className="font-medium">What we hold about you</h2><ul className="list-disc pl-5">{Object.entries(data.holds).map(([k, v]) => <li key={k}>{v} {k.replaceAll("_", " ")}</li>)}</ul></section>
      <section aria-labelledby="c"><h2 id="c" className="font-medium">Your consents</h2><ul className="list-disc pl-5">{Object.entries(data.consents).map(([k, v]) => <li key={k}>{k.replaceAll("_", " ")}: <strong>{v ? "allowed" : "off"}</strong></li>)}</ul>
        <p className="text-xs text-gray-600">Each is opt-in and can be turned off in <Link className="underline" href="/settings">Settings</Link>.</p></section>
      <section aria-labelledby="t" className="rounded border p-3"><h2 id="t" className="font-medium">People in your imports</h2>
        <p>Contacts you import are other people&apos;s personal data. Use them only for lawful, relevant outreach, keep opt-outs, and delete what you no longer need. The do-not-contact list is kept even when you re-import. This page is guidance, not legal advice.</p></section>
      <p>Raw import files are {data.raw_import_retention_days ? `deleted automatically after ${data.raw_import_retention_days} days` : "kept until you delete them or set an automatic deletion period"}. Full documentation: docs/PRIVACY.md.</p>
    </div>
  );
}
