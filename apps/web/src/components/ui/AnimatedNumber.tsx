"use client";

import { useEffect, useRef, useState } from "react";

interface AnimatedNumberProps {
  value: number;
  decimals?: number;
  prefix?: string;
  suffix?: string;
  duration?: number;
  className?: string;
  color?: "auto" | "green" | "red" | "neutral";
}

export function AnimatedNumber({
  value,
  decimals = 2,
  prefix = "",
  suffix = "",
  duration = 700,
  className = "",
  color = "auto",
}: AnimatedNumberProps) {
  const [display, setDisplay] = useState(value);
  const prevRef = useRef(value);
  const frameRef = useRef<number | null>(null);

  useEffect(() => {
    const start = prevRef.current;
    const diff = value - start;
    const startTime = performance.now();

    function animate(now: number) {
      const elapsed = now - startTime;
      const progress = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 4); // easeOutQuart — snappier
      setDisplay(start + diff * eased);
      if (progress < 1) {
        frameRef.current = requestAnimationFrame(animate);
      } else {
        prevRef.current = value;
      }
    }

    frameRef.current = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(frameRef.current!);
  }, [value, duration]);

  const derivedColor =
    color === "auto"
      ? display > 0
        ? "#00e5a0"
        : display < 0
        ? "#ff4466"
        : "var(--color-text-muted)"
      : color === "green"
      ? "#00e5a0"
      : color === "red"
      ? "#ff4466"
      : "var(--color-text-primary)";

  return (
    <span
      className={`font-data tabular-nums ${className}`}
      style={{ color: derivedColor, transition: "color 0.3s ease" }}
    >
      {prefix}
      {display.toFixed(decimals)}
      {suffix}
    </span>
  );
}
