"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { api } from "@/lib/api";

type Mode = "verify" | "forgot" | "reset";
const COPY: Record<Mode, { title: string; button: string; done: string }> = {
  verify: { title: "Verify your email", button: "Verify", done: "Email verified. You can sign in now." },
  forgot: { title: "Reset your password", button: "Send reset instructions", done: "If that address has an account, reset instructions were sent." },
  reset: { title: "Choose a new password", button: "Set new password", done: "Password changed. All devices were signed out; sign in again." },
};

function Inner({ mode }: { mode: Mode }) {
  const q = useSearchParams();
  const [token, setToken] = useState(q.get("token") ?? "");
  const [value, setValue] = useState("");
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const c = COPY[mode];
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(""); setMsg("");
    try {
      if (mode === "verify") await api("/auth/verify", { body: { token } });
      else if (mode === "forgot") await api("/auth/forgot", { body: { email: value } });
      else await api("/auth/reset", { body: { token, password: value } });
      setMsg(c.done);
    } catch (x) { setErr((x as Error).message); }
  }
  return (
    <main className="mx-auto flex min-h-screen max-w-sm flex-col justify-center gap-4 px-4">
      <h1 className="text-2xl font-semibold">{c.title}</h1>
      <form onSubmit={submit} className="flex flex-col gap-3">
        {mode !== "forgot" && <label className="flex flex-col gap-1 text-sm">Token from your email<input className="rounded border px-3 py-2" required value={token} onChange={(e) => setToken(e.target.value)} /></label>}
        {mode === "forgot" && <label className="flex flex-col gap-1 text-sm">Email<input type="email" className="rounded border px-3 py-2" required value={value} onChange={(e) => setValue(e.target.value)} /></label>}
        {mode === "reset" && <label className="flex flex-col gap-1 text-sm">New password<input type="password" minLength={10} className="rounded border px-3 py-2" required autoComplete="new-password" value={value} onChange={(e) => setValue(e.target.value)} /><span className="text-xs text-gray-500">At least 10 characters with a letter and a digit.</span></label>}
        {err && <p role="alert" className="text-sm text-red-700">{err}</p>}{msg && <p role="status" className="text-sm text-green-800">{msg}</p>}
        <button className="rounded bg-black px-3 py-2 text-white">{c.button}</button>
      </form>
      <p className="text-sm"><Link className="underline" href="/login">Back to sign in</Link></p>
    </main>
  );
}

export default function TokenForm({ mode }: { mode: Mode }) {
  return <Suspense fallback={<p role="status" className="p-8">Loading…</p>}><Inner mode={mode} /></Suspense>;
}
