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
}: StatCardProps) {
  const sizeClasses = {
    sm: "p-2",
    md: "p-3",
    lg: "p-4",
  };

  const valueClasses = {
    sm: "text-base",
    md: "text-xl",
    lg: "text-2xl",
  };

  return (
    <div className={`bg-zinc-900/60 border border-zinc-800/60 rounded-lg ${sizeClasses[size]} hover:border-zinc-700/60 transition-colors`}>
      <div className="flex items-center justify-between mb-1">
        <p className="text-[10px] uppercase tracking-wider text-zinc-500 font-medium">{label}</p>
        {sparkData && (
          <svg width={48} height={16} className="opacity-60">
            {sparkData.slice(-20).map((v, i, arr) => {
              const min = Math.min(...arr);
              const max = Math.max(...arr);
              const range = max - min || 1;
              const x = (i / (arr.length - 1)) * 48;
              const y = 14 - ((v - min) / range) * 12;
              return i > 0 ? (
                <line
                  key={i}
                  x1={(i - 1) / (arr.length - 1) * 48}
                  y1={14 - ((arr[i - 1] - min) / range) * 12}
                  x2={x}
                  y2={y}
                  stroke={v >= arr[0] ? "#10b981" : "#ef4444"}
                  strokeWidth={1}
                />
              ) : null;
            })}
          </svg>
        )}
      </div>
      <div className="flex items-baseline gap-1">
        {typeof value === "number" ? (
          <AnimatedNumber
            value={value}
            decimals={decimals}
            prefix={prefix}
            suffix={suffix}
            color={color}
            className={`font-semibold ${valueClasses[size]}`}
          />
        ) : (
          <span className={`font-semibold ${valueClasses[size]} text-zinc-100`}>{value}</span>
        )}
      </div>
      {subtext && <p className="text-[10px] text-zinc-600 mt-0.5">{subtext}</p>}
    </div>
  );
}
