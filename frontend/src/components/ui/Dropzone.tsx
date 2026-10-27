"use client";
import { useState } from "react";

// Wraps the real <input type=file> (kept as is so labels and setInputFiles keep working); only adds the drag-over affordance.
export default function Dropzone({ children, hint }: { children: React.ReactNode; hint?: string }) {
  const [over, setOver] = useState(false);
  return (
    <div className="dropzone grid gap-1" data-over={over} onDragEnter={() => setOver(true)} onDragLeave={() => setOver(false)} onDrop={() => setOver(false)}>
      {children}
      {hint && <span className="text-xs text-muted">{hint}</span>}
    </div>
  );
}
