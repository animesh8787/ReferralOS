"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { sendPasswordResetEmail } from "firebase/auth";
import { api } from "@/lib/api";
import { fbAuth, fbMessage, firebaseEnabled } from "@/lib/firebase";

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
  if (firebaseEnabled && mode !== "forgot") {  // Firebase sends links that open on its own page
    return <main className="mx-auto flex min-h-screen max-w-sm flex-col justify-center gap-4 px-4"><h1>{c.title}</h1><p>Use the link in the email Firebase sent you. If it has expired, sign in and press “Resend verification email”.</p><p><Link href="/login">Back to sign in</Link></p></main>;
  }
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr(""); setMsg("");
    try {
      if (firebaseEnabled) await sendPasswordResetEmail(fbAuth(), value);
      else if (mode === "verify") await api("/auth/verify", { body: { token } });
      else if (mode === "forgot") await api("/auth/forgot", { body: { email: value } });
      else await api("/auth/reset", { body: { token, password: value } });
      setMsg(c.done);
    } catch (x) { setErr(firebaseEnabled ? fbMessage(x) : (x as Error).message); }
  }
  return (
    <main className="mx-auto flex min-h-screen max-w-sm flex-col justify-center gap-5 px-4">
      <Link href="/" className="brand !p-0">ReferralOS</Link>
      <h1>{c.title}</h1>
      <form onSubmit={submit} className="card flex flex-col gap-3 p-5">
        {mode !== "forgot" && <label className="flex flex-col gap-1 text-sm font-medium">Token from your email<input  required value={token} onChange={(e) => setToken(e.target.value)} /></label>}
        {mode === "forgot" && <label className="flex flex-col gap-1 text-sm font-medium">Email<input type="email"  required value={value} onChange={(e) => setValue(e.target.value)} /></label>}
        {mode === "reset" && <label className="flex flex-col gap-1 text-sm font-medium">New password<input type="password" minLength={10}  required autoComplete="new-password" value={value} onChange={(e) => setValue(e.target.value)} /><span className="text-xs text-muted">At least 10 characters with a letter and a digit.</span></label>}
        {err && <p role="alert" className="notice notice-err">{err}</p>}{msg && <p role="status" className="notice notice-ok">{msg}</p>}
        <button className="rounded bg-black px-3 py-2 text-white w-full">{c.button}</button>
      </form>
      <p className="text-sm"><Link className="underline" href="/login">Back to sign in</Link></p>
    </main>
  );
}

export default function TokenForm({ mode }: { mode: Mode }) {
  return <Suspense fallback={<p role="status" className="p-8">Loading…</p>}><Inner mode={mode} /></Suspense>;
}
