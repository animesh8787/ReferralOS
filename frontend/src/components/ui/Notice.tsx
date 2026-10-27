// Errors are alerts, everything else is a status message (the tests and screen readers rely on the roles).
export default function Notice({ kind = "info", children }: { kind?: "ok" | "err" | "warn" | "info"; children: React.ReactNode }) {
  if (!children) return null;
  return <p role={kind === "err" ? "alert" : "status"} className={`notice notice-${kind}`}>{children}</p>;
}
