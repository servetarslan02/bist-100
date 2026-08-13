"use client";

import { useState, useMemo } from "react";
import { usePolling, type Signal } from "@/lib/api";

const CATEGORIES = ["ALL", "HIGH_CONVICTION", "CANDIDATE", "WATCH", "NORMAL"] as const;

export default function Opportunities() {
  const { data: signals, loading } = usePolling<Signal[]>("/signals?limit=100", 15000);
  const [filter, setFilter] = useState<string>("ALL");

  const filtered = useMemo(() => {
    if (!signals) return [];
    if (filter === "ALL") return signals;
    return signals.filter(s => s.spec_category === filter);
  }, [signals, filter]);

  const counts = useMemo(() => {
    if (!signals) return {};
    return {
      ALL: signals.length,
      HIGH_CONVICTION: signals.filter(s => s.spec_category === "HIGH_CONVICTION").length,
      CANDIDATE: signals.filter(s => s.spec_category === "CANDIDATE").length,
      WATCH: signals.filter(s => s.spec_category === "WATCH").length,
      NORMAL: signals.filter(s => s.spec_category === "NORMAL").length,
    };
  }, [signals]);

  return (
    <div className="p-4 space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-zinc-100">Opportunities</h1>
          <p className="text-[11px] text-zinc-600">SPEC • Momentum • Breakout • Value • Event Driven</p>
        </div>
      </div>

      {/* Category Filter */}
      <div className="flex gap-1.5">
        {CATEGORIES.map(cat => (
          <button
            key={cat}
            onClick={() => setFilter(cat)}
            className={`px-2.5 py-1 text-[10px] rounded transition-colors ${
              filter === cat
                ? "bg-zinc-800 text-zinc-200 border border-zinc-700"
                : "bg-zinc-900 text-zinc-600 border border-zinc-800 hover:text-zinc-400"
            }`}
          >
            {cat.replace("_", " ")}
            <span className="ml-1 text-zinc-600">({counts[cat] || 0})</span>
          </button>
        ))}
      </div>

      {/* Table */}
      <div className="bg-zinc-900/60 border border-zinc-800/60 rounded-lg overflow-hidden">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="text-zinc-500 border-b border-zinc-800/60 bg-zinc-950/50">
              <th className="text-left py-1.5 px-3 font-medium">TICKER</th>
              <th className="text-left py-1.5 px-3 font-medium">NAME</th>
              <th className="text-right py-1.5 px-3 font-medium">SCORE</th>
              <th className="text-center py-1.5 px-3 font-medium">DIR</th>
              <th className="text-center py-1.5 px-3 font-medium">RISK</th>
              <th className="text-center py-1.5 px-3 font-medium">HORIZON</th>
              <th className="text-right py-1.5 px-3 font-medium">EXP RET</th>
              <th className="text-center py-1.5 px-3 font-medium">CATEGORY</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={8} className="text-center py-12 text-zinc-600">
                <div className="flex items-center justify-center gap-2">
                  <div className="w-4 h-4 border-2 border-zinc-700 border-t-zinc-400 rounded-full animate-spin" />
                  Scanning...
                </div>
              </td></tr>
            ) : filtered.length === 0 ? (
              <tr><td colSpan={8} className="text-center py-12 text-zinc-600">No opportunities found</td></tr>
            ) : (
              filtered.map((s, i) => (
                <tr key={i} className="border-b border-zinc-800/20 row-hover cursor-pointer">
                  <td className="py-1.5 px-3 font-semibold text-zinc-200">{s.ticker}</td>
                  <td className="py-1.5 px-3 text-zinc-500 truncate max-w-[140px]">{s.name}</td>
                  <td className="py-1.5 px-3 text-right">
                    <span className={`font-mono font-semibold ${
                      s.score >= 80 ? "text-emerald-400" :
                      s.score >= 60 ? "text-amber-400" : "text-zinc-400"
                    }`}>
                      {s.score?.toFixed(0)}
                    </span>
                  </td>
                  <td className="py-1.5 px-3 text-center">
                    <span className={`font-medium ${s.direction === "LONG" ? "text-emerald-400" : "text-red-400"}`}>
                      {s.direction}
                    </span>
                  </td>
                  <td className="py-1.5 px-3 text-center">
                    <span className={`text-[9px] px-1.5 py-0.5 rounded ${
                      s.risk_level === "LOW" ? "bg-emerald-950 text-emerald-400" :
                      s.risk_level === "HIGH" ? "bg-red-950 text-red-400" :
                      "bg-amber-950 text-amber-400"
                    }`}>
                      {s.risk_level}
                    </span>
                  </td>
                  <td className="py-1.5 px-3 text-center text-zinc-500">{s.horizon}</td>
                  <td className="py-1.5 px-3 text-right font-mono">
                    <span className={s.expected_return_pct > 0 ? "text-emerald-400" : "text-red-400"}>
                      {s.expected_return_pct > 0 ? "+" : ""}{s.expected_return_pct?.toFixed(1)}%
                    </span>
                  </td>
                  <td className="py-1.5 px-3 text-center">
                    <span className={`text-[9px] px-1.5 py-0.5 rounded font-medium ${
                      s.spec_category === "HIGH_CONVICTION" ? "bg-red-950 text-red-400" :
                      s.spec_category === "CANDIDATE" ? "bg-amber-950 text-amber-400" :
                      s.spec_category === "WATCH" ? "bg-zinc-800 text-zinc-400" :
                      "bg-zinc-900 text-zinc-600"
                    }`}>
                      {s.spec_category}
                    </span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
