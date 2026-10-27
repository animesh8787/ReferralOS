"use client";
import { Monitor, Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";

type Mode = "system" | "light" | "dark";
const NEXT: Record<Mode, Mode> = { system: "light", light: "dark", dark: "system" };

function read(): Mode {
  try { const t = localStorage.getItem("referralos-theme"); return t === "light" || t === "dark" ? t : "system"; } catch { return "system"; }
}

export function applyTheme(m: Mode) {
  const dark = m === "dark" || (m === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  if (m === "system") document.documentElement.removeAttribute("data-theme"); else document.documentElement.dataset.theme = m;
  if (m === "system" && dark) document.documentElement.dataset.theme = "dark";
  try { m === "system" ? localStorage.removeItem("referralos-theme") : localStorage.setItem("referralos-theme", m); } catch { /* private mode: theme just isn't remembered */ }
}

export default function ThemeToggle() {
  const [mode, setMode] = useState<Mode>("system");
  useEffect(() => {
    setMode(read());
    const mq = matchMedia("(prefers-color-scheme: dark)");
    const on = () => read() === "system" && applyTheme("system");
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  const Icon = mode === "light" ? Sun : mode === "dark" ? Moon : Monitor;
  return (
    <button type="button" className="btn" aria-label={`Theme: ${mode}. Switch theme`} title={`Theme: ${mode}`}
      onClick={() => { const n = NEXT[mode]; setMode(n); applyTheme(n); }}>
      <Icon size={15} strokeWidth={1.6} aria-hidden="true" />
    </button>
  );
}
