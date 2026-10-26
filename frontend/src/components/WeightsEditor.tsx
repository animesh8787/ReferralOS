"use client";
import { useState } from "react";

export default function WeightsEditor({ title, weights, onSave }: { title: string; weights: Record<string, number>; onSave: (w: Record<string, number>) => Promise<void> }) {
  const [w, setW] = useState<Record<string, number> | null>(null);
  const [msg, setMsg] = useState("");
  const cur = w ?? weights;
  const total = Object.values(cur).reduce((a, b) => a + (Number(b) || 0), 0);
  return (
    <form className="grid gap-1 text-sm" onSubmit={async (e) => { e.preventDefault(); setMsg(""); try { await onSave(cur); setW(null); setMsg("Saved. Weights are rescaled to total 100."); } catch (x) { setMsg((x as Error).message); } }}>
      <h3 className="font-medium">{title}</h3>
      {Object.keys(weights).map((k) => <label key={k} className="flex flex-wrap items-center gap-2"><span className="w-44 sm:w-56">{k.replaceAll("_", " ")}</span>
        <input type="number" min={0} className="w-20 rounded border px-2 py-1" value={cur[k] ?? 0} onChange={(e) => setW({ ...cur, [k]: Number(e.target.value) })} /></label>)}
      <p className="text-xs text-gray-600">Current total {Math.round(total)} (rescaled to 100 on save).</p>
      <button className="w-fit rounded border px-3 py-1">Save</button>{msg && <p role="status">{msg}</p>}
    </form>
  );
}
