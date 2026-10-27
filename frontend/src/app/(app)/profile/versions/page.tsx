"use client";
import useSWR from "swr";
import Skeleton from "@/components/ui/Skeleton";
import { api } from "@/lib/api";

type V = { id: string; version: number; reason: string; created_at: string };

export default function Versions() {
  const { data, error } = useSWR<V[]>("/profile/versions", (p: string) => api<V[]>(p));
  if (error) return <p role="alert" className="text-danger">Could not load versions.</p>;
  if (!data) return <Skeleton rows={5} />;
  return (
    <div className="max-w-2xl">
      <h1 className="mb-3 ">Profile version history</h1>
      {data.length === 0 ? <p className="text-sm text-muted">No changes yet.</p> : (
        <ol className="grid gap-1 text-sm">{data.map((v) => <li key={v.id} className="rounded border p-2">v{v.version} · {v.reason} · {new Date(v.created_at + "Z").toLocaleString()}</li>)}</ol>
      )}
    </div>
  );
}
