"use client";
import { createUserWithEmailAndPassword, GoogleAuthProvider, sendEmailVerification, signInWithEmailAndPassword, signInWithPopup } from "firebase/auth";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";
import { fbAuth, fbMessage, firebaseEnabled } from "@/lib/firebase";

export default function AuthForm({ mode }: { mode: "login" | "signup" }) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");

  // Firebase proves who the user is; the API then issues its own session cookie for the ID token.
  async function exchange(user: { getIdToken: () => Promise<string> }) {
    await api("/auth/firebase", { body: { id_token: await user.getIdToken() } });
    router.push("/dashboard");
  }

  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    try { await fn(); } catch (err) { setError(firebaseEnabled ? fbMessage(err) : (err as Error).message); } finally { setBusy(false); }
  }

  const submit = (e: React.FormEvent) => { e.preventDefault(); run(async () => {
    if (firebaseEnabled) {
      if (mode === "signup") {
        const c = await createUserWithEmailAndPassword(fbAuth(), email, password);
        await sendEmailVerification(c.user);
        setNotice("Account created. We sent a verification link to your email.");
        await exchange(c.user);
      } else {
        await exchange((await signInWithEmailAndPassword(fbAuth(), email, password)).user);
      }
    } else if (mode === "signup") {
      await api("/auth/signup", { body: { email, password } });
      setNotice("Account created. Check your email for the verification link, then sign in.");
    } else {
      await api("/auth/login", { body: { email, password } });
      router.push("/dashboard");
    }
  }); };

  return (
    <main className="mx-auto flex min-h-screen max-w-sm flex-col justify-center gap-5 px-4">
      <Link href="/" className="text-lg font-semibold no-underline">ReferralOS</Link>
      <h1>{mode === "login" ? "Sign in to ReferralOS" : "Create your account"}</h1>
      {firebaseEnabled && (
        <button type="button" disabled={busy} className="btn" onClick={() => run(async () => exchange((await signInWithPopup(fbAuth(), new GoogleAuthProvider())).user))}>
          Continue with Google
        </button>
      )}
      <form onSubmit={submit} className="card flex flex-col gap-4 p-5" aria-describedby={error ? "form-error" : undefined}>
        <label className="flex flex-col gap-1 text-sm font-medium">
          Email
          <input type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label className="flex flex-col gap-1 text-sm font-medium">
          Password
          <input type="password" required minLength={firebaseEnabled ? 6 : 10} autoComplete={mode === "login" ? "current-password" : "new-password"} value={password} onChange={(e) => setPassword(e.target.value)} />
          {mode === "signup" && !firebaseEnabled && <span className="text-xs font-normal text-muted">At least 10 characters with a letter and a digit.</span>}
        </label>
        {error && <p id="form-error" role="alert" className="notice notice-err">{error}</p>}
        {notice && <p role="status" className="notice notice-ok">{notice}</p>}
        <button disabled={busy} className="rounded bg-black px-3 py-2 text-white disabled:opacity-50 w-full">{busy ? "Working…" : mode === "login" ? "Sign in" : "Sign up"}</button>
      </form>
      <p className="text-sm">
        <Link href="/forgot">Forgot your password?</Link>{!firebaseEnabled && <> · <Link href="/verify">Verify your email</Link></>}<br />
        {mode === "login" ? <>New here? <Link href="/signup">Create an account</Link></> : <>Have an account? <Link href="/login">Sign in</Link></>}
      </p>
    </main>
  );
}
