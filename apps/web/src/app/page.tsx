"use client";

import { usePolling, type MarketState, type Signal, type WorldState, type SystemStatus } from "@/lib/api";
import { StatCard } from "@/components/ui/StatCard";
import { AnimatedNumber } from "@/components/ui/AnimatedNumber";

export default function Overview() {
  const { data: market } = usePolling<MarketState>("/market/state", 15000);
  const { data: signals } = usePolling<Signal[]>("/signals?limit=10", 30000);
  const { data: world } = usePolling<WorldState>("/world/state", 30000);
  const { data: status } = usePolling<SystemStatus>("/status", 10000);

  const regimeColor = (r?: string) => {
    if (!r) return "text-zinc-500";
    if (r.includes("UP") || r.includes("EXPANSION") || r.includes("ON")) return "text-emerald-400";
    if (r.includes("DOWN") || r.includes("PANIC") || r.includes("OFF")) return "text-red-400";
    if (r.includes("HIGH")) return "text-amber-400";
    return "text-zinc-400";
  };

  return (
    <div className="p-4 space-y-4">
      {/* Header Bar */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <h1 className="text-lg font-semibold text-zinc-100">ALPHA BIST</h1>
          <div className="flex items-center gap-1.5">
            <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 pulse-dot" />
            <span className="text-[10px] text-zinc-500 uppercase tracking-wider">Live</span>
          </div>
        </div>
        <div className="flex items-center gap-4 text-[11px] text-zinc-500">
          <span>{new Date().toLocaleTimeString("tr-TR")}</span>
          <span className="text-zinc-700">|</span>
          <span>800+ instruments</span>
          <span className="text-zinc-700">|</span>
          <span className={status?.status === "ok" ? "text-emerald-500" : "text-red-500"}>
            {status?.status === "ok" ? "● ALL SYSTEMS" : "● DEGRADED"}
          </span>
        </div>
      </div>

      {/* Market State Bar */}
      <div className="bg-zinc-900/60 border border-zinc-800/60 rounded-lg p-3">
        <div className="grid grid-cols-6 gap-4">
          <div>
            <p className="text-[9px] uppercase tracking-wider text-zinc-600">Regime</p>
            <p className={`text-sm font-semibold ${regimeColor(market?.regime)}`}>
              {market?.regime || "—"}
            </p>
          </div>
          <div>
            <p className="text-[9px] uppercase tracking-wider text-zinc-600">Breadth</p>
            <p className="text-sm font-mono text-zinc-200">
              {market?.breadth_pct?.toFixed(1) || "—"}%
            </p>
          </div>
          <div>
            <p className="text-[9px] uppercase tracking-wider text-zinc-600">Adv / Dec</p>
            <p className="text-sm font-mono">
              <span className="text-emerald-400">{market?.advancing || 0}</span>
              <span className="text-zinc-600 mx-1">/</span>
              <span className="text-red-400">{market?.declining || 0}</span>
            </p>
          </div>
          <div>
            <p className="text-[9px] uppercase tracking-wider text-zinc-600">Avg RSI</p>
            <p className={`text-sm font-mono ${
              (market?.avg_rsi || 50) > 70 ? "text-red-400" :
              (market?.avg_rsi || 50) < 30 ? "text-emerald-400" : "text-zinc-200"
            }`}>
              {market?.avg_rsi?.toFixed(1) || "—"}
            </p>
          </div>
          <div>
            <p className="text-[9px] uppercase tracking-wider text-zinc-600">Anomalies</p>
            <p className={`text-sm font-mono ${
              (market?.anomaly_count || 0) > 10 ? "text-amber-400" : "text-zinc-200"
            }`}>
              {market?.anomaly_count || 0}
            </p>
          </div>
          <div>
            <p className="text-[9px] uppercase tracking-wider text-zinc-600">Risk Appetite</p>
            <div className="flex items-center gap-2 mt-0.5">
              <div className="flex-1 h-1 bg-zinc-800 rounded-full overflow-hidden">
                <div
                  className="h-full bg-emerald-500 rounded-full transition-all duration-500"
                  style={{ width: `${(market?.risk_appetite || 0) * 100}%` }}
                />
              </div>
              <span className="text-[11px] font-mono text-zinc-400">
                {((market?.risk_appetite || 0) * 100).toFixed(0)}%
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Stat Cards */}
      <div className="grid grid-cols-5 gap-3">
        <StatCard
          label="Global Risk"
          value={(world?.global_risk_appetite || 0) * 100}
          decimals={0}
          suffix="%"
          color="auto"
          size="sm"
        />
        <StatCard
          label="VIX"
          value={world?.vix_level || 0}
          decimals={1}
          color={world && world.vix_level > 25 ? "red" : "green"}
          size="sm"
        />
        <StatCard
          label="USD Strength"
          value={(world?.usd_strength || 0) * 100}
          decimals={0}
          suffix="%"
          size="sm"
        />
        <StatCard
          label="Turkey Macro"
          value={(world?.turkey_macro_risk || 0) * 100}
          decimals={0}
          suffix="%"
          color={world && world.turkey_macro_risk > 0.6 ? "red" : "neutral"}
          size="sm"
        />
        <StatCard
          label="Oil Pressure"
          value={(world?.oil_pressure || 0) * 100}
          decimals={0}
          suffix="%"
          size="sm"
        />
      </div>

      {/* Opportunity Engine */}
      <div className="bg-zinc-900/60 border border-zinc-800/60 rounded-lg">
        <div className="px-4 py-2.5 border-b border-zinc-800/60 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-emerald-500 text-sm">◈</span>
            <h2 className="text-xs font-semibold text-zinc-300 uppercase tracking-wider">Opportunity Engine</h2>
          </div>
          <span className="text-[10px] text-zinc-600">{signals?.length || 0} active</span>
        </div>

        {!signals || signals.length === 0 ? (
          <div className="p-8 text-center text-zinc-600 text-sm">No active signals</div>
        ) : (
          <table className="w-full text-[12px]">
            <thead>
              <tr className="text-zinc-600 border-b border-zinc-800/40">
                <th className="text-left py-1.5 px-3 font-medium">TICKER</th>
                <th className="text-left py-1.5 px-3 font-medium">NAME</th>
                <th className="text-right py-1.5 px-3 font-medium">SCORE</th>
                <th className="text-center py-1.5 px-3 font-medium">DIR</th>
                <th className="text-center py-1.5 px-3 font-medium">RISK</th>
                <th className="text-center py-1.5 px-3 font-medium">HORIZON</th>
                <th className="text-right py-1.5 px-3 font-medium">EXP</th>
                <th className="text-center py-1.5 px-3 font-medium">CAT</th>
              </tr>
            </thead>
            <tbody>
              {signals.map((s, i) => (
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
                    <span className={s.direction === "LONG" ? "text-emerald-400" : "text-red-400"}>
                      {s.direction}
                    </span>
                  </td>
                  <td className="py-1.5 px-3 text-center">
                    <span className={`text-[10px] px-1.5 py-0.5 rounded ${
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
                    <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                      s.spec_category === "HIGH_CONVICTION" ? "bg-red-950 text-red-400" :
                      s.spec_category === "CANDIDATE" ? "bg-amber-950 text-amber-400" :
                      s.spec_category === "WATCH" ? "bg-zinc-800 text-zinc-400" :
                      "bg-zinc-900 text-zinc-600"
                    }`}>
                      {s.spec_category}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Live Intelligence */}
      <div className="grid grid-cols-2 gap-3">
        <div className="bg-zinc-900/60 border border-zinc-800/60 rounded-lg p-3">
          <h3 className="text-[10px] uppercase tracking-wider text-zinc-600 font-medium mb-2">System Health</h3>
          <div className="space-y-1.5">
            {status?.services && Object.entries(status.services).map(([name, health]) => (
              <div key={name} className="flex items-center justify-between">
                <span className="text-[11px] text-zinc-500 capitalize">{name.replace("_", " ")}</span>
                <div className="flex items-center gap-1.5">
                  <div className={`w-1.5 h-1.5 rounded-full ${health === "healthy" ? "bg-emerald-500" : "bg-red-500"}`} />
                  <span className={`text-[10px] ${health === "healthy" ? "text-emerald-500" : "text-red-500"}`}>
                    {health}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="bg-zinc-900/60 border border-zinc-800/60 rounded-lg p-3">
          <h3 className="text-[10px] uppercase tracking-wider text-zinc-600 font-medium mb-2">World State</h3>
          <div className="space-y-1.5">
            {world && [
              { label: "Geopolitical", value: world.geopolitical_risk, invert: true },
              { label: "EM Risk", value: world.em_risk_appetite, invert: false },
              { label: "Inflation", value: world.inflation_pressure, invert: true },
              { label: "US Rates", value: world.us_rate_pressure, invert: true },
            ].map(f => (
              <div key={f.label} className="flex items-center justify-between">
                <span className="text-[11px] text-zinc-500">{f.label}</span>
                <div className="flex items-center gap-2">
                  <div className="w-16 h-1 bg-zinc-800 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full transition-all duration-500 ${
                        f.invert
                          ? f.value > 0.7 ? "bg-red-500" : f.value > 0.4 ? "bg-amber-500" : "bg-emerald-500"
                          : f.value > 0.6 ? "bg-emerald-500" : f.value > 0.3 ? "bg-amber-500" : "bg-red-500"
                      }`}
                      style={{ width: `${f.value * 100}%` }}
                    />
                  </div>
                  <span className="text-[10px] font-mono text-zinc-500 w-8 text-right">
                    {(f.value * 100).toFixed(0)}%
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
