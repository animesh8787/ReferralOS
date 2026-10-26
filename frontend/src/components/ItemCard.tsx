"use client";
import { useState } from "react";
import { api } from "@/lib/api";
import ProvenanceBadges, { Item } from "./ProvenanceBadge";

function title(i: Item): string {
  const d = i.data as Record<string, string | null>;
  return [d.title, d.organization, d.institution, d.degree, d.name, d.email].filter(Boolean).slice(0, 2).join(" · ") || i.section;
}

export default function ItemCard({ item, onChange }: { item: Item; onChange: () => void }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<Record<string, unknown>>(item.data);
  const [err, setErr] = useState("");

  async function run(fn: () => Promise<unknown>) {
    setErr("");
    try {
      await fn();
      onChange();
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  return (
    <li className="rounded border p-3">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-medium">{title(item)}</p>
          <ProvenanceBadges item={item} />
        </div>
        <div className="flex shrink-0 gap-2 text-sm">
          {!item.verified && <button className="underline" onClick={() => run(() => api(`/profile/items/${item.id}/confirm`, { method: "POST", body: {} }))}>Confirm</button>}
          <button className="underline" onClick={() => setEditing(!editing)}>{editing ? "Cancel" : "Edit"}</button>
          <button className="text-red-700 underline" onClick={() => run(() => api(`/profile/items/${item.id}`, { method: "DELETE" }))}>Delete</button>
        </div>
      </div>
      {item.flags.map((f, i) => <p key={i} className="mt-1 text-sm text-red-800">{f.note}</p>)}
      {!editing && Array.isArray(item.data.bullets) && (
        <ul className="mt-2 list-disc pl-5 text-sm">{(item.data.bullets as string[]).map((b, i) => <li key={i}>{b}</li>)}</ul>
      )}
      {editing && (
        <form className="mt-3 grid gap-2 text-sm" onSubmit={(e) => { e.preventDefault(); run(async () => { await api(`/profile/items/${item.id}`, { method: "PATCH", body: { data: draft } }); setEditing(false); }); }}>
          {Object.entries(draft).filter(([, v]) => typeof v === "string" || v === null || Array.isArray(v)).map(([k, v]) => (
            <label key={k} className="grid gap-1">
              <span className="text-gray-600">{k}{Array.isArray(v) ? " (one per line)" : ""}</span>
              {Array.isArray(v) ? (
                <textarea className="rounded border px-2 py-1" rows={3} value={(v as string[]).join("\n")} onChange={(e) => setDraft({ ...draft, [k]: e.target.value.split("\n").filter(Boolean) })} />
              ) : (
                <input className="rounded border px-2 py-1" value={(v as string) ?? ""} onChange={(e) => setDraft({ ...draft, [k]: e.target.value || null })} />
              )}
            </label>
          ))}
          <p className="text-xs text-gray-600">Saving marks this as confirmed by you and creates a new profile version.</p>
          <button className="w-fit rounded bg-black px-3 py-1 text-white">Save</button>
        </form>
      )}
      {err && <p role="alert" className="mt-2 text-sm text-red-700">{err}</p>}
    </li>
  );
}
