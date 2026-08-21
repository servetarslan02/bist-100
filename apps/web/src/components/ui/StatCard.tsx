"use client";

import { AnimatedNumber } from "./AnimatedNumber";

interface StatCardProps {
  label: string;
  value: number | string;
  decimals?: number;
  prefix?: string;
  suffix?: string;
  color?: "auto" | "green" | "red" | "neutral";
  sparkData?: number[];
  subtext?: string;
  size?: "sm" | "md" | "lg";
  accent?: string;
}

export function StatCard({
  label,
  value,
  decimals = 2,
  prefix = "",
  suffix = "",
  color = "auto",
  sparkData,
  subtext,
  size = "md",
  accent,
}: StatCardProps) {
  const numValue = typeof value === "number" ? value : parseFloat(value as string);
  const derivedAccent = accent
    ? accent
    : color === "green" ? "#00e5a0"
    : color === "red" ? "#ff4466"
    : color === "auto" ? (numValue >= 0 ? "#00e5a0" : "#ff4466")
    : "#8892a4";

  const textSize = size === "sm" ? "text-lg" : size === "md" ? "text-xl" : "text-2xl";

  return (
    <div
      className="card-hover rounded-xl p-4 space-y-2"
      style={{
        background: "var(--color-bg-card)",
        border: "1px solid var(--color-border-subtle)",
        borderTop: `1px solid ${derivedAccent}30`,
      }}
    >
      <div className="flex items-center justify-between">
        <p className="text-[10px] uppercase tracking-widest font-semibold" style={{ color: "var(--color-text-muted)" }}>
          {label}
        </p>
        {sparkData && sparkData.length > 1 && (() => {
          const min = Math.min(...sparkData);
          const max = Math.max(...sparkData);
          const range = max - min || 1;
          const points = sparkData.slice(-20).map((v, i, arr) => {
            const x = (i / (arr.length - 1)) * 48;
            const y = 14 - ((v - min) / range) * 12;
            return `${x},${y}`;
          }).join(" ");
          return (
            <svg width={48} height={16} className="opacity-50">
              <polyline points={points} fill="none" stroke={derivedAccent} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          );
        })()}
      </div>

      <div className="flex items-baseline gap-0.5">
        {typeof value === "number" ? (
          <AnimatedNumber
            value={value}
            decimals={decimals}
            prefix={prefix}
            suffix={suffix}
            color={color}
            className={`font-bold font-data ${textSize}`}
          />
        ) : (
          <span className={`font-bold font-data ${textSize}`} style={{ color: "var(--color-text-primary)" }}>
            {prefix}{value}{suffix}
          </span>
        )}
      </div>

      {subtext && (
        <p className="text-[10px]" style={{ color: "var(--color-text-muted)" }}>{subtext}</p>
      )}
    </div>
  );
}
