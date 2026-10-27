"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import Skeleton from "@/components/ui/Skeleton";
import { api } from "@/lib/api";

function Inner() {
  const q = useSearchParams();
  const [state, setState] = useState<"working" | "ok" | "error">("working");
  const [msg, setMsg] = useState("");
  const once = useRef(false); // an authorisation code can be exchanged only once
  useEffect(() => {
    if (once.current) return;
    once.current = true;
    const code = q.get("code"), st = q.get("state");
    if (q.get("error") || !code || !st) { setState("error"); setMsg(q.get("error") === "access_denied" ? "You declined access, so nothing was connected." : "Google did not return an authorisation code."); return; }
    api<{ account: string }>("/email/gmail/callback", { body: { code, state: st } })
      .then((r) => { setState("ok"); setMsg(`Connected as ${r.account}.`); })
      .catch((e) => { setState("error"); setMsg((e as Error).message); });
  }, [q]);
  return (
    <div className="grid max-w-xl gap-3 text-sm">
      <h1>Connecting Gmail</h1>
      {state === "working" && <p role="status">Finishing the connection with Google…</p>}
      {state === "ok" && <p role="status" className="text-ok">{msg} You can approve and send emails from your account now; nothing is sent without your approval.</p>}
      {state === "error" && <p role="alert" className="text-danger">{msg} Nothing was saved.</p>}
      <p><Link className="underline" href="/outreach/settings">Back to outreach settings</Link></p>
    </div>
  );
}

export default function GmailCallback() {
  return <Suspense fallback={<Skeleton rows={5} />}><Inner /></Suspense>;
}
