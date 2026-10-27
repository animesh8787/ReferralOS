export type Item = {
  id: string;
  section: string;
  data: Record<string, unknown>;
  status: string;
  source: string;
  verified: boolean;
  confidence: number;
  evidence_level: string | null;
  flags: { type: string; note: string }[];
};

const cls = "badge";

export default function ProvenanceBadges({ item }: { item: Item }) {
  return (
    <span className="flex flex-wrap gap-1">
      <span className={`${cls} badge-muted`}>from {item.source}</span>
      <span className={`${cls} ${item.verified ? "badge-ok" : "badge-warn"}`}>
        {item.verified ? "confirmed by you" : "not confirmed"}
      </span>
      <span className={`${cls} badge-muted`} title="How sure the extractor is. Not a measure of truth.">
        confidence {Math.round(item.confidence * 100)}%
      </span>
      {item.evidence_level && <span className={`${cls} badge-accent`}>{item.evidence_level.replaceAll("_", " ").toLowerCase()}</span>}
      {item.status === "suggested" && <span className={`${cls} badge-accent`}>suggestion</span>}
      {item.flags.map((f, i) => (
        <span key={i} className={`${cls} badge-danger`} title={f.note}>
          {f.type.replaceAll("_", " ")}
        </span>
      ))}
    </span>
  );
}
