"use client";

import { usePolling, type WorldState } from "@/lib/api";

const FACTORS = [
  { key: "global_risk_appetite", label: "Global Risk Appetite", invert: false, icon: "◉" },
  { key: "usd_strength", label: "USD Strength", invert: false, icon: "$" },
  { key: "us_rate_pressure", label: "US Rate Pressure", invert: true, icon: "%" },
  { key: "commodity_pressure", label: "Commodity Pressure", invert: true, icon: "◈" },
  { key: "oil_pressure", label: "Oil Pressure", invert: true, icon: "◉" },
  { key: "turkey_macro_risk", label: "Turkey Macro Risk", invert: true, icon: "₺" },
  { key: "geopolitical_risk", label: "Geopolitical Risk", invert: true, icon: "⚑" },
  { key: "em_risk_appetite", label: "EM Risk Appetite", invert: false, icon: "⊕" },
  { key: "inflation_pressure", label: "Inflation Pressure", invert: true, icon: "↑" },
] as const;

export default function WorldIntelligence() {
  const { data: world } = usePolling<WorldState>("/world/state", 30000);

  const getBarColor = (value: number, invert: boolean) => {
    if (invert) {
      return value > 0.7 ? "bg-red-500" : value > 0.4 ? "bg-amber-500" : "bg-emerald-500";
    }
    return value > 0.6 ? "bg-emerald-500" : value > 0.3 ? "bg-amber-500" : "bg-red-500";
  };

  const getTextColor = (value: number, invert: boolean) => {
    if (invert) {
      return value > 0.7 ? "text-red-400" : value > 0.4 ? "text-amber-400" : "text-emerald-400";
    }
    return value > 0.6 ? "text-emerald-400" : value > 0.3 ? "text-amber-400" : "text-red-400";
  };

  return (
    <div className="p-4 space-y-4">
      <div>
        <h1 className="text-lg font-semibold text-zinc-100">World Intelligence</h1>
        <p className="text-[11px] text-zinc-600">Global macro state — event-driven latent factors</p>
      </div>

      {/* Top Metrics */}
      <div className="grid grid-cols-4 gap-3">
        <div className="bg-zinc-900/60 border border-zinc-800/60 rounded-lg p-3">
          <p className="text-[9px] uppercase tracking-wider text-zinc-600">VIX Level</p>
          <p className={`text-xl font-mono font-semibold mt-1 ${
            (world?.vix_level || 20) > 30 ? "text-red-400" :
            (world?.vix_level || 20) > 25 ? "text-amber-400" : "text-emerald-400"
          }`}>
            {world?.vix_level?.toFixed(1) || "—"}
          </p>
          <p className="text-[9px] text-zinc-700 mt-0.5">CBOE Volatility Index</p>
        </div>
        <div className="bg-zinc-900/60 border border-zinc-800/60 rounded-lg p-3">
          <p className="text-[9px] uppercase tracking-wider text-zinc-600">Global Risk</p>
          <p className="text-xl font-mono font-semibold mt-1 text-zinc-200">
            {world ? (world.global_risk_appetite * 100).toFixed(0) : "—"}%
          </p>
          <div className="w-full h-1 bg-zinc-800 rounded-full mt-2 overflow-hidden">
            <div
              className="h-full bg-emerald-500 rounded-full transition-all duration-500"
              style={{ width: `${(world?.global_risk_appetite || 0) * 100}%` }}
            />
          </div>
        </div>
        <div className="bg-zinc-900/60 border border-zinc-800/60 rounded-lg p-3">
          <p className="text-[9px] uppercase tracking-wider text-zinc-600">Turkey Macro</p>
          <p className={`text-xl font-mono font-semibold mt-1 ${
            (world?.turkey_macro_risk || 0.5) > 0.6 ? "text-red-400" : "text-zinc-200"
          }`}>
            {world ? (world.turkey_macro_risk * 100).toFixed(0) : "—"}%
          </p>
          <p className="text-[9px] text-zinc-700 mt-0.5">Macro risk index</p>
        </div>
        <div className="bg-zinc-900/60 border border-zinc-800/60 rounded-lg p-3">
          <p className="text-[9px] uppercase tracking-wider text-zinc-600">USD Strength</p>
          <p className="text-xl font-mono font-semibold mt-1 text-zinc-200">
            {world ? (world.usd_strength * 100).toFixed(0) : "—"}%
          </p>
          <p className="text-[9px] text-zinc-700 mt-0.5">DXY relative strength</p>
        </div>
      </div>

      {/* Latent Factors */}
      <div className="bg-zinc-900/60 border border-zinc-800/60 rounded-lg p-4">
        <h2 className="text-[10px] uppercase tracking-wider text-zinc-600 font-medium mb-4">Latent Factors</h2>
        <div className="space-y-3">
          {FACTORS.map(f => {
            const value = world ? (world as any)[f.key] || 0 : 0;
            return (
              <div key={f.key} className="group">
                <div className="flex items-center justify-between mb-1">
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] text-zinc-700 w-3 text-center">{f.icon}</span>
                    <span className="text-[11px] text-zinc-500 group-hover:text-zinc-400 transition-colors">
                      {f.label}
                    </span>
                  </div>
                  <span className={`text-[11px] font-mono ${getTextColor(value, f.invert)}`}>
                    {(value * 100).toFixed(0)}%
                  </span>
                </div>
                <div className="w-full h-1.5 bg-zinc-800 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all duration-700 ${getBarColor(value, f.invert)}`}
                    style={{ width: `${value * 100}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Propagation Chain */}
      <div className="bg-zinc-900/60 border border-zinc-800/60 rounded-lg p-4">
        <h2 className="text-[10px] uppercase tracking-wider text-zinc-600 font-medium mb-3">Impact Propagation</h2>
        <div className="flex items-center gap-2 text-[11px] overflow-x-auto pb-2">
          {["FED", "USD", "EM Risk", "BIST", "Banks", "AKBNK"].map((node, i) => (
            <div key={node} className="flex items-center gap-2 shrink-0">
              <div className="px-2 py-1 rounded bg-zinc-800 border border-zinc-700/50 text-zinc-400">
                {node}
              </div>
              {i < 5 && <span className="text-zinc-700">→</span>}
            </div>
          ))}
        </div>
        <p className="text-[10px] text-zinc-700 mt-2">
          Example: Fed rate hike → USD strengthen → EM risk off → BIST decline → Banking sector → AKBNK/GARAN
        </p>
      </div>
    </div>
  );
}
