"use client";

/**
 * Skeleton — Loading Placeholder Components
 * ==========================================
 * Tüm sayfalar için tutarlı skeleton loading.
 * Bloomberg/TradingView standardı: içerik yüklenirken parlayan placeholder.
 */

import { memo } from "react";

interface SkeletonProps {
  className?: string;
  style?: React.CSSProperties;
}

/** Tek satır skeleton */
export function SkeletonLine({ className = "", style }: SkeletonProps) {
  return (
    <div
      className={`animate-pulse rounded bg-zinc-800/80 ${className}`}
      style={{ height: 12, ...style }}
    />
  );
}

/** Kart skeleton */
export function SkeletonCard({ className = "", style }: SkeletonProps) {
  return (
    <div
      className={`animate-pulse rounded-xl bg-zinc-900/60 border border-zinc-800 p-4 space-y-3 ${className}`}
      style={style}
    >
      <SkeletonLine className="w-1/3 h-3" />
      <SkeletonLine className="w-2/3 h-5" />
      <SkeletonLine className="w-1/2 h-3" />
    </div>
  );
}

/** Tablo satır skeleton */
export function SkeletonRow({ cols = 4 }: { cols?: number }) {
  return (
    <div className="flex items-center gap-4 py-2">
      {Array.from({ length: cols }).map((_, i) => (
        <SkeletonLine
          key={i}
          className={i === 0 ? "w-20" : "flex-1"}
          style={{ height: 14 }}
        />
      ))}
    </div>
  );
}

/** Tablo skeleton */
export function SkeletonTable({ rows = 5, cols = 4 }: { rows?: number; cols?: number }) {
  return (
    <div className="space-y-1">
      {Array.from({ length: rows }).map((_, i) => (
        <SkeletonRow key={i} cols={cols} />
      ))}
    </div>
  );
}

/** Dashboard stat card skeleton */
export function SkeletonStat() {
  return (
    <div className="animate-pulse rounded-xl bg-zinc-900/60 border border-zinc-800 p-4 space-y-2">
      <SkeletonLine className="w-1/4 h-3" />
      <SkeletonLine className="w-1/2 h-7" />
      <SkeletonLine className="w-1/3 h-3" />
    </div>
  );
}

/** Chart skeleton */
export function SkeletonChart({ height = 300 }: { height?: number }) {
  return (
    <div
      className="animate-pulse rounded-xl bg-zinc-900/60 border border-zinc-800 flex items-center justify-center"
      style={{ height }}
    >
      <div className="flex flex-col items-center gap-2">
        <div className="w-8 h-8 rounded-full border-2 border-zinc-700 border-t-cyan-500 animate-spin" />
        <span className="text-[10px] text-zinc-600">Grafik Yükleniyor...</span>
      </div>
    </div>
  );
}

/** Liste skeleton */
export function SkeletonList({ count = 5 }: { count?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className="animate-pulse rounded-lg bg-zinc-900/60 border border-zinc-800 p-3 flex items-center gap-3"
        >
          <div className="w-8 h-8 rounded-full bg-zinc-800" />
          <div className="flex-1 space-y-1.5">
            <SkeletonLine className="w-1/3 h-3" />
            <SkeletonLine className="w-2/3 h-3" />
          </div>
          <SkeletonLine className="w-16 h-4" />
        </div>
      ))}
    </div>
  );
}
