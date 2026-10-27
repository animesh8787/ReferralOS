"use client";
import { useEffect } from "react";

// Adds .in to every .reveal when it scrolls into view. Without IntersectionObserver or with reduced motion everything is simply shown.
export default function RevealInit() {
  useEffect(() => {
    const els = document.querySelectorAll<HTMLElement>(".reveal");
    if (!("IntersectionObserver" in window) || matchMedia("(prefers-reduced-motion: reduce)").matches) { els.forEach((e) => e.classList.add("in")); return; }
    const io = new IntersectionObserver((es) => es.forEach((e) => { if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); } }), { threshold: 0.12 });
    els.forEach((e) => io.observe(e));
    const glare = (e: PointerEvent) => {
      const el = (e.target as HTMLElement | null)?.closest<HTMLElement>(".glare");
      if (el) { const r = el.getBoundingClientRect(); el.style.setProperty("--gx", `${e.clientX - r.left}px`); el.style.setProperty("--gy", `${e.clientY - r.top}px`); }
    };
    addEventListener("pointermove", glare, { passive: true });
    return () => { io.disconnect(); removeEventListener("pointermove", glare); };
  }, []);
  return null;
}
