import type { LucideIcon } from "lucide-react";

export default function EmptyState({ icon: Icon, title, sub, children }: { icon: LucideIcon; title: string; sub?: string; children?: React.ReactNode }) {
  return (
    <div className="card grid place-items-center gap-1 px-6 py-10 text-center">
      <Icon size={28} strokeWidth={1.6} className="text-faint" aria-hidden="true" />
      <p className="text-lg font-semibold">{title}</p>
      {sub && <p className="max-w-md text-muted">{sub}</p>}
      {children}
    </div>
  );
}
