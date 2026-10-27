const STYLE: Record<string, string> = {
  ACTIVE_VERIFIED: "badge-ok", ACTIVE_UNCONFIRMED: "badge-warn", POSSIBLY_CLOSED: "badge-warn", CLOSED: "badge-danger", UNKNOWN: "badge-muted",
};
const TEXT: Record<string, string> = {
  ACTIVE_VERIFIED: "Verified open", ACTIVE_UNCONFIRMED: "Unconfirmed", POSSIBLY_CLOSED: "Possibly closed", CLOSED: "Closed", UNKNOWN: "Unknown",
};

export default function StatusBadge({ status }: { status: string }) {
  return <span className={`badge ${STYLE[status] ?? STYLE.UNKNOWN}`}>{TEXT[status] ?? status}</span>;
}
