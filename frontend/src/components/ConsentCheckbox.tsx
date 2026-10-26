"use client";
import { useState } from "react";
import useSWR from "swr";
import { api } from "@/lib/api";

type Consents = Record<string, { granted: boolean; description: string }>;

/** Optimistic: flips immediately, saves in the background, and rolls back (with a message) if the server refuses. */
export default function ConsentCheckbox({ name, extra, onChange }: { name: string; extra?: string; onChange?: () => void }) {
  const { data, mutate } = useSWR<Consents>("/consents", (p: string) => api<Consents>(p));
  const [local, setLocal] = useState<boolean | null>(null);
  const [err, setErr] = useState("");
  const checked = local ?? !!data?.[name]?.granted;
  return (
    <div>
      <label className="flex items-start gap-2">
        <input
          type="checkbox"
          checked={checked}
          onChange={async (e) => {
            const v = e.target.checked;
            setLocal(v);
            setErr("");
            try { await api(`/consents/${name}`, { method: "PUT", body: { granted: v } }); await mutate(); onChange?.(); } catch (x) { setErr((x as Error).message); } finally { setLocal(null); }
          }}
        />
        <span>{data?.[name]?.description ?? name}{extra && ` ${extra}`}</span>
      </label>
      {err && <p role="alert" className="text-xs text-red-700">{err}</p>}
    </div>
  );
}
