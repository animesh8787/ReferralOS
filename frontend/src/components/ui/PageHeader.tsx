export default function PageHeader({ title, sub, actions }: { title: string; sub?: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <header className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div className="grid gap-1">
        <h1>{title}</h1>
        {sub && <p className="max-w-2xl text-muted">{sub}</p>}
      </div>
      {actions}
    </header>
  );
}
