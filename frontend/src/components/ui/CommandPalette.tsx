"use client";
import { Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

export type NavItem = { href: string; label: string; group: string };

// Ctrl/Cmd+K jump-to. Rendered only while open, so it never duplicates the sidebar's links for tests or screen readers.
export default function CommandPalette({ items, open, onClose }: { items: NavItem[]; open: boolean; onClose: () => void }) {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [i, setI] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const hits = items.filter((n) => `${n.label} ${n.group}`.toLowerCase().includes(q.trim().toLowerCase()));
  useEffect(() => { if (open) { setQ(""); setI(0); input.current?.focus(); } }, [open]);
  if (!open) return null;
  const go = (h: NavItem | undefined) => { if (h) { onClose(); router.push(h.href); } };
  return (
    <div className="fixed inset-0 z-[170] grid place-items-start justify-items-center bg-black/55 px-4 pt-[14vh]" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div role="dialog" aria-modal="true" aria-label="Jump to" className="card w-full max-w-lg overflow-hidden" style={{ animation: "rise .22s var(--ease)", boxShadow: "var(--shadow-lg)" }}
        onKeyDown={(e) => {
          if (e.key === "Escape") onClose();
          else if (e.key === "ArrowDown") { e.preventDefault(); setI((v) => Math.min(v + 1, hits.length - 1)); }
          else if (e.key === "ArrowUp") { e.preventDefault(); setI((v) => Math.max(v - 1, 0)); }
          else if (e.key === "Enter") go(hits[i]);
        }}>
        <div className="flex items-center gap-2 border-b px-3">
          <Search size={15} strokeWidth={1.6} className="text-muted" aria-hidden="true" />
          <input ref={input} aria-label="Search pages" placeholder="Jump to a page…" className="!border-0 !shadow-none w-full !bg-transparent !px-0 !py-3" value={q} onChange={(e) => { setQ(e.target.value); setI(0); }} />
        </div>
        <ul className="max-h-72 overflow-y-auto p-1" role="listbox" aria-label="Pages">
          {hits.map((n, k) => (
            <li key={n.href} role="option" aria-selected={k === i}>
              <button type="button" className={`flex w-full items-center justify-between rounded px-3 py-2 text-left ${k === i ? "bg-accent-weak text-accent" : ""}`} onMouseEnter={() => setI(k)} onClick={() => go(n)}>
                <span>{n.label}</span><span className="field-label">{n.group}</span>
              </button>
            </li>
          ))}
          {hits.length === 0 && <li className="px-3 py-3 text-muted">No page matches.</li>}
        </ul>
      </div>
    </div>
  );
}
