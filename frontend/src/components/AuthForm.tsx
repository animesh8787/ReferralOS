"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";

export default function AuthForm({ mode }: { mode: "login" | "signup" }) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (mode === "signup") {
        await api("/auth/signup", { body: { email, password } });
        setNotice("Account created. Check your email for the verification token (dev: data/outbox), then sign in.");
      } else {
        await api("/auth/login", { body: { email, password } });
        router.push("/dashboard");
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-sm flex-col justify-center gap-6 px-4">
      <h1 className="text-2xl font-semibold">{mode === "login" ? "Sign in to ReferralOS" : "Create your account"}</h1>
      <form onSubmit={submit} className="flex flex-col gap-4" aria-describedby={error ? "form-error" : undefined}>
        <label className="flex flex-col gap-1 text-sm">
          Email
          <input className="rounded border px-3 py-2" type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Password
          <input className="rounded border px-3 py-2" type="password" required minLength={10} autoComplete={mode === "login" ? "current-password" : "new-password"} value={password} onChange={(e) => setPassword(e.target.value)} />
          {mode === "signup" && <span className="text-xs text-gray-500">At least 10 characters with a letter and a digit.</span>}
        </label>
        {error && <p id="form-error" role="alert" className="text-sm text-red-700">{error}</p>}
        {notice && <p role="status" className="text-sm text-green-800">{notice}</p>}
        <button disabled={busy} className="rounded bg-black px-3 py-2 text-white disabled:opacity-50">{busy ? "Working…" : mode === "login" ? "Sign in" : "Sign up"}</button>
      </form>
      <p className="text-sm">
        {mode === "login" ? <>New here? <Link className="underline" href="/signup">Create an account</Link></> : <>Have an account? <Link className="underline" href="/login">Sign in</Link></>}
      </p>
    </main>
  );
}
