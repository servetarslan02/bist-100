"use client";

import { useMemo } from "react";
import { usePolling, type Instrument } from "@/lib/api";

interface SectorBlock {
  sector: string;
  stocks: number;
  avgChange: number;
  color: string;
}

export default function MarketMap() {
  const { data: instruments, loading } = usePolling<Instrument[]>("/market/instruments?limit=500", 60000);

  const sectors = useMemo(() => {
    if (!instruments) return [];
    const sectorMap: Record<string, number> = {};
    instruments.forEach(i => {
      sectorMap[i.sector] = (sectorMap[i.sector] || 0) + 1;
    });
    return Object.entries(sectorMap)
      .map(([sector, count]) => ({
        sector,
        stocks: count,
        avgChange: Math.random() * 6 - 2, // Placeholder
        size: Math.max(count * 12, 60),
      }))
      .sort((a, b) => b.stocks - a.stocks);
  }, [instruments]);

  const getColor = (change: number) => {
    if (change > 3) return "bg-emerald-600/80 border-emerald-500/50";
    if (change > 1) return "bg-emerald-800/60 border-emerald-700/40";
    if (change > 0) return "bg-emerald-900/40 border-emerald-800/30";
    if (change > -1) return "bg-red-900/40 border-red-800/30";
    if (change > -3) return "bg-red-800/60 border-red-700/40";
    return "bg-red-600/80 border-red-500/50";
  };

  return (
    <div className="p-4 space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-zinc-100">Market Map</h1>
        <p className="text-[11px] text-zinc-600">Sector treemap • size = stock count • color = performance</p>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="w-5 h-5 border-2 border-zinc-700 border-t-zinc-400 rounded-full animate-spin" />
        </div>
      ) : (
        <div className="flex flex-wrap gap-2">
          {sectors.map(s => (
            <div
              key={s.sector}
              className={`${getColor(s.avgChange)} border rounded-lg p-3 hover:brightness-110 transition-all cursor-pointer`}
              style={{ minWidth: `${s.size}px`, minHeight: `${s.size}px` }}
            >
              <p className="text-[10px] font-semibold text-zinc-200">{s.sector}</p>
              <p className="text-[9px] text-zinc-400">{s.stocks} stocks</p>
              <p className={`text-[11px] font-mono mt-1 ${s.avgChange >= 0 ? "text-emerald-300" : "text-red-300"}`}>
                {s.avgChange >= 0 ? "+" : ""}{s.avgChange.toFixed(1)}%
              </p>
            </div>
          ))}
        </div>
      )}

      {/* Legend */}
      <div className="bg-zinc-900/60 border border-zinc-800/60 rounded-lg p-3">
        <div className="flex items-center gap-4 text-[10px]">
          <span className="text-zinc-600">Legend:</span>
          <div className="flex items-center gap-1">
            <div className="w-3 h-3 rounded bg-emerald-600/80" />
            <span className="text-zinc-500">Strong positive</span>
          </div>
          <div className="flex items-center gap-1">
            <div className="w-3 h-3 rounded bg-emerald-900/40" />
            <span className="text-zinc-500">Slight positive</span>
          </div>
          <div className="flex items-center gap-1">
            <div className="w-3 h-3 rounded bg-red-900/40" />
            <span className="text-zinc-500">Slight negative</span>
          </div>
          <div className="flex items-center gap-1">
            <div className="w-3 h-3 rounded bg-red-600/80" />
            <span className="text-zinc-500">Strong negative</span>
          </div>
        </div>
      </div>
    </div>
  );
}
