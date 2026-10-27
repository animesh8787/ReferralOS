export default function Skeleton({ rows = 4, className = "" }: { rows?: number; className?: string }) {
  return (
    <div className={`grid gap-2 ${className}`} role="status" aria-busy="true">
      <span className="sr-only">Loading…</span>
      {Array.from({ length: rows }, (_, i) => <div key={i} className="skeleton h-9" style={{ width: `${100 - (i % 3) * 12}%` }} />)}
    </div>
  );
}
