const STYLE: Record<string, string> = {
  ACTIVE_VERIFIED: "bg-green-100 text-green-900",
  ACTIVE_UNCONFIRMED: "bg-amber-100 text-amber-900",
  POSSIBLY_CLOSED: "bg-orange-100 text-orange-900",
  CLOSED: "bg-red-100 text-red-900",
  UNKNOWN: "bg-gray-100 text-gray-800",
};
const TEXT: Record<string, string> = {
  ACTIVE_VERIFIED: "Verified open", ACTIVE_UNCONFIRMED: "Unconfirmed", POSSIBLY_CLOSED: "Possibly closed", CLOSED: "Closed", UNKNOWN: "Unknown",
};

export default function StatusBadge({ status }: { status: string }) {
  return <span className={`inline-block rounded px-2 py-0.5 text-xs ${STYLE[status] ?? STYLE.UNKNOWN}`}>{TEXT[status] ?? status}</span>;
}
