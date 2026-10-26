"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import useSWR from "swr";
import { api, Me } from "@/lib/api";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { data: me, error } = useSWR<Me>("/auth/me", (p: string) => api<Me>(p), { shouldRetryOnError: false });

  useEffect(() => {
    if (error) router.replace("/login");
  }, [error, router]);

  if (!me) return <p className="p-8" role="status">Loading…</p>;

  return (
    <div className="min-h-screen">
      <header className="flex items-center justify-between border-b px-6 py-3">
        <nav aria-label="Main" className="flex gap-4 text-sm">
          <Link href="/dashboard" className="font-semibold">ReferralOS</Link>
          <Link href="/profile">Profile</Link>
        </nav>
        <button
          className="text-sm underline"
          onClick={async () => {
            await api("/auth/logout", { method: "POST", body: {} });
            router.replace("/login");
          }}
        >
          Sign out ({me.email})
        </button>
      </header>
      {!me.email_verified && (
        <p role="alert" className="bg-amber-100 px-6 py-2 text-sm">Your email is not verified yet. Some features stay locked until it is.</p>
      )}
      <main className="p-6">{children}</main>
    </div>
  );
}
