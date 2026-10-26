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

const cls = "inline-block rounded px-2 py-0.5 text-xs";

export default function ProvenanceBadges({ item }: { item: Item }) {
  return (
    <span className="flex flex-wrap gap-1">
      <span className={`${cls} bg-gray-100`}>from {item.source}</span>
      <span className={`${cls} ${item.verified ? "bg-green-100 text-green-900" : "bg-amber-100 text-amber-900"}`}>
        {item.verified ? "confirmed by you" : "not confirmed"}
      </span>
      <span className={`${cls} bg-gray-100`} title="How sure the extractor is. Not a measure of truth.">
        confidence {Math.round(item.confidence * 100)}%
      </span>
      {item.evidence_level && <span className={`${cls} bg-blue-100 text-blue-900`}>{item.evidence_level.replaceAll("_", " ").toLowerCase()}</span>}
      {item.status === "suggested" && <span className={`${cls} bg-purple-100 text-purple-900`}>suggestion</span>}
      {item.flags.map((f, i) => (
        <span key={i} className={`${cls} bg-red-100 text-red-900`} title={f.note}>
          {f.type.replaceAll("_", " ")}
        </span>
      ))}
    </span>
  );
}
